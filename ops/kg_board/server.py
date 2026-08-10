#!/usr/bin/env python3
"""kg 懸賞板 — 常駐在 felix 的唯讀看板 + 一層本機排序覆蓋。

版本與主機邊界
--------------
應用與自檢跟著 KG repo 版控；launchd plist、token、state 與 sync tick 是主機 glue，
留在 butler。服務不 import backlog 實作，而是 shell out 到 clone 同版的 CLI：
`list --json` 提供完整票面，`dispatch --json` 提供 canonical 可派工 ids 與 blocked metadata。

資料從哪來（以及「近即時」到底多近）
------------------------------------
真相是 **oscar 的本地 main**——它隨每次 cutover 前進，而 oscar 是會睡的筆電。
felix 是 24/7 且手機連得到，所以看板在 felix，讀一份追 `origin/main` 的 clone
(`KG_BOARD_CLONE`)，由本程序的背景執行緒週期 `fetch` + `reset --hard`。

因此新鮮度 = oscar 推 origin/main 的節奏（`com.kg.sync`，Phase 4）+ 本程序的
refresh tick。oscar 睡著時看板會凍在最後一次推送——那是對的，因為那段時間本來也
沒有東西在變。`/healthz` 與 Health 分頁**具名回報**這個延遲，不假裝即時。

安全模型（講清楚它擋什麼、不擋什麼）
------------------------------------
* 預設綁 Tailscale IP（見 plist），所以**網路可達性本身就是第一道認證**——只有
  使用者自己的 tailnet 裝置連得到。同機的 `felix-status`(8002) 就是這個模型。
* 手機頁面的 `/api/priority` 只接受 JSON、嚴格同源 Origin 與程序啟動時產生的
  `X-KG-CSRF`；短期 token 注入同源 HTML，不把長期 bearer 放進瀏覽器。
* oscar 主機 glue 寫入的 `/api/mirror/*` 仍只接受長期 Bearer token，token 取自
  `~/.secrets/kg-board.token`，不接受頁面 CSRF token。
* **fail-closed**：token 檔不存在或為空 → 服務**拒絕啟動**。一個沒有認證卻在跑的
  看板，比沒有看板更糟；而「啟動成功但寫入永遠 401」會讓人以為只是設定錯。
* 若之後放到 Cloudflare Tunnel 對外，設 `KG_BOARD_REQUIRE_TOKEN=1`，連讀取也要
  token——因為那時可達性不再等於身分。

「已梳理」只有一個 owner
------------------------
本服務只消費 clone 同版 `backlog.py list/dispatch --json` 的 canonical partition，
不複製 groom 欄位規則。**本服務任何一頁都不得出現第二套判準。**
"""
from __future__ import annotations

import gzip
import hmac
import html
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from ops.kg_board.git_tree import project_snapshot
except ModuleNotFoundError:  # direct launch via the release checkout
    from git_tree import project_snapshot

TZ = ZoneInfo("Asia/Taipei")

HOME = Path.home()
CLONE = Path(os.environ.get("KG_BOARD_CLONE", HOME / "kg-board"))
STATE_DIR = Path(os.environ.get("KG_BOARD_STATE", HOME / "kg-board-state"))
TOKEN_FILE = Path(os.environ.get("KG_BOARD_TOKEN_FILE", HOME / ".secrets" / "kg-board.token"))
BIND = os.environ.get("KG_BOARD_BIND", "127.0.0.1:8007")
REFRESH_SECONDS = int(os.environ.get("KG_BOARD_REFRESH_SECONDS", "60"))
REQUIRE_TOKEN_FOR_READS = os.environ.get("KG_BOARD_REQUIRE_TOKEN") == "1"
RELEASE_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = RELEASE_DIR.parents[1]
WEB_DIR = RELEASE_DIR / "web"
CSRF_TOKEN = secrets.token_urlsafe(32)
GZIP_MIN_BYTES = 1024
QVALUE_PATTERN = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)")


def _release_revision() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(RELEASE_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


# Immutable for this process and derived from the app release checkout, never from
# the separately refreshed data clone.
APP_REVISION = os.environ.get("KG_BOARD_APP_REVISION") or _release_revision() or "unknown"


def _configured_hosts() -> frozenset[str]:
    raw = os.environ.get("KG_BOARD_ALLOWED_HOSTS")
    values = raw.split(",") if raw else [BIND]
    return frozenset(value.strip().lower() for value in values if value.strip())


ALLOWED_HOSTS = _configured_hosts()

LOG_PATH = STATE_DIR / "kg-board.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP = 3

OVERLAY_PATH = STATE_DIR / "overlay.json"
MIRROR_PATH = STATE_DIR / "mirror.json"

RESOLVED_STATUSES = ("fixed", "wont-fix")

# Read-only observability classification.  This is deliberately based on the
# ticket's declared code/document location, not its category: ``tool`` spans
# several areas and would answer the user's question with a misleading bucket.
# Keep the evidence in the projection so the UI can say what the classification
# means instead of presenting a heuristic as ground truth.
AREA_RULES = (
    ("iOS", ("ios/",)),
    ("Backend", ("backend/",)),
    ("OPS / 底層工具", ("ops/", "devops.sh", ".github/workflows/")),
    ("文件 / 流程", ("docs/", ".claude/")),
    ("Lab / Podcast", ("lab/",)),
    ("KG 看板", ("kg-board",)),
)
AREA_ORDER = tuple(label for label, _ in AREA_RULES) + ("跨域", "未標定")

_lock = threading.Lock()
_clone_lock = threading.RLock()
_state_lock = threading.RLock()
_cache: dict = {
    "valid": False,
    "sha": None,
    "registry_fingerprint": None,
    "entries": [],
    "dispatch_ids": [],
    "dispatch_meta": {},
    "local_held": {},
    "ungroomed_ids": [],
    "read_at": None,
    "error": None,
}
_refresh_state: dict = {"last_ok": None, "last_error": None, "last_attempt": None}


# ---------------------------------------------------------------- logging

def log(msg: str) -> None:
    line = f"{datetime.now(TZ).isoformat(timespec='seconds')} {msg}\n"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            # launchd's StandardOutPath does not rotate, so a long-lived KeepAlive
            # service silently fills the disk. Keep launchd's streams for crashes
            # and own the application log here.
            for i in range(LOG_KEEP - 1, 0, -1):
                older, newer = LOG_PATH.with_suffix(f".{i+1}"), LOG_PATH.with_suffix(f".{i}")
                if newer.exists():
                    newer.replace(older)
            LOG_PATH.replace(LOG_PATH.with_suffix(".1"))
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    sys.stderr.write(line)
    sys.stderr.flush()


# ---------------------------------------------------------------- data plane

def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(CLONE), *args],
                          capture_output=True, text=True, timeout=120)


def clone_head() -> str | None:
    proc = _git(["rev-parse", "HEAD"])
    return proc.stdout.strip() if proc.returncode == 0 else None


def _clone_head_probe() -> tuple[str | None, str | None]:
    try:
        sha = clone_head()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git rev-parse HEAD failed: {type(exc).__name__}: {exc}"
    if sha is None:
        return None, "git rev-parse HEAD failed: no revision returned"
    return sha, None


def _registry_fingerprint() -> tuple[
    tuple[bool, int | None, int | None, int | None] | None,
    str | None,
]:
    """Fingerprint the atomic worktree ledger used by backlog dispatch."""
    try:
        proc = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"registry common-dir failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return None, f"registry common-dir exited {proc.returncode}: {proc.stderr.strip()[:300]}"
    common_dir = proc.stdout.strip()
    if not common_dir:
        return None, "registry common-dir failed: no path returned"
    ledger = Path(common_dir).parent / ".cache" / "worktree_registry.json"
    try:
        stat = ledger.stat()
    except FileNotFoundError:
        return (False, None, None, None), None
    except OSError as exc:
        return None, f"registry fingerprint failed: {type(exc).__name__}: {exc}"
    return (True, stat.st_ino, stat.st_mtime_ns, stat.st_size), None


def _run_backlog(tool: Path, subcommand: str) -> tuple[subprocess.CompletedProcess | None, str | None]:
    try:
        return subprocess.run(
            [sys.executable, str(tool), subcommand, "--json"],
            cwd=str(CLONE), capture_output=True, text=True, timeout=180,
        ), None
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"backlog.py {subcommand} failed: {type(exc).__name__}: {exc}"


def refresh_clone() -> None:
    with _clone_lock:
        _refresh_clone_locked()


def _refresh_clone_locked() -> None:
    """fetch + hard reset onto origin/main.

    `reset --hard` rather than `pull`: this clone is never written to by anyone, so
    there is nothing to preserve and nothing to merge — and a pull that hits a
    conflict would wedge the board until someone ssh'd in. The overlay lives OUTSIDE
    the clone (`KG_BOARD_STATE`) precisely so this cannot touch it.
    """
    _refresh_state["last_attempt"] = datetime.now(TZ).isoformat(timespec="seconds")
    fetch = _git(["fetch", "--prune", "origin"])
    if fetch.returncode != 0:
        _refresh_state["last_error"] = f"fetch: {fetch.stderr.strip()[:300]}"
        return
    reset = _git(["reset", "--hard", "origin/main"])
    if reset.returncode != 0:
        _refresh_state["last_error"] = f"reset: {reset.stderr.strip()[:300]}"
        return
    _refresh_state["last_error"] = None
    _refresh_state["last_ok"] = _refresh_state["last_attempt"]


def read_entries(force: bool = False) -> dict:
    with _clone_lock:
        return _read_entries_locked(force)


def _read_entries_locked(force: bool = False) -> dict:
    """Shell out to the CLONE's own backlog.py.

    Shelling out rather than importing is the whole point: the reader is always the
    version that ships with the data. The complete canonical projection is cached
    on clone HEAD plus the exact atomic worktree-ledger fingerprint. Mirror claims
    remain a per-request overlay outside this cache.
    """
    sha, head_error = _clone_head_probe()
    registry_fingerprint = None
    registry_error = None
    if head_error is None:
        registry_fingerprint, registry_error = _registry_fingerprint()
    with _lock:
        has_successful_snapshot = _cache.get(
            "valid",
            _cache.get("error") is None and _cache.get("read_at") is not None,
        )
        if (
            not force
            and head_error is None
            and registry_error is None
            and has_successful_snapshot
            and _cache["error"] is None
            and _cache["sha"] == sha
            and _cache.get("registry_fingerprint") == registry_fingerprint
        ):
            return dict(_cache)
        cached_entries = None
        if (
            not force
            and sha is not None
            and has_successful_snapshot
            and _cache["sha"] == sha
        ):
            cached_entries = list(_cache["entries"])
    tool = CLONE / "ops" / "backlog.py"
    if head_error is not None:
        payload = {"sha": sha, "entries": [],
                   "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                   "ungroomed_ids": [],
                   "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                   "error": head_error}
    elif registry_error is not None:
        payload = {"sha": sha, "entries": [],
                   "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                   "ungroomed_ids": [],
                   "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                   "error": registry_error}
    elif not tool.exists():
        payload = {"sha": sha, "entries": [], "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                   "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                   "ungroomed_ids": [],
                   "error": f"no backlog CLI at {tool} — is {CLONE} a kg clone?"}
    else:
        list_proc = None
        invocation_error = None
        if cached_entries is None:
            list_proc, invocation_error = _run_backlog(tool, "list")
        dispatch_proc = None
        if invocation_error is None:
            dispatch_proc, invocation_error = _run_backlog(tool, "dispatch")
        if invocation_error is not None:
            payload = {"sha": sha, "entries": [],
                       "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                       "ungroomed_ids": [],
                       "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                       "error": invocation_error}
        else:
            failed = next(
                (p for p in (list_proc, dispatch_proc) if p is not None and p.returncode != 0),
                None,
            )
            if failed is not None:
                subcommand = "list" if failed is list_proc else "dispatch"
                payload = {"sha": sha, "entries": [],
                           "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                           "ungroomed_ids": [],
                           "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                           "error": (f"backlog.py {subcommand} exited {failed.returncode}: "
                                     f"{failed.stderr.strip()[:300]}")}
            else:
                final_registry_fingerprint, final_registry_error = _registry_fingerprint()
                if final_registry_error is not None:
                    payload = {"sha": sha, "entries": [],
                               "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                               "ungroomed_ids": [],
                               "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                               "error": f"final {final_registry_error}"}
                elif final_registry_fingerprint != registry_fingerprint:
                    payload = {"sha": sha, "entries": [],
                               "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                               "ungroomed_ids": [],
                               "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                               "error": "registry changed during canonical read"}
                else:
                    payload = None
            if failed is None and payload is None:
                try:
                    list_body = json.loads(list_proc.stdout) if list_proc is not None else None
                    dispatch_body = json.loads(dispatch_proc.stdout)
                    entries = (
                        cached_entries
                        if cached_entries is not None
                        else list_body.get("entries", [])
                    )
                    dispatch_entries = dispatch_body.get("entries", [])
                    dispatch_ids = {str(row["id"]) for row in dispatch_entries}
                    dispatch_meta = dispatch_body.get("dispatch") or {}
                    local_held = dispatch_body.get("held") or {}
                    blocked_ids = {
                        str(row["id"]) for row in dispatch_meta.get("withheld_blocked", [])
                        if isinstance(row, dict) and row.get("id")
                    }
                    unresolved_ids = {
                        str(row["id"]) for row in entries
                        if row.get("status") not in RESOLVED_STATUSES
                    }
                    # backlog.py is the sole groom predicate owner. Its list/dispatch
                    # metadata partitions unresolved into dispatch, held, blocked and
                    # the remainder (ungroomed), so this service never reimplements
                    # plan/acceptance/groomed_by rules.
                    ungroomed_ids = unresolved_ids - dispatch_ids - set(local_held) - blocked_ids
                    payload = {"sha": sha, "entries": entries,
                               "dispatch_ids": sorted(dispatch_ids),
                               "dispatch_meta": dispatch_meta,
                               "local_held": local_held,
                               "ungroomed_ids": sorted(ungroomed_ids),
                               "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                               "error": None}
                except json.JSONDecodeError as exc:
                    payload = {"sha": sha, "entries": [],
                               "dispatch_ids": [], "dispatch_meta": {}, "local_held": {},
                               "ungroomed_ids": [],
                               "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                               "error": f"backlog.py emitted non-JSON: {exc}"}
    if payload["error"] is None:
        final_sha, final_head_error = _clone_head_probe()
        if final_head_error is not None:
            payload = {
                "sha": sha,
                "entries": [],
                "dispatch_ids": [],
                "dispatch_meta": {},
                "local_held": {},
                "ungroomed_ids": [],
                "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                "error": f"final {final_head_error}",
            }
        elif final_sha != sha:
            payload = {
                "sha": final_sha,
                "entries": [],
                "dispatch_ids": [],
                "dispatch_meta": {},
                "local_held": {},
                "ungroomed_ids": [],
                "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                "error": (
                    "clone changed during canonical read: "
                    f"before={sha or 'unknown'} after={final_sha or 'unknown'}"
                ),
            }
    payload.setdefault("registry_fingerprint", registry_fingerprint)
    with _lock:
        # Keep the last good entries when a read fails: a board that blanks out on a
        # transient git error is less useful than one that shows stale data and says
        # so. `error` is surfaced on Health either way.
        has_successful_snapshot = _cache.get(
            "valid",
            _cache.get("error") is None and _cache.get("read_at") is not None,
        )
        if payload["error"] is None:
            payload["valid"] = True
            _cache.update(payload)
        elif not has_successful_snapshot:
            payload["valid"] = False
            _cache.update(payload)
        else:
            _cache["error"] = payload["error"]
        return dict(_cache)


def refresh_loop() -> None:
    while True:
        try:
            refresh_clone()
            read_entries()
        except Exception as exc:                      # never let the thread die
            _refresh_state["last_error"] = f"{type(exc).__name__}: {exc}"
            log(f"refresh loop error: {exc}")
        time.sleep(REFRESH_SECONDS)


# ---------------------------------------------------------------- overlay

def _load_json(path: Path, default):
    with _state_lock:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default


def _save_json(path: Path, payload) -> None:
    with _state_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def _update_json(path: Path, default, update):
    """Serialize one complete read-modify-write transaction."""
    with _state_lock:
        current = _load_json(path, default)
        payload = update(current)
        _save_json(path, payload)
        return payload


def load_overlay(known_ids: set[str] | None = None) -> dict:
    """The phone's whole surface: rank / pin / snooze. Nothing else.

    Deliberately NOT stored in the repo. It is a per-person view preference, it
    changes far more often than the ledger, and putting it in git would recreate
    the write-amplification the store's one-file-per-entry layout exists to avoid.
    Deliberately NOT under `~/butler` either: Syncthing plus a file this service
    rewrites live is a conflict generator.

    Garbage-collected against the store on every read — an overlay row for an id
    that no longer exists is invisible in the UI but keeps the file growing, and a
    snooze whose date has passed must stop hiding its entry.
    """
    with _state_lock:
        data = _load_json(OVERLAY_PATH, {})
        if not isinstance(data, dict):
            return {}
        today = datetime.now(TZ).date().isoformat()
        cleaned, dropped = {}, 0
        for entry_id, row in data.items():
            if known_ids is not None and entry_id not in known_ids:
                dropped += 1
                continue
            row = dict(row) if isinstance(row, dict) else {}
            if row.get("snooze_until") and row["snooze_until"] <= today:
                row.pop("snooze_until", None)
            if row.get("rank") is None and not row.get("pinned") and not row.get("snooze_until"):
                dropped += 1
                continue
            cleaned[entry_id] = row
        if dropped:
            _save_json(OVERLAY_PATH, cleaned)
            log(f"overlay gc: dropped {dropped} stale row(s), {len(cleaned)} remain")
        return cleaned


def mirror_held_claims() -> dict:
    """Ticket id -> the worktree record holding it, from the mirror oscar pushes.

    Deliberately NO expiry. A claim is released by `resolve`/`sweep`, not by the
    passage of time, so a stale mirror makes this map INCOMPLETE (a claim taken
    since the last push is missing) — never wrong about the claims it does list.
    Subtracting a stale-but-still-true claim costs one hidden row that reappears
    on the next push; not subtracting it costs two sessions on one ticket.

    Reads `records` for the branch name and falls back to the flat `tickets_held`
    list, so an older payload shape still suppresses the row even if it cannot
    say who holds it.
    """
    claims = (_load_json(MIRROR_PATH, {}) or {}).get("claims") or {}
    held: dict[str, dict] = {}
    for rec in claims.get("records") or []:
        for ticket in rec.get("backlog") or []:
            held[str(ticket)] = {"branch": rec.get("branch"),
                                 "claimed_at": rec.get("claimed_at"),
                                 "intent": rec.get("intent")}
    for ticket in claims.get("tickets_held") or []:
        held.setdefault(str(ticket), {"branch": None, "claimed_at": None,
                                      "intent": None})
    return held


def merge_held_claims(local: dict, mirror: dict) -> dict:
    merged: dict[str, dict] = {}
    for source, records in (("mirror", mirror), ("local", local)):
        for ticket, raw in (records or {}).items():
            row = dict(raw) if isinstance(raw, dict) else {}
            prior = merged.get(str(ticket), {})
            sources = set(prior.get("sources") or [])
            sources.add(source)
            # Local registry data is authoritative for this machine and is applied
            # second; mirror remains evidence that another machine may also hold it.
            merged[str(ticket)] = {**prior, **row, "sources": sorted(sources)}
    return merged


# ---------------------------------------------------------------- projection

def classify_area(entry: dict) -> tuple[str, str]:
    """Return a stable area label and the field used as its evidence.

    ``fix_site`` is the strongest signal.  The fallback to ``surface`` keeps
    product tickets visible when a ticket has not yet named a code path.  A
    multi-area fix is intentionally called ``跨域`` rather than assigned to an
    arbitrary first match.
    """
    fix_site = str(entry.get("fix_site") or "").strip()
    if fix_site:
        haystack = fix_site.lower()
        hits = [label for label, needles in AREA_RULES
                if any(needle.lower() in haystack for needle in needles)]
        if len(hits) == 1:
            return hits[0], "fix_site"
        if len(hits) > 1:
            return "跨域", "fix_site"
    surface = str(entry.get("surface") or "").strip()
    if surface:
        return f"產品 / {surface}", "surface"
    return "未標定", "未提供 fix_site / surface"


def project(
    entries: list[dict],
    overlay: dict,
    held: dict | None = None,
    *,
    canonical_dispatch_ids: set[str] | None = None,
    canonical_ungroomed_ids: set[str] | None = None,
    dispatch_meta: dict | None = None,
) -> dict:
    today = datetime.now(TZ).date().isoformat()
    held = held or {}
    canonical_dispatch_ids = canonical_dispatch_ids or set()
    canonical_ungroomed_ids = canonical_ungroomed_ids or set()
    dispatch_meta = dispatch_meta or {}
    unresolved = [e for e in entries if e.get("status") not in RESOLVED_STATUSES]
    ready = [e for e in unresolved if e["id"] not in canonical_ungroomed_ids]
    sev_order = {"high": 0, "med": 1, "low": 2}

    def decorate(e: dict) -> dict:
        ov = overlay.get(e["id"], {})
        area, area_evidence = classify_area(e)
        return {
            "id": e["id"], "stream": e.get("stream"), "status": e.get("status"),
            "severity": e.get("severity"), "category": e.get("category"),
            "date": e.get("date"), "source": e.get("source"),
            "brief": e.get("brief") or "", "scope": e.get("scope") or "",
            "detail": (e.get("detail") or "")[:400],
            "fix_site": (e.get("fix_site") or "")[:200],
            "plan": (e.get("plan") or "")[:400],
            "acceptance": (e.get("acceptance") or "")[:200],
            "groomed_by": e.get("groomed_by"), "groomed_at": e.get("groomed_at"),
            "verdict": e.get("verdict"), "surface": e.get("surface"),
            "area": area, "area_evidence": area_evidence,
            "ready": e["id"] not in canonical_ungroomed_ids,
            "canonical_dispatch": e["id"] in canonical_dispatch_ids,
            "rank": ov.get("rank"), "pinned": bool(ov.get("pinned")),
            "snooze_until": ov.get("snooze_until"),
            "snoozed": bool(ov.get("snooze_until") and ov["snooze_until"] > today),
            "held": held.get(e["id"]),
        }

    def sort_key(row: dict):
        return (0 if row["pinned"] else 1,
                row["rank"] if row["rank"] is not None else 10**6,
                sev_order.get(row["severity"], 9),
                row["date"] or "")

    board = sorted((decorate(e) for e in unresolved), key=sort_key)
    # Canonical eligibility belongs to backlog.py dispatch. The phone's personal
    # snooze is deliberately not a clause; the clone cannot see oscar's per-machine
    # registry, so mirrored claims are the one additional suppression applied here.
    canonical = [r for r in board if r["canonical_dispatch"]]
    dispatch = [r for r in canonical if not r["held"]]
    # Exactly the rows hidden from the Now presentation. Canonical dispatch and
    # its metric remain unchanged; All still contains these rows for undo.
    deferred = [r for r in dispatch if r["snoozed"]]
    blocked_ids = {
        str(row.get("id")) for row in dispatch_meta.get("withheld_blocked", [])
        if isinstance(row, dict) and row.get("id")
    }
    blocked = [r for r in board if r["id"] in blocked_ids]
    # A PARTITION of `unresolved`, in this precedence, so the four segments sum to
    # it exactly and the bar cannot show a lie. A row can be both held and snoozed;
    # without a precedence the segments would overlap and the widths would exceed
    # the whole.
    def bucket(r: dict) -> str:
        if r["held"]:
            return "held"
        if not r["ready"]:
            return "ungroomed"
        if r["snoozed"]:
            return "snoozed"
        if r["canonical_dispatch"]:
            return "dispatch"
        return "blocked"
    segments = {k: 0 for k in ("dispatch", "held", "snoozed", "blocked", "ungroomed")}
    for r in board:
        segments[bucket(r)] += 1
    dispatch_ids = {r["id"] for r in dispatch}
    area_names = list(AREA_ORDER)
    area_names.extend(sorted({r["area"] for r in board if r["area"] not in area_names}))
    by_area = {}
    for area in area_names:
        rows = [r for r in board if r["area"] == area]
        if not rows:
            continue
        by_area[area] = {
            "unresolved": len(rows),
            "high": sum(1 for r in rows if r["severity"] == "high"),
            "ready": sum(1 for r in rows if r["ready"]),
            "dispatch": sum(1 for r in rows if r["id"] in dispatch_ids),
            "held": sum(1 for r in rows if r["held"]),
            "ungroomed": sum(1 for r in rows if not r["ready"]),
        }
    return {
        "board": board,
        "dispatch": dispatch,
        "deferred": deferred,
        "blocked": blocked,
        "dispatch_meta": dispatch_meta,
        "segments": segments,
        "counts": {
            # Readiness comes from canonical backlog list/dispatch metadata.
            "total": len(entries),
            "unresolved": len(unresolved),
            "ready": len(ready),
            "ready_definition": "KG CLI groomed clause (list/dispatch metadata)",
            "dispatch": len(dispatch),
            "canonical_dispatch": len(canonical),
            "claims_subtracted": sum(1 for r in canonical if r["held"]),
            "mirror_claims_subtracted": sum(
                1 for r in canonical
                if r["held"] and "mirror" in set(r["held"].get("sources") or ["mirror"])
            ),
            "local_claims_subtracted": sum(
                1 for r in canonical
                if r["held"] and "local" in set(r["held"].get("sources") or [])
            ),
            "held": sum(1 for r in board if r["held"]),
            "dispatch_definition": "KG CLI dispatch ∧ ¬mirror-claimed; personal snooze not applied",
            "by_severity": {s: sum(1 for e in unresolved if e.get("severity") == s)
                            for s in ("high", "med", "low")},
            "by_stream": {s: sum(1 for e in unresolved if e.get("stream") == s)
                          for s in ("IMP", "APP")},
            "by_area": by_area,
            "area_definition": "依 fix_site 分類；多個領域為跨域，沒有 fix_site 時回退 surface，仍無法判定則未標定",
            "held_sources": {
                kind: sum(
                    1 for r in board
                    if r["held"] and (
                        (kind == "both" and set(r["held"].get("sources") or ["mirror"]) == {"local", "mirror"})
                        or (kind != "both" and set(r["held"].get("sources") or ["mirror"]) == {kind})
                    )
                )
                for kind in ("local", "mirror", "both")
            },
            "decision": {
                "now": len(dispatch),
                "inflight": sum(1 for r in board if r["held"]),
                "blocked": len(blocked),
                "ungroomed": segments["ungroomed"],
                "deferred": len(deferred),
            },
            "history": {
                "total": len(entries),
                "fixed": sum(1 for e in entries if e.get("status") == "fixed"),
                "wont_fix": sum(1 for e in entries if e.get("status") == "wont-fix"),
            },
        },
    }


def _nonnegative_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def freshness() -> dict:
    mirror = _load_json(MIRROR_PATH, {})
    with _lock:
        snap = dict(_cache)
    lag = None
    src = mirror.get("sync_state", {}).get("at")
    if src:
        try:
            lag = int((datetime.now(TZ) - datetime.fromisoformat(src)).total_seconds())
        except ValueError:
            lag = None
    clone_lag_error = None
    try:
        behind_proc = _git(["rev-list", "--count", "HEAD..origin/main"])
        clone_behind_origin = (
            _nonnegative_int(behind_proc.stdout.strip()) if behind_proc.returncode == 0 else None
        )
        if behind_proc.returncode != 0:
            clone_lag_error = f"git rev-list: {behind_proc.stderr.strip()[:300]}"
    except (OSError, subprocess.SubprocessError) as exc:
        clone_behind_origin = None
        clone_lag_error = f"git rev-list: {type(exc).__name__}: {exc}"
    sync_state = mirror.get("sync_state") or {}
    local_ahead = _nonnegative_int(sync_state.get("ahead_count"))
    if (snap.get("error") is not None or _refresh_state.get("last_error") is not None
            or clone_lag_error is not None):
        freshness_state = "error"
    elif clone_behind_origin is None or local_ahead is None:
        freshness_state = "unknown"
    elif clone_behind_origin > 0 or local_ahead > 0:
        freshness_state = "stale"
    else:
        freshness_state = "current"
    return {
        "app_revision": APP_REVISION,
        "clone": str(CLONE),
        "clone_head": snap.get("sha"),
        "clone_behind_origin": clone_behind_origin,
        "clone_lag_error": clone_lag_error,
        "local_ahead": local_ahead,
        "local_main_sha": sync_state.get("local_main_sha"),
        "local_sync_at": sync_state.get("at"),
        "freshness_state": freshness_state,
        "entries_read_at": snap.get("read_at"),
        "read_error": snap.get("error"),
        "refresh": dict(_refresh_state),
        "refresh_seconds": REFRESH_SECONDS,
        "mirror": mirror,
        "seconds_since_origin_push": lag,
        "now": datetime.now(TZ).isoformat(timespec="seconds"),
    }


def board_payload() -> dict:
    snap = read_entries()
    entries = snap["entries"]
    overlay = load_overlay({e["id"] for e in entries})
    held = merge_held_claims(snap.get("local_held") or {}, mirror_held_claims())
    projected = project(
        entries,
        overlay,
        held,
        canonical_dispatch_ids=set(snap.get("dispatch_ids") or []),
        canonical_ungroomed_ids=set(snap.get("ungroomed_ids") or []),
        dispatch_meta=snap.get("dispatch_meta") or {},
    )

    def compact(row: dict) -> dict:
        return {
            "id": row["id"],
            "brief": row["brief"],
            "detail": row.get("detail") or row.get("scope") or "",
            "severity": row["severity"],
            "stream": row["stream"],
            "held": row["held"],
            "ready": row["ready"],
            "pinned": row["pinned"],
            "snoozed": row["snoozed"],
            "rank": row["rank"],
        }

    return {
        "schema": "kg.board.v2",
        "board": [compact(row) for row in projected["board"]],
        "dispatch_ids": [row["id"] for row in projected["dispatch"]],
        "blocked_ids": [row["id"] for row in projected["blocked"]],
        "deferred_ids": [row["id"] for row in projected["deferred"]],
        "dispatch_meta": projected["dispatch_meta"],
        "segments": projected["segments"],
        "counts": projected["counts"],
        "freshness": freshness(),
    }


def git_tree_payload() -> dict:
    """Return the mirrored Git/worktree graph with canonical ticket annotations."""
    mirror = _load_json(MIRROR_PATH, {}) or {}
    entries = read_entries().get("entries") or []
    tickets = {
        str(entry.get("id")): {
            "brief": entry.get("brief") or "",
            "severity": entry.get("severity"),
        }
        for entry in entries if entry.get("id")
    }
    payload = project_snapshot(mirror.get("git_tree"), tickets)
    payload["freshness"] = freshness()
    return payload


def health_payload() -> dict:
    snap = freshness()
    ok = (snap["read_error"] is None and snap["refresh"]["last_error"] is None
          and snap.get("clone_lag_error") is None)
    return {"ok": ok, **snap}


# ---------------------------------------------------------------- http

def read_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


TOKEN = ""


def _accepts_gzip(value: str) -> bool:
    for item in value.split(","):
        token, *parameters = item.split(";")
        if token.strip().lower() != "gzip":
            continue
        if not parameters:
            return True
        if len(parameters) != 1:
            continue
        name, separator, raw = parameters[0].partition("=")
        quality = raw.strip()
        if (
            separator
            and name.strip().lower() == "q"
            and QVALUE_PATTERN.fullmatch(quality)
            and float(quality) > 0.0
        ):
            return True
    return False


def _gzip_eligible(code: int, body: bytes, ctype: str) -> bool:
    if code < 200 or code in (204, 205, 304) or len(body) < GZIP_MIN_BYTES:
        return False
    media_type = ctype.split(";", 1)[0].strip().lower()
    # Deliberately opt in only the board/data plane. The HTML index embeds the
    # ephemeral CSRF token, so compressing it would create a BREACH-style length
    # oracle; static assets are not large enough to justify widening this boundary.
    return media_type == "application/json"


def render_index() -> bytes:
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    rendered = template.replace("{{CSRF_TOKEN}}", html.escape(CSRF_TOKEN, quote=True))
    rendered = rendered.replace(
        "{{APP_REVISION}}", html.escape(APP_REVISION or "unknown", quote=True)
    )
    return rendered.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "kg-board"

    def log_message(self, fmt, *args):          # launchd logs are for crashes
        pass

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        gzip_eligible = _gzip_eligible(code, body, ctype)
        content_encoding = None
        if gzip_eligible and _accepts_gzip(self.headers.get("Accept-Encoding", "")):
            compressed = gzip.compress(body, compresslevel=6, mtime=0)
            if len(compressed) < len(body):
                body = compressed
                content_encoding = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if content_encoding is not None:
            self.send_header("Content-Encoding", content_encoding)
        if gzip_eligible:
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return header.startswith("Bearer ") and header[7:].strip() == TOKEN

    def _json_precondition(self) -> str | None:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return "writes require Content-Type: application/json"
        return None

    def _priority_precondition(self) -> str | None:
        problem = self._json_precondition()
        if problem:
            return problem
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "").strip().lower()
        if host not in ALLOWED_HOSTS:
            return f"configured host required (Host {host!r} not in allowlist)"
        parsed = urllib.parse.urlparse(origin or "")
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != host:
            return f"same-origin write required (Origin {origin!r} != Host {host!r})"
        supplied = self.headers.get("X-KG-CSRF", "")
        if not supplied or not hmac.compare_digest(supplied, CSRF_TOKEN):
            return "missing or bad csrf token"
        return None

    def _mirror_precondition(self) -> str | None:
        problem = self._json_precondition()
        if problem:
            return problem
        if not self._authorized():
            return "missing or bad bearer token"
        return None

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            raise ValueError("empty or oversized body")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if REQUIRE_TOKEN_FOR_READS and not self._authorized():
            self._json(401, {"error": "token required for reads (KG_BOARD_REQUIRE_TOKEN=1)"})
            return
        if path == "/healthz":
            payload = health_payload()
            self._json(200 if payload["ok"] else 503, payload)
            return
        if path in ("/", "/index.html"):
            self._send(200, render_index(), "text/html; charset=utf-8")
            return
        if path == "/assets/app.css":
            self._send(200, (WEB_DIR / "app.css").read_bytes(), "text/css; charset=utf-8")
            return
        if path == "/assets/app.js":
            self._send(200, (WEB_DIR / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            return
        if path == "/api/board":
            self._json(200, board_payload())
            return
        if path == "/api/git-tree":
            self._json(200, git_tree_payload())
            return
        self._json(404, {"error": f"no such path: {path}"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/priority":
            problem = self._priority_precondition()
        elif path in ("/api/mirror/claims", "/api/mirror/sync-state", "/api/mirror/git-tree"):
            problem = self._mirror_precondition()
        else:
            self._json(404, {"error": f"no such path: {path}"})
            return
        if problem:
            self._json(401 if "bearer" in problem else 403, {"error": problem})
            return
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"bad body: {exc}"})
            return

        if path == "/api/priority":
            # The phone's ENTIRE write surface: rank, pin, snooze. Claiming is not
            # here on purpose — a claim must be atomic against the worktree ledger
            # on the machine that owns the worktrees, and a phone cannot be that.
            entry_id = str(body.get("id") or "").strip()
            if not entry_id:
                self._json(400, {"error": "id is required"})
                return
            def update_priority(current):
                overlay = dict(current) if isinstance(current, dict) else {}
                row = dict(overlay.get(entry_id) or {})
                if "rank" in body:
                    row["rank"] = None if body["rank"] is None else int(body["rank"])
                if "pinned" in body:
                    row["pinned"] = bool(body["pinned"])
                if "snooze_days" in body:
                    days = int(body["snooze_days"])
                    row["snooze_until"] = (
                        None if days <= 0
                        else (datetime.now(TZ).date() + timedelta(days=days)).isoformat())
                overlay[entry_id] = row
                return overlay

            overlay = _update_json(OVERLAY_PATH, {}, update_priority)
            row = overlay[entry_id]
            log(f"priority {entry_id}: {row}")
            self._json(200, {"ok": True, "id": entry_id, "overlay": row})
            return

        if path in ("/api/mirror/claims", "/api/mirror/sync-state", "/api/mirror/git-tree"):
            # Pushed by oscar (`com.kg.sync`). The board cannot read oscar's ledger
            # or its local main — both live on a laptop that sleeps — so oscar
            # reports and this stores verbatim.
            key = ("claims" if path.endswith("claims") else
                   "sync_state" if path.endswith("sync-state") else "git_tree")
            def update_mirror(current):
                mirror = dict(current) if isinstance(current, dict) else {}
                mirror[key] = body
                mirror[f"{key}_received_at"] = datetime.now(TZ).isoformat(timespec="seconds")
                return mirror

            _update_json(MIRROR_PATH, {}, update_mirror)
            self._json(200, {"ok": True, "stored": key})
            return

        self._json(404, {"error": f"no such path: {path}"})



def main() -> int:
    global TOKEN
    TOKEN = read_token()
    if not TOKEN:
        # Fail-closed, and loudly. A board that starts without auth and only refuses
        # writes at request time reads as a config typo, not as an open service.
        sys.stderr.write(
            f"kg-board: refusing to start — no token in {TOKEN_FILE}.\n"
            f"  create it with:  umask 077 && openssl rand -hex 32 > {TOKEN_FILE}\n")
        return 78                                     # sysexits EX_CONFIG
    if not CLONE.exists():
        sys.stderr.write(
            f"kg-board: refusing to start — no clone at {CLONE}.\n"
            f"  create it with:  git clone <kg remote> {CLONE}\n")
        return 78
    if CLONE.resolve() == RELEASE_ROOT.resolve():
        sys.stderr.write(
            "kg-board: refusing to start — mutable data clone and immutable app "
            "release checkout must be different paths.\n"
        )
        return 78
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    host, _, port = BIND.rpartition(":")
    threading.Thread(target=refresh_loop, daemon=True).start()
    server = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    log(f"kg-board listening on {BIND}; clone={CLONE} refresh={REFRESH_SECONDS}s "
        f"reads_need_token={REQUIRE_TOKEN_FOR_READS}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

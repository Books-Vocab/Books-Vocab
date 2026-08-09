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
* **寫入端點一律要 Bearer token**，即使在 tailnet 內。理由是 tailnet 內的瀏覽器
  可能被惡意頁面誘導對本服務發 POST（CSRF）。三道一起擋：
    - `Content-Type` 必須是 `application/json`（HTML form 發不出這個 content type）
    - `Origin` 若存在必須同源
    - `Authorization: Bearer <token>`，token 取自 `~/.secrets/kg-board.token`
* **fail-closed**：token 檔不存在或為空 → 服務**拒絕啟動**。一個沒有認證卻在跑的
  看板，比沒有看板更糟；而「啟動成功但寫入永遠 401」會讓人以為只是設定錯。
* 若之後放到 Cloudflare Tunnel 對外，設 `KG_BOARD_REQUIRE_TOKEN=1`，連讀取也要
  token——因為那時可達性不再等於身分。

「已梳理」只有一個定義
----------------------
`plan ∧ acceptance ∧ groomed_by`（`READY_FIELDS`）。這個 repo 今天有三種互相矛盾
的算法，而 `_check_groom` 沒有 `groomed_by` 就直接短路返回，所以少了它的「已梳理」
是沒被任何規則檢查過的自稱。**本服務任何一頁都不得出現第二個數字。**
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

HOME = Path.home()
CLONE = Path(os.environ.get("KG_BOARD_CLONE", HOME / "kg-board"))
STATE_DIR = Path(os.environ.get("KG_BOARD_STATE", HOME / "kg-board-state"))
TOKEN_FILE = Path(os.environ.get("KG_BOARD_TOKEN_FILE", HOME / ".secrets" / "kg-board.token"))
BIND = os.environ.get("KG_BOARD_BIND", "127.0.0.1:8007")
REFRESH_SECONDS = int(os.environ.get("KG_BOARD_REFRESH_SECONDS", "60"))
REQUIRE_TOKEN_FOR_READS = os.environ.get("KG_BOARD_REQUIRE_TOKEN") == "1"

LOG_PATH = STATE_DIR / "kg-board.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP = 3

OVERLAY_PATH = STATE_DIR / "overlay.json"
MIRROR_PATH = STATE_DIR / "mirror.json"

# The one definition. See the module docstring.
READY_FIELDS = ("plan", "acceptance", "groomed_by")
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
_cache: dict = {
    "sha": None,
    "entries": [],
    "dispatch_ids": [],
    "dispatch_meta": {},
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


def refresh_clone() -> None:
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
    """Shell out to the CLONE's own backlog.py. Cached on the clone's HEAD sha.

    Shelling out rather than importing is the whole point: the reader is always the
    version that ships with the data. Caching on the sha rather than on a clock
    means a refresh that changed nothing costs nothing, and one that changed
    something is picked up on the very next request.
    """
    sha = clone_head()
    with _lock:
        if not force and sha is not None and _cache["sha"] == sha and _cache["entries"]:
            return dict(_cache)
    tool = CLONE / "ops" / "backlog.py"
    if not tool.exists():
        payload = {"sha": sha, "entries": [], "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                   "error": f"no backlog CLI at {tool} — is {CLONE} a kg clone?"}
    else:
        list_proc = subprocess.run([sys.executable, str(tool), "list", "--json"],
                                   cwd=str(CLONE), capture_output=True, text=True, timeout=180)
        dispatch_proc = subprocess.run([sys.executable, str(tool), "dispatch", "--json"],
                                       cwd=str(CLONE), capture_output=True, text=True, timeout=180)
        failed = next((p for p in (list_proc, dispatch_proc) if p.returncode != 0), None)
        if failed is not None:
            subcommand = "list" if failed is list_proc else "dispatch"
            payload = {"sha": sha, "entries": [],
                       "dispatch_ids": [], "dispatch_meta": {},
                       "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                       "error": (f"backlog.py {subcommand} exited {failed.returncode}: "
                                 f"{failed.stderr.strip()[:300]}")}
        else:
            try:
                list_body = json.loads(list_proc.stdout)
                dispatch_body = json.loads(dispatch_proc.stdout)
                dispatch_entries = dispatch_body.get("entries", [])
                payload = {"sha": sha, "entries": list_body.get("entries", []),
                           "dispatch_ids": [str(row["id"]) for row in dispatch_entries],
                           "dispatch_meta": dispatch_body.get("dispatch") or {},
                           "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                           "error": None}
            except json.JSONDecodeError as exc:
                payload = {"sha": sha, "entries": [],
                           "dispatch_ids": [], "dispatch_meta": {},
                           "read_at": datetime.now(TZ).isoformat(timespec="seconds"),
                           "error": f"backlog.py emitted non-JSON: {exc}"}
    with _lock:
        # Keep the last good entries when a read fails: a board that blanks out on a
        # transient git error is less useful than one that shows stale data and says
        # so. `error` is surfaced on Health either way.
        if payload["error"] is None or not _cache["entries"]:
            _cache.update(payload)
        else:
            _cache["error"] = payload["error"]
            _cache["read_at"] = payload["read_at"]
        return dict(_cache)


def refresh_loop() -> None:
    while True:
        try:
            refresh_clone()
            read_entries(force=True)
        except Exception as exc:                      # never let the thread die
            _refresh_state["last_error"] = f"{type(exc).__name__}: {exc}"
            log(f"refresh loop error: {exc}")
        time.sleep(REFRESH_SECONDS)


# ---------------------------------------------------------------- overlay

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


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


def held_claims() -> dict:
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


# ---------------------------------------------------------------- projection

def is_ready(entry: dict) -> bool:
    return all(str(entry.get(f) or "").strip() for f in READY_FIELDS)


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
    dispatch_meta: dict | None = None,
) -> dict:
    today = datetime.now(TZ).date().isoformat()
    held = held or {}
    canonical_dispatch_ids = canonical_dispatch_ids or set()
    dispatch_meta = dispatch_meta or {}
    unresolved = [e for e in entries if e.get("status") not in RESOLVED_STATUSES]
    ready = [e for e in unresolved if is_ready(e)]
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
            "ready": is_ready(e),
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
    # A PARTITION of `unresolved`, in this precedence, so the four segments sum to
    # it exactly and the bar cannot show a lie. A row can be both held and snoozed;
    # without a precedence the segments would overlap and the widths would exceed
    # the whole.
    def bucket(r: dict) -> str:
        if not r["ready"]:
            return "ungroomed"
        if r["held"]:
            return "held"
        if r["canonical_dispatch"]:
            return "dispatch"
        if r["snoozed"]:
            return "snoozed"
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
        "dispatch_meta": dispatch_meta,
        "segments": segments,
        "counts": {
            # ONE definition of ready. Do not add a second number to any page.
            # `dispatch` below is NOT a second reading of ready: it is ready minus
            # the two suppressions, and the page must show both or a row that
            # vanishes has no visible reason.
            "total": len(entries),
            "unresolved": len(unresolved),
            "ready": len(ready),
            "ready_definition": " ∧ ".join(READY_FIELDS),
            "dispatch": len(dispatch),
            "canonical_dispatch": len(canonical),
            "mirror_claims_subtracted": sum(1 for r in canonical if r["held"]),
            "held": sum(1 for r in board if r["held"]),
            "dispatch_definition": "KG CLI dispatch ∧ ¬mirror-claimed; personal snooze not applied",
            "by_severity": {s: sum(1 for e in unresolved if e.get("severity") == s)
                            for s in ("high", "med", "low")},
            "by_stream": {s: sum(1 for e in unresolved if e.get("stream") == s)
                          for s in ("IMP", "APP")},
            "by_area": by_area,
            "area_definition": "依 fix_site 分類；多個領域為跨域，沒有 fix_site 時回退 surface，仍無法判定則未標定",
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
    return {
        **project(
            entries,
            overlay,
            held_claims(),
            canonical_dispatch_ids=set(snap.get("dispatch_ids") or []),
            dispatch_meta=snap.get("dispatch_meta") or {},
        ),
        "freshness": freshness(),
    }


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


class Handler(BaseHTTPRequestHandler):
    server_version = "kg-board"

    def log_message(self, fmt, *args):          # launchd logs are for crashes
        pass

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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

    def _write_precondition(self) -> str | None:
        """Three checks, each blocking a different thing. See the module docstring.

        Content-Type first because it is the one an HTML form cannot forge: a
        cross-origin form POST can only send urlencoded / multipart / plain text.
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            return "writes require Content-Type: application/json"
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if urllib.parse.urlparse(origin).netloc != host:
                return f"cross-origin write refused (Origin {origin!r} != Host {host!r})"
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
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/board":
            self._json(200, board_payload())
            return
        self._json(404, {"error": f"no such path: {path}"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        problem = self._write_precondition()
        if problem:
            self._json(403 if "token" not in problem else 401, {"error": problem})
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
            overlay = _load_json(OVERLAY_PATH, {})
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
            _save_json(OVERLAY_PATH, overlay)
            log(f"priority {entry_id}: {row}")
            self._json(200, {"ok": True, "id": entry_id, "overlay": row})
            return

        if path in ("/api/mirror/claims", "/api/mirror/sync-state"):
            # Pushed by oscar (`com.kg.sync`). The board cannot read oscar's ledger
            # or its local main — both live on a laptop that sleeps — so oscar
            # reports and this stores verbatim.
            key = "claims" if path.endswith("claims") else "sync_state"
            mirror = _load_json(MIRROR_PATH, {})
            mirror[key] = body
            mirror[f"{key}_received_at"] = datetime.now(TZ).isoformat(timespec="seconds")
            _save_json(MIRROR_PATH, mirror)
            self._json(200, {"ok": True, "stored": key})
            return

        self._json(404, {"error": f"no such path: {path}"})


LEGACY_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>kg 懸賞板</title>
<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#111;--dim:#666;--line:#e3e3e3;--card:#fafafa;--hi:#0b5;--warn:#c60}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--dim:#999;--line:#2a2a2a;--card:#181818}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 14px;z-index:2}
h1{margin:0 0 8px;font-size:17px;font-weight:600}
nav button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:6px 13px;margin-right:6px;font-size:14px}
nav button[aria-selected=true]{background:var(--fg);color:var(--bg)}
main{padding:12px 14px 60px;max-width:900px;margin:0 auto}
.counts{color:var(--dim);font-size:13px;margin:4px 0 12px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:10px 0 6px}
.bar i{display:block;height:100%}
.bar i.dispatch{background:#0b5}.bar i.held{background:#c60}
.bar i.snoozed{background:#89a}.bar i.ungroomed{background:var(--line);box-shadow:inset 0 0 0 1px var(--dim)}
.bar.sev{height:8px;border-radius:4px;margin:8px 0 4px}
.bar.sev i.high{background:#d33}.bar.sev i.med{background:#e9a13b}.bar.sev i.low{background:#8bb}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--dim);margin-bottom:12px}
.legend b{font-weight:600;color:var(--fg)}
.legend span::before{content:'';display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px;background:var(--k)}
.brief{font-size:15px;margin:6px 0 4px}
.scope{font-size:13px;color:var(--dim);margin-bottom:4px}
details.more{margin-top:4px}
details.more summary{font-size:12px;color:var(--dim);cursor:pointer}
.card{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:10px 12px;margin-bottom:9px}
.row1{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.tag{font-size:11px;border:1px solid var(--line);border-radius:4px;padding:1px 5px;color:var(--dim)}
.tag.high{color:#d33;border-color:#d33}.tag.ready{color:var(--hi);border-color:var(--hi)}
.tag.held{color:var(--warn);border-color:var(--warn)}
.detail{color:var(--dim);font-size:13px;margin-top:5px;white-space:pre-wrap;overflow-wrap:anywhere}
.acts{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}
.acts button{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:5px 10px;font-size:13px}
.pinned{border-color:var(--hi)}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto;font-size:12px}
.err{color:var(--warn)}
</style>
<header>
  <h1>kg 懸賞板</h1>
  <nav id=tabs>
    <button data-tab=board aria-selected=true>看板</button>
    <button data-tab=dispatch>可派工</button>
    <button data-tab=inflight>在飛</button>
    <button data-tab=health>健康</button>
  </nav>
</header>
<main><div class=counts id=counts>載入中…</div><div id=view></div></main>
<script>
let DATA=null, TAB='board', TOKEN=localStorage.getItem('kgBoardToken')||'';
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function load(){
  const r=await fetch('/api/board',{headers:TOKEN?{Authorization:'Bearer '+TOKEN}:{}});
  if(!r.ok){document.getElementById('counts').innerHTML='<span class=err>讀取失敗 '+r.status+'</span>';return}
  DATA=await r.json(); render();
}
async function post(path,body){
  if(!TOKEN){TOKEN=prompt('Bearer token（存在此裝置）')||'';localStorage.setItem('kgBoardToken',TOKEN)}
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+TOKEN},body:JSON.stringify(body)});
  if(!r.ok){alert('寫入失敗 '+r.status+': '+(await r.text()));return}
  await load();
}
function card(e){
  return '<div class="card'+(e.pinned?' pinned':'')+'">'
   +'<div class=row1><span class=id>'+esc(e.id)+'</span>'
   +'<span class="tag '+esc(e.severity)+'">'+esc(e.severity)+'</span>'
   +'<span class=tag>'+esc(e.stream)+'/'+esc(e.category)+'</span>'
   +'<span class=tag>'+esc(e.status)+'</span>'
   +(e.ready&&!e.held?'<span class="tag ready">可派工</span>':'')
   +(e.held?'<span class="tag held">認領中 '+esc(e.held.branch||'?')+'</span>':'')
   +(e.snoozed?'<span class=tag>延後到 '+esc(e.snooze_until)+'</span>':'')
   +(e.rank!=null?'<span class=tag>#'+esc(e.rank)+'</span>':'')+'</div>'
   // 有白話說明才把技術細節收起來。還沒回填的票維持原樣攤開——收起一段沒有替代品的
   // 內容，等於為了未來的整潔先讓今天變難用。
   +(e.brief?'<div class=brief>'+esc(e.brief)+'</div>':'')
   +(e.scope?'<div class=scope>動到：'+esc(e.scope)+'</div>':'')
   +(e.brief
      ?'<details class=more><summary>技術細節</summary><div class=detail>'+esc(e.detail)+'</div>'
        +(e.fix_site?'<div class=detail>修改點：'+esc(e.fix_site)+'</div>':'')+'</details>'
      :'<div class=detail>'+esc(e.detail)+'</div>'
        +(e.fix_site?'<div class=detail>修改點：'+esc(e.fix_site)+'</div>':''))
   +'<div class=acts>'
   +'<button onclick="post(\\'/api/priority\\',{id:\\''+e.id+'\\',pinned:'+(!e.pinned)+'})">'+(e.pinned?'取消釘選':'釘選')+'</button>'
   +'<button onclick="rank(\\''+e.id+'\\')">排序</button>'
   +'<button onclick="post(\\'/api/priority\\',{id:\\''+e.id+'\\',snooze_days:7})">延後 7 天</button>'
   +(e.snoozed?'<button onclick="post(\\'/api/priority\\',{id:\\''+e.id+'\\',snooze_days:0})">取消延後</button>':'')
   +'</div></div>';
}
function rank(id){const v=prompt('名次（留空清除）');post('/api/priority',{id:id,rank:v===''||v===null?null:parseInt(v,10)})}
function render(){
  const c=DATA.counts, s=DATA.segments, N=c.unresolved||1;
  const seg=(k,label,n)=>n?'<i class="'+k+'" style="width:'+(100*n/N)+'%" title="'+label+' '+n+'"></i>':'';
  const key=(col,label,n)=>'<span style="--k:'+col+'"><b>'+n+'</b> '+label+'</span>';
  document.getElementById('counts').innerHTML=
     '<div class=bar>'+seg('dispatch','可派工',s.dispatch)+seg('held','認領中',s.held)
       +seg('snoozed','延後',s.snoozed)+seg('ungroomed','未梳理',s.ungroomed)+'</div>'
    +'<div class=legend>'+key('#0b5','可派工',s.dispatch)+key('#c60','認領中',s.held)
       +key('#89a','延後',s.snoozed)+key('var(--line)','未梳理',s.ungroomed)
       +'<span style="--k:transparent">共 '+c.unresolved+' 未解（總數 '+c.total+'）</span></div>'
    +'<div class=bar-sev-wrap><div class="bar sev">'
       +'<i class=high style="width:'+(100*c.by_severity.high/N)+'%"></i>'
       +'<i class=med style="width:'+(100*c.by_severity.med/N)+'%"></i>'
       +'<i class=low style="width:'+(100*c.by_severity.low/N)+'%"></i></div>'
    +'<div class=legend>'+key('#d33','high',c.by_severity.high)+key('#e9a13b','med',c.by_severity.med)
       +key('#8bb','low',c.by_severity.low)
       +'<span style="--k:transparent">同一批 '+c.unresolved+' 張的另一種切法</span></div></div>';
  const v=document.getElementById('view');
  if(TAB==='board') v.innerHTML=DATA.board.filter(e=>!e.snoozed).map(card).join('')
     +'<div class=counts>延後中 '+DATA.board.filter(e=>e.snoozed).length+' 筆</div>'
     +DATA.board.filter(e=>e.snoozed).map(card).join('');
  else if(TAB==='dispatch') v.innerHTML=DATA.dispatch.length?DATA.dispatch.map(card).join('')
     :'<div class=counts>沒有可派工的單——先梳理（plan + acceptance + groomed_by 三者齊全才算）</div>';
  else if(TAB==='inflight'){
    const m=(DATA.freshness.mirror||{}).claims;
    const at=(DATA.freshness.mirror||{}).claims_received_at;
    if(!m){v.innerHTML='<div class=counts>oscar 還沒回報過認領狀態（com.kg.sync 未跑或未送達）</div>'}
    else{
      const recs=m.records||[];
      v.innerHTML='<div class=counts>'+recs.length+' 條工作樹在飛 · 回報於 '+esc(at||m.at||'?')
        +'（認領由 resolve 釋放，不會自己過期——這個時間只說明「新的認領有沒有到」）</div>'
        +(recs.length?recs.map(r=>'<div class=card><div class=row1>'
          +'<span class=id>'+esc(r.branch||'?')+'</span>'
          +(r.backlog||[]).map(t=>'<span class="tag held">'+esc(t)+'</span>').join('')
          +'</div><div class=detail>'+esc(r.intent||'')+'</div>'
          +'<div class=detail>認領於 '+esc(r.claimed_at||'?')+'</div></div>').join('')
          :'<div class=counts>沒有工作樹在飛</div>');
    }
  }
  else v.innerHTML='<pre>'+esc(JSON.stringify(DATA.freshness,null,2))+'</pre>';
  document.querySelectorAll('#tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===TAB));
}
document.getElementById('tabs').onclick=e=>{if(e.target.dataset.tab){TAB=e.target.dataset.tab;render()}};
load(); setInterval(load,30000);
</script>
"""


PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KG 工作進度</title>
<style>
:root{color-scheme:light dark;--bg:#f7f8fa;--fg:#17202a;--dim:#697586;--line:#dfe4ea;--card:#fff;--soft:#eef3f7;--accent:#1769aa;--good:#087f5b;--warn:#a15c00;--bad:#c92a2a}
@media(prefers-color-scheme:dark){:root{--bg:#101418;--fg:#eef2f6;--dim:#aab4c0;--line:#2c3640;--card:#171d23;--soft:#202a33;--accent:#75b7f0;--good:#63d4ad;--warn:#f0b05a;--bad:#ff8585}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
header{position:sticky;top:0;background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:14px 16px 10px;z-index:2}
.brand{max-width:1060px;margin:0 auto}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--accent);font-weight:700}.brand h1{margin:1px 0 0;font-size:22px;font-weight:700}.brand p{margin:2px 0 10px;color:var(--dim);font-size:13px}
nav{max-width:1060px;margin:0 auto;display:flex;gap:6px;overflow:auto}nav button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:7px 14px;white-space:nowrap;font-size:14px}nav button[aria-selected=true]{background:var(--fg);color:var(--bg)}
main{padding:16px 16px 64px;max-width:1060px;margin:0 auto}.notice{border:1px solid var(--line);background:var(--soft);border-radius:10px;padding:9px 12px;color:var(--dim);font-size:13px;margin-bottom:14px}.notice strong{color:var(--fg)}
.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin-bottom:16px}.metric{border:1px solid var(--line);background:var(--card);border-radius:12px;padding:12px}.metric .value{font-size:25px;font-weight:700;line-height:1.1}.metric .label{font-size:12px;color:var(--dim);margin-top:4px}.metric .note{font-size:11px;color:var(--dim);margin-top:3px}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:10px;margin:20px 0 9px}.section-head h2{margin:0;font-size:17px}.section-head p{margin:0;color:var(--dim);font-size:12px}
.areas{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.area-card{border:1px solid var(--line);background:var(--card);border-radius:12px;padding:12px;text-align:left;color:var(--fg);cursor:pointer;min-height:124px}.area-card:hover{border-color:var(--accent)}.area-title{font-weight:650;display:flex;justify-content:space-between;gap:8px}.area-total{font-size:24px;font-weight:700;line-height:1.1;margin-top:12px}.area-meta{color:var(--dim);font-size:12px;margin-top:3px}.area-meta b{color:var(--fg)}.area-bar{height:5px;background:var(--soft);border-radius:3px;margin-top:12px;overflow:hidden}.area-bar i{display:block;height:100%;background:var(--accent);border-radius:3px}
.fresh{border:1px solid var(--line);background:var(--card);border-radius:12px;padding:12px;margin-top:16px}.fresh.good{border-color:color-mix(in srgb,var(--good) 50%,var(--line))}.fresh.warn{border-color:color-mix(in srgb,var(--warn) 55%,var(--line))}.fresh.bad{border-color:color-mix(in srgb,var(--bad) 60%,var(--line))}.fresh-title{display:flex;justify-content:space-between;gap:8px;font-weight:650}.fresh-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:9px}.fresh-item{font-size:12px;color:var(--dim)}.fresh-item b{display:block;color:var(--fg);font-weight:500;overflow-wrap:anywhere}
.worktree{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:11px 12px;margin-bottom:9px}.worktree-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}.branch{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;font-weight:600}.claim-age{margin-left:auto;color:var(--dim);font-size:12px}.intent{margin-top:5px}.claim-tickets{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.claim-tickets .tag{color:var(--accent);border-color:var(--accent)}
.ticket,.card{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:11px 12px;margin-bottom:9px}.ticket-head{display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}.id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.tag{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:1px 6px;color:var(--dim)}.tag.area{color:var(--accent);border-color:var(--accent)}.tag.high{color:var(--bad);border-color:var(--bad)}.tag.ready{color:var(--good);border-color:var(--good)}.tag.held{color:var(--warn);border-color:var(--warn)}.brief{font-size:14px;margin:7px 0 2px}.scope,.detail{color:var(--dim);font-size:12px;margin-top:3px;overflow-wrap:anywhere}.detail{white-space:pre-wrap}.ticket details{margin-top:6px}.ticket summary{font-size:12px;color:var(--dim);cursor:pointer}
.search{width:100%;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:9px 11px;font-size:14px;margin:4px 0 12px}.empty{border:1px dashed var(--line);border-radius:10px;padding:18px;color:var(--dim);text-align:center}.muted{color:var(--dim);font-size:13px}.err{color:var(--bad)}pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:11px;overflow:auto;font-size:11px}
@media(max-width:760px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics .metric:first-child{grid-column:span 2}.areas{grid-template-columns:repeat(2,minmax(0,1fr))}.fresh-grid{grid-template-columns:1fr 1fr}.claim-age{margin-left:0;width:100%}}
@media(max-width:440px){.areas{grid-template-columns:1fr}.fresh-grid{grid-template-columns:1fr}.brand h1{font-size:20px}}
</style>
<header>
  <div class=brand><div class=eyebrow>KNOWLEDGE GRAPH</div><h1>工作進度</h1><p>只讀觀測：目前有哪些問題、各領域多少、團隊正在做什麼</p></div>
  <nav id=tabs>
    <button data-tab=overview aria-selected=true>總覽</button>
    <button data-tab=areas>領域</button>
    <button data-tab=inflight>在飛</button>
    <button data-tab=health>健康</button>
  </nav>
</header>
<main><div id=metrics></div><div id=view><div class=empty>載入中…</div></div></main>
<script>
let DATA=null,TAB='overview',AREA=null,QUERY='';
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>Number(v||0).toLocaleString('zh-TW');
const age=iso=>{if(!iso)return '未知';const d=Math.max(0,Math.floor((Date.now()-new Date(iso).getTime())/1000));return d<60?d+' 秒前':d<3600?Math.floor(d/60)+' 分鐘前':d<86400?Math.floor(d/3600)+' 小時前':Math.floor(d/86400)+' 天前'};
const shortSha=s=>s?s.slice(0,9):'未知';
function claims(){const m=(DATA.freshness.mirror||{}).claims;return {records:(m&&m.records)||[],at:(DATA.freshness.mirror||{}).claims_received_at||(m&&m.at)}}
function freshState(f){return f.read_error||f.refresh.last_error?'bad':(f.seconds_since_origin_push!=null&&f.seconds_since_origin_push>900?'warn':'good')}
function freshnessBox(){
  const f=DATA.freshness,s=freshState(f),c=claims();
  const title=s==='good'?'資料正常':s==='warn'?'資料可能落後':'資料讀取異常';
  const error=f.read_error||f.refresh.last_error;
  return '<section class="fresh '+s+'"><div class=fresh-title><span>'+title+'</span><span class=muted>每 '+n(f.refresh_seconds)+' 秒刷新</span></div>'
    +(error?'<div class="muted err">'+esc(error)+'</div>':'')
    +'<div class=fresh-grid><div class=fresh-item>資料版本<b>'+esc(shortSha(f.clone_head))+'</b></div>'
    +'<div class=fresh-item>資料讀取<b>'+esc(age(f.entries_read_at))+'</b></div>'
    +'<div class=fresh-item>origin/main 鏡像<b>'+esc(f.seconds_since_origin_push==null?'尚無回報':age(new Date(Date.now()-f.seconds_since_origin_push*1000).toISOString()))+'</b></div>'
    +'<div class=fresh-item>認領鏡像<b>'+esc(c.at?age(c.at):'尚無回報')+'</b></div>'
    +'<div class=fresh-item>刷新上次成功<b>'+esc(age(f.refresh.last_ok))+'</b></div>'
    +'<div class=fresh-item>工作樹認領<b>'+n(c.records.length)+' 條</b></div></div></section>';
}
function metric(label,value,note){return '<div class=metric><div class=value>'+n(value)+'</div><div class=label>'+label+'</div>'+(note?'<div class=note>'+note+'</div>':'')+'</div>'}
function areaEntries(){return Object.entries((DATA.counts&&DATA.counts.by_area)||{}).sort((a,b)=>b[1].unresolved-a[1].unresolved)}
function areaCard(label,s,max){
  return '<button class=area-card data-area="'+esc(label)+'"><div class=area-title><span>'+esc(label)+'</span><span class=tag>'+n(s.high)+' high</span></div>'
   +'<div class=area-total>'+n(s.unresolved)+' <span class=muted>未解</span></div>'
   +'<div class=area-meta><b>'+n(s.held)+'</b> 在飛 · <b>'+n(s.ready)+'</b> 已梳理 · <b>'+n(s.ungroomed)+'</b> 未梳理</div>'
   +'<div class=area-bar><i style="width:'+Math.round(100*s.unresolved/Math.max(1,max))+'%"></i></div></button>';
}
function ticket(e){
  return '<article class=ticket><div class=ticket-head><span class=id>'+esc(e.id)+'</span>'
   +'<span class="tag area">'+esc(e.area)+'</span><span class="tag '+esc(e.severity)+'">'+esc(e.severity)+'</span>'
   +'<span class=tag>'+esc(e.stream)+' / '+esc(e.category)+'</span>'
   +(e.ready?'<span class="tag ready">已梳理</span>':'<span class=tag>未梳理</span>')
   +(e.held?'<span class="tag held">認領中</span>':'')+'</div>'
   +(e.brief?'<div class=brief>'+esc(e.brief)+'</div>':'')
   +(e.scope?'<div class=scope>範圍：'+esc(e.scope)+'</div>':'')
   +'<details><summary>查看技術內容</summary><div class=detail>'+esc(e.detail||'尚無 detail')+'</div>'
   +(e.fix_site?'<div class=detail>修改位置：'+esc(e.fix_site)+'</div>':'')
   +'</details></article>';
}
function overview(){
  const c=DATA.counts,entries=areaEntries(),m=claims(),max=entries.length?entries[0][1].unresolved:1;
  return '<div class=notice><strong>這裡是觀測面，不是待辦清單。</strong> 可派工、未梳理與領域數量是狀態指標；認領與結案仍由工作流在本機完成。</div>'
   +'<div class=section-head><h2>問題總量</h2><p>共 '+n(c.total)+' 張票，已解 '+n(c.total-c.unresolved)+'</p></div>'
   +'<div class=metrics>'+metric('未解',c.unresolved,'目前仍需處理')+metric('在飛工作樹',m.records.length,'認領鏡像')+metric('可派工',c.dispatch,'狀態指標，不在此操作')+metric('未梳理',DATA.segments.ungroomed,'尚未進入派工')+metric('High',c.by_severity.high,'未解中的高優先')+'</div>'
   +'<div class=section-head><h2>各領域未解數</h2><p>按 fix_site 推定，點選只查看</p></div>'
   +'<div class=areas>'+entries.map(([label,s])=>areaCard(label,s,max)).join('')+'</div>'
   +freshnessBox()
   +'<div class=section-head><h2>目前在做</h2><p>'+n(m.records.length)+' 條工作樹</p></div>'
   +renderWorktrees(m.records,true);
}
function renderWorktrees(records,compact){
  if(!records.length)return '<div class=empty>目前沒有收到工作樹認領回報。</div>';
  return records.map(r=>'<article class=worktree><div class=worktree-head><span class=branch>'+esc(r.branch||'未命名工作樹')+'</span><span class=claim-age>認領 '+esc(age(r.claimed_at))+'</span></div>'
    +(r.intent?'<div class=intent>'+esc(r.intent)+'</div>':'<div class=muted>未回報 intent</div>')
    +'<div class=claim-tickets>'+((r.backlog||[]).length?(r.backlog||[]).map(t=>'<span class="tag">'+esc(t)+'</span>').join(''):'<span class=muted>未列票號</span>')+'</div></article>').join('');
}
function areasView(){
  const entries=areaEntries(),max=entries.length?entries[0][1].unresolved:1;
  let html='<div class=notice><strong>領域是為了看懂範圍。</strong> 分類證據優先取票的 <code>fix_site</code>；多領域標成跨域，無法判定的票不會被偷偷歸類。</div><input id=query class=search placeholder="只讀搜尋票號、說明或修改位置" value="'+esc(QUERY)+'"><div class=areas>'+entries.map(([label,s])=>areaCard(label,s,max)).join('')+'</div>';
  if(AREA){
    const rows=DATA.board.filter(e=>e.area===AREA&&(!QUERY||[e.id,e.brief,e.detail,e.fix_site].join(' ').toLowerCase().includes(QUERY.toLowerCase())));
    html+='<div class=section-head><h2>'+esc(AREA)+'</h2><p>'+n(rows.length)+' 筆符合</p></div>'+ (rows.length?rows.map(ticket).join(''):'<div class=empty>這個領域沒有符合搜尋的票。</div>');
  }
  return html;
}
function inflight(){
  const m=claims();
  return '<div class=notice><strong>在飛 = 收到的工作樹認領。</strong> 這裡不虛構百分比進度；沒有 per-agent progress 回報時，只呈現工作樹、intent、票號與認領時間。</div>'
   +'<div class=section-head><h2>目前在做</h2><p>鏡像回報 '+esc(m.at?age(m.at):'尚無回報')+'</p></div>'+renderWorktrees(m.records,false)+freshnessBox();
}
function health(){
  const f=DATA.freshness,s=freshState(f),c=claims();
  return '<div class=notice><strong>健康只回答資料面是否可信。</strong> 它不代表每張票的程式修復已完成。</div>'+freshnessBox()
   +'<div class=section-head><h2>資料來源</h2><p>版本 '+esc(shortSha(f.clone_head))+'</p></div>'
   +'<div class=card><div class=detail>領域分類：'+esc(DATA.counts.area_definition)+'</div><div class=detail>已梳理定義：'+esc(DATA.counts.ready_definition)+'</div><div class=detail>可派工定義：'+esc(DATA.counts.dispatch_definition)+'</div><div class=detail>認領資料：'+n(c.records.length)+' 條工作樹，鏡像時間 '+esc(c.at||'尚無')+'</div></div>'
   +'<details><summary class=muted>查看原始健康資料</summary><pre>'+esc(JSON.stringify(f,null,2))+'</pre></details>';
}
function render(){
  if(!DATA)return;
  document.getElementById('metrics').innerHTML='';
  const v=document.getElementById('view');
  v.innerHTML=TAB==='overview'?overview():TAB==='areas'?areasView():TAB==='inflight'?inflight():health();
  document.querySelectorAll('#tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===TAB));
  const q=document.getElementById('query');if(q){q.oninput=()=>{QUERY=q.value;render()};q.focus();q.setSelectionRange(QUERY.length,QUERY.length)}
}
async function load(){
  try{
    const r=await fetch('/api/board');if(!r.ok)throw new Error('讀取失敗 '+r.status);
    DATA=await r.json();render();
  }catch(e){document.getElementById('view').innerHTML='<div class="empty err">'+esc(e.message)+'</div>'}
}
document.getElementById('tabs').onclick=e=>{if(e.target.dataset.tab){TAB=e.target.dataset.tab;AREA=null;QUERY='';render()}};
document.addEventListener('click',e=>{const a=e.target.closest('[data-area]');if(a){AREA=a.dataset.area;TAB='areas';render()}});
load();setInterval(load,30000);
</script>
"""


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

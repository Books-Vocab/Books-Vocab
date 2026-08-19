#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Small local ownership ledger for parallel GitHub work.

GitHub is the source of truth for product work, review, checks, and merge.  This
ledger deliberately stores only facts that exist on the local machine and cannot
be represented reliably by a remote issue or pull request: which worktree owns a
checkout, which files it intends to touch, its stable Codex owner, and the exact
commit handed back by that worktree.

The file is machine-local at ``<git-common-dir parent>/.cache`` and is never a
second issue database.  ``external_ids`` are opaque references such as ``#123``
or a GitHub issue URL; the registry never creates, closes, prioritises, or
validates them against a remote service.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from lib.worktree_scope import coerce_scope, normalise_scope, scope_files, scope_problems

SCHEMA = "kg.worktree.registry.v2"
STATUS_ACTIVE = "active"
RESOLVE_STATUS = ("merged", "abandoned")
HAND_BACK_SEAL_SCHEMA = "kg.worktree.handback.v1"
HAND_BACK_OUTCOMES = ("changed", "no-op-existing-fix")
GREEN_ACCEPTANCE_STATUSES = {"pass", "passed", "green", "ok", "success"}
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CLAIMED = 75
EXIT_USAGE = 64
CURRENT_RECORD_FIELDS = (
    "branch", "path", "intent", "base", "status", "external_ids", "scope",
    "codex_thread_id", "delegated", "created_at", "claimed_at", "resolved_at",
    "base_sha", "handed_back_at", "handed_back_sha", "handback_seal",
    "handback_outcomes",
)


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def repo_root() -> Path:
    rc, out = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    return Path(out).resolve() if rc == 0 and out else Path.cwd().resolve()


def common_anchor() -> Path:
    root = repo_root()
    rc, out = _git(["rev-parse", "--git-common-dir"], root)
    if rc != 0 or not out:
        return root
    common = Path(out)
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent


def default_state_path() -> Path:
    return common_anchor() / ".cache" / "worktree_registry.json"


def _norm(path: str | os.PathLike[str]) -> str:
    return str(Path(path).expanduser().resolve())


def _parse_at(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def resolve_now(value: str | None = None) -> tuple[int, str]:
    now = _parse_at(value)
    return int(now.timestamp()), now.strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def _ledger_lock(state_path: Path) -> Iterator[None]:
    """Serialize local registry mutations without locking product files."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _state_path(args: argparse.Namespace) -> Path:
    return Path(args.state).expanduser().resolve() if getattr(args, "state", None) else default_state_path()


def _external_ids(value: object) -> list[str]:
    if value is None:
        return []
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        raise ValueError("external ids must be a list of strings")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("external ids must contain non-empty strings")
        item = item.strip()
        if item not in out:
            out.append(item)
    return out


def _legacy_external_ids(record: dict[str, Any]) -> list[str]:
    """Read the old machine cache once while it is being rewritten.

    Existing active worktrees were created before the GitHub migration.  Keeping
    this one read-only conversion protects their ownership claims without keeping
    the removed local data store or lifecycle semantics alive.
    """
    value = record.get("external_ids")
    if value is None:
        value = record.get("backlog")
    try:
        return _external_ids(value)
    except ValueError:
        return []


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or default_state_path()).expanduser().resolve()
    if not target.exists():
        return {"schema": SCHEMA, "records": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"registry state is unreadable: {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"registry state must be an object: {target}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError(f"registry state records must be a list: {target}")
    clean_records: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record["external_ids"] = _legacy_external_ids(record)
        # This is a one-time in-memory migration of the ignored machine cache.
        # It is intentionally not copied into the new state format.
        record.pop("backlog", None)
        clean_records.append(record)
    # Rebuild the envelope instead of carrying unknown top-level keys forward.
    # Older ignored caches may still contain campaign/reservation stores; those
    # were part of the removed local delivery system and are not registry state.
    return {"schema": SCHEMA, "records": clean_records}


def save_state(path: Path, state: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "records": [
            dict(item) for item in state.get("records", []) if isinstance(item, dict)
        ],
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only current local-ownership facts in a retained active record."""
    compacted = {
        key: record[key] for key in CURRENT_RECORD_FIELDS if key in record
    }
    compacted["external_ids"] = _legacy_external_ids(record)
    compacted.pop("backlog", None)
    return compacted


def _record_matches(record: dict[str, Any], *, branch: str | None = None,
                    path: str | None = None) -> bool:
    return ((branch is None or record.get("branch") == branch)
            and (path is None or _norm(str(record.get("path") or "")) == _norm(path)))


def _active_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in state.get("records", [])
            if isinstance(r, dict) and r.get("status") == STATUS_ACTIVE]


def _scope_from_args(args: argparse.Namespace, *, required: bool = False) -> object:
    raw = getattr(args, "scope", None)
    scope_file = getattr(args, "scope_file", None)
    if raw is not None and scope_file is not None:
        raise ValueError("--scope and --scope-file are mutually exclusive")
    if scope_file is not None:
        raw = Path(scope_file).expanduser().read_text(encoding="utf-8")
    if raw is None:
        if required:
            raise ValueError("a structured Scope is required")
        return None
    return coerce_scope(raw)


def _scope_error(scope: object) -> str | None:
    problems = scope_problems(scope)
    return json.dumps(problems, ensure_ascii=False) if problems else None


def _register_record(
    state: dict[str, Any], *, branch: str, path: str, intent: str,
    base: str, external_ids: list[str], scope: object = None,
    codex_thread_id: str | None = None, delegated: bool | None = None,
    at: str | None = None,
) -> tuple[int, dict[str, Any]]:
    branch = branch.strip()
    path = _norm(path)
    if not branch or not intent.strip():
        return EXIT_USAGE, {"reason": "branch and intent are required"}
    try:
        ids = _external_ids(external_ids)
    except ValueError as exc:
        return EXIT_USAGE, {"reason": str(exc)}
    if scope is not None:
        try:
            scope = normalise_scope(scope)
        except ValueError as exc:
            return EXIT_USAGE, {"reason": str(exc)}
    owners = []
    wanted = set(ids)
    for record in _active_records(state):
        if record.get("branch") == branch or _norm(str(record.get("path") or "")) == path:
            continue
        overlap = wanted.intersection(_legacy_external_ids(record))
        if overlap:
            owners.append({"branch": record.get("branch"), "path": record.get("path"),
                           "external_ids": sorted(overlap)})
    if owners:
        return EXIT_CLAIMED, {"reason": "external reference already owned", "owners": owners}
    _, now_iso = resolve_now(at)
    existing = next((r for r in state["records"]
                     if isinstance(r, dict) and (r.get("branch") == branch
                         or _norm(str(r.get("path") or "")) == path)), None)
    if existing is not None and existing.get("status") == STATUS_ACTIVE:
        existing.update({"branch": branch, "path": path, "intent": intent.strip(),
                         "base": base, "external_ids": ids,
                         "claimed_at": existing.get("claimed_at") or now_iso})
        if scope is not None:
            existing["scope"] = scope
        if codex_thread_id is not None:
            existing["codex_thread_id"] = codex_thread_id
        if delegated is not None:
            existing["delegated"] = delegated
        return EXIT_OK, existing
    record: dict[str, Any] = {
        "branch": branch, "path": path, "intent": intent.strip(), "base": base,
        "status": STATUS_ACTIVE, "external_ids": ids, "scope": scope,
        "codex_thread_id": codex_thread_id, "delegated": delegated,
        "created_at": now_iso, "claimed_at": now_iso,
        "resolved_at": None, "handed_back_at": None, "handed_back_sha": None,
    }
    state["records"].append(record)
    return EXIT_OK, record


def cmd_register(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    try:
        scope = _scope_from_args(args)
        ids = _external_ids(getattr(args, "external_id", None))
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": SCHEMA, "action": "refused", "reason": str(exc)},
                         ensure_ascii=False))
        return EXIT_USAGE
    with _ledger_lock(state_path):
        state = load_state(state_path)
        rc, record = _register_record(
            state, branch=args.branch, path=args.path or str(repo_root()),
            intent=args.intent, base=args.base, external_ids=ids, scope=scope,
            codex_thread_id=args.codex_thread_id, delegated=args.delegated, at=args.at,
        )
        if rc == EXIT_OK:
            save_state(state_path, state)
    payload = {"schema": SCHEMA, "action": "register" if rc == EXIT_OK else "refused",
               "record": record}
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json
          else (f"✓ registered [{record.get('branch')}]" if rc == EXIT_OK
                else f"✗ register refused: {record.get('reason')}"))
    return rc


def cmd_scope_set(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    try:
        scope = _scope_from_args(args, required=True)
        scope = normalise_scope(scope)
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": SCHEMA, "action": "refused", "reason": str(exc)},
                         ensure_ascii=False))
        return EXIT_USAGE
    with _ledger_lock(state_path):
        state = load_state(state_path)
        matches = [r for r in _active_records(state)
                   if _record_matches(r, branch=args.branch, path=args.path)]
        if len(matches) != 1:
            reason = "scope selector must match exactly one active worktree"
            print(json.dumps({"schema": SCHEMA, "action": "refused", "reason": reason},
                             ensure_ascii=False))
            return EXIT_USAGE
        matches[0]["scope"] = scope
        save_state(state_path, state)
    print(json.dumps({"schema": SCHEMA, "action": "scope-set", "record": matches[0]},
                     indent=2, ensure_ascii=False) if args.json
          else f"✓ scope set [{matches[0].get('branch')}]" )
    return EXIT_OK


def cmd_owner_bind(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    with _ledger_lock(state_path):
        state = load_state(state_path)
        matches = [r for r in _active_records(state)
                   if _record_matches(r, branch=args.branch, path=args.path)]
        if len(matches) != 1:
            print("✗ owner selector must match exactly one active worktree", file=sys.stderr)
            return EXIT_USAGE
        matches[0]["codex_thread_id"] = args.codex_thread_id
        if args.delegated is not None:
            matches[0]["delegated"] = args.delegated
        save_state(state_path, state)
    print(json.dumps({"schema": SCHEMA, "action": "owner-bind", "record": matches[0]},
                     indent=2, ensure_ascii=False) if args.json
          else f"✓ owner bound [{matches[0].get('branch')}]" )
    return EXIT_OK


def _record_view(record: dict[str, Any]) -> dict[str, Any]:
    view = dict(record)
    view["path"] = _norm(str(view["path"])) if view.get("path") else None
    view["scope_status"] = "known" if not scope_problems(view.get("scope")) else "unknown"
    view["external_ids"] = _legacy_external_ids(view)
    return view


def _conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    holders: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("status") != STATUS_ACTIVE:
            continue
        for external_id in _legacy_external_ids(record):
            holders.setdefault(external_id, []).append({
                "branch": record.get("branch"), "path": record.get("path"),
            })
    return [{"external_id": key, "owners": owners}
            for key, owners in sorted(holders.items()) if len(owners) > 1]


def cmd_list(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    state = load_state(state_path)
    records = state["records"]
    selected = [r for r in records if isinstance(r, dict)]
    if args.active_only:
        selected = [r for r in selected if r.get("status") == STATUS_ACTIVE]
    if args.branch:
        selected = [r for r in selected if r.get("branch") == args.branch]
    if args.path:
        selected = [r for r in selected if _record_matches(r, path=args.path)]
    if args.external_id:
        selected = [r for r in selected if args.external_id in _legacy_external_ids(r)]
    if args.conflicts:
        payload = {"schema": SCHEMA, "ledger": str(state_path),
                   "conflicts": _conflicts(selected)}
        print(json.dumps(payload, indent=2, ensure_ascii=False)); return EXIT_OK
    if args.json:
        print(json.dumps({"schema": SCHEMA, "ledger": str(state_path),
                          "records": [_record_view(r) for r in selected]},
                         indent=2, ensure_ascii=False))
        return EXIT_OK
    if not selected:
        print(f"(empty ledger: {state_path})")
        return EXIT_OK
    print("branch\texternal_ids\tstatus\tpath\tscope\tthread")
    for record in selected:
        print("\t".join([
            str(record.get("branch") or "-"),
            ",".join(_legacy_external_ids(record)) or "-",
            str(record.get("status") or "-"), str(record.get("path") or "-"),
            "known" if not scope_problems(record.get("scope")) else "unknown",
            str(record.get("codex_thread_id") or "-"),
        ]))
    return EXIT_OK


def _acceptance_status(value: object) -> str:
    return str(value or "").strip().lower()


def _load_outcomes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("outcomes")
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("outcomes must be a JSON list of objects")
    return [dict(item) for item in payload]


def _seal_body(record: dict[str, Any], *, base_sha: str, tip_sha: str,
               outcomes: list[dict[str, Any]], handed_back_at: str) -> dict[str, Any]:
    return {
        "schema": HAND_BACK_SEAL_SCHEMA, "branch": record.get("branch"),
        "path": _norm(str(record.get("path") or "")),
        "external_ids": sorted(_legacy_external_ids(record)),
        "base_sha": base_sha, "tip_sha": tip_sha,
        "outcomes": outcomes, "handed_back_at": handed_back_at,
    }


def _seal_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    result["digest"] = hashlib.sha256(_canonical_json(body)).hexdigest()
    return result


def validate_handback_seal(record: dict[str, Any], *, repo: Path | None = None,
                           require_green: bool = True) -> list[dict[str, Any]]:
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        return [{"kind": "handback-seal-missing"}]
    digest = seal.get("digest")
    body = {key: value for key, value in seal.items() if key != "digest"}
    problems: list[dict[str, Any]] = []
    if seal.get("schema") != HAND_BACK_SEAL_SCHEMA:
        problems.append({"kind": "handback-seal-schema-invalid"})
    if digest != hashlib.sha256(_canonical_json(body)).hexdigest():
        problems.append({"kind": "handback-seal-digest-invalid"})
    if body.get("branch") != record.get("branch"):
        problems.append({"kind": "handback-seal-branch-mismatch"})
    if sorted(body.get("external_ids") or []) != sorted(_legacy_external_ids(record)):
        problems.append({"kind": "handback-seal-external-ids-mismatch"})
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        problems.append({"kind": "handback-outcomes-invalid"})
    elif require_green:
        for item in outcomes:
            if not isinstance(item, dict) or _acceptance_status(item.get("status")) not in GREEN_ACCEPTANCE_STATUSES:
                problems.append({"kind": "handback-outcome-not-green", "outcome": item})
    return problems


def cmd_hand_back(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    with _ledger_lock(state_path):
        state = load_state(state_path)
        matches = [r for r in _active_records(state)
                   if _record_matches(r, branch=args.branch, path=args.path)]
        if len(matches) != 1:
            reason = "hand-back selector must match exactly one active worktree"
            print(json.dumps({"schema": SCHEMA, "action": "refused", "reason": reason},
                             ensure_ascii=False)); return EXIT_USAGE
        record = matches[0]
        worktree = Path(record["path"])
        if not worktree.is_dir():
            print(f"✗ registered worktree is missing: {worktree}", file=sys.stderr)
            return EXIT_PARTIAL
        rc, branch = _git(["branch", "--show-current"], worktree)
        if rc != 0 or branch != record.get("branch"):
            print("✗ worktree branch does not match registry", file=sys.stderr)
            return EXIT_PARTIAL
        rc, tip_sha = _git(["rev-parse", "--verify", "HEAD^{commit}"], worktree)
        if rc != 0 or not tip_sha:
            print("✗ cannot read worktree HEAD", file=sys.stderr); return EXIT_PARTIAL
        if args.outcomes:
            try:
                outcomes = _load_outcomes(Path(args.outcomes).expanduser())
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"✗ outcomes unreadable: {exc}", file=sys.stderr); return EXIT_PARTIAL
            dirty_rc, dirty = _git(["status", "--porcelain=v1"], worktree)
            if dirty_rc != 0 or dirty:
                print("✗ hand-back outcomes require a clean worktree", file=sys.stderr)
                return EXIT_PARTIAL
            base_sha = record.get("base_sha")
            if not base_sha:
                base_rc, base_sha = _git(["rev-parse", f"{record.get('base', 'main')}^{{commit}}"], worktree)
                if base_rc != 0:
                    base_sha = ""
            if not base_sha:
                print("✗ cannot determine the recorded base commit", file=sys.stderr)
                return EXIT_PARTIAL
            normalized = []
            for item in outcomes:
                status = _acceptance_status(item.get("status") or item.get("outcome"))
                if status not in GREEN_ACCEPTANCE_STATUSES:
                    print("✗ every hand-back outcome must be green", file=sys.stderr)
                    return EXIT_PARTIAL
                normalized.append(item)
            _, now_iso = resolve_now(args.at)
            record["handback_seal"] = _seal_with_digest(
                _seal_body(record, base_sha=base_sha, tip_sha=tip_sha,
                           outcomes=normalized, handed_back_at=now_iso))
            record["handback_outcomes"] = normalized
        _, now_iso = resolve_now(args.at)
        record["handed_back_at"] = now_iso
        record["handed_back_sha"] = tip_sha
        save_state(state_path, state)
    payload = {"schema": SCHEMA, "action": "hand-back", "record": _record_view(record)}
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json
          else f"✓ handed back [{record.get('branch')}] @ {tip_sha[:12]}")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    if args.status not in RESOLVE_STATUS or (not args.branch and not args.path):
        print("✗ resolve needs --branch/--path and a valid terminal status", file=sys.stderr)
        return EXIT_USAGE
    state_path = _state_path(args)
    with _ledger_lock(state_path):
        state = load_state(state_path)
        matches = [r for r in _active_records(state)
                   if _record_matches(r, branch=args.branch, path=args.path)]
        if not matches:
            print("✗ no active registry record matches selector", file=sys.stderr)
            return EXIT_USAGE
        _, now_iso = resolve_now(args.at)
        for record in matches:
            record["status"] = args.status
            record["resolved_at"] = now_iso
        save_state(state_path, state)
    print(json.dumps({"schema": SCHEMA, "action": "resolve", "status": args.status,
                      "records": [_record_view(r) for r in matches]},
                     indent=2, ensure_ascii=False) if args.json
          else "\n".join(f"✓ resolved [{r.get('branch')}] -> {args.status}" for r in matches))
    return EXIT_OK


def _worktree_rows() -> list[dict[str, str | None]]:
    rc, out = _git(["worktree", "list", "--porcelain"], repo_root())
    if rc != 0:
        return []
    rows: list[dict[str, str | None]] = []
    current: dict[str, str | None] = {}
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            if current:
                rows.append(current)
            current = {"path": line[9:]}
        elif line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
        elif line == "":
            if current:
                rows.append(current); current = {}
    return rows


def cmd_sweep(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    state = load_state(state_path)
    known = {_norm(str(row.get("path"))) for row in _worktree_rows() if row.get("path")}
    orphaned = [r for r in _active_records(state)
                if r.get("path") and _norm(str(r["path"])) not in known]
    payload = {"schema": SCHEMA, "action": "sweep", "orphaned": [_record_view(r) for r in orphaned],
               "commit": bool(args.commit)}
    if args.commit and orphaned:
        with _ledger_lock(state_path):
            state = load_state(state_path)
            _, now_iso = resolve_now(args.at)
            for record in _active_records(state):
                if record.get("path") and _norm(str(record["path"])) not in known:
                    record["status"] = "abandoned"
                    record["resolved_at"] = now_iso
            save_state(state_path, state)
        payload["action"] = "sweep-committed"
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json
          else ("✓ no orphaned registry records" if not orphaned
                else "\n".join(f"! orphaned: {r.get('branch')} {r.get('path')}" for r in orphaned)))
    return EXIT_OK


def cmd_compact(args: argparse.Namespace) -> int:
    """Retain active ownership only and remove historical delivery metadata."""
    state_path = _state_path(args)
    state = load_state(state_path)
    active = [_compact_record(record) for record in _active_records(state)]
    removed = len(state.get("records", [])) - len(active)
    payload = {
        "schema": SCHEMA,
        "action": "compact",
        "active_preserved": len(active),
        "historical_records_removed": removed,
        "commit": bool(args.commit),
    }
    if args.commit:
        with _ledger_lock(state_path):
            state = load_state(state_path)
            active = [_compact_record(record) for record in _active_records(state)]
            removed = len(state.get("records", [])) - len(active)
            save_state(state_path, {"schema": SCHEMA, "records": active})
        payload["active_preserved"] = len(active)
        payload["historical_records_removed"] = removed
        payload["action"] = "compact-committed"
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json else json.dumps(payload, ensure_ascii=False)
    )
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local worktree ownership and hand-back evidence")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state", default=None)
        p.add_argument("--json", action="store_true")
        p.add_argument("--at", default=None, help=argparse.SUPPRESS)

    reg = sub.add_parser("register", help="record one local worktree owner")
    common(reg); reg.add_argument("--branch", required=True); reg.add_argument("--path", default=None)
    reg.add_argument("--intent", required=True); reg.add_argument("--base", default="main")
    reg.add_argument("--external-id", action="append", default=[])
    reg.add_argument("--scope", default=None); reg.add_argument("--scope-file", default=None)
    reg.add_argument("--codex-thread-id", default=None)
    reg.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    reg.set_defaults(func=cmd_register)

    scope = sub.add_parser("scope-set", help="replace a worktree's structured file Scope")
    common(scope); scope.add_argument("--branch"); scope.add_argument("--path")
    scope.add_argument("--scope", default=None); scope.add_argument("--scope-file", default=None)
    scope.set_defaults(func=cmd_scope_set)

    owner = sub.add_parser("owner-bind", help="bind the stable local owner identity")
    common(owner); owner.add_argument("--branch"); owner.add_argument("--path")
    owner.add_argument("--codex-thread-id", required=True)
    owner.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    owner.set_defaults(func=cmd_owner_bind)

    listed = sub.add_parser("list", help="list local worktree records")
    common(listed); listed.add_argument("--active-only", action="store_true")
    listed.add_argument("--branch"); listed.add_argument("--path"); listed.add_argument("--external-id")
    listed.add_argument("--conflicts", action="store_true")
    listed.set_defaults(func=cmd_list)

    hand = sub.add_parser("hand-back", help="record exact HEAD and optional green evidence")
    common(hand); hand.add_argument("--branch"); hand.add_argument("--path")
    hand.add_argument("--outcomes", default=None); hand.set_defaults(func=cmd_hand_back)

    resolved = sub.add_parser("resolve", help="close local ownership after a GitHub merge or abandonment")
    common(resolved); resolved.add_argument("--branch"); resolved.add_argument("--path")
    resolved.add_argument("--status", choices=RESOLVE_STATUS, required=True)
    resolved.set_defaults(func=cmd_resolve)

    sweep = sub.add_parser("sweep", help="report missing registered worktrees")
    common(sweep); sweep.add_argument("--commit", action="store_true")
    sweep.set_defaults(func=cmd_sweep)

    compact = sub.add_parser(
        "compact", help="retain active ownership and remove old local delivery history"
    )
    common(compact); compact.add_argument("--commit", action="store_true")
    compact.set_defaults(func=cmd_compact)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

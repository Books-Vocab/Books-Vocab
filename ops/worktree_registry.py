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
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from lib.worktree_scope import coerce_scope, normalise_scope, scope_problems

SCHEMA = "kg.worktree.registry.v2"
STATUS_ACTIVE = "active"
STATUS_CLEANUP_PENDING = "cleanup_pending"
RESOLVE_STATUS = (STATUS_CLEANUP_PENDING, "published", "merged", "abandoned")
HAND_BACK_SEAL_SCHEMA = "kg.worktree.handback.v1"
HAND_BACK_OUTCOMES = ("changed", "no-op-existing-fix")
GREEN_ACCEPTANCE_STATUSES = {"pass", "passed", "green", "ok", "success"}
ORIGIN_MAIN_REF = "refs/heads/main"
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CLAIMED = 75
EXIT_USAGE = 64
CURRENT_RECORD_FIELDS = (
    "branch", "path", "intent", "base", "status", "external_ids", "scope",
    "codex_thread_id", "delegated", "created_at", "claimed_at", "resolved_at",
    "claim_generation", "base_sha", "handed_back_at", "handed_back_sha",
    "handback_claim_generation", "handback_seal", "handback_outcomes",
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
        raise TypeError("external ids must be a list of strings")
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
    except (TypeError, ValueError):
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
        raise TypeError(f"registry state must be an object: {target}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise TypeError(f"registry state records must be a list: {target}")
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


def _claim_generation(record: dict[str, Any], field: str) -> int | None:
    value = record.get(field, 0)
    return value if type(value) is int and value >= 0 else None


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
    except (TypeError, ValueError) as exc:
        return EXIT_USAGE, {"reason": str(exc)}
    if scope is not None:
        try:
            scope = normalise_scope(scope)
        except ValueError as exc:
            return EXIT_USAGE, {"reason": str(exc)}
    owners = []
    wanted = set(ids)
    for record in _admission_records(state):
        if record.get("branch") == branch or _norm(str(record.get("path") or "")) == path:
            continue
        overlap = wanted.intersection(_legacy_external_ids(record))
        if overlap:
            owners.append({"branch": record.get("branch"), "path": record.get("path"),
                           "external_ids": sorted(overlap)})
    if owners:
        return EXIT_CLAIMED, {"reason": "external reference already owned", "owners": owners}
    _, now_iso = resolve_now(at)
    matching_records = [
        record
        for record in state["records"]
        if isinstance(record, dict)
        and (
            record.get("branch") == branch
            or _norm(str(record.get("path") or "")) == path
        )
    ]
    cleanup_leases = [
        record
        for record in matching_records
        if record.get("status") == STATUS_CLEANUP_PENDING
    ]
    if cleanup_leases:
        existing = cleanup_leases[0]
        return EXIT_CLAIMED, {
            "reason": "local assets are protected by an exact cleanup lease",
            "branch": existing.get("branch"),
            "path": existing.get("path"),
            "claim_generation": existing.get("claim_generation"),
        }
    active_records = [
        record
        for record in matching_records
        if record.get("status") == STATUS_ACTIVE
    ]
    existing = active_records[0] if active_records else None
    generations = [
        generation
        for record in matching_records
        if (generation := _claim_generation(record, "claim_generation")) is not None
    ]
    next_generation = max(generations, default=-1) + 1
    if existing is not None and existing.get("status") == STATUS_ACTIVE:
        existing["claim_generation"] = next_generation
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
        "resolved_at": None, "claim_generation": next_generation,
        "handed_back_at": None, "handed_back_sha": None,
    }
    state["records"].append(record)
    return EXIT_OK, record


def cmd_register(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    try:
        scope = _scope_from_args(args)
        ids = _external_ids(getattr(args, "external_id", None))
    except (OSError, TypeError, ValueError) as exc:
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
        record = matches[0]
        if record.get("scope") != scope:
            _advance_claim(record)
            record["scope"] = scope
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
        record = matches[0]
        assignment_changed = record.get("codex_thread_id") != args.codex_thread_id
        if args.delegated is not None:
            assignment_changed = (
                assignment_changed or record.get("delegated") != args.delegated
            )
        if assignment_changed:
            _advance_claim(record)
        record["codex_thread_id"] = args.codex_thread_id
        if args.delegated is not None:
            record["delegated"] = args.delegated
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


def _clear_handback(record: dict[str, Any]) -> None:
    record["handed_back_at"] = None
    record["handed_back_sha"] = None
    record.pop("handback_claim_generation", None)
    record.pop("handback_seal", None)
    record.pop("handback_outcomes", None)


def _advance_claim(record: dict[str, Any]) -> None:
    generation = _claim_generation(record, "claim_generation")
    record["claim_generation"] = (generation if generation is not None else -1) + 1
    _clear_handback(record)


def _seal_body(record: dict[str, Any], *, base_sha: str, tip_sha: str,
               outcomes: list[dict[str, Any]], handed_back_at: str,
               origin_main_sha: str | None = None) -> dict[str, Any]:
    body = {
        "schema": HAND_BACK_SEAL_SCHEMA, "branch": record.get("branch"),
        "path": _norm(str(record.get("path") or "")),
        "external_ids": sorted(_legacy_external_ids(record)),
        "owner_thread_id": record.get("codex_thread_id"),
        "base_sha": base_sha, "tip_sha": tip_sha,
        "outcomes": outcomes, "handed_back_at": handed_back_at,
    }
    if origin_main_sha is not None:
        body["origin_main_sha"] = origin_main_sha
    return body


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
    if body.get("owner_thread_id") != record.get("codex_thread_id"):
        problems.append({"kind": "handback-seal-owner-mismatch"})
    if sorted(body.get("external_ids") or []) != sorted(_legacy_external_ids(record)):
        problems.append({"kind": "handback-seal-external-ids-mismatch"})
    origin_main_sha = body.get("origin_main_sha")
    if origin_main_sha is not None and not _is_commit_sha(origin_main_sha):
        problems.append({"kind": "handback-origin-main-sha-invalid"})
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        problems.append({"kind": "handback-outcomes-invalid"})
    elif require_green:
        for item in outcomes:
            if not isinstance(item, dict) or _acceptance_status(item.get("status")) not in GREEN_ACCEPTANCE_STATUSES:
                problems.append({"kind": "handback-outcome-not-green", "outcome": item})
    return problems


def _has_valid_stored_handback(record: dict[str, Any]) -> bool:
    branch = record.get("branch")
    path = record.get("path")
    handed_back_at = record.get("handed_back_at")
    handed_back_sha = record.get("handed_back_sha")
    seal = record.get("handback_seal")
    if not isinstance(branch, str) or not branch:
        return False
    if not isinstance(path, str) or not path:
        return False
    if not isinstance(handed_back_at, str) or not handed_back_at:
        return False
    if not isinstance(handed_back_sha, str) or not handed_back_sha:
        return False
    if not isinstance(seal, dict):
        return False
    try:
        _parse_at(handed_back_at)
    except ValueError:
        return False
    if seal.get("handed_back_at") != handed_back_at:
        return False
    if seal.get("tip_sha") != handed_back_sha:
        return False
    generation = _claim_generation(record, "claim_generation")
    handed_back_generation = _claim_generation(record, "handback_claim_generation")
    if generation is None or handed_back_generation is None or generation != handed_back_generation:
        return False
    return not validate_handback_seal(record)


def _has_valid_handback(record: dict[str, Any]) -> bool:
    if not _has_valid_stored_handback(record):
        return False
    branch = str(record["branch"])
    handed_back_sha = str(record["handed_back_sha"])
    worktree = Path(str(record["path"]))
    if not worktree.is_dir():
        return False
    branch_rc, current_branch = _git(["branch", "--show-current"], worktree)
    if branch_rc != 0 or current_branch != branch:
        return False
    dirty_rc, dirty = _git(["status", "--porcelain=v1"], worktree)
    if dirty_rc != 0 or dirty:
        return False
    head_rc, current_head = _git(["rev-parse", "--verify", "HEAD^{commit}"], worktree)
    return head_rc == 0 and current_head == handed_back_sha


def _admission_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [record for record in _active_records(state) if not _has_valid_handback(record)]


def _is_commit_sha(value: object) -> bool:
    return isinstance(value, str) and COMMIT_SHA_RE.fullmatch(value) is not None


def _live_origin_main_sha(worktree: Path) -> str | None:
    rc, output = _git(["ls-remote", "origin", ORIGIN_MAIN_REF], worktree)
    if rc != 0:
        return None
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if len(rows) != 1:
        return None
    fields = rows[0]
    if len(fields) != 2 or fields[1] != ORIGIN_MAIN_REF or not _is_commit_sha(fields[0]):
        return None
    return fields[0]


def _declared_base_sha(record: dict[str, Any], worktree: Path) -> str | None:
    base_sha = record.get("base_sha")
    if base_sha is not None:
        return base_sha if _is_commit_sha(base_sha) else None
    base_ref = record.get("base", "main")
    if not isinstance(base_ref, str) or not base_ref.strip():
        return None
    rc, resolved = _git(["rev-parse", f"{base_ref}^{{commit}}"], worktree)
    return resolved if rc == 0 and _is_commit_sha(resolved) else None


def _is_ancestor(worktree: Path, ancestor: str, descendant: str) -> bool:
    rc, _ = _git(["merge-base", "--is-ancestor", ancestor, descendant], worktree)
    return rc == 0


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
            base_sha = _declared_base_sha(record, worktree)
            if not base_sha:
                print("✗ cannot determine the recorded base commit", file=sys.stderr)
                return EXIT_PARTIAL
            origin_main_sha = _live_origin_main_sha(worktree)
            if not origin_main_sha:
                print("✗ cannot read live origin/main", file=sys.stderr)
                return EXIT_PARTIAL
            if not _is_ancestor(worktree, base_sha, origin_main_sha):
                print("✗ declared base is not an ancestor of live origin/main", file=sys.stderr)
                return EXIT_PARTIAL
            if not _is_ancestor(worktree, base_sha, tip_sha):
                print("✗ declared base is not an ancestor of worktree HEAD", file=sys.stderr)
                return EXIT_PARTIAL
            if not _is_ancestor(worktree, origin_main_sha, tip_sha):
                print("✗ live origin/main is not an ancestor of worktree HEAD", file=sys.stderr)
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
                           outcomes=normalized, handed_back_at=now_iso,
                           origin_main_sha=origin_main_sha))
            record["handback_outcomes"] = normalized
        _, now_iso = resolve_now(args.at)
        record["handed_back_at"] = now_iso
        record["handed_back_sha"] = tip_sha
        generation = _claim_generation(record, "claim_generation")
        record["claim_generation"] = generation if generation is not None else 0
        record["handback_claim_generation"] = record["claim_generation"]
        save_state(state_path, state)
    payload = {"schema": SCHEMA, "action": "hand-back", "record": _record_view(record)}
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json
          else f"✓ handed back [{record.get('branch')}] @ {tip_sha[:12]}")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    if args.status not in RESOLVE_STATUS or (not args.branch and not args.path):
        print("✗ resolve needs --branch/--path and a valid local disposition", file=sys.stderr)
        return EXIT_USAGE
    if args.expected_generation is None or args.expected_head_sha is None:
        print(
            "✗ resolve requires exact generation and HEAD compare-and-swap guards",
            file=sys.stderr,
        )
        return EXIT_USAGE
    state_path = _state_path(args)
    with _ledger_lock(state_path):
        state = load_state(state_path)
        newer_live_claims = [
            record
            for record in state.get("records", [])
            if isinstance(record, dict)
            and record.get("status") in {STATUS_ACTIVE, STATUS_CLEANUP_PENDING}
            and (
                (args.branch is not None and record.get("branch") == args.branch)
                or (
                    args.path is not None
                    and _norm(str(record.get("path") or "")) == _norm(args.path)
                )
            )
            and (
                generation := _claim_generation(record, "claim_generation")
            ) is not None
            and generation > args.expected_generation
        ]
        if newer_live_claims:
            print(
                "✗ newer registry claim blocks historical transition",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
        source_statuses = {
            STATUS_CLEANUP_PENDING: {STATUS_ACTIVE, "published"},
            "published": {STATUS_CLEANUP_PENDING},
            "merged": {STATUS_ACTIVE, "published", STATUS_CLEANUP_PENDING},
            "abandoned": {STATUS_ACTIVE, "published"},
        }[args.status]
        matches = [
            record
            for record in state.get("records", [])
            if record.get("status") in source_statuses
            and _record_matches(record, branch=args.branch, path=args.path)
        ]
        matches = [
            record
            for record in matches
            if _claim_generation(record, "claim_generation")
            == args.expected_generation
        ]
        exact_matches = []
        for record in matches:
            expected_head = record.get("handed_back_sha")
            if not _is_commit_sha(expected_head):
                branch = record.get("branch")
                if isinstance(branch, str) and branch:
                    rc, branch_head = _git(
                        ["rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"],
                        repo_root(),
                    )
                    if rc == 0 and _is_commit_sha(branch_head.strip()):
                        expected_head = branch_head.strip()
            if not _is_commit_sha(expected_head):
                expected_head = record.get("base_sha")
            if expected_head == args.expected_head_sha:
                exact_matches.append(record)
        matches = exact_matches
        if not matches:
            print("✗ no exact registry record matches transition", file=sys.stderr)
            return EXIT_CLAIMED
        if len(matches) != 1:
            print("✗ registry transition selector is ambiguous", file=sys.stderr)
            return EXIT_CLAIMED
        source_status = matches[0].get("status")
        requires_stored_handback = (
            args.status == "published"
            or args.status == STATUS_CLEANUP_PENDING
            and source_status == "published"
        )
        valid_handback = (
            _has_valid_stored_handback(matches[0])
            if requires_stored_handback
            else _has_valid_handback(matches[0])
        )
        if args.status in {STATUS_CLEANUP_PENDING, "published"} and not valid_handback:
            required_kind = "stored" if requires_stored_handback else "physical"
            print(
                f"✗ {args.status} transition requires a valid {required_kind} hand-back",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
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
    if args.commit:
        print(
            "✗ bulk sweep mutation is disabled; use exact resolve CAS per record",
            file=sys.stderr,
        )
        return EXIT_USAGE
    state_path = _state_path(args)
    state = load_state(state_path)
    known = {_norm(str(row.get("path"))) for row in _worktree_rows() if row.get("path")}
    orphaned = [r for r in _active_records(state)
                if r.get("path") and _norm(str(r["path"])) not in known]
    payload = {"schema": SCHEMA, "action": "sweep", "orphaned": [_record_view(r) for r in orphaned],
               "commit": bool(args.commit)}
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
    resolved.add_argument("--expected-generation", type=int)
    resolved.add_argument("--expected-head-sha")
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

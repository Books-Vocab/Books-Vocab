#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Thin local worktree coordinator.

The delivery model is intentionally GitHub-native:

    direct assignment or Issue -> branch/worktree -> pull request
    -> Actions/CR/DS -> CM merge

This command owns only local concerns: creating or adopting a worktree, recording
file ownership, running the same focused checks locally, and handing back exact
HEAD evidence. It does not own GitHub work-item state, branch integration, merge
state, or release state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

OPS_DIR = Path(__file__).resolve().parent
ROOT = OPS_DIR.parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

import worktree_registry as registry
from lib.worktree_scope import scope_files, scope_status

SCHEMA = "kg.worktree.orchestrate.v2"
GATE_SCHEMA = "kg.worktree.gate.v2"
HANDOFF_SCHEMA = "kg.worktree.handoff.v1"
BASE_DEFAULT = "main"
BRANCH_TYPES = ("debug", "feat", "research")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXIT_OK = 0
EXIT_BLOCK = 1
EXIT_USAGE = 64


def _git(args: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              check=False)
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.strip()


def _emit(payload: dict[str, Any], *, as_json: bool, human: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else human)


def _path(value: str) -> Path:
    raw = Path(value).expanduser()
    return raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()


def _intent_type(intent: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    lowered = intent.lower()
    if any(word in lowered for word in ("bug", "fix", "crash", "broken", "error")):
        return "debug"
    if any(word in lowered for word in ("research", "investigate", "spike", "audit")):
        return "research"
    return "feat"


def _freeze_path() -> Path:
    return registry.default_state_path().with_name("worktree-freeze.json")


def _is_frozen() -> dict[str, Any] | None:
    path = _freeze_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_freeze(payload: dict[str, Any] | None) -> None:
    path = _freeze_path()
    if payload is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _require_unfrozen(command: str) -> str | None:
    freeze = _is_frozen()
    if freeze:
        return f"local worktree operations are frozen: {freeze.get('reason', 'no reason')}"
    return None


def _scope_args(args: argparse.Namespace) -> list[str]:
    if args.scope is not None:
        return ["--scope", args.scope]
    if args.scope_file is not None:
        return ["--scope-file", args.scope_file]
    return []


def _registry_register(*, branch: str, path: Path, intent: str, base: str,
                       external_ids: list[str], args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    state_path = Path(args.state).expanduser().resolve() if args.state else registry.default_state_path()
    try:
        scope = registry._scope_from_args(args)
    except (OSError, ValueError) as exc:
        return EXIT_USAGE, {"reason": str(exc)}
    with registry._ledger_lock(state_path):
        state = registry.load_state(state_path)
        active_matches = [
            record for record in registry._active_records(state)
            if registry._record_matches(record, branch=branch, path=str(path))
        ]
        if len(active_matches) > 1:
            return EXIT_BLOCK, {
                "reason": "multiple active records match the same worktree",
                "owners": [
                    {"branch": item.get("branch"), "path": item.get("path")}
                    for item in active_matches
                ],
            }
        if active_matches:
            # Keep terminal records in place as history, but put the one live
            # owner first so registry._register_record cannot select an older
            # abandoned record with the same branch/path.
            active = active_matches[0]
            state["records"] = [active] + [
                record for record in state["records"] if record is not active
            ]
        rc, record = registry._register_record(
            state, branch=branch, path=str(path), intent=intent, base=base,
            external_ids=external_ids, scope=scope,
            codex_thread_id=args.codex_thread_id, delegated=args.delegated,
        )
        if rc == registry.EXIT_OK:
            registry.save_state(state_path, state)
    return rc, record


def cmd_open(args: argparse.Namespace) -> int:
    refusal = _require_unfrozen("open")
    if refusal:
        _emit({"schema": SCHEMA, "action": "refused", "reason": refusal},
              as_json=args.json, human=f"✗ open refused: {refusal}")
        return EXIT_BLOCK
    if not SLUG_RE.fullmatch(args.slug):
        _emit({"schema": SCHEMA, "action": "refused", "reason": "slug must be kebab-case"},
              as_json=args.json, human="✗ open refused: slug must be kebab-case")
        return EXIT_USAGE
    branch = f"{_intent_type(args.intent, args.type)}/{args.slug}"
    worktree = _path(args.path) if args.path else ROOT / ".claude" / "worktrees" / args.slug
    if worktree.exists():
        _emit({"schema": SCHEMA, "action": "refused", "reason": f"path exists: {worktree}"},
              as_json=args.json, human=f"✗ open refused: path exists: {worktree}")
        return EXIT_USAGE
    external_ids = list(args.external_id or [])
    rc, record = _registry_register(
        branch=branch, path=worktree, intent=args.intent, base=args.base,
        external_ids=external_ids, args=args,
    )
    if rc != registry.EXIT_OK:
        _emit({"schema": SCHEMA, "action": "refused", "record": record},
              as_json=args.json, human=f"✗ open refused: {record.get('reason', record)}")
        return rc
    git_rc, output = _git(["worktree", "add", "-b", branch, str(worktree), args.base])
    if git_rc != 0:
        # Keep the ledger truthful if provisioning fails; no branch is deleted here
        # because GitHub may already know the name and branch removal is a separate
        # explicit action.
        registry.main(["resolve", "--branch", branch, "--status", "abandoned",
                       "--state", str(registry.default_state_path()), "--json"])
        _emit({"schema": SCHEMA, "action": "refused", "reason": "git worktree add failed",
               "git": output, "record": record}, as_json=args.json,
              human=f"✗ open refused: git worktree add failed: {output}")
        return EXIT_BLOCK
    record["path"] = str(worktree)
    _emit({"schema": SCHEMA, "action": "open", "record": record}, as_json=args.json,
          human=f"✓ opened {branch} at {worktree}")
    return EXIT_OK


def cmd_adopt(args: argparse.Namespace) -> int:
    refusal = _require_unfrozen("adopt")
    if refusal:
        _emit({"schema": SCHEMA, "action": "refused", "reason": refusal},
              as_json=args.json, human=f"✗ adopt refused: {refusal}")
        return EXIT_BLOCK
    worktree = _path(args.worktree or os.getcwd())
    if not worktree.is_dir():
        _emit({"schema": SCHEMA, "action": "refused", "reason": f"not a directory: {worktree}"},
              as_json=args.json, human=f"✗ adopt refused: not a directory: {worktree}")
        return EXIT_USAGE
    rc, branch = _git(["branch", "--show-current"], worktree)
    if rc != 0 or not branch:
        _emit({"schema": SCHEMA, "action": "refused", "reason": "worktree is detached"},
              as_json=args.json, human="✗ adopt refused: worktree is detached")
        return EXIT_USAGE
    rc, record = _registry_register(
        branch=branch, path=worktree, intent=args.intent, base=args.base,
        external_ids=list(args.external_id or []), args=args,
    )
    _emit({"schema": SCHEMA, "action": "adopt" if rc == EXIT_OK else "refused",
           "record": record}, as_json=args.json,
          human=(f"✓ adopted {branch} at {worktree}" if rc == EXIT_OK
                 else f"✗ adopt refused: {record.get('reason', record)}"))
    return rc


def _changed_files(worktree: Path, base: str) -> list[str]:
    rc, output = _git(["diff", "--name-only", base], worktree)
    files = set(output.splitlines()) if rc == 0 else set()
    rc, output = _git(["ls-files", "--others", "--exclude-standard"], worktree)
    if rc == 0:
        files.update(output.splitlines())
    return sorted(item for item in files if item)


def _resolve_commit(worktree: Path, ref: str) -> str | None:
    rc, output = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], worktree)
    return output if rc == 0 and output else None


def _diff_names(worktree: Path, start: str, end: str) -> list[str] | None:
    rc, output = _git(["diff", "--name-only", f"{start}..{end}"], worktree)
    if rc != 0:
        return None
    return sorted({item for item in output.splitlines() if item})


def _rebase_preflight(
    worktree: Path, *, base: str, incoming_main: str, scope: object,
) -> dict[str, Any]:
    """Compare declared ownership only with the incoming-main commit range."""
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "action": "rebase-preflight",
        "verdict": "block",
        "worktree": str(worktree),
        "base": base,
        "incoming_main": incoming_main,
        "scope_files": [],
        "incoming_main_files": [],
        "branch_files": [],
        "collisions": [],
    }
    if scope_status(scope) != "known":
        payload["reason"] = "declared Scope is unstructured or invalid"
        return payload

    scope_paths = sorted({item["path"] for item in scope_files(scope)})
    payload["scope_files"] = scope_paths
    base_sha = _resolve_commit(worktree, base)
    if base_sha is None:
        payload["reason"] = "base ref cannot be resolved"
        return payload
    incoming_main_sha = _resolve_commit(worktree, incoming_main)
    if incoming_main_sha is None:
        payload["reason"] = "incoming-main ref cannot be resolved"
        return payload
    head_sha = _resolve_commit(worktree, "HEAD")
    if head_sha is None:
        payload["reason"] = "branch HEAD cannot be resolved"
        return payload
    payload.update({
        "base_sha": base_sha,
        "incoming_main_sha": incoming_main_sha,
        "head_sha": head_sha,
    })
    if _git(["merge-base", "--is-ancestor", base_sha, incoming_main_sha], worktree)[0] != 0:
        payload["reason"] = "base is not an ancestor of incoming-main"
        return payload
    if _git(["merge-base", "--is-ancestor", base_sha, head_sha], worktree)[0] != 0:
        payload["reason"] = "base is not an ancestor of branch HEAD"
        return payload

    incoming_main_files = _diff_names(worktree, base_sha, incoming_main_sha)
    if incoming_main_files is None:
        payload["reason"] = "incoming-main diff could not be computed"
        return payload
    branch_files = _diff_names(worktree, base_sha, head_sha)
    if branch_files is None:
        payload["reason"] = "branch diff could not be computed"
        return payload
    collisions = sorted(set(scope_paths).intersection(incoming_main_files))
    payload.update({
        "incoming_main_files": incoming_main_files,
        "branch_files": branch_files,
        "collisions": collisions,
    })
    if collisions:
        payload["reason"] = "incoming-main changes collide with declared Scope"
        return payload
    payload["verdict"] = "pass"
    return payload


def _plan_checks(files: list[str], *, worktree: Path | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [{
        "name": "git-diff-check", "kind": "shell", "cwd": ".",
        "cmd": ["git", "diff", "--check"], "level": "block",
    }]
    # `git diff --name-only` includes deleted paths.  A deleted shell script
    # still matters to the diff and docs checks, but it cannot be parsed from
    # the target worktree.  Do not turn intentional cleanup into a false gate
    # failure.
    shell_files = [
        item
        for item in files
        if item.endswith(".sh") and (worktree is None or (worktree / item).is_file())
    ]
    for item in shell_files:
        checks.append({"name": f"shell-syntax:{item}", "kind": "shell", "cwd": ".",
                       "cmd": ["bash", "-n", item], "level": "block"})
    docs = [item for item in files if item.startswith("docs/") and item.endswith(".md")]
    if "docs/registry.yml" in files or docs:
        checks.append({"name": "docs-lint", "kind": "shell", "cwd": ".",
                       "cmd": (["./ops/docs_lint.sh", "--registry"] if not docs else
                               ["./ops/docs_lint.sh", "--files", *docs]), "level": "block"})
    if any(item.startswith("backend/") for item in files):
        checks.append({"name": "backend-tests", "kind": "shell", "cwd": "backend",
                       "cmd": ["uv", "run", "--locked", "python", "-m", "pytest", "-q"],
                       "level": "block"})
    if any(item.startswith("ios/") for item in files):
        checks.append({"name": "ios-tests", "kind": "shell", "cwd": ".",
                       "cmd": ["./ops/ios_ops.sh", "test", "--unit"], "level": "block"})
    if any(item.startswith(("ops/", ".github/workflows/")) for item in files):
        checks.append({"name": "ops-tests", "kind": "shell", "cwd": ".",
                       "cmd": ["./ops/test_ops.sh", "worktree"], "level": "block"})
    return checks


def _run_check(check: dict[str, Any], worktree: Path) -> dict[str, Any]:
    cwd = worktree / str(check.get("cwd") or ".")
    started = time.monotonic()
    with tempfile.NamedTemporaryFile(prefix="kg-gate-", suffix=".log", delete=False) as log:
        log_path = Path(log.name)
        process = subprocess.Popen(check["cmd"], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   text=True)
        print(f"gate={check['name']} phase=start pid={process.pid}", file=sys.stderr, flush=True)
        last_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now - last_heartbeat >= 20:
                print(f"gate={check['name']} phase=heartbeat elapsed={int(now-started)}s "
                      f"pid={process.pid} alive=true", file=sys.stderr, flush=True)
                last_heartbeat = now
            time.sleep(0.25)
        returncode = process.returncode
    duration = time.monotonic() - started
    try:
        output = log_path.read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass
    print(f"gate={check['name']} phase=done elapsed={duration:.1f}s pid={process.pid} "
          f"alive=false rc={returncode}", file=sys.stderr, flush=True)
    return {"name": check["name"], "cmd": check["cmd"], "cwd": check["cwd"],
            "status": "pass" if returncode == 0 else "block", "rc": returncode,
            "duration_s": round(duration, 3), "output_tail": output[-12000:]}


def _gate_record_path(state: str | None, worktree: Path) -> Path:
    base = Path(state).expanduser().resolve().parent if state else registry.default_state_path().parent
    key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:16]
    return base / "worktree_gates" / f"{key}.json"


def cmd_gate(args: argparse.Namespace) -> int:
    worktree = _path(args.worktree)
    if not worktree.is_dir():
        _emit({"schema": GATE_SCHEMA, "action": "refused", "reason": "worktree not found"},
              as_json=args.json, human="✗ gate refused: worktree not found")
        return EXIT_USAGE
    files = _changed_files(worktree, args.base)
    checks = _plan_checks(files, worktree=worktree)
    payload: dict[str, Any] = {"schema": GATE_SCHEMA, "worktree": str(worktree),
                               "base": args.base, "files": files, "checks": checks}
    if args.plan_only:
        _emit(payload, as_json=args.json, human=json.dumps(payload, indent=2, ensure_ascii=False))
        return EXIT_OK
    results = [_run_check(check, worktree) for check in checks]
    verdict = "block" if any(result["status"] == "block" for result in results) else "pass"
    payload.update({"verdict": verdict, "results": results,
                    "head": _git(["rev-parse", "HEAD"], worktree)[1]})
    record_path = _gate_record_path(args.state, worktree)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    _emit(payload, as_json=args.json,
          human=f"{'✓' if verdict == 'pass' else '✗'} gate {verdict}: {worktree}")
    return EXIT_OK if verdict == "pass" else EXIT_BLOCK


def _handoff_payload(*, status: str, worktree: Path, reason: str | None = None,
                     observed_main_sha: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": HANDOFF_SCHEMA,
        "action": "handoff",
        "status": status,
        "worktree": str(worktree),
    }
    if reason:
        payload["reason"] = reason
    if observed_main_sha:
        payload["observed_main_sha"] = observed_main_sha
    return payload


def cmd_handoff(args: argparse.Namespace) -> int:
    """Emit one exact, IM-consumable package from a valid local hand-back.

    The incoming main SHA is supplied by IM after its live-main requery.  This
    command deliberately does not fetch, push, open a PR, or mutate GitHub;
    it only turns already-sealed local evidence into one machine-readable
    admission result.
    """
    worktree = _path(args.worktree)
    state_path = Path(args.state).expanduser().resolve() if args.state else registry.default_state_path()
    if not worktree.is_dir():
        payload = _handoff_payload(status="blocked", worktree=worktree,
                                   reason="worktree not found")
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    branch_rc, branch = _git(["branch", "--show-current"], worktree)
    state = registry.load_state(state_path)
    matches = [
        record for record in registry._active_records(state)
        if branch_rc == 0 and branch
        and registry._record_matches(record, branch=branch, path=str(worktree))
    ]
    if len(matches) != 1:
        payload = _handoff_payload(
            status="blocked", worktree=worktree,
            reason="handoff selector must match exactly one active worktree",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    record = matches[0]
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        payload = _handoff_payload(
            status="blocked", worktree=worktree,
            reason="typed kg.worktree.handback.v1 seal is missing",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    observed_main_sha = _resolve_commit(worktree, args.incoming_main) or args.incoming_main
    base_sha = str(seal.get("base_sha") or record.get("base_sha") or record.get("base") or "")
    if not base_sha:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="hand-back base is missing",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    if observed_main_sha != base_sha:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason=f"incoming main {observed_main_sha} does not equal hand-back base {base_sha}",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    if not registry._has_valid_handback(record):
        problems = registry.validate_handback_seal(record, repo=worktree)
        reason = "local hand-back is not valid"
        if problems:
            reason = f"local hand-back is not valid: {', '.join(item['kind'] for item in problems)}"
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason=reason,
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    tip_sha = str(seal.get("tip_sha") or record.get("handed_back_sha") or "")
    scope = record.get("scope")
    if scope_status(scope) != "known":
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="declared Scope is unstructured or invalid",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    scope_paths = sorted({item["path"] for item in scope_files(scope)})
    gate_path = _gate_record_path(str(state_path), worktree)
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        gate = None
    if not isinstance(gate, dict) or gate.get("verdict") != "pass":
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="no passing local gate is recorded for this worktree",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    if gate.get("schema") != GATE_SCHEMA or _path(str(gate.get("worktree") or "")) != worktree:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="local gate provenance does not match this worktree",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    gate_base = _resolve_commit(worktree, str(gate.get("base") or "")) or str(gate.get("base") or "")
    if gate_base != base_sha:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="local gate base does not equal hand-back base",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    if gate.get("head") != tip_sha:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="local gate HEAD does not equal hand-back tip",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK
    if sorted(gate.get("files") or []) != scope_paths:
        payload = _handoff_payload(
            status="blocked", worktree=worktree, observed_main_sha=observed_main_sha,
            reason="local gate changed files do not equal declared Scope",
        )
        _emit(payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}")
        return EXIT_BLOCK

    payload = _handoff_payload(
        status="ready-for-im", worktree=worktree, observed_main_sha=observed_main_sha,
    )
    payload.update({
        "branch": branch,
        "external_ids": sorted(registry._legacy_external_ids(record)),
        "base_sha": base_sha,
        "tip_sha": tip_sha,
        "scope": scope_paths,
        "handback_seal": seal,
        "validation": {
            "registry": {
                "status": "pass",
                "scope_status": "known",
                "handback": "valid",
                "clean": True,
            },
            "gate": gate,
        },
    })
    _emit(payload, as_json=args.json,
          human=f"✓ handoff ready-for-im: {branch} @ {tip_sha[:12]}")
    return EXIT_OK


def cmd_preflight(args: argparse.Namespace) -> int:
    state_path = Path(args.state).expanduser().resolve() if args.state else registry.default_state_path()
    state = registry.load_state(state_path)
    rebase_args = (args.worktree, args.base, args.incoming_main)
    if any(item is not None for item in rebase_args):
        missing = [name for name, value in (
            ("--worktree", args.worktree), ("--base", args.base),
            ("--incoming-main", args.incoming_main),
        ) if value is None]
        if missing:
            reason = f"rebase preflight requires {' '.join(missing)}"
            _emit({"schema": SCHEMA, "action": "rebase-preflight", "verdict": "block",
                   "reason": reason}, as_json=args.json,
                  human=f"✗ rebase preflight blocked: {reason}")
            return EXIT_USAGE
        worktree = _path(args.worktree)
        if not worktree.is_dir():
            reason = f"worktree not found: {worktree}"
            _emit({"schema": SCHEMA, "action": "rebase-preflight", "verdict": "block",
                   "reason": reason}, as_json=args.json,
                  human=f"✗ rebase preflight blocked: {reason}")
            return EXIT_USAGE
        branch_rc, branch = _git(["branch", "--show-current"], worktree)
        matches = [record for record in registry._active_records(state)
                   if branch_rc == 0 and branch
                   and registry._record_matches(record, branch=branch, path=str(worktree))]
        if len(matches) != 1:
            reason = "preflight selector must match exactly one active worktree"
            _emit({"schema": SCHEMA, "action": "rebase-preflight", "verdict": "block",
                   "reason": reason, "worktree": str(worktree)}, as_json=args.json,
                  human=f"✗ rebase preflight blocked: {reason}")
            return EXIT_BLOCK
        payload = _rebase_preflight(
            worktree, base=args.base, incoming_main=args.incoming_main,
            scope=matches[0].get("scope"),
        )
        payload.update({"registry": str(state_path), "branch": branch})
        _emit(payload, as_json=args.json,
              human=(f"✓ rebase preflight pass: {worktree}" if payload["verdict"] == "pass"
                     else f"✗ rebase preflight blocked: {payload.get('reason', 'unknown reason')}"))
        return EXIT_OK if payload["verdict"] == "pass" else EXIT_BLOCK
    active = [record for record in state.get("records", []) if record.get("status") == "active"]
    payload = {"schema": SCHEMA, "action": "preflight", "registry": str(state_path),
               "active_worktrees": len(active), "worktrees": _git(["worktree", "list"], ROOT)[1]}
    _emit(payload, as_json=args.json,
          human=f"✓ preflight: {len(active)} active local worktree(s)")
    return EXIT_OK


def cmd_freeze(args: argparse.Namespace) -> int:
    current = _is_frozen()
    if args.action == "status":
        _emit({"schema": "kg.worktree.freeze.v1", "frozen": current is not None,
               "state": current}, as_json=args.json,
              human=(f"frozen: {current.get('reason')}" if current else "not frozen"))
        return EXIT_OK
    if args.action == "on":
        if current and not args.force:
            return EXIT_BLOCK
        if not args.reason:
            return EXIT_USAGE
        _, now = registry.resolve_now()
        payload = {"schema": "kg.worktree.freeze.v1", "reason": args.reason,
                   "created_at": now}
        _write_freeze(payload)
        _emit({"schema": "kg.worktree.freeze.v1", "action": "on", "state": payload},
              as_json=args.json, human=f"✓ frozen: {args.reason}")
        return EXIT_OK
    _write_freeze(None)
    _emit({"schema": "kg.worktree.freeze.v1", "action": "off"}, as_json=args.json,
          human="✓ unfrozen")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    argv = ["resolve", "--status", args.status]
    if args.branch:
        argv += ["--branch", args.branch]
    if args.path:
        argv += ["--path", args.path]
    if args.state:
        argv += ["--state", args.state]
    if args.json:
        argv.append("--json")
    if args.expected_generation is not None:
        argv += ["--expected-generation", str(args.expected_generation)]
    if args.expected_head_sha:
        argv += ["--expected-head-sha", args.expected_head_sha]
    rc = registry.main(argv)
    if rc != EXIT_OK or not args.remove:
        return rc
    worktree = _path(args.path) if args.path else None
    if worktree and worktree != ROOT:
        git_rc, output = _git(["worktree", "remove", str(worktree)], ROOT)
        if git_rc != 0:
            print(f"✗ worktree remove failed: {output}", file=sys.stderr)
            return EXIT_BLOCK
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub-native local worktree coordinator")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state", default=None); p.add_argument("--json", action="store_true")

    pre = sub.add_parser("preflight", help="show local worktree/registry health")
    common(pre); pre.add_argument("--worktree"); pre.add_argument("--base")
    pre.add_argument("--incoming-main"); pre.set_defaults(func=cmd_preflight)

    op = sub.add_parser("open", help="create a branch and linked worktree")
    common(op); op.add_argument("--intent", required=True); op.add_argument("--slug", required=True)
    op.add_argument("--type", choices=BRANCH_TYPES); op.add_argument("--base", default=BASE_DEFAULT)
    op.add_argument("--path", default=None); op.add_argument("--external-id", action="append", default=[])
    op.add_argument("--scope"); op.add_argument("--scope-file"); op.add_argument("--codex-thread-id")
    op.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    op.set_defaults(func=cmd_open)

    ad = sub.add_parser("adopt", help="register an existing linked worktree")
    common(ad); ad.add_argument("--worktree", default=None); ad.add_argument("--intent", required=True)
    ad.add_argument("--base", default=BASE_DEFAULT); ad.add_argument("--external-id", action="append", default=[])
    ad.add_argument("--scope"); ad.add_argument("--scope-file"); ad.add_argument("--codex-thread-id")
    ad.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    ad.set_defaults(func=cmd_adopt)

    gate = sub.add_parser("gate", help="run focused local checks for changed files")
    common(gate); gate.add_argument("--worktree", required=True); gate.add_argument("--base", default=BASE_DEFAULT)
    gate.add_argument("--plan-only", action="store_true"); gate.set_defaults(func=cmd_gate)

    handoff = sub.add_parser("handoff", help="package a valid local hand-back for IM")
    common(handoff); handoff.add_argument("--worktree", required=True)
    handoff.add_argument("--incoming-main", required=True)
    handoff.set_defaults(func=cmd_handoff)

    hand = sub.add_parser("hand-back", help="record exact HEAD evidence")
    common(hand); hand.add_argument("--branch"); hand.add_argument("--path"); hand.add_argument("--outcomes")
    hand.set_defaults(func=lambda args: registry.main([
        "hand-back", *(["--branch", args.branch] if args.branch else []),
        *(["--path", args.path] if args.path else []),
        *(["--state", args.state] if args.state else []),
        *(["--outcomes", args.outcomes] if args.outcomes else []),
        *(["--json"] if args.json else []),
    ]))

    resolved = sub.add_parser("resolve", help="transition an exact local ownership claim")
    common(resolved); resolved.add_argument("--branch"); resolved.add_argument("--path")
    resolved.add_argument("--status", choices=registry.RESOLVE_STATUS, required=True)
    resolved.add_argument("--expected-generation", type=int)
    resolved.add_argument("--expected-head-sha")
    resolved.add_argument("--remove", action="store_true")
    resolved.set_defaults(func=cmd_resolve)

    freeze = sub.add_parser("freeze", help="pause local worktree birth/adoption")
    common(freeze); freeze.add_argument("action", choices=("on", "off", "status"))
    freeze.add_argument("--reason"); freeze.add_argument("--force", action="store_true")
    freeze.set_defaults(func=cmd_freeze)

    listed = sub.add_parser("list", help="show local ownership records")
    common(listed); listed.add_argument("--active-only", action="store_true"); listed.add_argument("--branch")
    listed.add_argument("--path"); listed.add_argument("--external-id"); listed.add_argument("--conflicts", action="store_true")
    listed.set_defaults(func=lambda args: registry.main([
        "list", *(["--state", args.state] if args.state else []),
        *(["--active-only"] if args.active_only else []), *(["--branch", args.branch] if args.branch else []),
        *(["--path", args.path] if args.path else []), *(["--external-id", args.external_id] if args.external_id else []),
        *(["--conflicts"] if args.conflicts else []), *(["--json"] if args.json else []),
    ]))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

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

import worktree_registry as registry  # noqa: E402

SCHEMA = "kg.worktree.orchestrate.v2"
GATE_SCHEMA = "kg.worktree.gate.v2"
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
    if any(item.startswith("ops/") or item.startswith(".github/workflows/") for item in files):
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


def cmd_preflight(args: argparse.Namespace) -> int:
    state_path = Path(args.state).expanduser().resolve() if args.state else registry.default_state_path()
    state = registry.load_state(state_path)
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
    common(pre); pre.set_defaults(func=cmd_preflight)

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

    hand = sub.add_parser("hand-back", help="record exact HEAD evidence")
    common(hand); hand.add_argument("--branch"); hand.add_argument("--path"); hand.add_argument("--outcomes")
    hand.set_defaults(func=lambda args: registry.main([
        "hand-back", *(["--branch", args.branch] if args.branch else []),
        *(["--path", args.path] if args.path else []),
        *(["--state", args.state] if args.state else []),
        *(["--outcomes", args.outcomes] if args.outcomes else []),
        *(["--json"] if args.json else []),
    ]))

    resolved = sub.add_parser("resolve", help="close local ownership after the GitHub PR is merged")
    common(resolved); resolved.add_argument("--branch"); resolved.add_argument("--path")
    resolved.add_argument("--status", choices=registry.RESOLVE_STATUS, required=True)
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

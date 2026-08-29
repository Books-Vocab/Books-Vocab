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

import worktree_cleanup
import worktree_reanchor
import worktree_reanchor_core.published_remote_recovery as worktree_published_remote_recovery
import worktree_registry as registry
import worktree_resume
from delivery_control.adapters.operation_lock import OperationLock
from lib.worktree_scope import scope_files, scope_status
from worktree_reanchor_core import git_ops as reanchor_git_ops
from worktree_reanchor_core import registry_ops as reanchor_registry_ops
from worktree_reanchor_core.domain import commit_sha as reanchor_commit_sha
from worktree_reanchor_core.errors import ReanchorRefused

SCHEMA = "kg.worktree.orchestrate.v2"
GATE_SCHEMA = "kg.worktree.gate.v2"
HANDOFF_SCHEMA = "kg.worktree.handoff.v1"
IOS_DIAGNOSTICS_SCHEMA = "kg.ios.diagnostics.v1"
IOS_TEST_CHECK = "ios-tests"
IOS_RECORDED_ISSUE_RE = re.compile(
    r"recorded an issue at (?P<file>[^:\s]+):(?P<line>\d+):(?P<column>\d+):"
)
BASE_DEFAULT = "main"
BRANCH_TYPES = ("debug", "feat", "research")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXIT_OK = 0
EXIT_BLOCK = 1
EXIT_USAGE = 64
MUTATING_COMMANDS = frozenset(
    {
        "open",
        "adopt",
        "reanchor",
        "reanchor-handback",
        "resume-published",
        "recover-published-remote",
        "hand-back",
        "resolve",
        "freeze",
    }
)


def _git(args: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
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
        return (
            f"local worktree operations are frozen: {freeze.get('reason', 'no reason')}"
        )
    return None


def _scope_args(args: argparse.Namespace) -> list[str]:
    if args.scope is not None:
        return ["--scope", args.scope]
    if args.scope_file is not None:
        return ["--scope-file", args.scope_file]
    return []


def _registry_register(
    *,
    branch: str,
    path: Path,
    intent: str,
    base: str,
    base_sha: str,
    external_ids: list[str],
    args: argparse.Namespace,
) -> tuple[int, dict[str, Any]]:
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    try:
        scope = registry._scope_from_args(args)
    except (OSError, ValueError) as exc:
        return EXIT_USAGE, {"reason": str(exc)}
    with registry._ledger_lock(state_path):
        state = registry.load_state(state_path)
        active_matches = [
            record
            for record in registry._active_records(state)
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
            state,
            branch=branch,
            path=str(path),
            intent=intent,
            base=base,
            external_ids=external_ids,
            scope=scope,
            codex_thread_id=args.codex_thread_id,
            delegated=args.delegated,
        )
        if rc == registry.EXIT_OK:
            record["base_sha"] = base_sha
            registry.save_state(state_path, state)
    return rc, record


def cmd_open(args: argparse.Namespace) -> int:
    refusal = _require_unfrozen("open")
    if refusal:
        _emit(
            {"schema": SCHEMA, "action": "refused", "reason": refusal},
            as_json=args.json,
            human=f"✗ open refused: {refusal}",
        )
        return EXIT_BLOCK
    if not SLUG_RE.fullmatch(args.slug):
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": "slug must be kebab-case",
            },
            as_json=args.json,
            human="✗ open refused: slug must be kebab-case",
        )
        return EXIT_USAGE
    branch = f"{_intent_type(args.intent, args.type)}/{args.slug}"
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    worktree = (
        _path(args.path) if args.path else ROOT / ".claude" / "worktrees" / args.slug
    )
    if worktree.exists():
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": f"path exists: {worktree}",
            },
            as_json=args.json,
            human=f"✗ open refused: path exists: {worktree}",
        )
        return EXIT_USAGE
    external_ids = list(getattr(args, "external_id", []) or [])
    requires_external_id = bool(
        getattr(args, "delegated", False) or getattr(args, "codex_thread_id", None)
    )
    if requires_external_id and not any(
        isinstance(external_id, str) and external_id.strip()
        for external_id in external_ids
    ):
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": "--external-id is required for delegated or owner-bound open",
            },
            as_json=args.json,
            human="✗ open refused: --external-id is required for delegated or owner-bound open",
        )
        return EXIT_BLOCK
    base_sha = _resolve_commit(ROOT, args.base)
    if base_sha is None:
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": "base ref cannot be resolved",
            },
            as_json=args.json,
            human="✗ open refused: base ref cannot be resolved",
        )
        return EXIT_BLOCK
    rc, record = _registry_register(
        branch=branch,
        path=worktree,
        intent=args.intent,
        base=args.base,
        base_sha=base_sha,
        external_ids=external_ids,
        args=args,
    )
    if rc != registry.EXIT_OK:
        _emit(
            {"schema": SCHEMA, "action": "refused", "record": record},
            as_json=args.json,
            human=f"✗ open refused: {record.get('reason', record)}",
        )
        return rc
    git_rc, output = _git(["worktree", "add", "-b", branch, str(worktree), base_sha])
    if git_rc != 0:
        # Keep the ledger truthful if provisioning fails; no branch is deleted here
        # because GitHub may already know the name and branch removal is a separate
        # explicit action.
        observed_branch_head = _resolve_commit(ROOT, branch) or base_sha
        expected_generation = str(record.get("claim_generation", 0))
        compensation_rc = registry.main(
            [
                "resolve",
                "--branch",
                branch,
                "--path",
                str(worktree),
                "--status",
                "abandoned",
                "--expected-generation",
                expected_generation,
                "--expected-head-sha",
                observed_branch_head,
                "--state",
                str(state_path),
                "--json",
            ],
            acquire_lock=False,
        )
        reason = (
            "git worktree add failed"
            if compensation_rc == registry.EXIT_OK
            else "git worktree add failed and registry compensation failed"
        )
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": reason,
                "git": output,
                "record": record,
                "compensation_rc": compensation_rc,
            },
            as_json=args.json,
            human=f"✗ open refused: {reason}: {output}",
        )
        return EXIT_BLOCK
    record["path"] = str(worktree)
    _emit(
        {"schema": SCHEMA, "action": "open", "record": record},
        as_json=args.json,
        human=f"✓ opened {branch} at {worktree}",
    )
    return EXIT_OK


def cmd_adopt(args: argparse.Namespace) -> int:
    refusal = _require_unfrozen("adopt")
    if refusal:
        _emit(
            {"schema": SCHEMA, "action": "refused", "reason": refusal},
            as_json=args.json,
            human=f"✗ adopt refused: {refusal}",
        )
        return EXIT_BLOCK
    worktree = _path(args.worktree or os.getcwd())
    if not worktree.is_dir():
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": f"not a directory: {worktree}",
            },
            as_json=args.json,
            human=f"✗ adopt refused: not a directory: {worktree}",
        )
        return EXIT_USAGE
    rc, branch = _git(["branch", "--show-current"], worktree)
    if rc != 0 or not branch:
        _emit(
            {"schema": SCHEMA, "action": "refused", "reason": "worktree is detached"},
            as_json=args.json,
            human="✗ adopt refused: worktree is detached",
        )
        return EXIT_USAGE
    base_sha = _resolve_commit(worktree, args.base)
    if base_sha is None:
        _emit(
            {
                "schema": SCHEMA,
                "action": "refused",
                "reason": "base ref cannot be resolved",
            },
            as_json=args.json,
            human="✗ adopt refused: base ref cannot be resolved",
        )
        return EXIT_BLOCK
    rc, record = _registry_register(
        branch=branch,
        path=worktree,
        intent=args.intent,
        base=args.base,
        base_sha=base_sha,
        external_ids=list(args.external_id or []),
        args=args,
    )
    _emit(
        {
            "schema": SCHEMA,
            "action": "adopt" if rc == EXIT_OK else "refused",
            "record": record,
        },
        as_json=args.json,
        human=(
            f"✓ adopted {branch} at {worktree}"
            if rc == EXIT_OK
            else f"✗ adopt refused: {record.get('reason', record)}"
        ),
    )
    return rc


def cmd_reanchor(args: argparse.Namespace) -> int:
    return worktree_reanchor.cmd_reanchor(
        args, freeze_reason=_require_unfrozen("reanchor")
    )


REANCHOR_HANDBACK_SCHEMA = "kg.worktree.reanchor-handback.v1"


def _branch_pull_requests(repo: Path, branch: str) -> tuple[int, ...]:
    """Read every PR for a branch before an owner-local handback reanchor."""

    from delivery_control.adapters.github_cli import GitHubCliAdapter

    try:
        inventory = GitHubCliAdapter(repo=repo).list_pull_requests_for_branch(branch)
    except Exception as exc:
        raise ReanchorRefused(
            "branch PR inventory could not be read",
            error=f"{type(exc).__name__}: {exc}",
        ) from exc
    if inventory.problems:
        raise ReanchorRefused(
            "branch PR inventory contains malformed GitHub facts",
            problems=[problem.reason for problem in inventory.problems],
        )
    return tuple(item.number for item in inventory.records)


def _remote_main_sha(repo: Path) -> str:
    """Read the authoritative remote main ref for an owner-local transition."""

    return reanchor_git_ops._remote_head(repo, "main")


def _reanchor_handback_diff_names(
    worktree: Path, *, start: str, end: str
) -> tuple[str, ...]:
    rc, output = reanchor_git_ops._git(
        ["diff", "--name-only", "--no-renames", f"{start}..{end}"], worktree
    )
    if rc != 0:
        raise ReanchorRefused(
            "reanchor handback diff could not be computed",
            start=start,
            end=end,
            git=output,
        )
    return tuple(sorted({item for item in output.splitlines() if item}))


def _reanchor_handback_payload(
    *,
    args: argparse.Namespace,
    worktree: Path,
    status: str,
    reason: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": REANCHOR_HANDBACK_SCHEMA,
        "action": "reanchor-handback",
        "status": status,
        "lane": args.lane,
        "branch": args.branch,
        "owner_thread_id": args.owner_thread_id,
        "claim_generation": args.claim_generation,
        "expected_head": args.expected_head_sha,
        "live_main": args.live_main,
        "worktree": str(worktree),
    }
    if reason:
        payload["reason"] = reason
    payload.update(details)
    return payload


def cmd_reanchor_handback(args: argparse.Namespace) -> int:
    """Reanchor one owner-local typed handback that has no durable PR yet.

    This is deliberately narrower than the PR-based ``reanchor`` command.  It
    proves that the active owner claim is still exact, that no PR or remote
    branch owns the branch, rebases the already-sealed local work onto the
    supplied live main, and only then advances the registry claim generation.
    """

    refusal = _require_unfrozen("reanchor-handback")
    worktree = _path(args.path)
    if refusal:
        payload = _reanchor_handback_payload(
            args=args, worktree=worktree, status="blocked", reason=refusal
        )
        _emit(
            payload, as_json=args.json, human=f"✗ reanchor-handback blocked: {refusal}"
        )
        return EXIT_BLOCK

    repo = _path(args.repo)
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path(repo)
    )
    try:
        live_main = reanchor_commit_sha(args.live_main, label="live main")
        expected_head = reanchor_commit_sha(
            args.expected_head_sha, label="expected hand-back HEAD"
        )
        if args.claim_generation < 0:
            raise ReanchorRefused("claim generation must be non-negative")
        reanchor_git_ops.validate_repository(repo)
        reanchor_git_ops.validate_repository(worktree)
        remote_main = _remote_main_sha(repo)
        if remote_main != live_main:
            raise ReanchorRefused(
                "supplied live main does not match remote origin/main",
                live_main=live_main,
                remote_main=remote_main,
            )
        preflight = reanchor_registry_ops.preflight(
            state_path=state_path,
            lane_id=args.lane,
            branch=args.branch,
            owner_thread_id=args.owner_thread_id,
            claim_generation=args.claim_generation,
            expected_remote_head=expected_head,
            live_main=live_main,
            target=worktree,
        )
        original = preflight.original
        if original.get("status") != registry.STATUS_ACTIVE:
            raise ReanchorRefused(
                "reanchor-handback requires an active claim with a typed hand-back",
                status=original.get("status"),
            )
        branch_rc, current_branch = reanchor_git_ops._git(
            ["branch", "--show-current"], worktree
        )
        head_rc, current_head = reanchor_git_ops._git(
            ["rev-parse", "--verify", "HEAD^{commit}"], worktree
        )
        status_rc, dirty = reanchor_git_ops._git(["status", "--porcelain=v1"], worktree)
        if branch_rc != 0 or current_branch != args.branch:
            raise ReanchorRefused("worktree branch differs from the exact active claim")
        if head_rc != 0 or current_head != expected_head:
            raise ReanchorRefused(
                "worktree HEAD differs from the exact stored hand-back",
                expected_head=expected_head,
                observed_head=current_head,
            )
        if status_rc != 0 or dirty:
            raise ReanchorRefused("owner worktree must be clean before reanchor")

        rows = reanchor_git_ops._worktree_rows(repo)
        matching_rows = [
            row
            for row in rows
            if Path(row.get("worktree", "")).expanduser().resolve() == worktree
        ]
        if len(matching_rows) != 1 or matching_rows[0].get("branch") != (
            f"refs/heads/{args.branch}"
        ):
            raise ReanchorRefused(
                "physical worktree inventory does not match the active claim"
            )
        local_branch = reanchor_git_ops._local_branch_sha(repo, args.branch)
        if local_branch != expected_head:
            raise ReanchorRefused(
                "local branch differs from the exact stored hand-back",
                expected_head=expected_head,
                observed_head=local_branch,
            )

        remote_rc, remote_output = reanchor_git_ops._git(
            ["ls-remote", "--heads", "origin", f"refs/heads/{args.branch}"], repo
        )
        if remote_rc != 0:
            raise ReanchorRefused(
                "remote branch inventory could not be read", git=remote_output
            )
        if [line for line in remote_output.splitlines() if line.strip()]:
            raise ReanchorRefused(
                "active handback reanchor requires the remote branch to be absent"
            )
        pull_requests = _branch_pull_requests(repo, args.branch)
        if pull_requests:
            raise ReanchorRefused(
                "active handback reanchor requires no branch PR",
                pull_requests=list(pull_requests),
            )

        base_sha = preflight.base_sha
        for label, ancestor, descendant in (
            ("hand-back base", base_sha, expected_head),
            ("hand-back base", base_sha, live_main),
        ):
            if (
                reanchor_git_ops._git(
                    ["merge-base", "--is-ancestor", ancestor, descendant], worktree
                )[0]
                != 0
            ):
                raise ReanchorRefused(
                    f"{label} is not an ancestor of the exact target commit",
                    ancestor=ancestor,
                    descendant=descendant,
                )
        stored_scope = reanchor_git_ops.scope_operations(
            worktree, start=base_sha, end=expected_head
        )
        if stored_scope != preflight.declared:
            raise ReanchorRefused(
                "stored hand-back differs from the exact declared Scope",
                declared_scope=list(preflight.declared),
                observed_scope=list(stored_scope),
            )
        scope_paths = tuple(item[0] for item in preflight.declared)
        incoming_files = _reanchor_handback_diff_names(
            worktree, start=base_sha, end=live_main
        )
        collisions = tuple(sorted(set(scope_paths).intersection(incoming_files)))
        if collisions:
            raise ReanchorRefused(
                "incoming main changes collide with the declared Scope",
                collisions=list(collisions),
            )

        rebase_rc, rebase_output = reanchor_git_ops._git(
            ["rebase", "--onto", live_main, base_sha, args.branch], worktree
        )
        if rebase_rc != 0:
            abort_rc, abort_output = reanchor_git_ops._git(
                ["rebase", "--abort"], worktree
            )
            raise ReanchorRefused(
                "active handback rebase failed; registry was left unchanged",
                git=rebase_output,
                rebase_abort_rc=abort_rc,
                rebase_abort=abort_output,
            )
        rebased = True
        try:
            final_branch_rc, final_branch = reanchor_git_ops._git(
                ["branch", "--show-current"], worktree
            )
            final_status_rc, final_dirty = reanchor_git_ops._git(
                ["status", "--porcelain=v1"], worktree
            )
            final_head_rc, new_head = reanchor_git_ops._git(
                ["rev-parse", "--verify", "HEAD^{commit}"], worktree
            )
            if (
                final_branch_rc != 0
                or final_branch != args.branch
                or final_status_rc != 0
                or final_dirty
                or final_head_rc != 0
            ):
                raise ReanchorRefused(
                    "reanchored worktree failed exact branch/clean/HEAD readback"
                )
            if (
                reanchor_git_ops._git(
                    ["merge-base", "--is-ancestor", live_main, new_head], worktree
                )[0]
                != 0
            ):
                raise ReanchorRefused("reanchored HEAD is not based on exact live main")
            if (
                reanchor_git_ops.scope_operations(
                    worktree, start=live_main, end=new_head
                )
                != preflight.declared
            ):
                raise ReanchorRefused("reanchored branch differs from the exact Scope")
            remote_main = _remote_main_sha(repo)
            if remote_main != live_main:
                raise ReanchorRefused(
                    "remote origin/main changed during reanchor",
                    live_main=live_main,
                    remote_main=remote_main,
                )
            active = reanchor_registry_ops.register_active(
                state_path=state_path,
                preflight_result=preflight,
                target=worktree,
                live_main=live_main,
                lane_id=args.lane,
                claim_generation=args.claim_generation,
            )
            rebased = False
        except Exception:
            if rebased:
                rollback_rc, rollback_output = reanchor_git_ops._git(
                    ["reset", "--hard", expected_head], worktree
                )
                if rollback_rc != 0:
                    raise ReanchorRefused(
                        "active handback reanchor failed and exact rollback failed",
                        rollback_rc=rollback_rc,
                        rollback=rollback_output,
                    )
            raise
    except (OSError, ReanchorRefused, TypeError, ValueError, KeyError) as exc:
        reason = exc.reason if isinstance(exc, ReanchorRefused) else str(exc)
        details = dict(exc.details) if isinstance(exc, ReanchorRefused) else {}
        payload = _reanchor_handback_payload(
            args=args, worktree=worktree, status="blocked", reason=reason, **details
        )
        _emit(
            payload, as_json=args.json, human=f"✗ reanchor-handback blocked: {reason}"
        )
        return EXIT_BLOCK

    payload = _reanchor_handback_payload(
        args=args,
        worktree=worktree,
        status="ready-for-owner-tests",
        previous_head=expected_head,
        head=new_head,
        base_sha=live_main,
        claim_generation=active["claim_generation"],
        scope=list(scope_paths),
        registry={
            "status": "pass",
            "original_claim_generation": args.claim_generation,
            "new_claim_generation": active["claim_generation"],
            "old_base_sha": base_sha,
        },
        remote_branch="absent",
        pull_requests=[],
        next_action=(
            "same owner runs the bounded gate and emits a fresh typed hand-back; "
            "PI may then create the durable PR"
        ),
        not_performed=["tests", "hand-back", "push", "force-push"],
    )
    _emit(
        payload,
        as_json=args.json,
        human=f"✓ reanchor-handback ready-for-owner-tests: {args.branch} @ {new_head[:12]}",
    )
    return EXIT_OK


def cmd_resume_published(args: argparse.Namespace) -> int:
    return worktree_resume.cmd_resume(
        args, freeze_reason=_require_unfrozen("resume-published")
    )


def cmd_recover_published_remote(args: argparse.Namespace) -> int:
    return worktree_published_remote_recovery.cmd_recover(
        args, freeze_reason=_require_unfrozen("recover-published-remote")
    )


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
    worktree: Path,
    *,
    base: str,
    incoming_main: str,
    scope: object,
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
    payload.update(
        {
            "base_sha": base_sha,
            "incoming_main_sha": incoming_main_sha,
            "head_sha": head_sha,
        }
    )
    if (
        _git(["merge-base", "--is-ancestor", base_sha, incoming_main_sha], worktree)[0]
        != 0
    ):
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
    payload.update(
        {
            "incoming_main_files": incoming_main_files,
            "branch_files": branch_files,
            "collisions": collisions,
        }
    )
    if collisions:
        payload["reason"] = "incoming-main changes collide with declared Scope"
        return payload
    payload["verdict"] = "pass"
    return payload


def _plan_checks(
    files: list[str],
    *,
    worktree: Path | None = None,
    scope_files: list[str] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [
        {
            "name": "git-diff-check",
            "kind": "shell",
            "cwd": ".",
            "cmd": ["git", "diff", "--check"],
            "level": "block",
        }
    ]
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
        checks.append(
            {
                "name": f"shell-syntax:{item}",
                "kind": "shell",
                "cwd": ".",
                "cmd": ["bash", "-n", item],
                "level": "block",
            }
        )
    docs = [item for item in files if item.startswith("docs/") and item.endswith(".md")]
    if "docs/registry.yml" in files or docs:
        checks.append(
            {
                "name": "docs-lint",
                "kind": "shell",
                "cwd": ".",
                "cmd": (
                    ["./ops/docs_lint.sh", "--registry"]
                    if not docs
                    else ["./ops/docs_lint.sh", "--files", *docs]
                ),
                "level": "block",
            }
        )
    if any(item.startswith("backend/") for item in files):
        checks.append(
            {
                "name": "backend-tests",
                "kind": "shell",
                "cwd": "backend",
                "cmd": ["uv", "run", "--locked", "python", "-m", "pytest", "-q"],
                "level": "block",
            }
        )
    if any(item.startswith("ios/") for item in files):
        checks.append(
            {
                "name": IOS_TEST_CHECK,
                "kind": "shell",
                "cwd": ".",
                # Keep the full unit suite, but require an isolated pool
                # simulator for every agent gate.  --json exposes the existing
                # xcresult/log diagnostics so a failure can be downgraded only
                # after its source is proven outside this changed Scope.
                "cmd": [
                    "./ops/ios_ops.sh",
                    "test",
                    "--unit",
                    "--lease",
                    "--json",
                ],
                "level": "block",
                "scope_files": sorted(
                    set(scope_files if scope_files is not None else files)
                ),
            }
        )
    if any(item.startswith(("ops/", ".github/workflows/")) for item in files):
        checks.append(
            {
                "name": "ops-tests",
                "kind": "shell",
                "cwd": ".",
                "cmd": ["./ops/test_ops.sh", "worktree"],
                "level": "block",
            }
        )
    python_files = sorted(
        {
            item
            for item in files
            if item.endswith(".py")
            and (worktree is None or (worktree / item).is_file())
        }
    )
    if python_files:
        checks.append(
            {
                "name": "python-format-check",
                "kind": "shell",
                "cwd": ".",
                "cmd": [
                    "uv",
                    "run",
                    "--no-project",
                    "--python",
                    "3.13",
                    "--with",
                    "ruff==0.16.3",
                    "ruff",
                    "format",
                    "--check",
                    *python_files,
                ],
                "level": "block",
            }
        )
    return checks


def _json_objects(output: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    starts = [match.start() for match in re.finditer(r"(?m)^[ \t]*\{", output)]
    for start in reversed(starts):
        try:
            value, _ = decoder.raw_decode(output[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _extract_ios_diagnostics(output: str) -> dict[str, Any] | None:
    for payload in _json_objects(output):
        if payload.get("schema") == IOS_DIAGNOSTICS_SCHEMA:
            return payload
        diagnostics = payload.get("diagnostics")
        if (
            isinstance(diagnostics, dict)
            and diagnostics.get("schema") == IOS_DIAGNOSTICS_SCHEMA
        ):
            return diagnostics
    return None


def _relative_worktree_path(value: Any, worktree: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    raw = raw.removeprefix("file://")
    candidate = Path(raw)
    root = worktree.resolve()
    if not candidate.is_absolute():
        if raw == ".." or raw.startswith("../"):
            return None
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _raw_ios_failure_files(output: str | None, worktree: Path) -> list[str] | None:
    if not isinstance(output, str):
        return None
    references = [
        match.group("file") for match in IOS_RECORDED_ISSUE_RE.finditer(output)
    ]
    if not references:
        return None

    root = worktree.resolve()
    resolved: set[str] = set()
    for reference in references:
        if reference.startswith(("/", "./")) or "/" in reference:
            normalized = _relative_worktree_path(reference, root)
        else:
            matches: list[str] = []
            try:
                candidates = root.rglob("*")
                for candidate in candidates:
                    if candidate.name != reference or not candidate.is_file():
                        continue
                    try:
                        relative = candidate.resolve().relative_to(root)
                    except (OSError, ValueError):
                        continue
                    if ".git" in relative.parts:
                        continue
                    matches.append(relative.as_posix())
            except OSError:
                return None
            normalized = matches[0] if len(matches) == 1 else None
        if normalized is None:
            return None
        resolved.add(normalized)
    return sorted(resolved)


def _classify_ios_failure(
    diagnostics: dict[str, Any] | None,
    *,
    scope_files: Any,
    worktree: Path,
    output: str | None = None,
) -> dict[str, Any]:
    blocked = {
        "verdict": "block",
        "reason": "diagnostics-unavailable",
        "failure_files": [],
    }
    if not isinstance(scope_files, list) or not scope_files:
        blocked["reason"] = "changed-scope-unknown"
        return blocked

    scope_paths: set[str] = set()
    for item in scope_files:
        normalized = _relative_worktree_path(item, worktree)
        if normalized is None:
            blocked["reason"] = "changed-scope-unknown"
            return blocked
        scope_paths.add(normalized)

    if not isinstance(diagnostics, dict):
        return blocked
    if diagnostics.get("schema") != IOS_DIAGNOSTICS_SCHEMA:
        return blocked
    if diagnostics.get("result") != "fail":
        blocked["reason"] = "diagnostics-result-unknown"
        return blocked
    if diagnostics.get("truncated") is not False:
        blocked["reason"] = "diagnostics-incomplete"
        return blocked

    counts = diagnostics.get("counts")
    items = diagnostics.get("diagnostics")
    total = diagnostics.get("totalDiagnostics")
    error_count = counts.get("errors") if isinstance(counts, dict) else None
    if (
        not isinstance(error_count, int)
        or isinstance(error_count, bool)
        or error_count <= 0
        or not isinstance(items, list)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total != len(items)
    ):
        blocked["reason"] = "failure-evidence-incomplete"
        return blocked

    failures = [
        item
        for item in items
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    if len(failures) != error_count:
        blocked["reason"] = "failure-evidence-incomplete"
        return blocked

    failure_files: set[str] = set()
    raw_failure_files: list[str] | None = None
    for item in failures:
        normalized = _relative_worktree_path(item.get("file"), worktree)
        if normalized is None:
            if raw_failure_files is None:
                raw_failure_files = _raw_ios_failure_files(output, worktree)
            if raw_failure_files is None:
                blocked["reason"] = "failure-location-unknown"
                return blocked
            failure_files.update(raw_failure_files)
            continue
        failure_files.add(normalized)

    result = {
        "verdict": "advisory",
        "reason": "all-failures-outside-changed-scope",
        "failure_files": sorted(failure_files),
    }
    if raw_failure_files is not None:
        result["raw_failure_files"] = raw_failure_files
        result["location_source"] = "recorded-issue-output"
    if failure_files.intersection(scope_paths):
        result["verdict"] = "block"
        result["reason"] = "failure-in-changed-scope"
    return result


def _run_check(check: dict[str, Any], worktree: Path) -> dict[str, Any]:
    cwd = worktree / str(check.get("cwd") or ".")
    started = time.monotonic()
    with tempfile.NamedTemporaryFile(
        prefix="kg-gate-", suffix=".log", delete=False
    ) as log:
        log_path = Path(log.name)
        process = subprocess.Popen(
            check["cmd"], cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True
        )
        print(
            f"gate={check['name']} phase=start pid={process.pid}",
            file=sys.stderr,
            flush=True,
        )
        last_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now - last_heartbeat >= 20:
                print(
                    f"gate={check['name']} phase=heartbeat elapsed={int(now - started)}s "
                    f"pid={process.pid} alive=true",
                    file=sys.stderr,
                    flush=True,
                )
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
    print(
        f"gate={check['name']} phase=done elapsed={duration:.1f}s pid={process.pid} "
        f"alive=false rc={returncode}",
        file=sys.stderr,
        flush=True,
    )
    diagnostics = (
        _extract_ios_diagnostics(output)
        if check.get("name") == IOS_TEST_CHECK
        else None
    )
    level = check["level"]
    failure_scope: dict[str, Any] | None = None
    if check.get("name") == IOS_TEST_CHECK and returncode != 0:
        failure_scope = _classify_ios_failure(
            diagnostics,
            scope_files=check.get("scope_files"),
            worktree=worktree,
            output=output,
        )
        if failure_scope["verdict"] != "advisory":
            level = "block"
        else:
            level = "advisory"
    result: dict[str, Any] = {
        "name": check["name"],
        "cmd": check["cmd"],
        "cwd": check["cwd"],
        "level": level,
        "status": "pass" if returncode == 0 else "block",
        "rc": returncode,
        "duration_s": round(duration, 3),
        "output_tail": output[-12000:],
    }
    if diagnostics is not None:
        result["diagnostics"] = diagnostics
    if failure_scope is not None:
        result["failure_scope"] = failure_scope
    return result


def _gate_record_path(state: str | None, worktree: Path) -> Path:
    base = (
        Path(state).expanduser().resolve().parent
        if state
        else registry.default_state_path().parent
    )
    key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:16]
    return base / "worktree_gates" / f"{key}.json"


def cmd_gate(args: argparse.Namespace) -> int:
    worktree = _path(args.worktree)
    if not worktree.is_dir():
        _emit(
            {
                "schema": GATE_SCHEMA,
                "action": "refused",
                "reason": "worktree not found",
            },
            as_json=args.json,
            human="✗ gate refused: worktree not found",
        )
        return EXIT_USAGE
    files = _changed_files(worktree, args.base)
    checks = _plan_checks(files, worktree=worktree, scope_files=files)
    payload: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "worktree": str(worktree),
        "base": args.base,
        "files": files,
        "checks": checks,
    }
    if args.plan_only:
        _emit(
            payload,
            as_json=args.json,
            human=json.dumps(payload, indent=2, ensure_ascii=False),
        )
        return EXIT_OK
    results = [_run_check(check, worktree) for check in checks]
    verdict = (
        "block"
        if any(
            result.get("status") == "block" and result.get("level", "block") == "block"
            for result in results
        )
        else "pass"
    )
    payload.update(
        {
            "verdict": verdict,
            "results": results,
            "head": _git(["rev-parse", "HEAD"], worktree)[1],
        }
    )
    record_path = _gate_record_path(args.state, worktree)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _emit(
        payload,
        as_json=args.json,
        human=f"{'✓' if verdict == 'pass' else '✗'} gate {verdict}: {worktree}",
    )
    return EXIT_OK if verdict == "pass" else EXIT_BLOCK


def _handoff_payload(
    *,
    status: str,
    worktree: Path,
    reason: str | None = None,
    observed_main_sha: str | None = None,
) -> dict[str, Any]:
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
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    if not worktree.is_dir():
        payload = _handoff_payload(
            status="blocked", worktree=worktree, reason="worktree not found"
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    branch_rc, branch = _git(["branch", "--show-current"], worktree)
    state = registry.load_state(state_path)
    matches = [
        record
        for record in registry._active_records(state)
        if branch_rc == 0
        and branch
        and registry._record_matches(record, branch=branch, path=str(worktree))
    ]
    if len(matches) != 1:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            reason="handoff selector must match exactly one active worktree",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    record = matches[0]
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            reason="typed kg.worktree.handback.v1 seal is missing",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    observed_main_sha = _resolve_commit(worktree, args.incoming_main)
    if observed_main_sha is None:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            reason=f"incoming main cannot be resolved: {args.incoming_main}",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    base_sha = str(
        seal.get("base_sha") or record.get("base_sha") or record.get("base") or ""
    )
    if not base_sha:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="hand-back base is missing",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    if (
        _git(["merge-base", "--is-ancestor", base_sha, observed_main_sha], worktree)[0]
        != 0
    ):
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason=f"hand-back base {base_sha} is not an ancestor of incoming main {observed_main_sha}",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    if not registry._has_valid_handback(record):
        problems = registry.validate_handback_seal(record, repo=worktree)
        reason = "local hand-back is not valid"
        if problems:
            reason = f"local hand-back is not valid: {', '.join(item['kind'] for item in problems)}"
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason=reason,
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    tip_sha = str(seal.get("tip_sha") or record.get("handed_back_sha") or "")
    scope = record.get("scope")
    if scope_status(scope) != "known":
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="declared Scope is unstructured or invalid",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    scope_paths = sorted({item["path"] for item in scope_files(scope)})
    gate_path = _gate_record_path(str(state_path), worktree)
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        gate = None
    if not isinstance(gate, dict) or gate.get("verdict") != "pass":
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="no passing local gate is recorded for this worktree",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    if (
        gate.get("schema") != GATE_SCHEMA
        or _path(str(gate.get("worktree") or "")) != worktree
    ):
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="local gate provenance does not match this worktree",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    gate_base = _resolve_commit(worktree, str(gate.get("base") or "")) or str(
        gate.get("base") or ""
    )
    if gate_base != base_sha:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="local gate base does not equal hand-back base",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    if gate.get("head") != tip_sha:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="local gate HEAD does not equal hand-back tip",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK
    if sorted(gate.get("files") or []) != scope_paths:
        payload = _handoff_payload(
            status="blocked",
            worktree=worktree,
            observed_main_sha=observed_main_sha,
            reason="local gate changed files do not equal declared Scope",
        )
        _emit(
            payload, as_json=args.json, human=f"✗ handoff blocked: {payload['reason']}"
        )
        return EXIT_BLOCK

    payload = _handoff_payload(
        status="ready-for-im",
        worktree=worktree,
        observed_main_sha=observed_main_sha,
    )
    payload.update(
        {
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
        }
    )
    _emit(
        payload,
        as_json=args.json,
        human=f"✓ handoff ready-for-im: {branch} @ {tip_sha[:12]}",
    )
    return EXIT_OK


def cmd_preflight(args: argparse.Namespace) -> int:
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    state = registry.load_state(state_path)
    rebase_args = (args.worktree, args.base, args.incoming_main)
    if any(item is not None for item in rebase_args):
        missing = [
            name
            for name, value in (
                ("--worktree", args.worktree),
                ("--base", args.base),
                ("--incoming-main", args.incoming_main),
            )
            if value is None
        ]
        if missing:
            reason = f"rebase preflight requires {' '.join(missing)}"
            _emit(
                {
                    "schema": SCHEMA,
                    "action": "rebase-preflight",
                    "verdict": "block",
                    "reason": reason,
                },
                as_json=args.json,
                human=f"✗ rebase preflight blocked: {reason}",
            )
            return EXIT_USAGE
        worktree = _path(args.worktree)
        if not worktree.is_dir():
            reason = f"worktree not found: {worktree}"
            _emit(
                {
                    "schema": SCHEMA,
                    "action": "rebase-preflight",
                    "verdict": "block",
                    "reason": reason,
                },
                as_json=args.json,
                human=f"✗ rebase preflight blocked: {reason}",
            )
            return EXIT_USAGE
        branch_rc, branch = _git(["branch", "--show-current"], worktree)
        matches = [
            record
            for record in registry._active_records(state)
            if branch_rc == 0
            and branch
            and registry._record_matches(record, branch=branch, path=str(worktree))
        ]
        if len(matches) != 1:
            reason = "preflight selector must match exactly one active worktree"
            _emit(
                {
                    "schema": SCHEMA,
                    "action": "rebase-preflight",
                    "verdict": "block",
                    "reason": reason,
                    "worktree": str(worktree),
                },
                as_json=args.json,
                human=f"✗ rebase preflight blocked: {reason}",
            )
            return EXIT_BLOCK
        payload = _rebase_preflight(
            worktree,
            base=args.base,
            incoming_main=args.incoming_main,
            scope=matches[0].get("scope"),
        )
        payload.update({"registry": str(state_path), "branch": branch})
        _emit(
            payload,
            as_json=args.json,
            human=(
                f"✓ rebase preflight pass: {worktree}"
                if payload["verdict"] == "pass"
                else f"✗ rebase preflight blocked: {payload.get('reason', 'unknown reason')}"
            ),
        )
        return EXIT_OK if payload["verdict"] == "pass" else EXIT_BLOCK
    active = [
        record
        for record in state.get("records", [])
        if record.get("status") == "active"
    ]
    payload = {
        "schema": SCHEMA,
        "action": "preflight",
        "registry": str(state_path),
        "active_worktrees": len(active),
        "worktrees": _git(["worktree", "list"], ROOT)[1],
    }
    _emit(
        payload,
        as_json=args.json,
        human=f"✓ preflight: {len(active)} active local worktree(s)",
    )
    return EXIT_OK


def cmd_freeze(args: argparse.Namespace) -> int:
    current = _is_frozen()
    if args.action == "status":
        _emit(
            {
                "schema": "kg.worktree.freeze.v1",
                "frozen": current is not None,
                "state": current,
            },
            as_json=args.json,
            human=(f"frozen: {current.get('reason')}" if current else "not frozen"),
        )
        return EXIT_OK
    if args.action == "on":
        if current and not args.force:
            return EXIT_BLOCK
        if not args.reason:
            return EXIT_USAGE
        _, now = registry.resolve_now()
        payload = {
            "schema": "kg.worktree.freeze.v1",
            "reason": args.reason,
            "created_at": now,
        }
        _write_freeze(payload)
        _emit(
            {"schema": "kg.worktree.freeze.v1", "action": "on", "state": payload},
            as_json=args.json,
            human=f"✓ frozen: {args.reason}",
        )
        return EXIT_OK
    _write_freeze(None)
    _emit(
        {"schema": "kg.worktree.freeze.v1", "action": "off"},
        as_json=args.json,
        human="✓ unfrozen",
    )
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    branch = None
    worktree = None
    if args.remove:
        branch, worktree, refusal = worktree_cleanup.resolve_remove_target(
            args,
            root=ROOT,
            path_resolver=_path,
            git=_git,
        )
        if refusal:
            print(f"✗ resolve --remove blocked: {refusal}", file=sys.stderr)
            return EXIT_BLOCK
        refusal = worktree_cleanup.preflight_resolve_remove(
            branch=branch,
            worktree=worktree,
            expected_head_sha=args.expected_head_sha,
            root=ROOT,
            git=_git,
        )
        if refusal:
            print(f"✗ resolve --remove blocked: {refusal}", file=sys.stderr)
            return EXIT_BLOCK
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
    rc = registry.main(argv, acquire_lock=False)
    if rc != EXIT_OK or not args.remove:
        return rc
    return worktree_cleanup.cleanup_resolved_local_assets(
        branch=branch,
        worktree=worktree,
        expected_head_sha=args.expected_head_sha,
        root=ROOT,
        git=_git,
        exit_block=EXIT_BLOCK,
        exit_ok=EXIT_OK,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub-native local worktree coordinator"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--state", default=None)
        p.add_argument("--json", action="store_true")

    pre = sub.add_parser("preflight", help="show local worktree/registry health")
    common(pre)
    pre.add_argument("--worktree")
    pre.add_argument("--base")
    pre.add_argument("--incoming-main")
    pre.set_defaults(func=cmd_preflight)

    op = sub.add_parser(
        "open",
        help="create a branch and linked worktree",
        epilog=(
            "Owner-bound contract: when delegated mode is enabled with "
            "--delegated or --codex-thread-id is supplied, provide at least "
            "one --external-id with a non-blank value. This validation runs "
            "before base resolution, registry, branch, or worktree mutation; "
            "legacy non-owner open semantics are unchanged."
        ),
    )
    common(op)
    op.add_argument("--intent", required=True)
    op.add_argument("--slug", required=True)
    op.add_argument("--type", choices=BRANCH_TYPES)
    op.add_argument("--base", default=BASE_DEFAULT)
    op.add_argument("--path", default=None)
    op.add_argument(
        "--external-id",
        action="append",
        default=[],
        help=(
            "durable lane identity; required and non-blank for delegated "
            "or owner-bound open"
        ),
    )
    op.add_argument("--scope")
    op.add_argument("--scope-file")
    op.add_argument("--codex-thread-id")
    op.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    op.set_defaults(func=cmd_open)

    ad = sub.add_parser("adopt", help="register an existing linked worktree")
    common(ad)
    ad.add_argument("--worktree", default=None)
    ad.add_argument("--intent", required=True)
    ad.add_argument("--base", default=BASE_DEFAULT)
    ad.add_argument("--external-id", action="append", default=[])
    ad.add_argument("--scope")
    ad.add_argument("--scope-file")
    ad.add_argument("--codex-thread-id")
    ad.add_argument("--delegated", action=argparse.BooleanOptionalAction, default=None)
    ad.set_defaults(func=cmd_adopt)

    worktree_reanchor.add_parser(
        sub, common=common, handler=cmd_reanchor, default_repo=ROOT
    )
    reanchor_handback = sub.add_parser(
        "reanchor-handback",
        help="reanchor one owner-local typed handback before PR publication",
        epilog=(
            "This owner-local recovery requires an active exact claim, a clean "
            "physical worktree, no remote branch, and no branch PR. It only "
            "reanchors to the supplied live main; it does not run tests, push, "
            "create a PR, or authorize a merge."
        ),
    )
    common(reanchor_handback)
    reanchor_handback.add_argument("--repo", default=str(ROOT))
    reanchor_handback.add_argument("--lane", required=True)
    reanchor_handback.add_argument("--branch", required=True)
    reanchor_handback.add_argument("--owner-thread-id", required=True)
    reanchor_handback.add_argument("--claim-generation", type=int, required=True)
    reanchor_handback.add_argument("--expected-head-sha", required=True)
    reanchor_handback.add_argument("--live-main", required=True)
    reanchor_handback.add_argument("--path", required=True)
    reanchor_handback.set_defaults(func=cmd_reanchor_handback)
    worktree_resume.add_parser(
        sub, common=common, handler=cmd_resume_published, default_repo=ROOT
    )
    worktree_published_remote_recovery.add_parser(
        sub, common=common, handler=cmd_recover_published_remote, default_repo=ROOT
    )

    gate = sub.add_parser("gate", help="run focused local checks for changed files")
    common(gate)
    gate.add_argument("--worktree", required=True)
    gate.add_argument("--base", default=BASE_DEFAULT)
    gate.add_argument("--plan-only", action="store_true")
    gate.set_defaults(func=cmd_gate)

    handoff = sub.add_parser("handoff", help="package a valid local hand-back for IM")
    common(handoff)
    handoff.add_argument("--worktree", required=True)
    handoff.add_argument("--incoming-main", required=True)
    handoff.set_defaults(func=cmd_handoff)

    hand = sub.add_parser("hand-back", help="record exact HEAD evidence")
    common(hand)
    hand.add_argument("--branch")
    hand.add_argument("--path")
    hand.add_argument("--outcomes")
    hand.set_defaults(
        func=lambda args: registry.main(
            [
                "hand-back",
                *(["--branch", args.branch] if args.branch else []),
                *(["--path", args.path] if args.path else []),
                *(["--state", args.state] if args.state else []),
                *(["--outcomes", args.outcomes] if args.outcomes else []),
                *(["--json"] if args.json else []),
            ],
            acquire_lock=False,
        )
    )

    resolved = sub.add_parser(
        "resolve", help="transition an exact local ownership claim"
    )
    common(resolved)
    resolved.add_argument("--branch")
    resolved.add_argument("--path")
    resolved.add_argument(
        "--status", choices=registry.PUBLIC_RESOLVE_STATUSES, required=True
    )
    resolved.add_argument("--expected-generation", type=int)
    resolved.add_argument("--expected-head-sha")
    resolved.add_argument("--remove", action="store_true")
    resolved.set_defaults(func=cmd_resolve)

    freeze = sub.add_parser("freeze", help="pause local worktree birth/adoption")
    common(freeze)
    freeze.add_argument("action", choices=("on", "off", "status"))
    freeze.add_argument("--reason")
    freeze.add_argument("--force", action="store_true")
    freeze.set_defaults(func=cmd_freeze)

    listed = sub.add_parser("list", help="show local ownership records")
    common(listed)
    listed.add_argument("--active-only", action="store_true")
    listed.add_argument("--branch")
    listed.add_argument("--path")
    listed.add_argument("--external-id")
    listed.add_argument("--conflicts", action="store_true")
    listed.set_defaults(
        func=lambda args: registry.main(
            [
                "list",
                *(["--state", args.state] if args.state else []),
                *(["--active-only"] if args.active_only else []),
                *(["--branch", args.branch] if args.branch else []),
                *(["--path", args.path] if args.path else []),
                *(["--external-id", args.external_id] if args.external_id else []),
                *(["--conflicts"] if args.conflicts else []),
                *(["--json"] if args.json else []),
            ]
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    needs_lock = args.command in MUTATING_COMMANDS and not (
        args.command == "freeze" and args.action == "status"
    )
    if not needs_lock:
        return int(args.func(args))
    anchor = registry.common_anchor(ROOT)
    with OperationLock(anchor, command=f"worktree:{args.command}"):
        return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

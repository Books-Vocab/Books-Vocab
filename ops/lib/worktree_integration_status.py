"""Pure, read-only projection of an in-flight worktree integration.

This module deliberately has no registry lock and no write path.  It reads the
atomic integration state, the registry snapshot, git facts, and the existing gate
record, then returns one stable JSON-shaped status object.  The orchestrator owns
the CLI and exit-code mapping; keeping the projector independent makes its
no-mutation contract straightforward to test.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 64
SCHEMA = "kg.worktree.integrate.status.v1"
INTEGRATE_SCHEMA = "kg.worktree.integrate.v1"


def _norm(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def integration_state_path(state_path: str | Path, slug: str) -> Path:
    """Return the state location without creating its parent directory."""
    return Path(state_path).expanduser().resolve().parent / "worktree_integrations" / f"{slug}.json"


def gate_record_path(state_path: str | Path, worktree: str) -> Path:
    base = Path(state_path).expanduser().resolve().parent
    key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
    return base / "worktree_gates" / f"{key}.json"


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, str(exc)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, f"expected JSON object, got {type(value).__name__}"
    return value, None


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True,
            check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _sha(repo: Path, ref: str) -> str | None:
    rc, out, _ = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return out if rc == 0 and out else None


def _current_branch(repo: Path) -> str | None:
    rc, out, _ = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    return out if rc == 0 and out else None


def _conflicts(repo: Path) -> list[str]:
    rc, out, _ = _git(repo, "diff", "--name-only", "--diff-filter=U")
    return out.splitlines() if rc == 0 and out else []


def _problem(kind: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, "message": message, **fields}


def _source_refs(state: dict[str, Any]) -> dict[str, str]:
    handoff = state.get("handoff")
    if isinstance(handoff, dict):
        refs = handoff.get("source_refs")
        if isinstance(refs, dict):
            return {str(branch): str(sha) for branch, sha in refs.items()}
    refs = state.get("source_refs")
    if isinstance(refs, dict):
        return {str(branch): str(sha) for branch, sha in refs.items()}
    return {}


def _owner_map(registry: dict[str, Any], state: dict[str, Any], branches: list[str]) -> dict[str, Any]:
    records = registry.get("records") if isinstance(registry, dict) else []
    if not isinstance(records, list):
        return {branch: None for branch in branches}
    expected_branch = state.get("branch")
    refs = _source_refs(state)
    result: dict[str, Any] = {}
    for branch in branches:
        owner: dict[str, Any] | None = None
        for record in records:
            if not isinstance(record, dict) or record.get("status") != "active":
                continue
            claim = record.get("integration_owner")
            if not isinstance(claim, dict):
                continue
            if claim.get("branch") != expected_branch:
                continue
            if branch in refs:
                owner = {
                    "branch": claim.get("branch"),
                    "slug": claim.get("slug"),
                    "path": _norm(record.get("path")) if record.get("path") else None,
                }
                break
        result[branch] = owner
    return result


def _gate_view(state_path: Path, state: dict[str, Any], current_head: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record_name = None
    gate = state.get("gate")
    if isinstance(gate, dict) and gate.get("record"):
        record_name = str(gate["record"])
    path = Path(record_name).expanduser() if record_name else gate_record_path(
        state_path, str(state.get("worktree") or ""),
    )
    payload, error = _read_json(path) if path.exists() else (None, None)
    if error:
        return {
            "path": str(path), "present": True, "fresh": False,
            "verdict": None, "head_sha": None,
        }, [_problem("gate-unreadable", f"gate record is unreadable: {path}", detail=error)]
    if payload is None:
        return {
            "path": str(path), "present": False, "fresh": False,
            "verdict": None, "head_sha": None,
        }, []
    gate_head = payload.get("head_sha")
    fresh = bool(current_head and gate_head == current_head)
    problems: list[dict[str, Any]] = []
    if not fresh:
        problems.append(_problem(
            "gate-stale", "gate record does not match the current integration HEAD",
            gate_head=gate_head, current_head=current_head,
        ))
    return {
        "path": str(path), "present": True, "fresh": fresh,
        "verdict": payload.get("verdict"), "head_sha": gate_head,
        "record": payload,
    }, problems


def project_status(
    *,
    slug: str,
    state_path: str | Path,
    repo: str | Path,
    registry_path: str | Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Project one integration without acquiring locks or writing any file."""
    if not slug or any(char in slug for char in "/\\"):
        return EXIT_USAGE, {
            "schema": SCHEMA, "slug": slug,
            "problems": [_problem("invalid-slug", "slug must be a non-empty name")],
            "next_action": "start",
        }
    state_file = integration_state_path(state_path, slug)
    base_payload: dict[str, Any] = {
        "schema": SCHEMA, "slug": slug, "state_file": str(state_file),
        "phase": "unknown", "picked": [], "skipped": [], "remaining": [],
        "conflicts": [], "source_tips": {}, "reservation_owner": {},
        "problems": [], "next_action": "start",
    }
    if not state_file.exists():
        base_payload["problems"] = [_problem(
            "state-missing", f"no in-flight integration state exists for {slug!r}",
        )]
        return EXIT_USAGE, base_payload
    state, error = _read_json(state_file)
    if error or state is None:
        base_payload["problems"] = [_problem(
            "state-unreadable", f"integration state is unreadable: {state_file}",
            detail=error,
        )]
        base_payload["next_action"] = "inspect-and-repair"
        return EXIT_USAGE, base_payload
    if state.get("schema") != INTEGRATE_SCHEMA:
        base_payload["problems"] = [_problem(
            "state-schema", f"unexpected integration state schema: {state.get('schema')!r}",
        )]
        base_payload["next_action"] = "inspect-and-repair"
        return EXIT_USAGE, base_payload

    repo_path = Path(repo).expanduser().resolve()
    persisted_worktree = state.get("worktree")
    if not isinstance(persisted_worktree, str) or not persisted_worktree:
        problems: list[dict[str, Any]] = [_problem(
            "worktree-drift", "integration state has no worktree identity",
        )]
    elif not Path(persisted_worktree).expanduser().is_dir():
        problems = [_problem(
            "worktree-drift", "persisted integration worktree is missing",
            expected=_norm(persisted_worktree),
        )]
    else:
        problems = []
    current_head = _sha(repo_path, "HEAD")
    branch_now = _current_branch(repo_path)
    expected_branch = state.get("branch")
    trunk = str(state.get("trunk") or state.get("base") or "main")
    expected_base = _sha(repo_path, trunk)
    expected_head = state.get("head_sha")
    if not expected_head:
        picked = state.get("picked") or []
        if isinstance(picked, list) and picked:
            last = picked[-1]
            if isinstance(last, dict):
                expected_head = last.get("new_sha") or last.get("sha")
    if not expected_head:
        expected_head = expected_base
    branches = [str(item) for item in (state.get("branches") or [])]
    refs = _source_refs(state)
    registry_file = Path(registry_path or state_path).expanduser().resolve()
    registry, registry_error = _read_json(registry_file)
    if registry_error or registry is None:
        problems.append(_problem("registry-unreadable", f"registry is unreadable: {registry_file}", detail=registry_error))
        registry = {}
    if branch_now != expected_branch:
        problems.append(_problem(
            "branch-drift", "integration worktree branch differs from persisted state",
            expected=expected_branch, current=branch_now,
        ))
    if current_head is None:
        problems.append(_problem("head-unreadable", "integration worktree HEAD is unreadable"))
    elif expected_head and current_head != expected_head:
        problems.append(_problem(
            "head-drift", "integration worktree HEAD differs from persisted state",
            expected=expected_head, current=current_head,
        ))
    if expected_base is None:
        problems.append(_problem("base-unreadable", f"integration base is unreadable: {trunk}"))

    source_tips: dict[str, Any] = {}
    for source_branch in branches:
        expected_tip = refs.get(source_branch)
        current_tip = _sha(repo_path, source_branch)
        source_tips[source_branch] = {
            "expected": expected_tip, "current": current_tip,
            "ok": bool(expected_tip and current_tip == expected_tip),
        }
        if expected_tip is None:
            problems.append(_problem("source-tip-missing", f"no handed-back tip for {source_branch!r}", branch=source_branch))
        elif current_tip != expected_tip:
            problems.append(_problem(
                "source-drift", f"source tip drifted for {source_branch!r}",
                branch=source_branch, expected=expected_tip, current=current_tip,
            ))

    owner_map = _owner_map(registry, state, branches)
    claim = state.get("source_claim")
    if isinstance(claim, dict) and claim.get("ok") is False:
        problems.append(_problem("owner-drift", "persisted source reservation is not healthy", detail=claim.get("problems")))
    elif branches and isinstance(claim, dict) and claim.get("ok") is True:
        missing = [branch for branch, owner in owner_map.items() if owner is None]
        if missing:
            problems.append(_problem("owner-drift", "source reservation owner is missing", branches=missing))

    conflicts = _conflicts(repo_path)
    if conflicts:
        problems.append(_problem("unmerged", "integration worktree has unresolved paths", paths=conflicts))
    gate_view, gate_problems = _gate_view(state_path=Path(state_path).resolve(), state=state, current_head=current_head)
    problems.extend(gate_problems)

    queue = state.get("queue") if isinstance(state.get("queue"), list) else []
    picked = state.get("picked") if isinstance(state.get("picked"), list) else []
    skipped = state.get("skipped") if isinstance(state.get("skipped"), list) else []
    gate_pending = bool(state.get("gate_pending")) or (not queue and isinstance(state.get("gate"), dict))
    if conflicts or state.get("stopped"):
        phase = "conflicted"
    elif gate_pending and not queue:
        phase = "gate-blocked" if gate_view.get("verdict") == "block" else "gate-pending"
    else:
        phase = "picking"
    drift_kinds = {
        "state-schema", "registry-unreadable", "branch-drift", "head-drift",
        "head-unreadable", "base-unreadable", "source-tip-missing", "source-drift",
        "owner-drift", "worktree-drift", "gate-unreadable", "gate-stale",
    }
    if any(item.get("kind") in drift_kinds for item in problems):
        next_action = "inspect-and-repair"
    elif conflicts or state.get("stopped"):
        next_action = "resolve-and-continue"
    elif queue:
        next_action = "continue"
    elif gate_pending:
        next_action = "continue-to-gate"
    else:
        next_action = "start"

    payload = {
        **base_payload,
        "phase": phase, "state_file": str(state_file),
        "worktree": state.get("worktree"), "branch": expected_branch,
        "base": state.get("base"), "trunk": trunk,
        "expected_head": expected_head, "current_head": current_head,
        "source_tips": source_tips, "reservation_owner": owner_map,
        "picked": picked, "skipped": skipped, "remaining": queue,
        "conflicts": conflicts, "gate_pending": gate_pending,
        "gate_fresh": gate_view.get("fresh"),
        "gate_verdict": gate_view.get("verdict"),
        "gate_head": gate_view.get("head_sha"),
        "gate": gate_view, "problems": problems, "next_action": next_action,
    }
    return (EXIT_DRIFT if problems else EXIT_OK), payload


inspect = project_status

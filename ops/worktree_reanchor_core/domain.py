"""Pure request, Scope, and output contracts for merge-front reanchor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.worktree_scope import scope_files, scope_status

from .errors import ReanchorRefused

SCHEMA = "kg.worktree.reanchor.v1"
EXIT_OK = 0
EXIT_BLOCK = 1
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DeclaredOperations = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ReanchorRequest:
    repo: Path
    state_path: Path
    merge_front_pr: int
    lane_id: str
    branch: str
    owner_thread_id: str
    claim_generation: int
    expected_remote_head: str
    live_main: str
    target: Path
    preserve_conflict: bool = False
    allow_required_failure_recovery: bool = False


@dataclass(frozen=True)
class RegistryPreflight:
    original: dict[str, Any]
    fingerprint: str
    base_sha: str
    published_base_sha: str
    declared: DeclaredOperations


def commit_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or COMMIT_SHA_RE.fullmatch(value) is None:
        raise ReanchorRefused(f"{label} must be a full lowercase commit SHA")
    return value


def declared_operations(scope: object) -> DeclaredOperations:
    if scope_status(scope) != "known":
        raise ReanchorRefused("original claim Scope is unstructured or invalid")
    return tuple(
        sorted((item["path"], item["operation"]) for item in scope_files(scope))
    )


def success_payload(
    request: ReanchorRequest,
    *,
    active: dict[str, Any],
    head: str,
    declared: DeclaredOperations,
    merge_front_policy: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "action": "reanchor",
        "status": "ready-for-owner-tests",
        "merge_front_pr": request.merge_front_pr,
        "merge_front_policy": merge_front_policy,
        "recovery_mode": (
            "required-failure"
            if request.allow_required_failure_recovery
            else "merge-front"
        ),
        "lane": request.lane_id,
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "original_claim_generation": request.claim_generation,
        "claim_generation": active["claim_generation"],
        "previous_head": request.expected_remote_head,
        "head": head,
        "base_sha": request.live_main,
        "worktree": str(request.target),
        "scope": [item[0] for item in declared],
        "record": active,
        "next_action": (
            "original owner runs tests and emits a fresh typed hand-back; "
            f"PI updates the same PR #{request.merge_front_pr}"
        ),
        "not_performed": ["tests", "hand-back", "push", "force-push"],
    }


def conflict_payload(
    request: ReanchorRequest,
    *,
    active: dict[str, Any],
    declared: DeclaredOperations,
    merge_front_policy: str | None,
    git_output: str,
) -> dict[str, Any]:
    """Keep one owner-visible rebase conflict as a registered active blocker."""

    return {
        "schema": SCHEMA,
        "action": "reanchor",
        "status": "owner-action-required",
        "merge_front_pr": request.merge_front_pr,
        "merge_front_policy": merge_front_policy,
        "recovery_mode": (
            "required-failure"
            if request.allow_required_failure_recovery
            else "merge-front"
        ),
        "lane": request.lane_id,
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "original_claim_generation": request.claim_generation,
        "claim_generation": active["claim_generation"],
        "previous_head": request.expected_remote_head,
        "base_sha": request.live_main,
        "worktree": str(request.target),
        "scope": [item[0] for item in declared],
        "record": active,
        "reason": "rebase conflict preserved for the original owner",
        "git": git_output,
        "next_action": (
            "original owner resolves the rebase conflict, completes the rebase, "
            "runs bounded tests, and emits a fresh typed hand-back"
        ),
        "not_performed": ["tests", "hand-back", "push", "force-push"],
    }

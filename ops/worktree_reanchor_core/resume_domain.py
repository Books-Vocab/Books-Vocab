"""Pure contracts for same-owner recovery of one published claim."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from delivery_control.domain.errors import DeliverySourceError
from delivery_control.domain.observations import PullRequestSnapshot
from delivery_control.services.pr_contract import parse_pull_request_body

from .domain import commit_sha
from .errors import ReanchorRefused

SCHEMA = "kg.worktree.resume-published.v1"
EXIT_OK = 0
EXIT_BLOCK = 1
ResumeMode = Literal["required-failure", "maintenance"]


@dataclass(frozen=True)
class ResumeRequest:
    repo: Path
    state_path: Path
    lane_id: str
    branch: str
    owner_thread_id: str
    claim_generation: int
    previous_handback: str | None
    expected_remote_head: str
    target: Path
    mode: ResumeMode


@dataclass(frozen=True)
class MergedMaintenanceProof:
    """Immutable proof for post-merge reconciliation without a worktree."""

    pr_number: int
    lane_id: str
    branch: str
    owner_thread_id: str
    claim_generation: int
    base_sha: str
    published_base_sha: str
    head_sha: str
    parent_sha: str
    merged_at: datetime
    action: str = "reconcile-merged-maintenance"
    verdict: str = "terminal-reconciliation-ready"


def verify_merged_maintenance_lifecycle(
    pull_request: PullRequestSnapshot,
    *,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_remote_head: str,
    previous_handback: str | None,
    recorded_base_sha: str,
    published_base_sha: str,
    source_parent_sha: str,
    declared_scope: tuple[tuple[str, str], ...],
    handback_digest: str | None,
) -> MergedMaintenanceProof:
    """Require one exact merged PR and its immutable handback/source proof."""

    if pull_request.state != "MERGED":
        raise ReanchorRefused(
            "merged maintenance requires the unique PR to be MERGED",
            pull_request=pull_request.number,
            state=pull_request.state,
        )
    if pull_request.base_branch != "main":
        raise ReanchorRefused("merged maintenance requires PR target main")
    if pull_request.merged_at is None:
        raise ReanchorRefused("merged maintenance requires merged-at evidence")
    if previous_handback is None or previous_handback != expected_remote_head:
        raise ReanchorRefused(
            "merged maintenance requires exact previous hand-back equal to remote HEAD"
        )
    if pull_request.base_sha != published_base_sha:
        raise ReanchorRefused(
            "merged PR base differs from the exact published source base",
            expected_base_sha=published_base_sha,
            actual_base_sha=pull_request.base_sha,
        )
    if pull_request.head_sha != expected_remote_head:
        raise ReanchorRefused(
            "merged PR HEAD differs from the exact previous hand-back",
            expected_head_sha=expected_remote_head,
            actual_head_sha=pull_request.head_sha,
        )

    try:
        receipt = parse_pull_request_body(pull_request.body)
    except DeliverySourceError as exc:
        raise ReanchorRefused(
            f"merged maintenance requires an exact typed delivery receipt: {exc}"
        ) from exc
    expected_scope = tuple(sorted(declared_scope))
    actual_scope = tuple(
        sorted((item.path, item.operation.value) for item in receipt.scope.files)
    )
    comparisons = (
        (receipt.lane_id, lane_id, "lane"),
        (receipt.branch, branch, "branch"),
        (receipt.owner_thread_id, owner_thread_id, "owner"),
        (receipt.claim_generation, claim_generation, "claim generation"),
        (receipt.base_sha, recorded_base_sha, "hand-back base"),
        (receipt.head_sha, expected_remote_head, "hand-back HEAD"),
        (receipt.parent_sha, source_parent_sha, "source parent"),
        (actual_scope, expected_scope, "Scope"),
    )
    for actual, expected, label in comparisons:
        if actual != expected:
            raise ReanchorRefused(
                f"merged maintenance {label} evidence differs from the exact claim",
                expected=expected,
                actual=actual,
            )
    if handback_digest is not None and receipt.content_digest != handback_digest:
        raise ReanchorRefused(
            "merged maintenance hand-back digest differs from the exact registry seal",
            expected_digest=handback_digest,
            actual_digest=receipt.content_digest,
        )
    return MergedMaintenanceProof(
        pr_number=pull_request.number,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        base_sha=recorded_base_sha,
        published_base_sha=published_base_sha,
        head_sha=expected_remote_head,
        parent_sha=source_parent_sha,
        merged_at=pull_request.merged_at,
    )


def build_request(
    *,
    repo: Path,
    state_path: Path,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_remote_head: str,
    target: Path,
    previous_handback: str | None = None,
    mode: str = "required-failure",
) -> ResumeRequest:
    if not lane_id.strip() or not branch.strip() or not owner_thread_id.strip():
        raise ReanchorRefused(
            "lane, branch, and owner must identify one published claim"
        )
    if claim_generation < 0:
        raise ReanchorRefused("claim generation must be non-negative")
    if mode not in {"required-failure", "maintenance"}:
        raise ReanchorRefused("resume mode must be 'required-failure' or 'maintenance'")
    current_head = commit_sha(expected_remote_head, label="expected remote HEAD")
    previous_head = (
        commit_sha(previous_handback, label="previous hand-back")
        if previous_handback is not None
        else None
    )
    if previous_head == current_head and mode != "maintenance":
        raise ReanchorRefused(
            "advanced published resume requires a different current remote HEAD"
        )
    return ResumeRequest(
        repo=repo,
        state_path=state_path,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        previous_handback=previous_head,
        expected_remote_head=current_head,
        target=target,
        mode=cast(ResumeMode, mode),
    )


def success_payload(
    request: ResumeRequest,
    *,
    active: dict[str, Any],
    recorded_base: str,
    base_sha: str,
    pull_request_number: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "action": "resume-published",
        "status": "ready-for-owner-fix",
        "pull_request": pull_request_number,
        "lane": request.lane_id,
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "original_claim_generation": request.claim_generation,
        "mode": request.mode,
        "claim_generation": active["claim_generation"],
        "head": request.expected_remote_head,
        "base": recorded_base,
        "base_sha": base_sha,
        "worktree": str(request.target),
        "record": active,
        "next_action": (
            "same owner may perform bounded maintenance, runs tests, and emits "
            "a fresh typed hand-back; PI updates the same published PR"
            if request.mode == "maintenance"
            else "same owner fixes the required code failure, runs tests, and emits "
            "a fresh typed hand-back; PI updates the same published PR"
        ),
        "not_performed": ["tests", "hand-back", "push", "force-push"],
    }


def merged_maintenance_payload(
    request: ResumeRequest,
    *,
    original: dict[str, Any],
    proof: MergedMaintenanceProof,
    recorded_base: str,
) -> dict[str, Any]:
    """Return terminal evidence without creating an active claim or worktree."""

    return {
        "schema": "kg.worktree.resume-merged-maintenance.v1",
        "action": proof.action,
        "status": "reconciliation-ready",
        "verdict": proof.verdict,
        "pull_request": proof.pr_number,
        "lane": request.lane_id,
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "claim_generation": request.claim_generation,
        "source": {
            "head_sha": proof.head_sha,
            "parent_sha": proof.parent_sha,
            "base_sha": proof.published_base_sha,
            "base_branch": "main",
            "pr_state": "MERGED",
            "merged_at": proof.merged_at.isoformat(),
        },
        "handback": {
            "head_sha": proof.head_sha,
            "base_sha": proof.base_sha,
            "previous_handback": request.previous_handback,
        },
        "recorded_base": recorded_base,
        "record": original,
        "worktree": None,
        "dispatchable": False,
        "publishable": False,
        "ownership_transition": "none",
        "next_action": (
            "upper layer re-reads live main and exact merged PR/registry evidence, "
            "then performs supported terminal reconciliation/cleanup"
        ),
        "not_performed": [
            "worktree-provision",
            "registry-ownership-transition",
            "tests",
            "hand-back",
            "push",
            "force-push",
        ],
    }

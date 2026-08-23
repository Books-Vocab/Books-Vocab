"""Pure contracts for same-owner recovery of one published claim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

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
    if previous_head == current_head:
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

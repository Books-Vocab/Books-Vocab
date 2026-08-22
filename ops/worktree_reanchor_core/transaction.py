"""Transaction orchestration for one machine-verified merge-front PR."""

from __future__ import annotations

from pathlib import Path

from . import compensation, git_ops, lifecycle_proof, registry_ops
from .domain import ReanchorRequest, commit_sha, success_payload
from .errors import ReanchorRefused


def _request(
    *, repo: Path, state_path: Path, merge_front_pr: int, lane_id: str,
    branch: str, owner_thread_id: str, claim_generation: int,
    expected_remote_head: str, live_main: str, target: Path,
) -> ReanchorRequest:
    if merge_front_pr <= 0:
        raise ReanchorRefused("one positive merge-front PR candidate is required")
    return ReanchorRequest(
        repo=repo,
        state_path=state_path,
        merge_front_pr=merge_front_pr,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_remote_head=commit_sha(
            expected_remote_head, label="expected remote HEAD"
        ),
        live_main=commit_sha(live_main, label="live main"),
        target=target,
    )


def perform_reanchor(
    *, repo: Path, state_path: Path, merge_front_pr: int, lane_id: str,
    branch: str, owner_thread_id: str, claim_generation: int,
    expected_remote_head: str, live_main: str, target: Path,
) -> dict[str, object]:
    request = _request(
        repo=repo, state_path=state_path, merge_front_pr=merge_front_pr,
        lane_id=lane_id, branch=branch, owner_thread_id=owner_thread_id,
        claim_generation=claim_generation, expected_remote_head=expected_remote_head,
        live_main=live_main, target=target,
    )
    git_ops.validate_repository(request.repo)
    preflight = registry_ops.preflight(
        state_path=request.state_path,
        lane_id=request.lane_id,
        branch=request.branch,
        owner_thread_id=request.owner_thread_id,
        claim_generation=request.claim_generation,
        expected_remote_head=request.expected_remote_head,
        live_main=request.live_main,
        target=request.target,
    )
    github = lifecycle_proof.build_github(request.repo, operation="reanchor")
    initial_lifecycle = lifecycle_proof.verify_reanchor_lifecycle(
        github,
        pull_request_number=request.merge_front_pr,
        branch=request.branch,
        expected_base_sha=preflight.base_sha,
        expected_remote_head=request.expected_remote_head,
        live_main_sha=request.live_main,
    )
    git_ops.validate_new_target(
        request.repo, target=request.target, branch=request.branch
    )
    git_ops.verify_remote_cas(
        request.repo,
        branch=request.branch,
        expected_remote_head=request.expected_remote_head,
        expected_live_main=request.live_main,
    )
    git_ops.ensure_commits_and_scope(
        request.repo,
        branch=request.branch,
        base_sha=preflight.base_sha,
        remote_head=request.expected_remote_head,
        live_main=request.live_main,
        declared=preflight.declared,
    )
    try:
        head = git_ops.recreate_and_rebase(
            request.repo,
            target=request.target,
            branch=request.branch,
            base_sha=preflight.base_sha,
            remote_head=request.expected_remote_head,
            live_main=request.live_main,
            declared=preflight.declared,
        )
        final_lifecycle = lifecycle_proof.verify_reanchor_lifecycle(
            github,
            pull_request_number=request.merge_front_pr,
            branch=request.branch,
            expected_base_sha=preflight.base_sha,
            expected_remote_head=request.expected_remote_head,
            live_main_sha=request.live_main,
        )
        if final_lifecycle != initial_lifecycle:
            raise ReanchorRefused("GitHub lifecycle changed during reanchor")
        active = registry_ops.register_active(
            state_path=request.state_path,
            preflight_result=preflight,
            target=request.target,
            live_main=request.live_main,
            lane_id=request.lane_id,
            claim_generation=request.claim_generation,
        )
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        cleanup = compensation.safe_compensate(
            request.repo, target=request.target, branch=request.branch
        )
        details = dict(exc.details) if isinstance(exc, ReanchorRefused) else {}
        details["compensation"] = cleanup
        reason = (
            exc.reason
            if isinstance(exc, ReanchorRefused)
            else f"reanchor source error: {type(exc).__name__}: {exc}"
        )
        raise ReanchorRefused(reason, **details) from exc
    return success_payload(
        request,
        active=active,
        head=head,
        declared=preflight.declared,
        merge_front_policy=final_lifecycle.merge_front_policy,
    )

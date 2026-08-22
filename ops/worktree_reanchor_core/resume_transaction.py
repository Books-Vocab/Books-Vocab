"""Transaction orchestration for one exact published-claim resume."""

from __future__ import annotations

from pathlib import Path

from . import git_ops, lifecycle_proof, registry_ops, resume_git_ops
from .errors import ReanchorRefused
from .resume_domain import build_request, success_payload


def perform_resume(
    *, repo: Path, state_path: Path, lane_id: str, branch: str,
    owner_thread_id: str, claim_generation: int,
    expected_remote_head: str, target: Path,
) -> dict[str, object]:
    request = build_request(
        repo=repo,
        state_path=state_path,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_remote_head=expected_remote_head,
        target=target,
    )
    git_ops.validate_repository(request.repo)
    preflight = registry_ops.preflight_resume(
        state_path=request.state_path,
        lane_id=request.lane_id,
        branch=request.branch,
        owner_thread_id=request.owner_thread_id,
        claim_generation=request.claim_generation,
        expected_remote_head=request.expected_remote_head,
        target=request.target,
    )
    github = lifecycle_proof.build_github(
        request.repo, operation="resume-published"
    )
    initial_lifecycle = lifecycle_proof.verify_resume_lifecycle(
        github,
        branch=request.branch,
        expected_base_sha=preflight.base_sha,
        expected_remote_head=request.expected_remote_head,
    )
    recorded_path = Path(str(preflight.original["path"])).expanduser().resolve()
    resume_git_ops.validate_released_assets(
        request.repo,
        recorded_path=recorded_path,
        target=request.target,
        branch=request.branch,
    )
    resume_git_ops.ensure_exact_source(
        request.repo,
        branch=request.branch,
        base_sha=preflight.base_sha,
        remote_head=request.expected_remote_head,
        declared=preflight.declared,
    )
    attempt = resume_git_ops.ProvisioningAttempt()
    try:
        resume_git_ops.provision_exact(
            request.repo,
            target=request.target,
            branch=request.branch,
            remote_head=request.expected_remote_head,
            base_sha=preflight.base_sha,
            declared=preflight.declared,
            attempt=attempt,
        )
        resume_git_ops.verify_remote_head(
            request.repo,
            branch=request.branch,
            expected_head=request.expected_remote_head,
        )
        final_lifecycle = lifecycle_proof.verify_resume_lifecycle(
            github,
            branch=request.branch,
            expected_base_sha=preflight.base_sha,
            expected_remote_head=request.expected_remote_head,
        )
        if final_lifecycle != initial_lifecycle:
            raise ReanchorRefused(
                "GitHub lifecycle changed during resume-published"
            )
        active = registry_ops.register_resumed(
            state_path=request.state_path,
            preflight_result=preflight,
            target=request.target,
            lane_id=request.lane_id,
            claim_generation=request.claim_generation,
        )
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        try:
            cleanup = resume_git_ops.compensate(
                request.repo,
                target=request.target,
                branch=request.branch,
                expected_head=request.expected_remote_head,
                attempt=attempt,
            )
        except (OSError, ReanchorRefused, TypeError, ValueError) as cleanup_exc:
            cleanup = {
                "complete": False,
                "reason": (
                    "compensation could not prove cleanup: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                ),
                "steps": [],
            }
        details = dict(exc.details) if isinstance(exc, ReanchorRefused) else {}
        details["compensation"] = cleanup
        reason = (
            exc.reason
            if isinstance(exc, ReanchorRefused)
            else f"resume-published source error: {type(exc).__name__}: {exc}"
        )
        raise ReanchorRefused(reason, **details) from exc
    return success_payload(
        request,
        active=active,
        recorded_base=str(preflight.original["base"]),
        base_sha=preflight.base_sha,
        pull_request_number=final_lifecycle.pull_request_number,
    )

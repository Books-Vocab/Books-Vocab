"""Transaction orchestration for one exact published-claim resume."""

from __future__ import annotations

from pathlib import Path

from delivery_control.domain.errors import DeliverySourceError
from delivery_control.domain.observations import PullRequestSnapshot

from . import git_ops, lifecycle_proof, registry_ops, resume_git_ops
from .errors import ReanchorRefused
from .resume_domain import (
    build_request,
    merged_maintenance_payload,
    success_payload,
    verify_merged_maintenance_lifecycle,
)


def _validate_existing_abandoned_assets(
    repo: Path,
    *,
    target: Path,
    branch: str,
    base_sha: str,
    remote_head: str,
    declared: tuple[tuple[str, str], ...],
) -> None:
    """Read-only proof for a released-looking but still existing owner checkout."""

    if not target.is_dir():
        raise ReanchorRefused(
            "abandoned PR recovery requires the exact existing owner worktree",
            path=str(target),
        )
    rows = git_ops._worktree_rows(repo)
    matching = [
        row
        for row in rows
        if Path(str(row.get("worktree") or "")).expanduser().resolve() == target
    ]
    if len(matching) != 1:
        raise ReanchorRefused(
            "abandoned PR recovery requires one exact registered physical worktree",
            path=str(target),
            matches=len(matching),
        )
    branch_rc, current_branch = git_ops._git(["branch", "--show-current"], target)
    status_rc, dirty = git_ops._git(["status", "--porcelain=v1"], target)
    head_rc, current_head = git_ops._git(
        ["rev-parse", "--verify", "HEAD^{commit}"], target
    )
    if (
        branch_rc != 0
        or current_branch != branch
        or status_rc != 0
        or dirty
        or head_rc != 0
        or current_head != remote_head
    ):
        raise ReanchorRefused(
            "abandoned PR recovery requires a clean worktree at the exact remote HEAD",
            branch=current_branch,
            head=current_head,
            dirty=dirty,
        )
    if git_ops._remote_head(repo, branch) != remote_head:
        raise ReanchorRefused("remote branch changed during abandoned PR recovery")
    for label, sha in (
        ("abandoned hand-back base", base_sha),
        ("remote HEAD", remote_head),
    ):
        rc, output = git_ops._git(["cat-file", "-e", f"{sha}^{{commit}}"], repo)
        if rc != 0:
            raise ReanchorRefused(f"{label} commit is unavailable", git=output)
    if (
        git_ops._git(["merge-base", "--is-ancestor", base_sha, remote_head], repo)[0]
        != 0
    ):
        raise ReanchorRefused(
            "abandoned hand-back base is not an ancestor of the PR HEAD"
        )
    if git_ops.scope_operations(repo, start=base_sha, end=remote_head) != declared:
        raise ReanchorRefused(
            "abandoned PR branch differs from the exact original Scope"
        )


def _perform_abandoned_recovery(request) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Restore one exact abandoned PR claim for the original owner only."""

    preflight = registry_ops.preflight_abandoned(
        state_path=request.state_path,
        lane_id=request.lane_id,
        branch=request.branch,
        owner_thread_id=request.owner_thread_id,
        claim_generation=request.claim_generation,
        expected_remote_head=request.expected_remote_head,
        target=request.target,
    )
    github = lifecycle_proof.build_github(
        request.repo, operation="recover-abandoned-pr"
    )
    handback_seal = preflight.original.get("handback_seal")
    handback_digest = (
        handback_seal.get("digest") if isinstance(handback_seal, dict) else None
    )
    proof = lifecycle_proof.verify_abandoned_pr_lifecycle(
        github,
        lane_id=request.lane_id,
        branch=request.branch,
        owner_thread_id=request.owner_thread_id,
        claim_generation=request.claim_generation,
        expected_base_sha=preflight.published_base_sha,
        expected_remote_head=request.expected_remote_head,
        recorded_base_sha=preflight.base_sha,
        declared_scope=preflight.declared,
        handback_digest=handback_digest,
    )
    _validate_existing_abandoned_assets(
        request.repo,
        target=request.target,
        branch=request.branch,
        base_sha=preflight.base_sha,
        remote_head=request.expected_remote_head,
        declared=preflight.declared,
    )
    active = registry_ops.register_recovered_abandoned(
        state_path=request.state_path,
        preflight_result=preflight,
        target=request.target,
        lane_id=request.lane_id,
        claim_generation=request.claim_generation,
    )
    payload = success_payload(
        request,
        active=active,
        recorded_base=str(preflight.original.get("base") or preflight.base_sha),
        base_sha=preflight.base_sha,
        pull_request_number=proof.pull_request_number,
    )
    payload["recovery"] = "abandoned-pr"
    payload["required_status"] = proof.required_status.value
    return payload


def _unique_branch_pr(
    github: lifecycle_proof.RecoveryGitHubPort, *, branch: str
) -> PullRequestSnapshot:
    try:
        inventory = github.list_pull_requests_for_branch(branch)
    except (DeliverySourceError, KeyError, TypeError, ValueError) as exc:
        raise ReanchorRefused(
            f"merged maintenance PR readback failed: {type(exc).__name__}: {exc}"
        ) from exc
    if inventory.problems:
        raise ReanchorRefused(
            "merged maintenance PR inventory contains malformed GitHub facts",
            problems=[problem.reason for problem in inventory.problems],
        )
    if len(inventory.records) != 1:
        raise ReanchorRefused(
            "merged maintenance requires one unique PR across the branch lifecycle",
            branch=branch,
            matches=len(inventory.records),
        )
    pull_request = inventory.records[0]
    if pull_request.branch != branch:
        raise ReanchorRefused("merged maintenance PR branch differs from the claim")
    return pull_request


def _exact_merged_source(
    repo: Path,
    *,
    pull_request_number: int,
    head_sha: str,
    base_sha: str,
    declared: tuple[tuple[str, str], ...],
) -> str:
    """Verify source object, parent, and Scope without provisioning a worktree."""

    rc, output = git_ops._git(["cat-file", "-e", f"{head_sha}^{{commit}}"], repo)
    if rc != 0:
        fetch_rc, fetch_output = git_ops._git(
            [
                "fetch",
                "--quiet",
                "--no-tags",
                "origin",
                f"refs/pull/{pull_request_number}/head",
            ],
            repo,
        )
        if fetch_rc != 0:
            raise ReanchorRefused(
                "merged maintenance source commit is unavailable",
                git=fetch_output or output,
            )
        rc, fetched = git_ops._git(["rev-parse", "FETCH_HEAD^{commit}"], repo)
        if rc != 0 or fetched != head_sha:
            raise ReanchorRefused(
                "merged maintenance PR source ref differs from exact hand-back",
                expected_head_sha=head_sha,
                fetched_head_sha=fetched,
            )
    parent_rc, parent_sha = git_ops._git(["rev-parse", f"{head_sha}^"], repo)
    if parent_rc != 0:
        raise ReanchorRefused(
            "merged maintenance source parent cannot be read", git=parent_sha
        )
    source_scope = git_ops.scope_operations(repo, start=base_sha, end=head_sha)
    if source_scope != declared:
        raise ReanchorRefused(
            "merged maintenance source differs from the exact original Scope",
            expected_scope=declared,
            actual_scope=source_scope,
        )
    return parent_sha


def perform_resume(
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
        previous_handback=previous_handback,
        mode=mode,
    )
    git_ops.validate_repository(request.repo)
    if request.mode == "abandoned-pr":
        return _perform_abandoned_recovery(request)
    preflight = registry_ops.preflight_resume(
        state_path=request.state_path,
        lane_id=request.lane_id,
        branch=request.branch,
        owner_thread_id=request.owner_thread_id,
        claim_generation=request.claim_generation,
        expected_remote_head=request.expected_remote_head,
        target=request.target,
        previous_handback=request.previous_handback,
    )
    github = lifecycle_proof.build_github(request.repo, operation="resume-published")
    if request.mode == "maintenance":
        pull_request = _unique_branch_pr(github, branch=request.branch)
        if pull_request.state == "MERGED":
            handback_seal = preflight.original.get("handback_seal")
            handback_digest = (
                handback_seal.get("digest") if isinstance(handback_seal, dict) else None
            )
            source_parent_sha = _exact_merged_source(
                request.repo,
                pull_request_number=pull_request.number,
                head_sha=request.expected_remote_head,
                base_sha=preflight.base_sha,
                declared=preflight.declared,
            )
            proof = verify_merged_maintenance_lifecycle(
                pull_request,
                lane_id=request.lane_id,
                branch=request.branch,
                owner_thread_id=request.owner_thread_id,
                claim_generation=request.claim_generation,
                expected_remote_head=request.expected_remote_head,
                previous_handback=request.previous_handback,
                recorded_base_sha=preflight.base_sha,
                published_base_sha=preflight.published_base_sha,
                source_parent_sha=source_parent_sha,
                declared_scope=preflight.declared,
                handback_digest=handback_digest,
            )
            return merged_maintenance_payload(
                request,
                original=preflight.original,
                proof=proof,
                recorded_base=str(preflight.original["base"]),
            )
        # An open PR may need bounded same-head maintenance when a non-code
        # gate (for example independent review evidence) failed after the
        # original hand-back was published.  The exact open-PR, owner, queue,
        # remote-head, and registry preflights above remain mandatory; the
        # required-code-failure resume path still rejects same-head requests
        # in ``build_request``.
    initial_lifecycle = lifecycle_proof.verify_resume_lifecycle(
        github,
        branch=request.branch,
        expected_base_sha=preflight.published_base_sha,
        expected_remote_head=request.expected_remote_head,
        require_failed=(
            request.mode == "required-failure" and request.previous_handback is None
        ),
        allow_missing_required=request.mode == "maintenance",
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
    if request.previous_handback is not None:
        ancestor_rc, _ = git_ops._git(
            [
                "merge-base",
                "--is-ancestor",
                request.previous_handback,
                request.expected_remote_head,
            ],
            request.repo,
        )
        if ancestor_rc != 0:
            raise ReanchorRefused(
                "advanced published resume requires the previous hand-back to "
                "be an ancestor of the current remote HEAD"
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
            expected_base_sha=preflight.published_base_sha,
            expected_remote_head=request.expected_remote_head,
            require_failed=(
                request.mode == "required-failure" and request.previous_handback is None
            ),
            allow_missing_required=request.mode == "maintenance",
        )
        if final_lifecycle != initial_lifecycle:
            raise ReanchorRefused("GitHub lifecycle changed during resume-published")
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

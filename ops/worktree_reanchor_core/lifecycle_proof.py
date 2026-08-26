"""Read-only GitHub proof for published-claim recovery transactions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.domain.errors import DeliverySourceError
from delivery_control.domain.models import CheckStatus
from delivery_control.domain.observations import (
    CheckSnapshot,
    MergeQueueEntrySnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from delivery_control.services.pr_contract import (
    parse_pull_request_body,
    pull_request_holds,
)

from .errors import ReanchorRefused

REQUIRED_CODE_CONTEXT = ("required",)
TRUSTED_REQUIRED_CODE_CONTEXT = ("agent-review", "required")
ACCEPTED_REQUIRED_CODE_CONTEXTS = frozenset(
    {REQUIRED_CODE_CONTEXT, TRUSTED_REQUIRED_CODE_CONTEXT}
)
MERGE_FRONT_POLICY = "lowest-required-green-unheld-pr-number"


class RecoveryGitHubPort(Protocol):
    """Small read-only seam used by recovery; no GitHub mutation is exposed."""

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory: ...

    def list_open_pull_requests(self) -> PullRequestInventory: ...

    def required_check_snapshot(self, number: int) -> CheckSnapshot: ...

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None: ...


@dataclass(frozen=True)
class RecoveryLifecycleProof:
    pull_request_number: int
    base_sha: str
    head_sha: str
    required_status: CheckStatus
    merge_front_policy: str | None = None


def build_github(repo: Path, *, operation: str) -> RecoveryGitHubPort:
    """Use the existing typed GitHub CLI query adapter at the CLI boundary."""

    if operation not in {"reanchor", "resume-published"}:
        raise ValueError(f"unsupported recovery operation: {operation}")
    return GitHubCliAdapter(repo=repo)


def _read(operation: str, callback):  # type: ignore[no-untyped-def]
    try:
        return callback()
    except ReanchorRefused:
        raise
    except (DeliverySourceError, KeyError, TypeError, ValueError) as exc:
        raise ReanchorRefused(
            f"GitHub lifecycle proof failed during {operation}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _unique_branch_pr(
    github: RecoveryGitHubPort,
    *,
    branch: str,
) -> PullRequestSnapshot:
    inventory = _read(
        "branch PR inventory",
        lambda: github.list_pull_requests_for_branch(branch),
    )
    if inventory.problems:
        raise ReanchorRefused(
            "branch PR inventory contains malformed GitHub facts",
            problems=[problem.reason for problem in inventory.problems],
        )
    if len(inventory.records) != 1:
        raise ReanchorRefused(
            "published branch must map to exactly one PR across its lifecycle",
            branch=branch,
            matches=len(inventory.records),
        )
    pull_request = inventory.records[0]
    if pull_request.branch != branch:
        raise ReanchorRefused("GitHub PR branch differs from published branch")
    return pull_request


def _exact_open_pr(
    github: RecoveryGitHubPort,
    *,
    branch: str,
    expected_base_sha: str,
    expected_remote_head: str,
) -> PullRequestSnapshot:
    pull_request = _unique_branch_pr(github, branch=branch)
    if pull_request.state != "OPEN":
        raise ReanchorRefused(
            "published recovery requires the unique PR to remain OPEN and unmerged",
            pull_request=pull_request.number,
            state=pull_request.state,
        )
    if pull_request.draft:
        raise ReanchorRefused("published recovery refuses a draft PR")
    if pull_request.base_branch != "main":
        raise ReanchorRefused("published recovery requires PR target main")
    if pull_request.base_sha != expected_base_sha:
        raise ReanchorRefused(
            "PR base differs from the exact published claim",
            pull_request=pull_request.number,
            expected_base_sha=expected_base_sha,
            actual_base_sha=pull_request.base_sha,
        )
    if pull_request.head_sha != expected_remote_head:
        raise ReanchorRefused(
            "PR HEAD differs from the exact published remote HEAD",
            pull_request=pull_request.number,
            expected_head_sha=expected_remote_head,
            actual_head_sha=pull_request.head_sha,
        )
    queue_entry = _read(
        f"PR#{pull_request.number} merge queue state",
        lambda: github.merge_queue_entry_snapshot(pull_request.node_id),
    )
    if queue_entry is not None:
        raise ReanchorRefused(
            "published recovery refuses a PR already owned by the native merge queue",
            pull_request=pull_request.number,
            queue_entry=queue_entry.entry_id,
        )
    return pull_request


def _required(
    github: RecoveryGitHubPort,
    pull_request: PullRequestSnapshot,
    *,
    allow_combined_context: bool = False,
) -> CheckSnapshot:
    check = _read(
        f"PR#{pull_request.number} required check",
        lambda: github.required_check_snapshot(pull_request.number),
    )
    if check.head_sha != pull_request.head_sha:
        raise ReanchorRefused(
            "required check is not bound to the exact PR HEAD",
            pull_request=pull_request.number,
            check_head_sha=check.head_sha,
            pull_request_head_sha=pull_request.head_sha,
        )
    normalized_context = tuple(sorted(set(check.names)))
    accepted_contexts = (
        ACCEPTED_REQUIRED_CODE_CONTEXTS
        if allow_combined_context
        else frozenset({REQUIRED_CODE_CONTEXT})
    )
    if normalized_context not in accepted_contexts:
        raise ReanchorRefused(
            "recovery requires the exact required code failure context",
            pull_request=pull_request.number,
            required_contexts=list(check.names),
        )
    return check


def verify_resume_lifecycle(
    github: RecoveryGitHubPort,
    *,
    branch: str,
    expected_base_sha: str,
    expected_remote_head: str,
    require_failed: bool = True,
) -> RecoveryLifecycleProof:
    """Prove that one published PR may be resumed for a code repair."""

    pull_request = _exact_open_pr(
        github,
        branch=branch,
        expected_base_sha=expected_base_sha,
        expected_remote_head=expected_remote_head,
    )
    check = _required(
        github,
        pull_request,
        allow_combined_context=not require_failed,
    )
    if require_failed and check.status is not CheckStatus.FAILURE:
        raise ReanchorRefused(
            "resume-published is allowed only for an exact required code failure",
            pull_request=pull_request.number,
            required_status=check.status.value,
        )
    if not require_failed and check.status is CheckStatus.ABSENT:
        raise ReanchorRefused(
            "maintenance resume requires an observed required check",
            pull_request=pull_request.number,
        )
    return RecoveryLifecycleProof(
        pull_request_number=pull_request.number,
        base_sha=pull_request.base_sha,
        head_sha=pull_request.head_sha,
        required_status=check.status,
    )


def _eligible_merge_front(
    github: RecoveryGitHubPort,
    pull_request: PullRequestSnapshot,
) -> bool:
    if (
        pull_request.state != "OPEN"
        or pull_request.base_branch != "main"
        or pull_request.draft
        or not pull_request.mergeable
    ):
        return False
    try:
        if pull_request_holds(pull_request):
            return False
    except DeliverySourceError as exc:
        raise ReanchorRefused(
            f"PR#{pull_request.number} hold evidence is malformed: {exc}"
        ) from exc
    try:
        receipt = parse_pull_request_body(pull_request.body)
    except DeliverySourceError:
        return False
    if (
        receipt.branch != pull_request.branch
        or receipt.base_sha != pull_request.base_sha
        or receipt.head_sha != pull_request.head_sha
    ):
        return False
    check = _required(github, pull_request, allow_combined_context=True)
    return check.status is CheckStatus.SUCCESS


def verify_reanchor_lifecycle(
    github: RecoveryGitHubPort,
    *,
    pull_request_number: int,
    branch: str,
    expected_remote_head: str,
    live_main_sha: str,
    expected_pr_base_sha: str | None = None,
    # Compatibility for callers written before publication began recording
    # the GitHub target OID separately from the typed handback base.
    expected_base_sha: str | None = None,
) -> RecoveryLifecycleProof:
    """Prove that one published PR is the deterministic merge-front candidate."""

    legacy_base_contract = expected_pr_base_sha is None
    published_base_sha = expected_pr_base_sha or expected_base_sha
    if published_base_sha is None:
        raise ReanchorRefused("published PR base is required for reanchor proof")

    candidate = _exact_open_pr(
        github,
        branch=branch,
        expected_base_sha=published_base_sha,
        expected_remote_head=expected_remote_head,
    )
    if candidate.number != pull_request_number:
        raise ReanchorRefused(
            "caller PR differs from the unique published branch PR",
            caller_pull_request=pull_request_number,
            actual_pull_request=candidate.number,
        )
    if legacy_base_contract and candidate.base_sha == live_main_sha:
        raise ReanchorRefused("reanchor requires a stale PR base")
    if candidate.draft:
        raise ReanchorRefused("reanchor refuses a draft PR")
    if not candidate.mergeable:
        raise ReanchorRefused("reanchor requires the PR to be mergeable")
    if pull_request_holds(candidate):
        raise ReanchorRefused("reanchor refuses a PR with an explicit hard hold")
    candidate_check = _required(
        github,
        candidate,
        allow_combined_context=True,
    )
    if candidate_check.status is not CheckStatus.SUCCESS:
        raise ReanchorRefused("reanchor requires an exact required-green PR")

    inventory = _read("open PR inventory", github.list_open_pull_requests)
    if inventory.problems:
        raise ReanchorRefused(
            "open PR inventory contains malformed GitHub facts",
            problems=[problem.reason for problem in inventory.problems],
        )
    for pull_request in inventory.records:
        queue_entry = _read(
            f"PR#{pull_request.number} merge queue state",
            lambda pull_request=pull_request: github.merge_queue_entry_snapshot(
                pull_request.node_id
            ),
        )
        if queue_entry is not None:
            raise ReanchorRefused(
                "native merge queue already owns the deterministic merge-front",
                pull_request=pull_request.number,
                queue_entry=queue_entry.entry_id,
            )
    eligible = tuple(
        sorted(
            (
                pull_request
                for pull_request in inventory.records
                if _eligible_merge_front(github, pull_request)
            ),
            key=lambda pull_request: pull_request.number,
        )
    )
    if not eligible:
        raise ReanchorRefused("no required-green unheld merge-front candidate exists")
    merge_front = eligible[0]
    if merge_front.number != candidate.number:
        raise ReanchorRefused(
            "caller PR is not the deterministic merge-front",
            caller_pull_request=candidate.number,
            merge_front_pull_request=merge_front.number,
            policy=MERGE_FRONT_POLICY,
        )
    return RecoveryLifecycleProof(
        pull_request_number=candidate.number,
        base_sha=candidate.base_sha,
        head_sha=candidate.head_sha,
        required_status=candidate_check.status,
        merge_front_policy=MERGE_FRONT_POLICY,
    )

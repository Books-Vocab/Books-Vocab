"""Shared exact-contract checks for delivery lane projections."""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.observations import (
    InventoryProblem,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from .pr_contract import parse_pull_request_body


def pr_receipt_matches_registry(
    record: RegistrySnapshot,
    pull_request: PullRequestSnapshot,
    problems: list[InventoryProblem],
) -> bool:
    """Validate the PR receipt against the exact registry tuple."""
    try:
        receipt = parse_pull_request_body(pull_request.body)
    except DeliverySourceError as error:
        problems.append(
            InventoryProblem("github", f"PR#{pull_request.number}", str(error))
        )
        return False
    exact = (
        receipt.lane_id == record.lane_id
        and receipt.owner_thread_id == record.owner_thread_id
        and receipt.claim_generation == record.claim_generation
        and receipt.branch == record.branch
        and Path(receipt.worktree_path).resolve() == record.path.resolve()
        and receipt.base_sha == record.base_sha
        and receipt.head_sha == record.handed_back_sha == pull_request.head_sha
        and receipt.origin_main_sha == record.handback_origin_main_sha
        and receipt.content_digest == record.handback_digest
        and receipt.scope == record.scope
        and pull_request.base_branch == "main"
    )
    if not exact:
        problems.append(
            InventoryProblem(
                "github",
                f"PR#{pull_request.number}",
                "PR receipt differs from the exact registry tuple",
            )
        )
    return exact

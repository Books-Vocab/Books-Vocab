"""Exact correlation between a durable PR receipt and local publication proof."""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import RegistrySnapshot
from ..ports.registry import RegistryQueryPort


def exact_published_record(
    registry: RegistryQueryPort, receipt: HandbackReceipt
) -> RegistrySnapshot:
    inventory = registry.list_records()
    if inventory.problems:
        raise PolicyViolation("registry inventory is incomplete")
    matches = [
        item
        for item in inventory.records
        if item.lane_id == receipt.lane_id
        and item.branch == receipt.branch
        and item.path.resolve() == Path(receipt.worktree_path).resolve()
        and item.status == "published"
        and item.base_sha == receipt.base_sha
        and item.scope == receipt.scope
        and item.claim_generation == receipt.claim_generation
        and item.owner_thread_id == receipt.owner_thread_id
        and item.handed_back_sha == receipt.head_sha
        and item.handback_claim_generation == receipt.claim_generation
        and item.handback_valid
        and item.handback_digest == receipt.content_digest
        and item.handback_origin_main_sha == receipt.origin_main_sha
    ]
    if len(matches) != 1:
        raise PolicyViolation(
            "operation lacks one exact local receipt in published state"
        )
    return matches[0]

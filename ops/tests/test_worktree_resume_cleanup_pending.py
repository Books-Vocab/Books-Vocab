from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import HandbackReceipt, Scope  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    RegistryInventory,
    RegistrySnapshot,
)
from delivery_control.services.receipt_registry import (  # noqa: E402
    exact_published_record,
)
from worktree_reanchor_core.registry_ops import _select_original  # noqa: E402


BASE = "a" * 40
HEAD = "b" * 40
DIGEST = "c" * 64
LANE = "DIRECT-CLEANUP-PENDING"
BRANCH = "debug/cleanup-pending"
OWNER = "owner-thread"
PATH = Path("/tmp/cleanup-pending")


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id=LANE,
        owner_thread_id=OWNER,
        claim_generation=2,
        branch=BRANCH,
        worktree_path=str(PATH),
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        origin_main_sha=BASE,
        content_digest=DIGEST,
        scope=Scope.from_paths(modify=("ops/example.py",)),
    )


def _record(receipt: HandbackReceipt) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=receipt.lane_id,
        branch=receipt.branch,
        path=PATH,
        status="cleanup_pending",
        scope=receipt.scope,
        base_sha=receipt.base_sha,
        claim_generation=receipt.claim_generation,
        owner_thread_id=receipt.owner_thread_id,
        handed_back_sha=receipt.head_sha,
        handback_claim_generation=receipt.claim_generation,
        handback_valid=True,
        handback_digest=receipt.content_digest,
        handback_origin_main_sha=receipt.origin_main_sha,
    )


class FakeRegistry:
    def __init__(self, record: RegistrySnapshot) -> None:
        self.record = record

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.record,))


def test_queue_receipt_accepts_cleanup_pending_after_publish_release() -> None:
    receipt = _receipt()

    matched = exact_published_record(FakeRegistry(_record(receipt)), receipt)

    assert matched.status == "cleanup_pending"


def test_resume_selector_accepts_cleanup_pending_original_claim() -> None:
    record = {
        "status": "cleanup_pending",
        "external_ids": [LANE],
        "branch": BRANCH,
        "claim_generation": 2,
    }

    selected = _select_original({"records": [record]}, lane_id=LANE, claim_generation=2)

    assert selected is record

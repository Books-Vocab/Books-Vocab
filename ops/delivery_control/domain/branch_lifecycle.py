"""Typed lifecycle facts for local and remote Git branch assets.

Branch refs are delivery assets, but they are not delivery lanes.  Keeping
their projection separate prevents an unregistered branch from disappearing
when the lane inventory has no matching worktree or pull request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .errors import InvalidReceipt
from .observations import InventoryProblem, RegistrySnapshot

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class BranchSide(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class BranchDisposition(StrEnum):
    PROTECTED = "protected"
    OPEN_PR_DURABLE = "open_pr_durable"
    ACTIVE_OR_PUBLISHED_LANE = "active_or_published_lane"
    MERGED_CLEANUP_READY = "merged_cleanup_ready"
    ABANDONED_WITH_HANDBACK = "abandoned_with_handback"
    CLOSED_DISPOSITION_REQUIRED = "closed_disposition_required"
    ORPHAN_LOCAL_RECONCILE = "orphan_local_reconcile"
    ORPHAN_REMOTE_RECONCILE = "orphan_remote_reconcile"
    REMOTE_DRIFT = "remote_drift"
    UNKNOWN = "unknown"


class BranchCleanupAction(StrEnum):
    PRESERVE_PROTECTED = "preserve_protected"
    PRESERVE_DURABLE_PR = "preserve_durable_pr"
    FOLLOW_OWNER_LANE = "follow_owner_lane"
    CLEANUP_MERGED = "cleanup_merged"
    RECOVER_OWNER_OR_REQUIRE_DISCARD_PROOF = "recover_owner_or_require_discard_proof"
    RECONCILE_CLOSED_PR = "reconcile_closed_pr"
    RECONCILE_LOCAL_ORPHAN = "reconcile_local_orphan"
    RECONCILE_REMOTE_ORPHAN = "reconcile_remote_orphan"
    PRESERVE_REMOTE_DRIFT = "preserve_remote_drift"
    INSPECT_UNKNOWN = "inspect_unknown"


def _require_text(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidReceipt(f"{field} must be canonical text")
    return value


def _optional_text(value: object, field: str) -> None:
    if value is not None:
        _require_text(value, field)


def _optional_sha(value: object, field: str) -> None:
    if value is not None and (
        type(value) is not str or _SHA_RE.fullmatch(value) is None
    ):
        raise InvalidReceipt(f"{field} must be a lowercase commit SHA or null")


@dataclass(frozen=True)
class BranchRegistryEvidence:
    """Non-authorizing provenance joined from one registry record."""

    lane_id: str
    branch: str
    path: str
    status: str
    claim_generation: int | None = None
    base_sha: str | None = None
    published_base_sha: str | None = None
    handed_back_sha: str | None = None
    handback_digest: str | None = None
    owner_thread_id: str | None = None
    scope_paths: tuple[str, ...] = ()
    external_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("lane_id", "branch", "path", "status"):
            _require_text(getattr(self, field_name), field_name)
        if self.claim_generation is not None and (
            type(self.claim_generation) is not int or self.claim_generation < 0
        ):
            raise InvalidReceipt(
                "claim_generation must be a non-negative integer or null"
            )
        _optional_sha(self.base_sha, "base_sha")
        _optional_sha(self.published_base_sha, "published_base_sha")
        _optional_sha(self.handed_back_sha, "handed_back_sha")
        if self.handback_digest is not None and (
            type(self.handback_digest) is not str
            or _DIGEST_RE.fullmatch(self.handback_digest) is None
        ):
            raise InvalidReceipt(
                "handback_digest must be a lowercase SHA-256 digest or null"
            )
        _optional_text(self.owner_thread_id, "owner_thread_id")
        for field_name in ("scope_paths", "external_ids"):
            values = getattr(self, field_name)
            if type(values) is not tuple or any(
                type(value) is not str or not value for value in values
            ):
                raise InvalidReceipt(f"{field_name} must contain canonical text")
            if tuple(sorted(set(values))) != values:
                raise InvalidReceipt(f"{field_name} must be sorted and unique")

    @property
    def sort_key(self) -> tuple[str, str, str, str, int, str]:
        """Stable ordering key; record identity is never inferred from reason."""

        return (
            self.lane_id,
            self.branch,
            self.path,
            self.status,
            self.claim_generation if self.claim_generation is not None else -1,
            self.handed_back_sha or "",
        )

    @classmethod
    def from_snapshot(cls, record: RegistrySnapshot) -> BranchRegistryEvidence:
        """Project a validated RegistrySnapshot without granting any authority."""

        return cls(
            lane_id=record.lane_id,
            branch=record.branch,
            path=str(record.path.resolve()),
            status=record.status,
            claim_generation=record.claim_generation,
            base_sha=record.base_sha,
            published_base_sha=record.published_base_sha,
            handed_back_sha=record.handed_back_sha,
            handback_digest=record.handback_digest,
            owner_thread_id=record.owner_thread_id,
            scope_paths=tuple(sorted(record.scope.paths)),
            external_ids=tuple(sorted(set(record.external_ids))),
        )


@dataclass(frozen=True)
class BranchAsset:
    """One observed local or remote ref and its deterministic disposition."""

    branch: str
    side: BranchSide
    sha: str
    disposition: BranchDisposition
    cleanup_action: BranchCleanupAction
    reason: str
    protected: bool = False
    pull_request_numbers: tuple[int, ...] = ()
    registry_statuses: tuple[str, ...] = ()
    physical_worktree_paths: tuple[str, ...] = ()
    dirty_worktree_paths: tuple[str, ...] = ()
    owner_thread_ids: tuple[str, ...] = ()
    registry_evidence: tuple[BranchRegistryEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.branch, "branch")
        try:
            side = BranchSide(self.side)
            disposition = BranchDisposition(self.disposition)
            action = BranchCleanupAction(self.cleanup_action)
        except (TypeError, ValueError) as error:
            raise InvalidReceipt("branch lifecycle enum is invalid") from error
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "cleanup_action", action)
        if type(self.sha) is not str or not _SHA_RE.fullmatch(self.sha):
            raise InvalidReceipt("branch asset SHA must be a lowercase commit SHA")
        _require_text(self.reason, "branch lifecycle reason")
        if type(self.protected) is not bool:
            raise InvalidReceipt("branch protected flag must be boolean")
        if type(self.pull_request_numbers) is not tuple or any(
            type(number) is not int or number <= 0
            for number in self.pull_request_numbers
        ):
            raise InvalidReceipt("branch pull request numbers are invalid")
        if tuple(sorted(set(self.pull_request_numbers))) != self.pull_request_numbers:
            raise InvalidReceipt(
                "branch pull request numbers must be sorted and unique"
            )
        for field_name, values in (
            ("registry_statuses", self.registry_statuses),
            ("physical_worktree_paths", self.physical_worktree_paths),
            ("dirty_worktree_paths", self.dirty_worktree_paths),
            ("owner_thread_ids", self.owner_thread_ids),
        ):
            if type(values) is not tuple or any(
                type(value) is not str or not value for value in values
            ):
                raise InvalidReceipt(f"{field_name} must contain canonical text")
            if tuple(sorted(set(values))) != values:
                raise InvalidReceipt(f"{field_name} must be sorted and unique")
        if type(self.registry_evidence) is not tuple or any(
            not isinstance(value, BranchRegistryEvidence)
            for value in self.registry_evidence
        ):
            raise InvalidReceipt("registry_evidence must contain typed evidence")
        evidence_keys = tuple(value.sort_key for value in self.registry_evidence)
        if evidence_keys != tuple(sorted(evidence_keys)):
            raise InvalidReceipt("registry_evidence must be canonically sorted")
        if self.protected != (self.disposition is BranchDisposition.PROTECTED):
            raise InvalidReceipt("protected flag does not match branch disposition")

    @property
    def cleanup_ready(self) -> bool:
        return self.disposition is BranchDisposition.MERGED_CLEANUP_READY


@dataclass(frozen=True)
class BranchLifecycleInventory:
    """A complete, exactly-once partition of observed local/remote refs."""

    assets: tuple[BranchAsset, ...] = ()
    source_problems: tuple[InventoryProblem, ...] = ()

    def __post_init__(self) -> None:
        if type(self.assets) is not tuple or any(
            not isinstance(asset, BranchAsset) for asset in self.assets
        ):
            raise InvalidReceipt("branch lifecycle assets must be typed")
        identities = [(asset.side, asset.branch) for asset in self.assets]
        if len(identities) != len(set(identities)):
            raise InvalidReceipt("branch lifecycle assets contain duplicate refs")
        if type(self.source_problems) is not tuple or any(
            not isinstance(problem, InventoryProblem)
            for problem in self.source_problems
        ):
            raise InvalidReceipt("branch lifecycle source problems must be typed")

    @property
    def local(self) -> tuple[BranchAsset, ...]:
        return tuple(asset for asset in self.assets if asset.side is BranchSide.LOCAL)

    @property
    def remote(self) -> tuple[BranchAsset, ...]:
        return tuple(asset for asset in self.assets if asset.side is BranchSide.REMOTE)

    @property
    def counts(self) -> dict[str, int]:
        return {
            disposition.value: sum(
                asset.disposition is disposition for asset in self.assets
            )
            for disposition in BranchDisposition
        }

    @property
    def cleanup_ready(self) -> tuple[BranchAsset, ...]:
        return tuple(asset for asset in self.assets if asset.cleanup_ready)


EMPTY_BRANCH_LIFECYCLE = BranchLifecycleInventory()


__all__ = [
    "EMPTY_BRANCH_LIFECYCLE",
    "BranchAsset",
    "BranchCleanupAction",
    "BranchDisposition",
    "BranchLifecycleInventory",
    "BranchRegistryEvidence",
    "BranchSide",
]

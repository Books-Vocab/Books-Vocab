"""Typed observations read from Git, GitHub, registry, and agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .errors import InvalidReceipt, InvalidScope
from .models import (
    CheckStatus,
    HandbackOutcome,
    Scope,
    _has_control,
    _require_sha,
    _safe_relative_path,
)


class FileOperation(StrEnum):
    """Canonical changed-file operations after Git boundary normalization."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


@dataclass(frozen=True, order=True)
class FileChange:
    operation: FileOperation
    path: str

    def __post_init__(self) -> None:
        try:
            operation = FileOperation(self.operation)
        except (TypeError, ValueError) as error:
            raise InvalidReceipt(
                f"unsupported file operation: {self.operation!r}"
            ) from error
        object.__setattr__(self, "operation", operation)
        try:
            path = _safe_relative_path(self.path)
        except InvalidScope as error:
            raise InvalidReceipt(str(error)) from error
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class WorktreeSnapshot:
    path: Path
    branch: str | None
    base_sha: str
    head_sha: str
    parent_sha: str
    clean: bool
    changes: tuple[FileChange, ...]

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(change.path for change in self.changes)


@dataclass(frozen=True)
class PhysicalWorktree:
    path: Path
    head_sha: str
    branch: str | None
    prunable: bool = False


@dataclass(frozen=True)
class CanonicalCheckoutSnapshot:
    path: Path
    branch: str | None
    head_sha: str
    clean: bool


@dataclass(frozen=True)
class InventoryProblem:
    source: str
    identity: str
    reason: str
    # Registry parsing can preserve whether an identity came from a branch,
    # path, or an unaddressable record slot.  Consumers must not infer this
    # from the identity's spelling: a path or a branch can both contain '/'.
    identity_kind: str | None = None
    # When parsing a concrete registry record fails, preserve its raw status so
    # downstream audits can count the malformed claim without treating it as a
    # valid RegistrySnapshot.  Adapter-reported/global problems leave this
    # unset because they are not tied to one raw record.
    record_status: str | None = None
    # A malformed registry record is still an ownership observation. Preserve
    # the raw path and owner so metrics can classify it as owner-bound or
    # ownerless without promoting the malformed claim into a valid lane.
    record_path: Path | None = None
    owner_thread_id: str | None = None
    # Preserve exact external IDs from the same malformed raw registry
    # record. Consumers may use these only for deterministic audit joins;
    # they never turn the malformed record into a valid claim.
    record_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegistrySnapshot:
    lane_id: str
    branch: str
    path: Path
    status: str
    scope: Scope
    base_sha: str
    claim_generation: int
    # The base recorded in the typed handback remains immutable.  GitHub may
    # advance a PR's target branch between publication and the next owner
    # handback, so the durable publication must keep that observed PR base
    # separately instead of overwriting the physical handback provenance.
    published_base_sha: str | None = None
    external_ids: tuple[str, ...] = ()
    owner_thread_id: str | None = None
    handed_back_sha: str | None = None
    handback_claim_generation: int | None = None
    handback_valid: bool = False
    handback_digest: str | None = None
    handback_origin_main_sha: str | None = None
    handed_back_at: datetime | None = None
    handback_outcomes: tuple[HandbackOutcome, ...] = ()
    handback_initial_holds: tuple[str, ...] = ()
    superseded_pr_number: int | None = None
    superseded_pr_head_sha: str | None = None
    superseded_patch_fingerprint: str | None = None


@dataclass(frozen=True)
class RegistryInventory:
    records: tuple[RegistrySnapshot, ...]
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class RegistryCollisionClaim:
    lane_id: str
    branch: str
    scope: Scope


@dataclass(frozen=True)
class RegistryCollisionInventory:
    records: tuple[RegistryCollisionClaim, ...]
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    url: str
    branch: str
    base_sha: str
    head_sha: str
    state: str
    draft: bool
    mergeable: bool
    base_branch: str = "main"
    title: str = ""
    body: str = ""
    auto_merge_enabled: bool = False
    node_id: str = ""
    labels: tuple[str, ...] = ()
    created_at: datetime | None = None
    merged_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.labels) is not tuple or any(
            type(label) is not str or not label or _has_control(label)
            for label in self.labels
        ):
            raise InvalidReceipt("PR labels must be canonical text")
        for name in ("created_at", "merged_at"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, datetime) or value.utcoffset() is None
            ):
                raise InvalidReceipt(f"PR {name} must be offset-aware")


@dataclass(frozen=True)
class PullRequestInventory:
    records: tuple[PullRequestSnapshot, ...]
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class MergeQueueEntrySnapshot:
    entry_id: str
    enqueued_at: datetime

    def __post_init__(self) -> None:
        if not self.entry_id or _has_control(self.entry_id):
            raise InvalidReceipt("merge queue entry id must be canonical text")
        if (
            not isinstance(self.enqueued_at, datetime)
            or self.enqueued_at.utcoffset() is None
        ):
            raise InvalidReceipt("merge queue enqueue timestamp must be offset-aware")


@dataclass(frozen=True)
class MainLandingSnapshot:
    """One first-parent landing observed while synchronizing local main."""

    sha: str
    landed_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.sha) is not str
            or len(self.sha) != 40
            or any(char not in "0123456789abcdef" for char in self.sha)
        ):
            raise InvalidReceipt("main landing SHA must be a lowercase commit SHA")
        if (
            not isinstance(self.landed_at, datetime)
            or self.landed_at.utcoffset() is None
        ):
            raise InvalidReceipt("main landing timestamp must be offset-aware")


@dataclass(frozen=True)
class CheckSnapshot:
    status: CheckStatus
    head_sha: str
    observed_at: datetime
    names: tuple[str, ...]
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CheckStatus(self.status))
        _require_sha("check head_sha", self.head_sha)
        if (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.utcoffset() is None
        ):
            raise InvalidReceipt("check timestamp must be offset-aware")
        if type(self.names) is not tuple or any(
            type(name) is not str or not name or _has_control(name)
            for name in self.names
        ):
            raise InvalidReceipt("check names must be canonical text")
        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, datetime) or value.utcoffset() is None
            ):
                raise InvalidReceipt(f"check {name} must be offset-aware")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise InvalidReceipt("check completion precedes check start")

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

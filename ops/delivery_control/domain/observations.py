"""Typed observations read from Git, GitHub, registry, and agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .errors import InvalidReceipt, InvalidScope
from .models import CheckStatus, Scope, _has_control, _require_sha, _safe_relative_path


class FileOperation(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    COPY = "copy"


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


@dataclass(frozen=True)
class RegistrySnapshot:
    lane_id: str
    branch: str
    path: Path
    status: str
    scope: Scope
    base_sha: str
    claim_generation: int
    owner_thread_id: str | None = None
    handed_back_sha: str | None = None
    handback_claim_generation: int | None = None
    handback_valid: bool = False
    handback_digest: str | None = None
    handback_origin_main_sha: str | None = None


@dataclass(frozen=True)
class RegistryInventory:
    records: tuple[RegistrySnapshot, ...]
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


@dataclass(frozen=True)
class PullRequestInventory:
    records: tuple[PullRequestSnapshot, ...]
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class CheckSnapshot:
    status: CheckStatus
    head_sha: str
    observed_at: datetime
    names: tuple[str, ...]

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

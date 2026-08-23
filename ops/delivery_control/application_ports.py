"""Aggregate ports consumed by the delivery application facade."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from .ports.git import (
    BranchContentQueryPort,
    GitCommandPort,
    GitQueryPort,
    UnreachableCommitQueryPort,
)
from .ports.github import (
    GitHubCommandPort,
    GitHubQueryPort,
    GitHubWorkflowCommandPort,
)
from .ports.registry import (
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    RegistryDiscardCommandPort,
    RegistryPublicationQueryPort,
    RegistryQueryPort,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class DeliveryGitPort(
    GitQueryPort,
    BranchContentQueryPort,
    UnreachableCommitQueryPort,
    GitCommandPort,
    Protocol,
):
    pass


class DeliveryGitHubPort(
    GitHubQueryPort,
    GitHubCommandPort,
    GitHubWorkflowCommandPort,
    Protocol,
):
    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]: ...


class DeliveryRegistryPort(
    RegistryQueryPort,
    RegistryPublicationQueryPort,
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    RegistryDiscardCommandPort,
    Protocol,
):
    pass


__all__ = ["DeliveryGitHubPort", "DeliveryGitPort", "DeliveryRegistryPort"]

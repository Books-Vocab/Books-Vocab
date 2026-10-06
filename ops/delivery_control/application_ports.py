"""Aggregate ports consumed by the delivery application facade."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from .ports.git import (
    BranchContentQueryPort,
    GitDiffFingerprintPort,
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
    RegistrySupersedeCommandPort,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class DeliveryGitPort(
    GitQueryPort,
    BranchContentQueryPort,
    GitDiffFingerprintPort,
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
    RegistrySupersedeCommandPort,
    Protocol,
):
    pass


__all__ = ["DeliveryGitHubPort", "DeliveryGitPort", "DeliveryRegistryPort"]

"""Read-only publication preflight across owner, Git, registry, and GitHub facts."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import DeliverySourceError, PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import (
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..domain.policies import evaluate_publication
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryPublicationQueryPort


@dataclass(frozen=True)
class PublicationContext:
    registry: RegistrySnapshot
    worktree: WorktreeSnapshot
    pull_request: PullRequestSnapshot | None
    remote_sha: str | None


class PublishPreflightService:
    def __init__(
        self,
        *,
        registry: RegistryPublicationQueryPort,
        git: GitQueryPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry = registry
        self.git = git
        self.github = github

    def _scope_collision(
        self,
        *,
        receipt: HandbackReceipt,
        registry: RegistrySnapshot,
        pull_requests: tuple[PullRequestSnapshot, ...],
    ) -> bool:
        paths = set(receipt.scope.paths)
        inventory = self.registry.list_collision_claims()
        if inventory.problems:
            reasons = "; ".join(problem.reason for problem in inventory.problems)
            raise DeliverySourceError(f"registry inventory is incomplete: {reasons}")
        for other in inventory.records:
            if other.lane_id == registry.lane_id or other.branch == receipt.branch:
                continue
            if paths.intersection(other.scope.paths):
                return True
        for pull_request in pull_requests:
            if pull_request.branch == receipt.branch:
                continue
            if paths.intersection(self.github.changed_paths(pull_request.number)):
                return True
        return False

    def check(self, receipt: HandbackReceipt) -> PublicationContext:
        registry = self.registry.get(receipt.lane_id)
        if registry is None:
            raise PolicyViolation("no active registry claim exists for handback lane")
        worktree = self.git.inspect_worktree(registry.path, receipt.base_sha)
        pull_request_inventory = self.github.list_open_pull_requests()
        if pull_request_inventory.problems:
            reasons = "; ".join(
                problem.reason for problem in pull_request_inventory.problems
            )
            raise PolicyViolation(f"GitHub PR inventory is incomplete: {reasons}")
        branch_matches = tuple(
            item
            for item in pull_request_inventory.records
            if item.branch == receipt.branch
        )
        if len(branch_matches) > 1:
            raise PolicyViolation("duplicate open PRs exist for handback branch")
        pull_request = branch_matches[0] if branch_matches else None
        if pull_request is not None:
            if pull_request.base_branch != "main":
                raise PolicyViolation("existing PR does not target main")
            observed_paths = self.github.changed_paths(pull_request.number)
            if tuple(sorted(observed_paths)) != tuple(sorted(receipt.scope.paths)):
                raise PolicyViolation("existing PR paths differ from handback Scope")
        try:
            collision = self._scope_collision(
                receipt=receipt,
                registry=registry,
                pull_requests=pull_request_inventory.records,
            )
        except DeliverySourceError as error:
            raise PolicyViolation(f"collision inventory failed: {error}") from error
        decision = evaluate_publication(
            receipt=receipt,
            registry=registry,
            worktree=worktree,
            duplicate_pr=False,
            scope_collision=collision,
        )
        if not decision.allowed:
            raise PolicyViolation("; ".join(decision.reasons))
        return PublicationContext(
            registry=registry,
            worktree=worktree,
            pull_request=pull_request,
            remote_sha=self.git.remote_branch_sha(receipt.branch),
        )

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
from .pr_contract import parse_pull_request_body


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

    def _require_canonical_main(self) -> None:
        """Protect publication from running cleanup from the owner checkout."""

        checkout = self.git.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before publication"
            )
        if not checkout.clean:
            raise PolicyViolation("canonical checkout is dirty before publication")

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

    def _validate_existing_pull_request_scope(
        self,
        *,
        receipt: HandbackReceipt,
        registry: RegistrySnapshot,
        pull_request: PullRequestSnapshot,
        observed_paths: tuple[str, ...],
    ) -> None:
        """Allow only monotonic Scope growth across an owner reanchor.

        A reanchored claim can legitimately add a file before publishing the
        same durable PR.  The old PR must still be self-describing and its
        changed paths must exactly match its previous typed receipt; otherwise
        a same-branch PR could be used to smuggle arbitrary Scope drift.
        """

        try:
            previous = parse_pull_request_body(pull_request.body)
        except PolicyViolation as error:
            raise PolicyViolation(
                "existing PR body must contain a typed handback before Scope update"
            ) from error
        if (
            previous.lane_id != registry.lane_id
            or previous.owner_thread_id != receipt.owner_thread_id
            or previous.branch != receipt.branch
        ):
            raise PolicyViolation("existing PR handback owner or lane differs")
        if (
            previous.base_sha != pull_request.base_sha
            or previous.head_sha != pull_request.head_sha
        ):
            raise PolicyViolation("existing PR body differs from its exact PR tuple")

        previous_paths = set(previous.scope.paths)
        observed = set(observed_paths)
        if observed != previous_paths:
            raise PolicyViolation("existing PR paths differ from its typed handback Scope")

        current_paths = set(receipt.scope.paths)
        if receipt.claim_generation < previous.claim_generation:
            raise PolicyViolation("handback claim generation regressed from existing PR")
        if receipt.claim_generation == previous.claim_generation:
            if current_paths != previous_paths:
                raise PolicyViolation(
                    "existing PR Scope may only grow after an owner reanchor"
                )
            return
        if not previous_paths.issubset(current_paths):
            raise PolicyViolation(
                "owner reanchor cannot remove paths from an existing PR Scope"
            )

    def check(self, receipt: HandbackReceipt) -> PublicationContext:
        self._require_canonical_main()
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
            self._validate_existing_pull_request_scope(
                receipt=receipt,
                registry=registry,
                pull_request=pull_request,
                observed_paths=observed_paths,
            )
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

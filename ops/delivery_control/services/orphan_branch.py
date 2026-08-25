"""CAS cleanup for unregistered local branches whose commits already landed."""

from __future__ import annotations

import hashlib
import json
import re
from time import monotonic
from dataclasses import dataclass

from ..domain.branch_refs import BranchInventory
from ..domain.errors import DeliverySourceError, PolicyViolation
from ..domain.observations import (
    PhysicalWorktree,
    PullRequestInventory,
    RegistryInventory,
)
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort

_SHA_RE = re.compile(r"[0-9a-f]{40}")
PATCH_EQUIVALENCE_BATCH_TIMEOUT_SECONDS = 30.0
PATCH_EQUIVALENCE_SKIPPED_BLOCKER = (
    "orphan branch tip is not an ancestor of live origin/main; "
    "patch-equivalence not evaluated because other blockers exist"
)


@dataclass(frozen=True)
class OrphanBranchDiscardResult:
    """Evidence returned after one unregistered local branch is released."""

    schema: str
    disposition: str
    branch: str
    head_sha: str
    main_sha: str
    operator: str
    reason: str
    proof_digest: str
    local_branch_absent: bool
    remote_branch_absent: bool
    worktree_absent: bool


@dataclass(frozen=True)
class OrphanBranchPreflight:
    """Read-only evidence for one possible local-orphan discard."""

    schema: str
    branch: str
    expected_head_sha: str
    main_sha: str | None
    eligible: bool
    passed_checks: tuple[str, ...]
    blockers: tuple[str, ...]
    patch_equivalent_to_main: bool | None = None
    side: str = "local"


@dataclass(frozen=True)
class _OrphanPreflightSnapshot:
    """One consistent read snapshot shared by a branch-audit batch."""

    main_sha: str
    registry: RegistryInventory | None
    registry_error: str | None
    physical_worktrees: tuple[PhysicalWorktree, ...] | None
    physical_error: str | None
    branches: BranchInventory | None
    branch_error: str | None


class OrphanBranchDiscardService:
    """Release only a local orphan whose complete change is already in main.

    This path deliberately does not repair the registry or delete a remote
    branch. Any registry claim, PR history, physical binding, remote ref, or
    non-ancestor tip is routed to its owner/lifecycle instead.
    """

    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry = registry
        self.git_query = git_query
        self.git_command = git_command
        self.github = github

    def _canonical_main(self) -> str:
        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before orphan branch discard"
            )
        if not checkout.clean:
            raise PolicyViolation(
                "canonical checkout is dirty before orphan branch discard"
            )
        origin_sha = self.git_query.origin_main_sha()
        if checkout.head_sha != origin_sha:
            raise PolicyViolation(
                "canonical main is not equal to live origin/main before orphan branch discard"
            )
        return origin_sha

    def _assert_unregistered(self, branch: str) -> None:
        inventory = self.registry.list_records()
        if any(record.branch == branch for record in inventory.records):
            raise PolicyViolation(
                "branch has a registry claim; use the owner-preserving lifecycle"
            )
        if any(problem.identity == branch for problem in inventory.problems):
            raise PolicyViolation("registry has a source problem for the target branch")

    def _assert_no_pr_history(
        self, branch: str, *, inventory: PullRequestInventory | None = None
    ) -> None:
        inventory = inventory or self.github.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if any(not hasattr(item, "branch") for item in inventory.records):
            raise PolicyViolation("GitHub branch PR history inventory is malformed")
        if any(item.branch == branch for item in inventory.records):
            raise PolicyViolation("orphan branch has PR history")

    def _assert_no_physical_worktree(self, branch: str) -> None:
        if any(item.branch == branch for item in self.git_query.list_worktrees()):
            raise PolicyViolation("orphan branch still has a physical worktree")

    def _snapshot(self) -> _OrphanPreflightSnapshot:
        """Read stable evidence once before evaluating multiple orphan refs."""

        main_sha = self._canonical_main()
        try:
            registry = self.registry.list_records()
        except DeliverySourceError as error:
            registry = None
            registry_error = str(error)
        else:
            registry_error = None
        try:
            physical_worktrees = self.git_query.list_worktrees()
        except DeliverySourceError as error:
            physical_worktrees = None
            physical_error = str(error)
        else:
            physical_error = None
        try:
            branches = self.git_query.branch_inventory()
        except DeliverySourceError as error:
            branches = None
            branch_error = str(error)
        else:
            branch_error = None
        return _OrphanPreflightSnapshot(
            main_sha=main_sha,
            registry=registry,
            registry_error=registry_error,
            physical_worktrees=physical_worktrees,
            physical_error=physical_error,
            branches=branches,
            branch_error=branch_error,
        )

    @staticmethod
    def _assert_unregistered_snapshot(
        branch: str, snapshot: _OrphanPreflightSnapshot
    ) -> None:
        if snapshot.registry_error is not None:
            raise DeliverySourceError(snapshot.registry_error)
        assert snapshot.registry is not None
        if any(record.branch == branch for record in snapshot.registry.records):
            raise PolicyViolation(
                "branch has a registry claim; use the owner-preserving lifecycle"
            )
        if any(problem.identity == branch for problem in snapshot.registry.problems):
            raise PolicyViolation("registry has a source problem for the target branch")

    @staticmethod
    def _assert_no_physical_worktree_snapshot(
        branch: str, snapshot: _OrphanPreflightSnapshot
    ) -> None:
        if snapshot.physical_error is not None:
            raise DeliverySourceError(snapshot.physical_error)
        assert snapshot.physical_worktrees is not None
        if any(item.branch == branch for item in snapshot.physical_worktrees):
            raise PolicyViolation("orphan branch still has a physical worktree")

    def _preflight(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        pr_history: PullRequestInventory | None,
        snapshot: _OrphanPreflightSnapshot | None,
        patch_equivalence_deadline: float | None = None,
        remote_only: bool = False,
    ) -> OrphanBranchPreflight:
        blockers: list[str] = []
        passed: list[str] = []
        main_sha: str | None = None
        patch_equivalent_to_main: bool | None = None
        if not branch or branch == "main" or branch.startswith("-"):
            blockers.append("orphan discard requires a non-main branch")
        if _SHA_RE.fullmatch(expected_head_sha) is None:
            blockers.append("orphan discard requires an exact lowercase HEAD SHA")

        if not blockers:
            try:
                main_sha = (
                    snapshot.main_sha
                    if snapshot is not None
                    else self._canonical_main()
                )
            except DeliverySourceError as error:
                blockers.append(str(error))
            else:
                passed.append("canonical main equals live origin/main and is clean")

        if not blockers:
            try:
                if snapshot is None:
                    self._assert_unregistered(branch)
                else:
                    self._assert_unregistered_snapshot(branch, snapshot)
            except DeliverySourceError as error:
                blockers.append(str(error))
            else:
                passed.append("registry has no claim or source problem for branch")
            try:
                self._assert_no_pr_history(branch, inventory=pr_history)
            except DeliverySourceError as error:
                blockers.append(str(error))
            else:
                passed.append("branch has no GitHub PR history")
            try:
                if snapshot is None:
                    self._assert_no_physical_worktree(branch)
                else:
                    self._assert_no_physical_worktree_snapshot(branch, snapshot)
            except DeliverySourceError as error:
                blockers.append(str(error))
            else:
                passed.append("branch has no physical worktree")
            try:
                if snapshot is None:
                    local_sha = self.git_query.local_branch_sha(branch)
                elif snapshot.branch_error is not None:
                    raise DeliverySourceError(snapshot.branch_error)
                else:
                    assert snapshot.branches is not None
                    local_sha = snapshot.branches.local_by_name.get(branch)
            except DeliverySourceError as error:
                blockers.append(f"local branch HEAD query failed: {error}")
            else:
                if remote_only:
                    if local_sha is None:
                        passed.append("local branch ref is absent")
                    elif local_sha == expected_head_sha:
                        passed.append("paired local branch HEAD equals expected SHA")
                    else:
                        blockers.append(
                            "paired local branch changed or has an unexpected HEAD"
                        )
                elif local_sha != expected_head_sha:
                    blockers.append("local branch HEAD changed or is absent")
                else:
                    passed.append("local branch HEAD equals expected SHA")
            try:
                if snapshot is None:
                    remote_sha = self.git_query.remote_branch_sha(branch)
                elif snapshot.branch_error is not None:
                    raise DeliverySourceError(snapshot.branch_error)
                else:
                    assert snapshot.branches is not None
                    remote_sha = snapshot.branches.remote_by_name.get(branch)
            except DeliverySourceError as error:
                blockers.append(f"remote branch query failed: {error}")
            else:
                if remote_only:
                    if remote_sha != expected_head_sha:
                        blockers.append("remote orphan branch changed or is absent")
                    else:
                        passed.append("remote branch HEAD equals expected SHA")
                elif remote_sha is not None:
                    blockers.append("orphan branch still has a remote ref")
                else:
                    passed.append("remote branch ref is absent")
            if main_sha is not None:
                try:
                    ancestor = self.git_query.is_ancestor(expected_head_sha, main_sha)
                except DeliverySourceError as error:
                    blockers.append(f"ancestor query failed: {error}")
                else:
                    if not ancestor and blockers:
                        blockers.append(PATCH_EQUIVALENCE_SKIPPED_BLOCKER)
                    elif not ancestor:
                        checker = getattr(self.git_query, "is_patch_equivalent", None)
                        if not callable(checker):
                            blockers.append(
                                "orphan branch tip is not an ancestor of live origin/main"
                            )
                        elif (
                            patch_equivalence_deadline is not None
                            and monotonic() >= patch_equivalence_deadline
                        ):
                            blockers.append("patch-equivalence batch budget exhausted")
                        else:
                            try:
                                patch_equivalent_to_main = bool(
                                    checker(expected_head_sha, main_sha)
                                )
                            except DeliverySourceError as error:
                                blockers.append(
                                    f"patch-equivalence query failed: {error}"
                                )
                            else:
                                if patch_equivalent_to_main:
                                    passed.append(
                                        "local branch commits are patch-equivalent to live origin/main"
                                    )
                                else:
                                    blockers.append(
                                        "orphan branch tip is not an ancestor of live origin/main and is not patch-equivalent"
                                    )
                    else:
                        passed.append(
                            "local branch tip is an ancestor of live origin/main"
                        )

        return OrphanBranchPreflight(
            schema="kg.delivery.orphan-branch-preflight.v1",
            branch=branch,
            expected_head_sha=expected_head_sha,
            main_sha=main_sha,
            eligible=not blockers,
            passed_checks=tuple(passed),
            blockers=tuple(blockers),
            patch_equivalent_to_main=patch_equivalent_to_main,
            side="remote" if remote_only else "local",
        )

    def preflight(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        pr_history: PullRequestInventory | None = None,
    ) -> OrphanBranchPreflight:
        """Evaluate discard eligibility without changing Git or the registry."""
        return self._preflight(
            branch=branch,
            expected_head_sha=expected_head_sha,
            pr_history=pr_history,
            snapshot=None,
            patch_equivalence_deadline=None,
        )

    def preflight_many(
        self,
        *,
        branches: tuple[tuple[str, str], ...],
        pr_history: PullRequestInventory | None = None,
    ) -> dict[str, OrphanBranchPreflight]:
        """Preflight many orphan refs from one stable local/remote snapshot."""

        ordered = tuple(dict.fromkeys(branches))
        if not ordered:
            return {}
        snapshot = self._snapshot()
        patch_equivalence_deadline = (
            monotonic() + PATCH_EQUIVALENCE_BATCH_TIMEOUT_SECONDS
        )
        return {
            branch: self._preflight(
                branch=branch,
                expected_head_sha=expected_head_sha,
                pr_history=pr_history,
                snapshot=snapshot,
                patch_equivalence_deadline=patch_equivalence_deadline,
            )
            for branch, expected_head_sha in ordered
        }

    def preflight_remote(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        pr_history: PullRequestInventory | None = None,
    ) -> OrphanBranchPreflight:
        """Evaluate one remote orphan without changing any state.

        An exact paired local ref is accepted as part of the same CAS packet;
        the discard command removes both refs only after both remain exact.
        """

        return self._preflight(
            branch=branch,
            expected_head_sha=expected_head_sha,
            pr_history=pr_history,
            snapshot=None,
            patch_equivalence_deadline=None,
            remote_only=True,
        )

    def preflight_remote_many(
        self,
        *,
        branches: tuple[tuple[str, str], ...],
        pr_history: PullRequestInventory | None = None,
    ) -> dict[str, OrphanBranchPreflight]:
        """Preflight remote orphan refs from one stable snapshot."""

        ordered = tuple(dict.fromkeys(branches))
        if not ordered:
            return {}
        snapshot = self._snapshot()
        patch_equivalence_deadline = (
            monotonic() + PATCH_EQUIVALENCE_BATCH_TIMEOUT_SECONDS
        )
        return {
            branch: self._preflight(
                branch=branch,
                expected_head_sha=expected_head_sha,
                pr_history=pr_history,
                snapshot=snapshot,
                patch_equivalence_deadline=patch_equivalence_deadline,
                remote_only=True,
            )
            for branch, expected_head_sha in ordered
        }

    def discard(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> OrphanBranchDiscardResult:
        if not branch or branch == "main" or branch.startswith("-"):
            raise PolicyViolation("orphan discard requires a non-main branch")
        if _SHA_RE.fullmatch(expected_head_sha) is None:
            raise PolicyViolation("orphan discard requires an exact lowercase HEAD SHA")
        if not operator.strip() or not reason.strip():
            raise PolicyViolation(
                "orphan discard requires a non-empty operator and reason"
            )

        main_sha = self._canonical_main()
        self._assert_unregistered(branch)
        self._assert_no_pr_history(branch)
        self._assert_no_physical_worktree(branch)

        if self.git_query.local_branch_sha(branch) != expected_head_sha:
            raise PolicyViolation("local orphan branch changed or is absent")
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation(
                "orphan branch still has a remote ref; preserve remote lifecycle"
            )
        if not self.git_query.is_ancestor(expected_head_sha, main_sha):
            checker = getattr(self.git_query, "is_patch_equivalent", None)
            if not callable(checker) or not bool(checker(expected_head_sha, main_sha)):
                raise PolicyViolation(
                    "orphan branch tip is not an ancestor of live origin/main and is not patch-equivalent"
                )

        latest_main = self._canonical_main()
        if latest_main != main_sha:
            raise PolicyViolation("origin/main changed during orphan discard preflight")
        if self.git_query.local_branch_sha(branch) != expected_head_sha:
            raise PolicyViolation(
                "local orphan branch changed during discard preflight"
            )
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation("remote orphan ref appeared during discard preflight")
        self._assert_no_physical_worktree(branch)
        if not self.git_query.is_ancestor(expected_head_sha, latest_main):
            checker = getattr(self.git_query, "is_patch_equivalent", None)
            if not callable(checker) or not bool(
                checker(expected_head_sha, latest_main)
            ):
                raise PolicyViolation(
                    "orphan branch tip is not an ancestor of live origin/main and is not patch-equivalent"
                )

        self.git_command.delete_local_branch(
            branch,
            expected_head_sha=expected_head_sha,
        )
        if self.git_query.local_branch_sha(branch) is not None:
            raise PolicyViolation("local orphan branch remains after discard")
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation("remote orphan ref appeared after discard")
        self._assert_no_physical_worktree(branch)

        proof = {
            "branch": branch,
            "head_sha": expected_head_sha,
            "main_sha": main_sha,
            "operator": operator,
            "reason": reason,
            "schema": "kg.delivery.orphan-branch-proof.v1",
        }
        proof_digest = hashlib.sha256(
            json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return OrphanBranchDiscardResult(
            schema="kg.delivery.orphan-branch-proof.v1",
            disposition="orphan_local_discarded",
            branch=branch,
            head_sha=expected_head_sha,
            main_sha=main_sha,
            operator=operator,
            reason=reason,
            proof_digest=proof_digest,
            local_branch_absent=True,
            remote_branch_absent=True,
            worktree_absent=True,
        )

    def discard_remote(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> OrphanBranchDiscardResult:
        """CAS-delete one unregistered remote ref already represented in main.

        A local ref at the same exact SHA is treated as a paired asset. It is
        removed first through its own expected-HEAD CAS, then the remote ref is
        removed through its exact-HEAD CAS. A drifted or mismatched local ref
        remains fail-closed.
        """

        if not branch or branch == "main" or branch.startswith("-"):
            raise PolicyViolation("remote orphan discard requires a non-main branch")
        if _SHA_RE.fullmatch(expected_head_sha) is None:
            raise PolicyViolation(
                "remote orphan discard requires an exact lowercase HEAD SHA"
            )
        if not operator.strip() or not reason.strip():
            raise PolicyViolation(
                "remote orphan discard requires a non-empty operator and reason"
            )

        main_sha = self._canonical_main()
        self._assert_unregistered(branch)
        self._assert_no_pr_history(branch)
        self._assert_no_physical_worktree(branch)

        local_sha = self.git_query.local_branch_sha(branch)
        if local_sha is not None and local_sha != expected_head_sha:
            raise PolicyViolation(
                "paired local branch changed or has an unexpected HEAD"
            )
        if self.git_query.remote_branch_sha(branch) != expected_head_sha:
            raise PolicyViolation("remote orphan branch changed or is absent")
        if not self.git_query.is_ancestor(expected_head_sha, main_sha):
            checker = getattr(self.git_query, "is_patch_equivalent", None)
            if not callable(checker) or not bool(checker(expected_head_sha, main_sha)):
                raise PolicyViolation(
                    "remote orphan branch tip is not an ancestor of live origin/main and is not patch-equivalent"
                )

        latest_main = self._canonical_main()
        if latest_main != main_sha:
            raise PolicyViolation("origin/main changed during remote orphan discard")
        latest_local_sha = self.git_query.local_branch_sha(branch)
        if latest_local_sha is not None and latest_local_sha != expected_head_sha:
            raise PolicyViolation(
                "paired local branch changed during discard preflight"
            )
        if self.git_query.remote_branch_sha(branch) != expected_head_sha:
            raise PolicyViolation(
                "remote orphan branch changed during discard preflight"
            )
        self._assert_no_physical_worktree(branch)
        if not self.git_query.is_ancestor(expected_head_sha, latest_main):
            checker = getattr(self.git_query, "is_patch_equivalent", None)
            if not callable(checker) or not bool(
                checker(expected_head_sha, latest_main)
            ):
                raise PolicyViolation(
                    "remote orphan branch tip is not an ancestor of live origin/main and is not patch-equivalent"
                )

        if latest_local_sha == expected_head_sha:
            self.git_command.delete_local_branch(
                branch,
                expected_head_sha=expected_head_sha,
            )
            if self.git_query.local_branch_sha(branch) is not None:
                raise PolicyViolation("paired local orphan ref remains after discard")

        self.git_command.delete_remote_branch(
            branch,
            expected_head_sha=expected_head_sha,
        )
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation("remote orphan ref remains after discard")
        if self.git_query.local_branch_sha(branch) is not None:
            raise PolicyViolation("remote orphan local ref appeared after discard")
        self._assert_no_physical_worktree(branch)

        proof = {
            "branch": branch,
            "head_sha": expected_head_sha,
            "main_sha": main_sha,
            "operator": operator,
            "reason": reason,
            "schema": "kg.delivery.orphan-remote-branch-proof.v1",
        }
        proof_digest = hashlib.sha256(
            json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return OrphanBranchDiscardResult(
            schema="kg.delivery.orphan-remote-branch-proof.v1",
            disposition="orphan_remote_discarded",
            branch=branch,
            head_sha=expected_head_sha,
            main_sha=main_sha,
            operator=operator,
            reason=reason,
            proof_digest=proof_digest,
            local_branch_absent=True,
            remote_branch_absent=True,
            worktree_absent=True,
        )


__all__ = [
    "OrphanBranchDiscardResult",
    "OrphanBranchDiscardService",
    "OrphanBranchPreflight",
]

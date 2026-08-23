"""Explicit discard lifecycle for clean abandoned handback branches."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import PolicyViolation
from ..domain.observations import RegistrySnapshot
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryDiscardCommandPort, RegistryTerminalQueryPort


@dataclass(frozen=True)
class DiscardResult:
    disposition: str
    branch: str
    head_sha: str
    worktree_absent: bool
    local_branch_absent: bool
    remote_branch_absent: bool


class AbandonedHandbackDiscardService:
    """Discard one ownerless clean handback only after exact CAS preflight.

    This is intentionally narrower than owner recovery.  A handback with an
    owner, a PR history, a dirty worktree, or a ref drift remains preserved.
    """

    def __init__(
        self,
        *,
        registry_query: RegistryTerminalQueryPort,
        registry_command: RegistryDiscardCommandPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry_query = registry_query
        self.registry_command = registry_command
        self.git_query = git_query
        self.git_command = git_command
        self.github = github

    def _require_canonical_main(self) -> None:
        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before abandoned-handback discard"
            )
        if not checkout.clean:
            raise PolicyViolation(
                "canonical checkout is dirty before abandoned-handback discard"
            )

    def _record(self, branch: str) -> RegistrySnapshot:
        record = self.registry_query.find_terminal_claim(branch=branch)
        if record is None or record.status != "abandoned":
            raise PolicyViolation("branch has no exact abandoned registry claim")
        if record.owner_thread_id is not None:
            raise PolicyViolation(
                "abandoned handback still has an owner; recover the owner instead"
            )
        if not record.handback_valid or record.handed_back_sha is None:
            raise PolicyViolation(
                "abandoned branch has no valid typed handback to discard"
            )
        return record

    def _assert_no_physical_assets(self, record: RegistrySnapshot) -> None:
        matches = tuple(
            item
            for item in self.git_query.list_worktrees()
            if item.branch == record.branch
            or item.path.resolve() == record.path.resolve()
        )
        if matches:
            raise PolicyViolation(
                "abandoned handback still has a physical worktree; preserve it"
            )

    def _assert_no_pr_history(self, branch: str) -> None:
        inventory = self.github.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if inventory.records:
            raise PolicyViolation("abandoned handback has PR history")

    def _assert_ref(self, branch: str, expected_head_sha: str) -> None:
        for label, observed in (
            ("local", self.git_query.local_branch_sha(branch)),
            ("remote", self.git_query.remote_branch_sha(branch)),
        ):
            if observed is not None and observed != expected_head_sha:
                raise PolicyViolation(
                    f"{label} branch changed before abandoned-handback discard"
                )

    def discard(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> DiscardResult:
        self._require_canonical_main()
        if not operator.strip() or not reason.strip():
            raise PolicyViolation("discard requires a non-empty operator and reason")
        record = self._record(branch)
        if record.handed_back_sha != expected_head_sha:
            raise PolicyViolation("discard HEAD does not match the stored handback")
        self._assert_no_pr_history(branch)
        self._assert_no_physical_assets(record)
        self._assert_ref(branch, expected_head_sha)

        self.registry_command.discard(
            lane_id=record.lane_id,
            expected_claim_generation=record.claim_generation,
            expected_branch=record.branch,
            expected_path=str(record.path),
            expected_head_sha=expected_head_sha,
            operator=operator,
            reason=reason,
        )

        local_sha = self.git_query.local_branch_sha(branch)
        if local_sha is not None:
            self.git_command.delete_local_branch(
                branch, expected_head_sha=expected_head_sha
            )
        remote_sha = self.git_query.remote_branch_sha(branch)
        if remote_sha is not None:
            if remote_sha != expected_head_sha:
                raise PolicyViolation(
                    "remote branch changed after discard proof was recorded"
                )
            self.git_command.delete_remote_branch(
                branch, expected_head_sha=expected_head_sha
            )

        self._assert_no_physical_assets(record)
        if self.git_query.local_branch_sha(branch) is not None:
            raise PolicyViolation(
                "local branch remains after abandoned-handback discard"
            )
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation(
                "remote branch remains after abandoned-handback discard"
            )
        return DiscardResult(
            disposition="abandoned_handback_discarded",
            branch=branch,
            head_sha=expected_head_sha,
            worktree_absent=True,
            local_branch_absent=True,
            remote_branch_absent=True,
        )


__all__ = ["AbandonedHandbackDiscardService", "DiscardResult"]

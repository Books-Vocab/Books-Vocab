"""CAS cleanup for terminal lanes created before the typed PR receipt contract."""

from __future__ import annotations

from ..domain.errors import PolicyViolation
from ..domain.observations import (
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from ..ports.registry import RegistryTerminalQueryPort
from .abandon import AbandonResult
from .cleanup import CleanupResult
from .pr_contract import pull_request_holds

_TERMINAL = {"merged", "abandoned"}


class LegacyTerminalCleanupService:
    """Release only provable legacy assets; never repairs their registry records."""

    def __init__(
        self,
        *,
        registry: RegistryTerminalQueryPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github_query: GitHubQueryPort,
        github_command: GitHubCommandPort,
    ) -> None:
        self.registry = registry
        self.git_query = git_query
        self.git_command = git_command
        self.github_query = github_query
        self.github_command = github_command

    def _require_canonical_main(self) -> None:
        """Protect legacy asset deletion from the checkout running the command."""

        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before legacy cleanup"
            )
        if not checkout.clean:
            raise PolicyViolation("canonical checkout is dirty before legacy cleanup")

    def cleanup_merged_pr(self, pull_request_number: int) -> CleanupResult:
        self._require_canonical_main()
        pull_request = self._single_branch_pr(pull_request_number)
        record = self._record(pull_request.branch, expected_status="merged")
        self._validate_pr(pull_request, record, expected_state="MERGED")
        physical = self._validate_assets(pull_request, record)

        if physical is not None:
            self.git_command.remove_worktree(
                physical.path, expected_head_sha=pull_request.head_sha
            )
        if self.git_query.local_branch_sha(pull_request.branch) is not None:
            self.git_command.delete_local_branch(
                pull_request.branch, expected_head_sha=pull_request.head_sha
            )
        if self.git_query.remote_branch_sha(pull_request.branch) is not None:
            self._recheck_merged(pull_request_number, record)
            self.git_command.delete_remote_branch(
                pull_request.branch, expected_head_sha=pull_request.head_sha
            )
        return self._result("merged", pull_request.branch)

    def abandon_open_pr(self, pull_request_number: int) -> AbandonResult:
        pull_request = self._single_open_pr(pull_request_number)
        record = self._record(pull_request.branch, expected_status="abandoned")
        self._validate_pr(pull_request, record, expected_state="OPEN")
        if pull_request_holds(pull_request):
            raise PolicyViolation("legacy PR carries an explicit hard hold")
        if pull_request.auto_merge_enabled or not pull_request.node_id:
            raise PolicyViolation("legacy PR is not safe to abandon")
        if self.github_query.merge_queue_entry_snapshot(pull_request.node_id) is not None:
            raise PolicyViolation("legacy PR is already scheduled in the merge queue")
        self._validate_assets_absent(pull_request, record)

        closed = self.github_command.close_pull_request(
            number=pull_request.number,
            expected_base_sha=pull_request.base_sha,
            expected_head_sha=pull_request.head_sha,
            expected_body=pull_request.body,
        )
        self._validate_pr(closed, record, expected_state="CLOSED")
        if self.git_query.remote_branch_sha(closed.branch) is not None:
            self.git_command.delete_remote_branch(
                closed.branch, expected_head_sha=closed.head_sha
            )
        final = self.github_query.get_pull_request(pull_request_number)
        inventory = self.github_query.list_pull_requests_for_branch(final.branch)
        if inventory.problems or any(item.state == "OPEN" for item in inventory.records):
            raise PolicyViolation("legacy abandoned branch still has an open PR")
        final_record = self._record(final.branch, expected_status="abandoned")
        self._validate_pr(final, final_record, expected_state="CLOSED")
        if self.git_query.remote_branch_sha(final.branch) is not None:
            raise PolicyViolation("legacy abandoned PR remote branch remains")
        return AbandonResult(
            pull_request_number=final.number,
            pull_request_state=final.state,
            registry_status=final_record.status,
            remote_branch_absent=True,
        )

    def cleanup_abandoned_branch(self, branch: str) -> CleanupResult:
        self._require_canonical_main()
        record = self._record(branch, expected_status="abandoned")
        if record.handed_back_sha is not None:
            raise PolicyViolation("abandoned branch has a hand-back but no PR proof")
        inventory = self.github_query.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if inventory.records:
            raise PolicyViolation("abandoned branch has PR history")
        physical = self._physical_for_branch(branch, record)
        if physical is not None:
            raise PolicyViolation("abandoned branch still has a physical worktree")
        self._validate_ref(branch, record.base_sha, "local")
        self._validate_ref(branch, record.base_sha, "remote")
        if self.git_query.local_branch_sha(branch) is not None:
            self.git_command.delete_local_branch(branch, expected_head_sha=record.base_sha)
        if self.git_query.remote_branch_sha(branch) is not None:
            self.git_command.delete_remote_branch(branch, expected_head_sha=record.base_sha)
        return self._result("abandoned", branch)

    def _single_branch_pr(self, pull_request_number: int) -> PullRequestSnapshot:
        pull_request = self.github_query.get_pull_request(pull_request_number)
        inventory = self.github_query.list_pull_requests_for_branch(pull_request.branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if len(inventory.records) != 1 or inventory.records[0].number != pull_request_number:
            raise PolicyViolation("branch does not map to one unique PR")
        return pull_request

    def _single_open_pr(self, pull_request_number: int) -> PullRequestSnapshot:
        pull_request = self.github_query.get_pull_request(pull_request_number)
        inventory = self.github_query.list_pull_requests_for_branch(pull_request.branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        open_records = tuple(item for item in inventory.records if item.state == "OPEN")
        if len(open_records) != 1 or open_records[0].number != pull_request_number:
            raise PolicyViolation("branch does not map to one unique open PR")
        return pull_request

    def _record(self, branch: str, *, expected_status: str) -> RegistrySnapshot:
        record = self.registry.find_terminal_claim(branch=branch)
        if record is None or record.status != expected_status:
            raise PolicyViolation("branch has no exact terminal registry claim")
        return record

    def _validate_pr(
        self,
        pull_request: PullRequestSnapshot,
        record: RegistrySnapshot,
        *,
        expected_state: str,
    ) -> None:
        if (
            pull_request.state != expected_state
            or pull_request.base_branch != "main"
            or pull_request.branch != record.branch
            or pull_request.base_sha != record.base_sha
            or pull_request.head_sha != record.handed_back_sha
            or expected_state == "MERGED" and pull_request.merged_at is None
            or tuple(sorted(self.github_query.changed_paths(pull_request.number)))
            != tuple(sorted(record.scope.paths))
        ):
            raise PolicyViolation("legacy PR differs from the exact terminal registry claim")

    def _validate_assets(
        self, pull_request: PullRequestSnapshot, record: RegistrySnapshot
    ) -> PhysicalWorktree | None:
        physical = self._physical_for_branch(pull_request.branch, record)
        self._validate_ref(pull_request.branch, pull_request.head_sha, "local")
        self._validate_ref(pull_request.branch, pull_request.head_sha, "remote")
        return physical

    def _validate_assets_absent(
        self, pull_request: PullRequestSnapshot, record: RegistrySnapshot
    ) -> None:
        physical = self._physical_for_branch(pull_request.branch, record)
        if physical is not None or self.git_query.local_branch_sha(pull_request.branch) is not None:
            raise PolicyViolation("legacy PR requires local assets to be absent")
        self._validate_ref(pull_request.branch, pull_request.head_sha, "remote")

    def _physical_for_branch(
        self, branch: str, record: RegistrySnapshot
    ) -> PhysicalWorktree | None:
        matches = tuple(
            item
            for item in self.git_query.list_worktrees()
            if item.branch == branch or item.path.resolve() == record.path.resolve()
        )
        if len(matches) > 1:
            raise PolicyViolation("terminal worktree binding is not unique")
        if not matches:
            return None
        physical = matches[0]
        if physical.branch != branch or physical.path.resolve() != record.path.resolve():
            raise PolicyViolation("terminal worktree path or branch drifted")
        snapshot = self.git_query.inspect_worktree(physical.path, record.base_sha)
        if (
            not snapshot.clean
            or snapshot.branch != branch
            or snapshot.head_sha != record.handed_back_sha
            or tuple(sorted(snapshot.changed_paths)) != tuple(sorted(record.scope.paths))
        ):
            raise PolicyViolation("terminal worktree is dirty or differs from the exact claim")
        return physical

    def _validate_ref(self, branch: str, expected: str, kind: str) -> None:
        actual = (
            self.git_query.local_branch_sha(branch)
            if kind == "local"
            else self.git_query.remote_branch_sha(branch)
        )
        if actual is not None and actual != expected:
            raise PolicyViolation(f"legacy {kind} branch differs from the exact terminal HEAD")

    def _recheck_merged(self, pull_request_number: int, record: RegistrySnapshot) -> None:
        current = self._single_branch_pr(pull_request_number)
        self._validate_pr(current, record, expected_state="MERGED")

    def _result(self, disposition: str, branch: str) -> CleanupResult:
        return CleanupResult(
            disposition=disposition,
            worktree_absent=not any(
                item.branch == branch for item in self.git_query.list_worktrees()
            ),
            local_branch_absent=self.git_query.local_branch_sha(branch) is None,
            remote_branch_absent=self.git_query.remote_branch_sha(branch) is None,
        )


__all__ = ["LegacyTerminalCleanupService"]

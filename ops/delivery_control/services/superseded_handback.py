"""Close an owner-bound handback whose exact content already merged elsewhere."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import PolicyViolation
from ..domain.observations import RegistrySnapshot
from ..domain.superseded_handback import (
    SUPERSEDED_PROOF_DISPOSITION,
    superseded_proof_with_digest,
)
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort, RegistrySupersedeCommandPort


@dataclass(frozen=True)
class SupersedeResult:
    schema: str
    disposition: str
    branch: str
    handback_head_sha: str
    merged_pr_number: int
    merged_pr_head_sha: str
    proof_digest: str | None
    worktree_absent: bool
    local_branch_absent: bool
    remote_branch_absent: bool


class SupersededHandbackService:
    """Terminalize only a redundant handback with exact merged-PR evidence.

    The current handback and the historical merged PR are kept as separate
    SHAs.  The proof records their independent bases, Scope, and normalized
    patch fingerprint before either ref is deleted.
    """

    def __init__(
        self,
        *,
        registry_query: RegistryQueryPort,
        registry_command: RegistrySupersedeCommandPort,
        git_query: GitQueryPort,
        git_command: GitCommandPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry_query = registry_query
        self.registry_command = registry_command
        self.git_query = git_query
        self.git_command = git_command
        self.github = github

    def _canonical_main(self) -> str:
        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before superseded-handback cleanup"
            )
        if not checkout.clean:
            raise PolicyViolation(
                "canonical checkout is dirty before superseded-handback cleanup"
            )
        origin_sha = self.git_query.origin_main_sha()
        if checkout.head_sha != origin_sha:
            raise PolicyViolation(
                "canonical main is not equal to live origin/main before superseded-handback cleanup"
            )
        return origin_sha

    def _record(self, branch: str, expected_head_sha: str) -> RegistrySnapshot:
        record = self.registry_query.find_terminal_claim(branch=branch)
        if record is None or record.status != "abandoned":
            raise PolicyViolation("branch has no exact abandoned registry claim")
        if not record.handback_valid or record.handed_back_sha is None:
            raise PolicyViolation("abandoned branch has no valid typed handback")
        if record.handed_back_sha != expected_head_sha:
            raise PolicyViolation(
                "superseded handback HEAD does not match the stored handback"
            )
        return record

    def _assert_no_worktree(self, record: RegistrySnapshot) -> None:
        if any(
            item.branch == record.branch or item.path.resolve() == record.path.resolve()
            for item in self.git_query.list_worktrees()
        ):
            raise PolicyViolation(
                "superseded handback still has a physical worktree; preserve it"
            )

    def _merged_pr(self, branch: str):
        inventory = self.github.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if len(inventory.records) != 1:
            raise PolicyViolation(
                "superseded handback requires exactly one historical PR"
            )
        pull_request = inventory.records[0]
        if (
            pull_request.state != "MERGED"
            or pull_request.base_branch != "main"
            or pull_request.branch != branch
        ):
            raise PolicyViolation(
                "superseded handback requires one merged PR targeting main"
            )
        return pull_request

    def _diff_fingerprint(self, base_sha: str, head_sha: str) -> str:
        fingerprint = getattr(self.git_query, "diff_fingerprint", None)
        if not callable(fingerprint):
            raise PolicyViolation("exact content fingerprint capability is unavailable")
        return fingerprint(base_sha, head_sha)

    def supersede(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        operator: str,
        reason: str,
    ) -> SupersedeResult:
        if not operator.strip() or not reason.strip():
            raise PolicyViolation("supersede requires a non-empty operator and reason")
        self._canonical_main()
        record = self._record(branch, expected_head_sha)
        self._assert_no_worktree(record)
        pull_request = self._merged_pr(branch)
        if self.github.branch_is_protected(branch):
            raise PolicyViolation("superseded handback branch is protected")
        changed_paths = tuple(sorted(self.github.changed_paths(pull_request.number)))
        scope_paths = tuple(sorted(record.scope.paths))
        if changed_paths != scope_paths:
            raise PolicyViolation(
                "merged PR Scope does not match the abandoned handback Scope"
            )
        remote_sha = self.git_query.remote_branch_sha(branch)
        if remote_sha is not None and remote_sha != pull_request.head_sha:
            raise PolicyViolation(
                "remote branch does not equal the exact merged PR HEAD"
            )
        local_sha = self.git_query.local_branch_sha(branch)
        if local_sha is not None and local_sha != expected_head_sha:
            raise PolicyViolation(
                "local branch does not equal the exact abandoned handback HEAD"
            )
        current_fingerprint = self._diff_fingerprint(record.base_sha, expected_head_sha)
        merged_fingerprint = self._diff_fingerprint(
            pull_request.base_sha, pull_request.head_sha
        )
        if current_fingerprint != merged_fingerprint:
            raise PolicyViolation(
                "current handback and merged PR content fingerprint differs"
            )
        proof_body = {
            "schema": "kg.worktree.superseded-handback-proof.v1",
            "disposition": SUPERSEDED_PROOF_DISPOSITION,
            "lane_id": record.lane_id,
            "branch": branch,
            "handback_sha": expected_head_sha,
            "claim_generation": record.claim_generation,
            "base_sha": record.base_sha,
            "handback_digest": record.handback_digest,
            "merged_pr_number": pull_request.number,
            "merged_pr_state": pull_request.state,
            "merged_pr_base_branch": pull_request.base_branch,
            "merged_pr_branch": pull_request.branch,
            "merged_pr_head_sha": pull_request.head_sha,
            "merged_pr_base_sha": pull_request.base_sha,
            "patch_fingerprint": current_fingerprint,
            "scope_paths": list(scope_paths),
            "operator": operator,
            "reason": reason,
        }
        self.registry_command.supersede(
            lane_id=record.lane_id,
            expected_claim_generation=record.claim_generation,
            expected_branch=record.branch,
            expected_path=str(record.path),
            expected_head_sha=expected_head_sha,
            proof_body=proof_body,
        )
        local_sha = self.git_query.local_branch_sha(branch)
        if local_sha is not None:
            if local_sha != expected_head_sha:
                raise PolicyViolation(
                    "local branch changed after superseded proof was recorded"
                )
            self.git_command.delete_local_branch(
                branch, expected_head_sha=expected_head_sha
            )
        remote_sha = self.git_query.remote_branch_sha(branch)
        if remote_sha is not None:
            if remote_sha != pull_request.head_sha:
                raise PolicyViolation(
                    "remote branch changed after superseded proof was recorded"
                )
            self.git_command.delete_remote_branch(
                branch, expected_head_sha=pull_request.head_sha
            )
        self._assert_no_worktree(record)
        if self.git_query.local_branch_sha(branch) is not None:
            raise PolicyViolation("local branch remains after superseded cleanup")
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation("remote branch remains after superseded cleanup")
        proof_digest = superseded_proof_with_digest(proof_body)["digest"]
        return SupersedeResult(
            schema="kg.delivery.superseded-handback.v1",
            disposition=SUPERSEDED_PROOF_DISPOSITION,
            branch=branch,
            handback_head_sha=expected_head_sha,
            merged_pr_number=pull_request.number,
            merged_pr_head_sha=pull_request.head_sha,
            proof_digest=proof_digest,
            worktree_absent=True,
            local_branch_absent=True,
            remote_branch_absent=True,
        )


__all__ = ["SupersedeResult", "SupersededHandbackService"]

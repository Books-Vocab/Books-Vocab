"""CAS cleanup for unregistered local branches whose commits already landed."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from ..domain.errors import PolicyViolation
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort

_SHA_RE = re.compile(r"[0-9a-f]{40}")


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

    def _assert_no_pr_history(self, branch: str) -> None:
        inventory = self.github.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise PolicyViolation("GitHub branch PR inventory is incomplete")
        if inventory.records:
            raise PolicyViolation("orphan branch has PR history")

    def _assert_no_physical_worktree(self, branch: str) -> None:
        if any(item.branch == branch for item in self.git_query.list_worktrees()):
            raise PolicyViolation("orphan branch still has a physical worktree")

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
            raise PolicyViolation(
                "orphan branch tip is not an ancestor of live origin/main"
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


__all__ = ["OrphanBranchDiscardResult", "OrphanBranchDiscardService"]

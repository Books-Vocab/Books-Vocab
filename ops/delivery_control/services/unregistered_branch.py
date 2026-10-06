"""Explicit CAS disposition for an unregistered, unlanded local branch."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from ..domain.branch_content import BranchContentEvidence
from ..domain.errors import DeliverySourceError, PolicyViolation
from ..ports.git import BranchContentQueryPort, GitCommandPort, GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from .branch_content import BranchContentService

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class UnregisteredBranchPreflight:
    """Exact evidence for an explicit local-only branch disposition."""

    schema: str
    branch: str
    expected_head_sha: str
    main_sha: str | None
    content: BranchContentEvidence
    eligible: bool
    passed_checks: tuple[str, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class UnregisteredBranchDiscardResult:
    """Proof returned after deleting one exact local-only branch ref."""

    schema: str
    disposition: str
    branch: str
    head_sha: str
    main_sha: str
    content_fingerprint: str
    operator: str
    reason: str
    unmerged_content_confirmed: bool
    proof_digest: str
    local_branch_absent: bool
    remote_branch_absent: bool
    worktree_absent: bool


class UnregisteredBranchDiscardService:
    """Require explicit loss confirmation for unlanded local-only commits.

    This is deliberately separate from ``discard-orphan-branch``.  The latter
    can discard only a branch already contained in ``origin/main``; this path
    exists solely so an operator can make a visible, exact decision about an
    unmerged branch after its content packet has been reviewed.
    """

    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        git_query: GitQueryPort,
        git_content: BranchContentQueryPort,
        git_command: GitCommandPort,
        github: GitHubQueryPort,
    ) -> None:
        self.registry = registry
        self.git_query = git_query
        self.content = BranchContentService(git=git_content)
        self.git_command = git_command
        self.github = github

    def _main(self) -> str:
        checkout = self.git_query.canonical_checkout()
        if checkout.branch != "main":
            raise PolicyViolation(
                "canonical checkout must be on main before local branch discard"
            )
        if not checkout.clean:
            raise PolicyViolation(
                "canonical checkout is dirty before local branch discard"
            )
        origin = self.git_query.origin_main_sha()
        if checkout.head_sha != origin:
            raise PolicyViolation(
                "canonical main is not equal to live origin/main before local branch discard"
            )
        return origin

    def preflight(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        allow_unmerged: bool = False,
    ) -> UnregisteredBranchPreflight:
        blockers: list[str] = []
        passed: list[str] = []
        main_sha: str | None = None
        if not branch or branch == "main" or branch.startswith("-"):
            blockers.append("local branch discard requires a non-main branch")
        if _SHA_RE.fullmatch(expected_head_sha) is None:
            blockers.append("local branch discard requires an exact lowercase HEAD SHA")

        if not blockers:
            try:
                main_sha = self._main()
            except DeliverySourceError as error:
                blockers.append(str(error))
            else:
                passed.append("canonical main equals live origin/main and is clean")

        content = self.content.inspect(
            branch=branch,
            base_sha=main_sha or "0" * 40,
        )
        if content.complete and content.head_sha != expected_head_sha:
            blockers.append("local branch HEAD differs from expected content HEAD")
        elif content.complete:
            passed.append("branch content HEAD equals expected SHA")
        else:
            blockers.append(f"branch content inspection incomplete: {content.error}")

        try:
            registry = self.registry.list_records()
        except DeliverySourceError as error:
            blockers.append(f"registry inventory query failed: {error}")
        else:
            relevant_problems = tuple(
                problem
                for problem in registry.problems
                if problem.identity_kind != "branch" or problem.identity == branch
            )
            if relevant_problems:
                blockers.append("registry inventory has source problems")
            elif any(record.branch == branch for record in registry.records):
                blockers.append("branch has a registry claim; use the owner lifecycle")
            else:
                passed.append("branch has no registry claim or source problem")

        try:
            prs = self.github.list_pull_requests_for_branch(branch)
        except DeliverySourceError as error:
            blockers.append(f"GitHub branch PR inventory query failed: {error}")
        else:
            if prs.problems:
                blockers.append("GitHub branch PR inventory is incomplete")
            elif prs.records:
                blockers.append("branch has PR history; preserve durable evidence")
            else:
                passed.append("branch has no GitHub PR history")

        try:
            physical = self.git_query.list_worktrees()
        except DeliverySourceError as error:
            blockers.append(f"physical worktree inventory query failed: {error}")
        else:
            if any(
                item.branch == branch or item.head_sha == expected_head_sha
                for item in physical
            ):
                blockers.append("branch HEAD is still bound to a physical worktree")
            else:
                passed.append("branch has no physical worktree")

        try:
            local_sha = self.git_query.local_branch_sha(branch)
        except DeliverySourceError as error:
            blockers.append(f"local branch query failed: {error}")
        else:
            if local_sha != expected_head_sha:
                blockers.append("local branch HEAD changed or is absent")
            else:
                passed.append("local branch HEAD equals expected SHA")

        try:
            remote_sha = self.git_query.remote_branch_sha(branch)
        except DeliverySourceError as error:
            blockers.append(f"remote branch query failed: {error}")
        else:
            if remote_sha is not None:
                blockers.append("branch still has a remote ref")
            else:
                passed.append("remote branch ref is absent")

        if content.complete and content.base_is_ancestor is True:
            blockers.append(
                "branch tip is already contained in live main; use discard-orphan-branch"
            )
        elif content.complete and not allow_unmerged:
            blockers.append(
                "unmerged local branch requires explicit discard confirmation"
            )
        elif content.complete and allow_unmerged:
            passed.append("operator explicitly confirmed unmerged content discard")

        return UnregisteredBranchPreflight(
            schema="kg.delivery.unregistered-branch-preflight.v1",
            branch=branch,
            expected_head_sha=expected_head_sha,
            main_sha=main_sha,
            content=content,
            eligible=not blockers,
            passed_checks=tuple(passed),
            blockers=tuple(blockers),
        )

    def discard(
        self,
        *,
        branch: str,
        expected_head_sha: str,
        expected_content_fingerprint: str,
        operator: str,
        reason: str,
        confirm_unmerged: bool,
    ) -> UnregisteredBranchDiscardResult:
        if not operator.strip() or not reason.strip():
            raise PolicyViolation("local branch discard requires operator and reason")
        if not confirm_unmerged:
            raise PolicyViolation(
                "unmerged local branch discard requires explicit confirmation"
            )
        first = self.preflight(
            branch=branch,
            expected_head_sha=expected_head_sha,
            allow_unmerged=True,
        )
        if not first.eligible or first.main_sha is None:
            raise PolicyViolation("; ".join(first.blockers))
        if first.content.change_fingerprint != expected_content_fingerprint:
            raise PolicyViolation("branch content fingerprint changed after review")
        if not first.content.unlanded:
            raise PolicyViolation(
                "branch content is not an unlanded change; use the matching lifecycle"
            )

        second = self.preflight(
            branch=branch,
            expected_head_sha=expected_head_sha,
            allow_unmerged=True,
        )
        if (
            not second.eligible
            or second.main_sha != first.main_sha
            or second.content.change_fingerprint != expected_content_fingerprint
        ):
            raise PolicyViolation("local branch changed during discard preflight")
        self.git_command.delete_local_branch(
            branch,
            expected_head_sha=expected_head_sha,
        )
        if self.git_query.local_branch_sha(branch) is not None:
            raise PolicyViolation("local branch remains after discard")
        if self.git_query.remote_branch_sha(branch) is not None:
            raise PolicyViolation("remote branch appeared after discard")
        if any(
            item.branch == branch or item.head_sha == expected_head_sha
            for item in self.git_query.list_worktrees()
        ):
            raise PolicyViolation("physical worktree appeared after discard")
        proof = {
            "branch": branch,
            "head_sha": expected_head_sha,
            "main_sha": first.main_sha,
            "content_fingerprint": expected_content_fingerprint,
            "operator": operator,
            "reason": reason,
            "unmerged_content_confirmed": True,
            "schema": "kg.delivery.unregistered-local-branch-proof.v1",
        }
        return UnregisteredBranchDiscardResult(
            schema="kg.delivery.unregistered-local-branch-proof.v1",
            disposition="unregistered_local_branch_discarded",
            branch=branch,
            head_sha=expected_head_sha,
            main_sha=first.main_sha,
            content_fingerprint=expected_content_fingerprint,
            operator=operator,
            reason=reason,
            unmerged_content_confirmed=True,
            proof_digest=hashlib.sha256(
                json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            local_branch_absent=True,
            remote_branch_absent=True,
            worktree_absent=True,
        )


__all__ = [
    "UnregisteredBranchDiscardResult",
    "UnregisteredBranchDiscardService",
    "UnregisteredBranchPreflight",
]

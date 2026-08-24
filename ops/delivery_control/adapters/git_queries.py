"""Read-only Git queries built on the argv client and pure parsers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path

from ..domain.branch_content import (
    BRANCH_CONTENT_PATH_LIMIT,
    BranchContentEvidence,
)
from ..domain.branch_refs import BranchInventory
from ..domain.errors import InvalidReceipt
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    MainLandingSnapshot,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from ..domain.unreachable_commits import (
    UNREACHABLE_COMMIT_PATH_LIMIT,
    UNREACHABLE_COMMIT_SAMPLE_SIZE,
    UnreachableCommitEvidence,
    UnreachableCommitInventory,
)
from .errors import AdapterCommandError, AdapterPayloadError
from .git_client import GitCliClient
from .git_parsing import (
    parse_branch_inventory,
    parse_changed_files,
    parse_commit_summaries,
    parse_first_parent_landings,
    parse_local_branch_sha,
    parse_origin_main_sha,
    parse_parent_sha,
    parse_remote_branch_sha,
    parse_unreachable_commit_shas,
    parse_worktrees,
)

UNREACHABLE_COMMIT_SCAN_TIMEOUT_SECONDS = 30.0
BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT = 20
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _normalized_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    return detail or error.__class__.__name__


def _incomplete_unreachable_commit_evidence(
    *, commit_sha: str, error: str
) -> UnreachableCommitEvidence:
    return UnreachableCommitEvidence(
        schema="kg.delivery.unreachable-commit.v1",
        commit_sha=commit_sha,
        parent_shas=(),
        subject=None,
        unreachable=True,
        changed_paths=(),
        changed_path_count=0,
        changed_paths_truncated=False,
        change_fingerprint=None,
        disposition="preserve_with_source_problem",
        source_problem_scope="git_objects",
        next_step="repair bounded object metadata before any owner or cleanup decision",
        complete=False,
        error=error,
    )


class GitQueries:
    def __init__(self, *, client: GitCliClient) -> None:
        self.client = client
        self.repo = client.repo

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            path=self.repo,
            branch=self.client.run("branch", "--show-current") or None,
            head_sha=self.client.run("rev-parse", "--verify", "HEAD^{commit}"),
            clean=not bool(
                self.client.run("status", "--porcelain=v1", "--untracked-files=all")
            ),
        )

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        records = parse_worktrees(self.client.run("worktree", "list", "--porcelain"))
        return tuple(
            PhysicalWorktree(
                path=record.path.resolve(),
                head_sha=record.head_sha,
                branch=record.branch,
                prunable=record.prunable,
            )
            for record in records
        )

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        path = path.resolve()
        head_sha = self.client.run("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
        branch = self.client.run("branch", "--show-current", cwd=path) or None
        parent_sha = parse_parent_sha(
            self.client.run("rev-list", "--parents", "-n", "1", head_sha, cwd=path),
            head_sha=head_sha,
            base_sha=base_sha,
        )
        status = self.client.run(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=path
        )
        changed = self.client.run(
            "diff",
            "--name-status",
            "-z",
            "--find-renames=100%",
            "--find-copies=100%",
            "--find-copies-harder",
            f"{base_sha}..{head_sha}",
            cwd=path,
        )
        return WorktreeSnapshot(
            path=path,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            parent_sha=parent_sha,
            clean=not bool(status),
            changes=parse_changed_files(changed),
        )

    def branch_inventory(self) -> BranchInventory:
        local_output = self.client.run(
            "for-each-ref",
            "--format=%(refname:strip=2)%09%(objectname)",
            "refs/heads",
        )
        remote_output = self.client.run("ls-remote", "--heads", "origin")
        return parse_branch_inventory(local_output, remote_output)

    def unreachable_commit_inventory(self) -> UnreachableCommitInventory:
        result = self.client.execute_with_timeout(
            "fsck",
            "--unreachable",
            "--no-reflogs",
            "--no-progress",
            timeout_seconds=UNREACHABLE_COMMIT_SCAN_TIMEOUT_SECONDS,
        )
        shas = parse_unreachable_commit_shas(result.stdout)
        problems = tuple(
            line.strip() for line in result.stderr.splitlines() if line.strip()
        )
        if result.exit_code != 0:
            problems = (f"git fsck exited with {result.exit_code}", *problems)
        sample_evidence: list[UnreachableCommitEvidence] = []
        sample_problems = list(problems)
        source_problem = "; ".join(problems)
        for commit_sha in shas[:UNREACHABLE_COMMIT_SAMPLE_SIZE]:
            try:
                sample_evidence.append(
                    self._inspect_unreachable_commit_from_inventory(
                        commit_sha=commit_sha,
                        inventory_shas=shas,
                        source_problem=source_problem,
                        max_paths=UNREACHABLE_COMMIT_PATH_LIMIT,
                    )
                )
            except (AdapterCommandError, AdapterPayloadError, InvalidReceipt) as error:
                detail = _normalized_error(error)
                sample_problems.append(
                    f"unreachable commit {commit_sha} evidence: {detail}"
                )
                sample_evidence.append(
                    _incomplete_unreachable_commit_evidence(
                        commit_sha=commit_sha,
                        error=detail,
                    )
                )
        final_problems = tuple(sample_problems)
        return UnreachableCommitInventory(
            shas=shas,
            problems=final_problems,
            complete=not final_problems,
            evidence=tuple(sample_evidence),
        )

    def inspect_unreachable_commit(
        self,
        *,
        commit_sha: str,
        max_paths: int = UNREACHABLE_COMMIT_PATH_LIMIT,
    ) -> UnreachableCommitEvidence:
        """Read bounded evidence for one object without creating a ref."""

        if _COMMIT_SHA_RE.fullmatch(commit_sha) is None:
            raise AdapterPayloadError("unreachable commit SHA is malformed")
        if type(max_paths) is not int or max_paths <= 0:
            raise AdapterPayloadError("unreachable commit path limit is invalid")

        inventory = self.unreachable_commit_inventory()
        for evidence in inventory.evidence:
            if evidence.commit_sha == commit_sha:
                changed_paths = evidence.changed_paths[:max_paths]
                return replace(
                    evidence,
                    changed_paths=changed_paths,
                    changed_paths_truncated=evidence.changed_path_count
                    > len(changed_paths),
                )
        source_problem = "; ".join(inventory.problems)
        return self._inspect_unreachable_commit_from_inventory(
            commit_sha=commit_sha,
            inventory_shas=inventory.shas,
            source_problem=source_problem,
            max_paths=max_paths,
        )

    def _inspect_unreachable_commit_from_inventory(
        self,
        *,
        commit_sha: str,
        inventory_shas: tuple[str, ...],
        source_problem: str,
        max_paths: int,
    ) -> UnreachableCommitEvidence:
        if source_problem and commit_sha not in inventory_shas:
            return UnreachableCommitEvidence(
                schema="kg.delivery.unreachable-commit.v1",
                commit_sha=commit_sha,
                parent_shas=(),
                subject=None,
                unreachable=None,
                changed_paths=(),
                changed_path_count=0,
                changed_paths_truncated=False,
                change_fingerprint=None,
                disposition="source_problem",
                source_problem_scope="git_objects",
                next_step="repair fsck source evidence before any owner or cleanup decision",
                complete=False,
                error=source_problem,
            )
        if not source_problem and commit_sha not in inventory_shas:
            return UnreachableCommitEvidence(
                schema="kg.delivery.unreachable-commit.v1",
                commit_sha=commit_sha,
                parent_shas=(),
                subject=None,
                unreachable=False,
                changed_paths=(),
                changed_path_count=0,
                changed_paths_truncated=False,
                change_fingerprint=None,
                disposition="refuse_not_unreachable",
                source_problem_scope=None,
                next_step="preserve current refs and require a fresh unreachable-object readback",
                complete=False,
                error="commit is not present in the current unreachable inventory",
            )

        metadata = self.client.run("show", "-s", "--format=%H%x00%P%x00%s", commit_sha)
        fields = metadata.split("\0", 2)
        if len(fields) != 3 or fields[0] != commit_sha or not fields[2]:
            raise AdapterPayloadError("unreachable commit metadata is malformed")
        parent_shas = tuple(fields[1].split())
        if any(_COMMIT_SHA_RE.fullmatch(parent) is None for parent in parent_shas):
            raise AdapterPayloadError("unreachable commit parents are malformed")

        diff_payload = self.client.run(
            "show",
            "--format=",
            "--name-status",
            "-z",
            "--find-renames=100%",
            "--find-copies=100%",
            commit_sha,
        )
        changes = parse_changed_files(diff_payload)
        changed_paths = tuple(sorted(change.path for change in changes))
        return UnreachableCommitEvidence(
            schema="kg.delivery.unreachable-commit.v1",
            commit_sha=commit_sha,
            parent_shas=parent_shas,
            subject=fields[2],
            unreachable=True,
            changed_paths=changed_paths[:max_paths],
            changed_path_count=len(changed_paths),
            changed_paths_truncated=len(changed_paths) > max_paths,
            change_fingerprint=hashlib.sha256(diff_payload.encode("utf-8")).hexdigest(),
            disposition=(
                "preserve_with_source_problem"
                if source_problem
                else "preserve_for_owner_correlation"
            ),
            source_problem_scope="git_objects" if source_problem else None,
            next_step=(
                "repair fsck source evidence before any owner or cleanup decision"
                if source_problem
                else "correlate with an owner, Issue, or PR before any lifecycle action"
            ),
            complete=not source_problem,
            error=source_problem or None,
        )

    def remote_branch_sha(self, branch: str) -> str | None:
        ref = f"refs/heads/{branch}"
        return parse_remote_branch_sha(
            self.client.run("ls-remote", "origin", ref),
            branch=branch,
        )

    def local_branch_sha(self, branch: str) -> str | None:
        ref = f"refs/heads/{branch}"
        result = self.client.execute("show-ref", "--verify", "--quiet", ref)
        if (
            result.exit_code == 1
            and not result.stdout.strip()
            and not result.stderr.strip()
        ):
            return None
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        return parse_local_branch_sha(
            self.client.run("rev-parse", "--verify", f"{ref}^{{commit}}"),
            ref=ref,
        )

    def local_main_sha(self) -> str:
        return self.client.run("rev-parse", "--verify", "main^{commit}")

    def origin_main_sha(self) -> str:
        return parse_origin_main_sha(
            self.client.run("ls-remote", "origin", "refs/heads/main")
        )

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        result = self.client.execute(
            "merge-base",
            "--is-ancestor",
            ancestor_sha,
            descendant_sha,
        )
        if result.exit_code == 0:
            return True
        if result.exit_code == 1 and not result.stderr.strip():
            return False
        raise AdapterCommandError(result)

    def inspect_branch_content(
        self,
        *,
        branch: str,
        base_sha: str,
        max_commit_summaries: int = BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT,
    ) -> BranchContentEvidence:
        """Read bounded diff evidence for one local branch against live main."""

        head_sha = self.local_branch_sha(branch)
        if head_sha is None:
            raise AdapterCommandError(
                self.client.execute(
                    "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
                )
            )
        base_is_ancestor = self.is_ancestor(base_sha, head_sha)
        ahead_output = self.client.run("rev-list", "--count", f"{base_sha}..{head_sha}")
        behind_output = self.client.run(
            "rev-list", "--count", f"{head_sha}..{base_sha}"
        )
        try:
            ahead_count = int(ahead_output)
            behind_count = int(behind_output)
        except ValueError as error:
            raise AdapterCommandError(
                self.client.execute("rev-list", "--count", f"{base_sha}..{head_sha}")
            ) from error
        diff_payload = self.client.run(
            "diff",
            "--name-status",
            "-z",
            "--find-renames=100%",
            "--find-copies=100%",
            f"{base_sha}..{head_sha}",
        )
        changes = parse_changed_files(diff_payload)
        summaries_payload = self.client.run(
            "log",
            "--format=%H%x09%s",
            f"--max-count={max_commit_summaries + 1}",
            f"{base_sha}..{head_sha}",
        )
        summaries, truncated = parse_commit_summaries(
            summaries_payload, limit=max_commit_summaries
        )
        all_changed_paths = tuple(sorted(change.path for change in changes))
        return BranchContentEvidence(
            schema="kg.delivery.branch-content.v1",
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            base_is_ancestor=base_is_ancestor,
            ahead_commit_count=ahead_count,
            behind_commit_count=behind_count,
            changed_paths=all_changed_paths[:BRANCH_CONTENT_PATH_LIMIT],
            changed_path_count=len(all_changed_paths),
            changed_paths_truncated=len(all_changed_paths) > BRANCH_CONTENT_PATH_LIMIT,
            change_fingerprint=hashlib.sha256(diff_payload.encode()).hexdigest(),
            commit_subjects=tuple(subject for _, subject in summaries),
            commit_subjects_truncated=truncated,
            complete=True,
        )

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]:
        return parse_first_parent_landings(
            self.client.run(
                "log",
                "--first-parent",
                "--reverse",
                "--format=%H%x09%cI",
                f"{before_sha}..{after_sha}",
            )
        )

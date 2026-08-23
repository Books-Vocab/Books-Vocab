"""Read-only Git queries built on the argv client and pure parsers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..domain.branch_content import (
    BRANCH_CONTENT_PATH_LIMIT,
    BranchContentEvidence,
)
from ..domain.branch_refs import BranchInventory
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    MainLandingSnapshot,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from ..domain.unreachable_commits import UnreachableCommitInventory
from .errors import AdapterCommandError
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
    parse_worktrees,
    parse_unreachable_commit_shas,
)

UNREACHABLE_COMMIT_SCAN_TIMEOUT_SECONDS = 30.0
BRANCH_CONTENT_COMMIT_SUMMARY_LIMIT = 20


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
        return UnreachableCommitInventory(
            shas=shas,
            problems=problems,
            complete=not problems,
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

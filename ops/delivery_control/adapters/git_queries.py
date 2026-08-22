"""Read-only Git queries built on the argv client and pure parsers."""

from __future__ import annotations

from pathlib import Path

from ..domain.branch_refs import BranchInventory
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    MainLandingSnapshot,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from .errors import AdapterCommandError
from .git_client import GitCliClient
from .git_parsing import (
    parse_branch_inventory,
    parse_changed_files,
    parse_first_parent_landings,
    parse_local_branch_sha,
    parse_origin_main_sha,
    parse_parent_sha,
    parse_remote_branch_sha,
    parse_worktrees,
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
                self.client.run(
                    "status", "--porcelain=v1", "--untracked-files=all"
                )
            ),
        )

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        records = parse_worktrees(
            self.client.run("worktree", "list", "--porcelain")
        )
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
        head_sha = self.client.run(
            "rev-parse", "--verify", "HEAD^{commit}", cwd=path
        )
        branch = self.client.run("branch", "--show-current", cwd=path) or None
        parent_sha = parse_parent_sha(
            self.client.run(
                "rev-list", "--parents", "-n", "1", head_sha, cwd=path
            ),
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

from __future__ import annotations

from pathlib import Path

from ..domain.errors import CompareAndSwapConflict
from ..domain.observations import (
    CanonicalCheckoutSnapshot,
    FileChange,
    FileOperation,
    PhysicalWorktree,
    WorktreeSnapshot,
)
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError
from .subprocess_runner import SubprocessCommandRunner


class GitCliAdapter:
    def __init__(
        self,
        *,
        repo: Path,
        runner: CommandRunnerPort | None = None,
    ) -> None:
        self.repo = repo.resolve()
        self.runner = runner or SubprocessCommandRunner()

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        target = (cwd or self.repo).resolve()
        argv = ("git", "-C", str(target), *args)
        result = self.runner.run(argv)
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        return result.stdout.strip()

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            path=self.repo,
            branch=self._git("branch", "--show-current") or None,
            head_sha=self._git("rev-parse", "--verify", "HEAD^{commit}"),
            clean=not bool(
                self._git("status", "--porcelain=v1", "--untracked-files=all")
            ),
        )

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        output = self._git("worktree", "list", "--porcelain")
        if not output:
            return ()
        records: list[PhysicalWorktree] = []
        for block in output.split("\n\n"):
            fields: dict[str, str] = {}
            flags: set[str] = set()
            for line in block.splitlines():
                key, separator, value = line.partition(" ")
                if separator:
                    fields[key] = value
                elif key:
                    flags.add(key)
            try:
                path = Path(fields["worktree"]).resolve()
                head_sha = fields["HEAD"]
            except KeyError as error:
                raise AdapterPayloadError(
                    "git worktree porcelain record is incomplete"
                ) from error
            branch_ref = fields.get("branch")
            branch = (
                branch_ref.removeprefix("refs/heads/")
                if branch_ref and branch_ref.startswith("refs/heads/")
                else None
            )
            records.append(
                PhysicalWorktree(
                    path=path,
                    head_sha=head_sha,
                    branch=branch,
                    prunable="prunable" in fields or "prunable" in flags,
                )
            )
        return tuple(records)

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        path = path.resolve()
        head_sha = self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
        branch = self._git("branch", "--show-current", cwd=path) or None
        parent_row = self._git("rev-list", "--parents", "-n", "1", head_sha, cwd=path)
        parent_fields = parent_row.split()
        if not parent_fields or parent_fields[0] != head_sha:
            raise AdapterPayloadError("git parent readback differs from worktree HEAD")
        parent_sha = parent_fields[1] if len(parent_fields) > 1 else base_sha
        status = self._git(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=path
        )
        changed = self._git(
            "diff",
            "--name-status",
            "-z",
            "--find-renames=100%",
            "--find-copies=100%",
            "--find-copies-harder",
            f"{base_sha}..{head_sha}",
            cwd=path,
        )
        changes = self._parse_changed_files(changed)
        return WorktreeSnapshot(
            path=path,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            parent_sha=parent_sha,
            clean=not bool(status),
            changes=changes,
        )

    @staticmethod
    def _parse_changed_files(payload: str) -> tuple[FileChange, ...]:
        """Parse ``git diff --name-status -z`` into canonical file changes.

        Scope v1 intentionally remains a flat operation/path schema.  A Git
        rename therefore claims both changed paths as delete(source) and
        add(destination), while a copy claims its newly added destination.
        This keeps collision and exact-diff checks complete without adding a
        source_path field to every Scope consumer.
        """

        if not payload:
            return ()
        fields = payload.split("\0")
        if fields[-1] != "":
            raise AdapterPayloadError(
                "git diff name-status payload is not NUL terminated"
            )
        fields.pop()
        changes: list[FileChange] = []
        index = 0
        while index < len(fields):
            status = fields[index]
            index += 1
            status_code = status[:1]
            if status_code in {"A", "M", "T", "D"}:
                if index >= len(fields):
                    raise AdapterPayloadError(
                        f"git diff status {status!r} is missing its path"
                    )
                path = fields[index]
                index += 1
                operation = {
                    "A": FileOperation.ADD,
                    "M": FileOperation.MODIFY,
                    "T": FileOperation.MODIFY,
                    "D": FileOperation.DELETE,
                }[status_code]
                changes.append(FileChange(operation, path))
                continue
            if status_code in {"R", "C"}:
                if index + 1 >= len(fields):
                    raise AdapterPayloadError(
                        f"git diff status {status!r} is missing source or destination"
                    )
                source = fields[index]
                destination = fields[index + 1]
                index += 2
                if status_code == "R":
                    changes.append(FileChange(FileOperation.DELETE, source))
                changes.append(FileChange(FileOperation.ADD, destination))
                continue
            raise AdapterPayloadError(f"unsupported git diff status: {status!r}")

        canonical = tuple(
            sorted(changes, key=lambda item: (item.path, item.operation.value))
        )
        paths = tuple(item.path for item in canonical)
        if len(paths) != len(set(paths)):
            raise AdapterPayloadError(
                "git diff normalization produced duplicate changed paths"
            )
        return canonical

    def remote_branch_sha(self, branch: str) -> str | None:
        ref = f"refs/heads/{branch}"
        output = self._git("ls-remote", "origin", ref)
        if not output:
            return None
        rows = [line.split() for line in output.splitlines() if line.strip()]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
            raise AdapterPayloadError(f"unexpected remote ref response for {ref}")
        return rows[0][0]

    def local_branch_sha(self, branch: str) -> str | None:
        ref = f"refs/heads/{branch}"
        argv = (
            "git",
            "-C",
            str(self.repo),
            "show-ref",
            "--verify",
            "--quiet",
            ref,
        )
        result = self.runner.run(argv)
        if (
            result.exit_code == 1
            and not result.stdout.strip()
            and not result.stderr.strip()
        ):
            return None
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        commit_sha = self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        if not commit_sha or len(commit_sha.splitlines()) != 1:
            raise AdapterPayloadError(f"local branch {ref} did not resolve uniquely")
        return commit_sha

    def local_main_sha(self) -> str:
        return self._git("rev-parse", "--verify", "main^{commit}")

    def origin_main_sha(self) -> str:
        output = self._git("ls-remote", "origin", "refs/heads/main")
        rows = [line.split() for line in output.splitlines() if line.strip()]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
            raise AdapterPayloadError("origin/main did not resolve uniquely")
        return rows[0][0]

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        worktree = worktree.resolve()
        current_branch = self._git("branch", "--show-current", cwd=worktree)
        current_head = self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=worktree)
        dirty = self._git(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree
        )
        if current_branch != branch or current_head != expected_local_sha or dirty:
            raise CompareAndSwapConflict("local branch, HEAD, or cleanliness changed")
        remote_sha = self.remote_branch_sha(branch)
        if remote_sha != expected_remote_sha:
            raise CompareAndSwapConflict("remote branch changed after preflight")
        destination = f"refs/heads/{branch}"
        expected_remote = expected_remote_sha or ""
        argv = [
            "push",
            "origin",
            f"--force-with-lease={destination}:{expected_remote}",
        ]
        argv.append(f"{expected_local_sha}:{destination}")
        try:
            self._git(*argv, cwd=worktree)
        except AdapterCommandError as error:
            raise CompareAndSwapConflict(
                "remote branch changed or push lease failed"
            ) from error
        readback = self.remote_branch_sha(branch)
        if readback != expected_local_sha:
            raise CompareAndSwapConflict(
                "remote branch readback differs from pushed HEAD"
            )
        return readback

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
        path = path.resolve()
        if path == self.repo:
            raise CompareAndSwapConflict("refusing to remove canonical checkout")
        matches = tuple(
            item for item in self.list_worktrees() if item.path.resolve() == path
        )
        if not matches:
            return
        if len(matches) != 1:
            raise AdapterPayloadError("worktree path did not resolve uniquely")
        if matches[0].head_sha != expected_head_sha:
            raise CompareAndSwapConflict("worktree changed before cleanup")
        head = self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
        dirty = self._git("status", "--porcelain=v1", "--untracked-files=all", cwd=path)
        if head != expected_head_sha or dirty:
            raise CompareAndSwapConflict("worktree changed before cleanup")
        self._git("worktree", "remove", "--", str(path))
        if any(item.path.resolve() == path for item in self.list_worktrees()):
            raise CompareAndSwapConflict("worktree still exists after cleanup")

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        if branch == "main":
            raise CompareAndSwapConflict("refusing to delete local main")
        ref = f"refs/heads/{branch}"
        current = self.local_branch_sha(branch)
        if current is None:
            return
        if current != expected_head_sha:
            raise CompareAndSwapConflict("local branch changed before cleanup")
        self._git("update-ref", "-d", ref, expected_head_sha)
        if self.local_branch_sha(branch) is None:
            return
        raise CompareAndSwapConflict("local branch still exists after cleanup")

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        if branch == "main":
            raise CompareAndSwapConflict("refusing to delete remote main")
        destination = f"refs/heads/{branch}"
        current = self.remote_branch_sha(branch)
        if current is None:
            return
        if current != expected_head_sha:
            raise CompareAndSwapConflict("remote branch changed before cleanup")
        self._git(
            "push",
            "origin",
            f"--force-with-lease={destination}:{expected_head_sha}",
            f":{destination}",
        )
        if self.remote_branch_sha(branch) is not None:
            raise CompareAndSwapConflict("remote branch still exists after cleanup")

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        if self._git("branch", "--show-current") != "main":
            raise CompareAndSwapConflict("canonical checkout is not on main")
        if self.local_main_sha() != expected_local_sha:
            raise CompareAndSwapConflict("local main changed after preflight")
        if self.origin_main_sha() != expected_origin_sha:
            raise CompareAndSwapConflict("origin/main changed after preflight")
        if self._git("status", "--porcelain=v1", "--untracked-files=all"):
            raise CompareAndSwapConflict("canonical main is dirty")
        self._git("fetch", "origin", "main")
        fetched = self._git(
            "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"
        )
        if fetched != expected_origin_sha:
            raise CompareAndSwapConflict(
                "fetched origin/main differs from expected SHA"
            )
        self._git("merge", "--ff-only", expected_origin_sha)
        readback = self.local_main_sha()
        if readback != expected_origin_sha:
            raise CompareAndSwapConflict(
                "local main readback differs after fast-forward"
            )
        return readback

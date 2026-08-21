from __future__ import annotations

from pathlib import Path

from ..domain.errors import CompareAndSwapConflict
from ..domain.observations import (
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
        try:
            parent_sha = self._git("rev-parse", "--verify", "HEAD^1^{commit}", cwd=path)
        except AdapterCommandError:
            parent_sha = base_sha
        status = self._git(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=path
        )
        changed = self._git(
            "diff",
            "--name-status",
            "--find-renames=100%",
            f"{base_sha}..{head_sha}",
            cwd=path,
        )
        changes: list[FileChange] = []
        operation_map = {
            "A": FileOperation.ADD,
            "M": FileOperation.MODIFY,
            "T": FileOperation.MODIFY,
            "D": FileOperation.DELETE,
            "R": FileOperation.RENAME,
            "C": FileOperation.COPY,
        }
        for line in changed.splitlines():
            fields = line.split("\t")
            status_code = fields[0][:1] if fields else ""
            if status_code not in operation_map or len(fields) < 2:
                raise AdapterPayloadError(f"unsupported git diff status row: {line!r}")
            path_field = fields[-1]
            changes.append(FileChange(operation_map[status_code], path_field))
        return WorktreeSnapshot(
            path=path,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            parent_sha=parent_sha,
            clean=not bool(status),
            changes=tuple(
                sorted(changes, key=lambda item: (item.path, item.operation.value))
            ),
        )

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
        try:
            return self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except AdapterCommandError:
            return None

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
        head = self._git("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
        dirty = self._git("status", "--porcelain=v1", "--untracked-files=all", cwd=path)
        if head != expected_head_sha or dirty:
            raise CompareAndSwapConflict("worktree changed before cleanup")
        self._git("worktree", "remove", "--", str(path))

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        if branch == "main":
            raise CompareAndSwapConflict("refusing to delete local main")
        ref = f"refs/heads/{branch}"
        try:
            current = self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except AdapterCommandError:
            return
        if current != expected_head_sha:
            raise CompareAndSwapConflict("local branch changed before cleanup")
        self._git("update-ref", "-d", ref, expected_head_sha)
        try:
            self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except AdapterCommandError:
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

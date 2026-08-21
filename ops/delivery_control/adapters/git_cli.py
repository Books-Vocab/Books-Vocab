from __future__ import annotations

from pathlib import Path

from delivery_control.domain.models import PhysicalWorktree, WorktreeSnapshot
from delivery_control.ports.process import CommandRunnerPort

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
        changed = self._git("diff", "--name-only", f"{base_sha}..{head_sha}", cwd=path)
        return WorktreeSnapshot(
            path=path,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            parent_sha=parent_sha,
            clean=not bool(status),
            changed_paths=tuple(sorted(line for line in changed.splitlines() if line)),
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

    def local_main_sha(self) -> str:
        return self._git("rev-parse", "--verify", "main^{commit}")

    def origin_main_sha(self) -> str:
        output = self._git("ls-remote", "origin", "refs/heads/main")
        rows = [line.split() for line in output.splitlines() if line.strip()]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
            raise AdapterPayloadError("origin/main did not resolve uniquely")
        return rows[0][0]

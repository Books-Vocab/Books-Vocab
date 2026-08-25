"""Compare-and-swap Git mutations separated from read queries."""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import CompareAndSwapConflict
from ..ports.git import GitQueryPort
from .errors import AdapterCommandError, AdapterPayloadError
from .git_client import GitCliClient


class GitCommands:
    def __init__(
        self,
        *,
        repo: Path,
        client: GitCliClient,
        query: GitQueryPort,
    ) -> None:
        self.repo = repo
        self.client = client
        self.query = query

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        worktree = worktree.resolve()
        current_branch = self.client.run("branch", "--show-current", cwd=worktree)
        current_head = self.client.run(
            "rev-parse", "--verify", "HEAD^{commit}", cwd=worktree
        )
        dirty = self.client.run(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree
        )
        if current_branch != branch or current_head != expected_local_sha or dirty:
            raise CompareAndSwapConflict("local branch, HEAD, or cleanliness changed")
        remote_sha = self.query.remote_branch_sha(branch)
        if remote_sha != expected_remote_sha:
            raise CompareAndSwapConflict("remote branch changed after preflight")
        destination = f"refs/heads/{branch}"
        expected_remote = expected_remote_sha or ""
        argv = [
            "push",
            "origin",
            f"--force-with-lease={destination}:{expected_remote}",
            f"{expected_local_sha}:{destination}",
        ]
        try:
            self.client.run(*argv, cwd=worktree)
        except AdapterCommandError as error:
            raise CompareAndSwapConflict(
                "remote branch changed or push lease failed"
            ) from error
        readback = self.query.remote_branch_sha(branch)
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
            item for item in self.query.list_worktrees() if item.path.resolve() == path
        )
        if not matches:
            return
        if len(matches) != 1:
            raise AdapterPayloadError("worktree path did not resolve uniquely")
        if matches[0].head_sha != expected_head_sha:
            raise CompareAndSwapConflict("worktree changed before cleanup")
        head = self.client.run("rev-parse", "--verify", "HEAD^{commit}", cwd=path)
        dirty = self.client.run(
            "status", "--porcelain=v1", "--untracked-files=all", cwd=path
        )
        if head != expected_head_sha or dirty:
            raise CompareAndSwapConflict("worktree changed before cleanup")
        self.client.run("worktree", "remove", "--", str(path))
        if any(item.path.resolve() == path for item in self.query.list_worktrees()):
            raise CompareAndSwapConflict("worktree still exists after cleanup")

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        if branch == "main":
            raise CompareAndSwapConflict("refusing to delete local main")
        ref = f"refs/heads/{branch}"
        current = self.query.local_branch_sha(branch)
        if current is None:
            return
        if current != expected_head_sha:
            raise CompareAndSwapConflict("local branch changed before cleanup")
        self.client.run("update-ref", "-d", ref, expected_head_sha)
        if self.query.local_branch_sha(branch) is None:
            return
        raise CompareAndSwapConflict("local branch still exists after cleanup")

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        if branch == "main":
            raise CompareAndSwapConflict("refusing to delete remote main")
        destination = f"refs/heads/{branch}"
        current = self.query.remote_branch_sha(branch)
        if current is None:
            return
        if current != expected_head_sha:
            raise CompareAndSwapConflict("remote branch changed before cleanup")
        self.client.run(
            "push",
            "origin",
            f"--force-with-lease={destination}:{expected_head_sha}",
            f":{destination}",
        )
        if self.query.remote_branch_sha(branch) is not None:
            raise CompareAndSwapConflict("remote branch still exists after cleanup")

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        if self.client.run("branch", "--show-current") != "main":
            raise CompareAndSwapConflict("canonical checkout is not on main")
        if self.query.local_main_sha() != expected_local_sha:
            raise CompareAndSwapConflict("local main changed after preflight")
        if self.query.origin_main_sha() != expected_origin_sha:
            raise CompareAndSwapConflict("origin/main changed after preflight")
        if self.client.run("status", "--porcelain=v1", "--untracked-files=all"):
            raise CompareAndSwapConflict("canonical main is dirty")
        self.client.run("fetch", "origin", "main")
        fetched = self.client.run(
            "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"
        )
        if fetched != expected_origin_sha:
            raise CompareAndSwapConflict(
                "fetched origin/main differs from expected SHA"
            )
        self.client.run("merge", "--ff-only", expected_origin_sha)
        readback = self.query.local_main_sha()
        if readback != expected_origin_sha:
            raise CompareAndSwapConflict(
                "local main readback differs after fast-forward"
            )
        return readback

    def park_main_to_origin(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        """CAS-park a preserved local main tip without reset/rebase/merge."""

        if expected_local_sha == expected_origin_sha:
            raise CompareAndSwapConflict(
                "main park requires distinct local and origin SHA values"
            )
        if self.client.run("branch", "--show-current") != "main":
            raise CompareAndSwapConflict("canonical checkout is not on main")
        if self.query.local_main_sha() != expected_local_sha:
            raise CompareAndSwapConflict("local main changed before main park")
        if self.query.origin_main_sha() != expected_origin_sha:
            raise CompareAndSwapConflict("origin/main changed before main park")
        if self.client.run("status", "--porcelain=v1", "--untracked-files=all"):
            raise CompareAndSwapConflict("canonical main is dirty")

        detached = False
        main_parked = False

        def compensate() -> str | None:
            """Restore the original main ref before returning a failed CAS."""

            nonlocal detached, main_parked
            try:
                if main_parked:
                    if not detached:
                        if self.client.run(
                            "status", "--porcelain=v1", "--untracked-files=all"
                        ):
                            return "canonical main became dirty during compensation"
                        self.client.run("checkout", "--detach", expected_local_sha)
                        detached = True
                    self.client.run(
                        "update-ref",
                        "refs/heads/main",
                        expected_local_sha,
                        expected_origin_sha,
                    )
                    main_parked = False
                if detached:
                    self.client.run("switch", "main")
                    detached = False
            except AdapterCommandError as error:
                return str(error)
            return None

        try:
            self.client.run("checkout", "--detach", expected_origin_sha)
            detached = True
            if self.query.local_main_sha() != expected_local_sha:
                raise CompareAndSwapConflict("local main changed during main park")
            if self.query.origin_main_sha() != expected_origin_sha:
                raise CompareAndSwapConflict("origin/main changed during main park")
            self.client.run(
                "update-ref",
                "refs/heads/main",
                expected_origin_sha,
                expected_local_sha,
            )
            main_parked = True
            if self.query.origin_main_sha() != expected_origin_sha:
                raise CompareAndSwapConflict("origin/main changed during main park")
            if self.query.local_main_sha() != expected_origin_sha:
                raise CompareAndSwapConflict("local main changed during main park")
            self.client.run("switch", "main")
            detached = False
        except CompareAndSwapConflict:
            compensation_error = compensate()
            detail = "canonical main park CAS precondition failed"
            if compensation_error is not None:
                detail += f"; compensation failed: {compensation_error}"
            raise CompareAndSwapConflict(detail)
        except AdapterCommandError as error:
            compensation_error = compensate()
            detail = f"canonical main park failed: {error}"
            if compensation_error is not None:
                detail += f"; compensation failed: {compensation_error}"
            raise CompareAndSwapConflict(detail) from error

        try:
            if self.client.run("branch", "--show-current") != "main":
                raise CompareAndSwapConflict(
                    "canonical checkout is not on main after park"
                )
            if self.query.origin_main_sha() != expected_origin_sha:
                raise CompareAndSwapConflict("origin/main changed after main park")
            if self.query.local_main_sha() != expected_origin_sha:
                raise CompareAndSwapConflict(
                    "local main readback differs after main park"
                )
            if self.client.run("status", "--porcelain=v1", "--untracked-files=all"):
                raise CompareAndSwapConflict("canonical main is dirty after main park")
        except CompareAndSwapConflict:
            compensation_error = compensate()
            detail = "canonical main park readback failed"
            if compensation_error is not None:
                detail += f"; compensation failed: {compensation_error}"
            raise CompareAndSwapConflict(detail)
        except AdapterCommandError as error:
            compensation_error = compensate()
            detail = f"canonical main park readback failed: {error}"
            if compensation_error is not None:
                detail += f"; compensation failed: {compensation_error}"
            raise CompareAndSwapConflict(detail) from error
        main_parked = False
        return expected_origin_sha

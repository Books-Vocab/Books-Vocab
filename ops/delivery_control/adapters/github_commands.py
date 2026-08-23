"""GitHub pull-request mutations guarded by exact readback checks."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..domain.errors import CompareAndSwapConflict
from ..domain.observations import PullRequestSnapshot
from .github_client import GitHubCliClient
from .github_queue import GitHubQueueGraphQLAdapter

_READ_AFTER_WRITE_ATTEMPTS = 5
_READ_AFTER_WRITE_DELAY_SECONDS = 1.0


class GitHubCommands:
    def __init__(
        self,
        *,
        client: GitHubCliClient,
        queue: GitHubQueueGraphQLAdapter,
        find_open_pull_request: Callable[[str], PullRequestSnapshot | None],
        get_pull_request: Callable[[int], PullRequestSnapshot],
        merge_queue_enabled: Callable[[str], bool],
    ) -> None:
        self.client = client
        self.queue = queue
        self.find_open_pull_request = find_open_pull_request
        self.get_pull_request = get_pull_request
        self.merge_queue_enabled = merge_queue_enabled

    def _read_until_head(
        self,
        *,
        number: int,
        expected_head_sha: str,
        conflict_message: str,
    ) -> PullRequestSnapshot:
        for attempt in range(_READ_AFTER_WRITE_ATTEMPTS):
            snapshot = self.get_pull_request(number)
            if snapshot.head_sha == expected_head_sha:
                return snapshot
            if attempt + 1 < _READ_AFTER_WRITE_ATTEMPTS:
                time.sleep(_READ_AFTER_WRITE_DELAY_SECONDS)
        raise CompareAndSwapConflict(conflict_message)

    def trigger_required(
        self,
        *,
        number: int,
        branch: str,
        base_sha: str,
        head_sha: str,
    ) -> tuple[str, ...]:
        argv = (
            "gh",
            "workflow",
            "run",
            "pr-gate.yml",
            "--ref",
            branch,
            "-f",
            f"pr_number={number}",
            "-f",
            f"base_sha={base_sha}",
            "-f",
            f"head_sha={head_sha}",
        )
        self.client.run(argv)
        return argv

    def trigger_readiness(
        self,
        *,
        number: int,
        branch: str,
        head_sha: str,
    ) -> tuple[str, ...]:
        argv = (
            "gh",
            "workflow",
            "run",
            "pr-readiness.yml",
            "--ref",
            branch,
            "-f",
            f"pr_number={number}",
            "-f",
            f"head_sha={head_sha}",
        )
        self.client.run(argv)
        return argv

    def create_pull_request(
        self, *, branch: str, title: str, body: str
    ) -> PullRequestSnapshot:
        self.client.run(
            (
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            )
        )
        created = self.find_open_pull_request(branch)
        if created is None:
            raise CompareAndSwapConflict("created PR did not read back by branch")
        return created

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        self._read_until_head(
            number=number,
            expected_head_sha=expected_head_sha,
            conflict_message="PR HEAD changed before metadata update",
        )
        self.client.run(
            ("gh", "pr", "edit", str(number), "--title", title, "--body", body)
        )
        return self._read_until_head(
            number=number,
            expected_head_sha=expected_head_sha,
            conflict_message="PR HEAD changed during metadata update",
        )

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        before = self.get_pull_request(number)
        self.client.run(("gh", "pr", "ready", str(number)))
        after = self.get_pull_request(number)
        if after.head_sha != before.head_sha:
            raise CompareAndSwapConflict("PR HEAD changed while marking ready")
        return after

    def close_pull_request(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> PullRequestSnapshot:
        return self._change_pull_request_state(
            number=number,
            command="close",
            before_state="OPEN",
            after_state="CLOSED",
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

    def reopen_pull_request(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> PullRequestSnapshot:
        return self._change_pull_request_state(
            number=number,
            command="reopen",
            before_state="CLOSED",
            after_state="OPEN",
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

    def _change_pull_request_state(
        self,
        *,
        number: int,
        command: str,
        before_state: str,
        after_state: str,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> PullRequestSnapshot:
        before = self.get_pull_request(number)
        if (
            before.state != before_state
            or before.merged_at is not None
            or before.base_branch != "main"
            or before.base_sha != expected_base_sha
            or before.head_sha != expected_head_sha
            or before.body != expected_body
        ):
            raise CompareAndSwapConflict(f"PR tuple changed before {command}")
        self.client.run(("gh", "pr", command, str(number)))
        after = self.get_pull_request(number)
        if (
            after.state != after_state
            or after.merged_at is not None
            or after.base_branch != "main"
            or after.base_sha != expected_base_sha
            or after.head_sha != expected_head_sha
            or after.body != expected_body
        ):
            raise CompareAndSwapConflict(f"PR tuple changed during {command}")
        return after

    def enqueue(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> None:
        before = self.get_pull_request(number)
        if (
            before.base_branch != "main"
            or before.base_sha != expected_base_sha
            or before.head_sha != expected_head_sha
            or before.body != expected_body
        ):
            raise CompareAndSwapConflict("PR tuple changed before enqueue")
        if not self.merge_queue_enabled("main"):
            raise CompareAndSwapConflict("main has no native merge queue rule")
        self.queue.enqueue(
            pull_request_id=before.node_id,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

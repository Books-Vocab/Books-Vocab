"""GitHub pull-request mutations guarded by exact readback checks."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from ..domain.errors import CompareAndSwapConflict
from ..domain.observations import PullRequestSnapshot
from .errors import AdapterCommandError, AdapterPayloadError
from .github_client import GitHubCliClient
from .github_queue import GitHubQueueGraphQLAdapter
from .timestamps import parse_optional_timestamp

_READ_AFTER_WRITE_ATTEMPTS = 5
_READ_AFTER_WRITE_DELAY_SECONDS = 1.0
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ACTIVE_RUN_STATUSES = frozenset(
    {"queued", "in_progress", "waiting", "requested", "pending"}
)
_STALE_QUEUED_RUN_AFTER = timedelta(minutes=15)
_CANCEL_REREAD_ATTEMPTS = 3
_CANCEL_REREAD_DELAY_SECONDS = 1.0
_CANCEL_COMPLETED_RACE_MARKER = "cannot cancel a workflow run that is completed"


def _required_run_list_command(*, branch: str, head_sha: str) -> tuple[str, ...]:
    return (
        "gh",
        "run",
        "list",
        "--workflow",
        "pr-gate.yml",
        "--branch",
        branch,
        "--event",
        "pull_request",
        "--commit",
        head_sha,
        "--limit",
        "20",
        "--json",
        "databaseId,headBranch,headSha,event,status,conclusion,createdAt",
    )


def _required_run_view_command(*, database_id: int) -> tuple[str, ...]:
    return (
        "gh",
        "run",
        "view",
        str(database_id),
        "--json",
        "databaseId,headBranch,headSha,event,status,conclusion,createdAt",
    )


def _select_exact_required_run(
    payload: object,
    *,
    branch: str,
    head_sha: str,
) -> tuple[datetime, int, str, str | None]:
    if not isinstance(payload, list):
        raise AdapterPayloadError("GitHub required workflow list must be a JSON list")

    candidates: list[tuple[datetime, int, str, str | None]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise AdapterPayloadError(f"GitHub required workflow[{index}] is malformed")
        database_id = item.get("databaseId")
        head_branch = item.get("headBranch")
        observed_head = item.get("headSha")
        event = item.get("event")
        status = item.get("status")
        conclusion = item.get("conclusion")
        if type(database_id) is not int or database_id <= 0:
            raise AdapterPayloadError(
                f"GitHub required workflow[{index}] databaseId is malformed"
            )
        if (
            type(head_branch) is not str
            or type(observed_head) is not str
            or _SHA_RE.fullmatch(observed_head) is None
            or type(event) is not str
            or type(status) is not str
            or conclusion is not None
            and type(conclusion) is not str
        ):
            raise AdapterPayloadError(
                f"GitHub required workflow[{index}] identity is malformed"
            )
        created_at = parse_optional_timestamp(
            item.get("createdAt"),
            field=f"GitHub required workflow[{index}] createdAt",
        )
        if created_at is None:
            raise AdapterPayloadError(
                f"GitHub required workflow[{index}] createdAt is required"
            )
        if (
            head_branch != branch
            or observed_head != head_sha
            or event != "pull_request"
        ):
            continue
        candidates.append((created_at, database_id, status.casefold(), conclusion))

    if not candidates:
        raise AdapterPayloadError(
            "no exact pull_request pr-gate run exists for the required PR HEAD"
        )
    return max(candidates, key=lambda item: (item[0], item[1]))


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
        del number, base_sha
        list_argv = _required_run_list_command(branch=branch, head_sha=head_sha)
        created_at, database_id, status, conclusion = _select_exact_required_run(
            self.client.load_json(list_argv),
            branch=branch,
            head_sha=head_sha,
        )
        if status in _ACTIVE_RUN_STATUSES:
            queued_is_stale = (
                status == "queued"
                and datetime.now(tz=UTC) - created_at >= _STALE_QUEUED_RUN_AFTER
            )
            if not queued_is_stale:
                raise AdapterPayloadError(
                    "exact pull_request pr-gate run is still active; refusing duplicate rerun"
                )

            cancel_argv = ("gh", "run", "cancel", "--force", str(database_id))
            cancel_result = self.client.runner.run(
                cancel_argv,
                cwd=self.client.repo,
            )
            # Cancellation is asynchronous and may race with GitHub's own
            # terminal transition. Never infer cancellation from exit status;
            # select the same exact run again before rerunning it. GitHub can
            # report the run as already completed while the list endpoint
            # briefly continues to expose its queued state, so only that
            # specific race gets a bounded additional read window.
            cancel_detail = f"{cancel_result.stdout}\n{cancel_result.stderr}".casefold()
            reread_attempts = (
                _CANCEL_REREAD_ATTEMPTS
                if (
                    cancel_result.exit_code != 0
                    and _CANCEL_COMPLETED_RACE_MARKER in cancel_detail
                )
                else 1
            )
            for attempt in range(reread_attempts):
                created_at, database_id, status, conclusion = (
                    _select_exact_required_run(
                        self.client.load_json(list_argv),
                        branch=branch,
                        head_sha=head_sha,
                    )
                )
                del created_at
                if status not in _ACTIVE_RUN_STATUSES:
                    break
                if attempt + 1 < reread_attempts:
                    time.sleep(_CANCEL_REREAD_DELAY_SECONDS)
            else:
                if (
                    cancel_result.exit_code == 0
                    or _CANCEL_COMPLETED_RACE_MARKER not in cancel_detail
                ):
                    if cancel_result.exit_code != 0:
                        raise AdapterCommandError(cancel_result)
                    raise AdapterPayloadError(
                        "stale exact pull_request pr-gate run remained active after forced cancel"
                    )

                expected_database_id = database_id
                view_argv = _required_run_view_command(database_id=expected_database_id)
                view_terminal = False
                for attempt in range(_CANCEL_REREAD_ATTEMPTS):
                    (
                        view_created_at,
                        viewed_database_id,
                        view_status,
                        view_conclusion,
                    ) = _select_exact_required_run(
                        [self.client.load_json(view_argv)],
                        branch=branch,
                        head_sha=head_sha,
                    )
                    del view_created_at
                    if viewed_database_id != expected_database_id:
                        raise AdapterPayloadError(
                            "authoritative exact pull_request pr-gate run identity changed"
                        )
                    database_id = viewed_database_id
                    status = view_status
                    conclusion = view_conclusion
                    if status not in _ACTIVE_RUN_STATUSES:
                        view_terminal = True
                        break
                    if attempt + 1 < _CANCEL_REREAD_ATTEMPTS:
                        time.sleep(_CANCEL_REREAD_DELAY_SECONDS)
                if not view_terminal:
                    raise AdapterPayloadError(
                        "authoritative exact pull_request pr-gate run remained active "
                        "after completed-cancel race"
                    )
            if status != "completed" or conclusion is None:
                raise AdapterPayloadError(
                    "exact pull_request pr-gate run has an invalid terminal state"
                )
        if status != "completed" or conclusion is None:
            raise AdapterPayloadError(
                "exact pull_request pr-gate run has an invalid terminal state"
            )
        if conclusion.casefold() == "success":
            raise AdapterPayloadError(
                "exact pull_request pr-gate run already succeeded; refusing duplicate rerun"
            )
        argv = ("gh", "run", "rerun", str(database_id))
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

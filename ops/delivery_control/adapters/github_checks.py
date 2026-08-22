"""Required-check observation with exact pull-request HEAD binding."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from ..domain.errors import CompareAndSwapConflict
from ..domain.models import CheckStatus
from ..domain.observations import CheckSnapshot, PullRequestSnapshot
from .errors import AdapterPayloadError
from .github_client import GitHubCliClient
from .timestamps import parse_optional_timestamp


class GitHubChecks:
    def __init__(
        self,
        *,
        client: GitHubCliClient,
        get_pull_request: Callable[[int], PullRequestSnapshot],
    ) -> None:
        self.client = client
        self.get_pull_request = get_pull_request

    def required_snapshot(self, number: int) -> CheckSnapshot:
        before = self.get_pull_request(number)
        payload = self.client.load_json(
            (
                "gh",
                "pr",
                "checks",
                str(number),
                "--required",
                "--json",
                "name,state,startedAt,completedAt",
            ),
            allow_nonzero=True,
        )
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub required checks must be a JSON list")
        names: list[str] = []
        states: set[str] = set()
        starts: list[datetime | None] = []
        completions: list[datetime | None] = []
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise AdapterPayloadError(f"required check[{index}] is not an object")
            name = item.get("name")
            state = item.get("state")
            if type(name) is not str or type(state) is not str:
                raise AdapterPayloadError(f"required check[{index}] is malformed")
            names.append(name)
            states.add(state.upper())
            starts.append(parse_optional_timestamp(item.get("startedAt"), field=f"required check[{index}] startedAt"))
            completions.append(
                parse_optional_timestamp(
                    item.get("completedAt"),
                    field=f"required check[{index}] completedAt",
                )
            )
        after = self.get_pull_request(number)
        if before.head_sha != after.head_sha:
            raise CompareAndSwapConflict("PR HEAD changed while reading required checks")
        if not states:
            status = CheckStatus.ABSENT
        elif states & {
            "FAILURE",
            "ERROR",
            "CANCELLED",
            "TIMED_OUT",
            "ACTION_REQUIRED",
        }:
            status = CheckStatus.FAILURE
        elif states <= {"SUCCESS", "SKIPPED", "NEUTRAL"}:
            status = CheckStatus.SUCCESS
        else:
            status = CheckStatus.PENDING
        started_at = (
            min(item for item in starts if item is not None)
            if starts and all(item is not None for item in starts)
            else None
        )
        completed_at = (
            max(item for item in completions if item is not None)
            if completions and all(item is not None for item in completions)
            else None
        )
        try:
            return CheckSnapshot(
                status=status,
                head_sha=after.head_sha,
                observed_at=datetime.now(tz=UTC),
                names=tuple(sorted(names)),
                started_at=started_at,
                completed_at=completed_at,
            )
        except ValueError as error:
            # GitHub timestamps are external evidence. Preserve the PR/HEAD
            # inventory and isolate only this malformed check observation so a
            # transient provider inconsistency cannot make the whole control
            # plane unreadable.
            raise AdapterPayloadError(
                "required check timestamps are inconsistent"
            ) from error

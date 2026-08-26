"""Required-check observation with exact pull-request HEAD binding."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from ..domain.errors import CompareAndSwapConflict
from ..domain.models import CheckStatus
from ..domain.observations import CheckSnapshot, PullRequestSnapshot
from .errors import AdapterPayloadError
from .github_client import GitHubCliClient
from .github_required_batch import batch_required_snapshots
from .timestamps import parse_optional_timestamp

_NO_REQUIRED_CHECKS_RE = re.compile(r"no checks reported on the '([^'\n]+)' branch")


def _status_from_states(states: set[str]) -> CheckStatus:
    if not states:
        return CheckStatus.ABSENT
    if states & {
        "FAILURE",
        "ERROR",
        "CANCELLED",
        "TIMED_OUT",
        "ACTION_REQUIRED",
    }:
        return CheckStatus.FAILURE
    if states <= {"SUCCESS", "SKIPPED", "NEUTRAL"}:
        return CheckStatus.SUCCESS
    return CheckStatus.PENDING


def _context_recency_key(
    *,
    started_at: datetime | None,
    completed_at: datetime | None,
    index: int,
) -> tuple[bool, datetime, datetime, int]:
    earliest = datetime.min.replace(tzinfo=UTC)
    return (
        started_at is not None or completed_at is not None,
        started_at or completed_at or earliest,
        completed_at or earliest,
        index,
    )


class GitHubChecks:
    def __init__(
        self,
        *,
        client: GitHubCliClient,
        get_pull_request: Callable[[int], PullRequestSnapshot],
    ) -> None:
        self.client = client
        self.get_pull_request = get_pull_request
        self._batched_required: dict[int, CheckSnapshot] = {}

    def prime_required_snapshots(self, numbers: tuple[int, ...]) -> None:
        """Prime an observation-only cache using bounded GraphQL batches."""

        self._batched_required = batch_required_snapshots(self.client, numbers)

    def _required_snapshot_live(
        self, number: int, *, before: PullRequestSnapshot
    ) -> CheckSnapshot:
        argv = (
            "gh",
            "pr",
            "checks",
            str(number),
            "--required",
            "--json",
            "name,state,startedAt,completedAt",
        )
        output = self.client.run(argv, allow_nonzero=True)
        empty_result = _NO_REQUIRED_CHECKS_RE.fullmatch(output)
        if empty_result is not None:
            if empty_result.group(1) != before.branch:
                raise AdapterPayloadError(
                    "GitHub required checks zero-result branch does not match "
                    "the exact PR"
                )
            payload: object = []
        else:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as error:
                raise AdapterPayloadError(
                    f"invalid JSON from {' '.join(argv)}"
                ) from error
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub required checks must be a JSON list")
        observations: dict[str, tuple[str, datetime | None, datetime | None, int]] = {}
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise AdapterPayloadError(f"required check[{index}] is not an object")
            name = item.get("name")
            state = item.get("state")
            if type(name) is not str or type(state) is not str:
                raise AdapterPayloadError(f"required check[{index}] is malformed")
            started_at = parse_optional_timestamp(
                item.get("startedAt"),
                field=f"required check[{index}] startedAt",
            )
            completed_at = parse_optional_timestamp(
                item.get("completedAt"),
                field=f"required check[{index}] completedAt",
            )
            candidate = (state, started_at, completed_at, index)
            previous = observations.get(name)
            if previous is None or _context_recency_key(
                started_at=started_at,
                completed_at=completed_at,
                index=index,
            ) >= _context_recency_key(
                started_at=previous[1],
                completed_at=previous[2],
                index=previous[3],
            ):
                observations[name] = candidate
        after = self.get_pull_request(number)
        if before.head_sha != after.head_sha:
            raise CompareAndSwapConflict(
                "PR HEAD changed while reading required checks"
            )
        starts = [item[1] for item in observations.values()]
        completions = [item[2] for item in observations.values()]
        return CheckSnapshot(
            status=_status_from_states(
                {item[0].upper() for item in observations.values()}
            ),
            head_sha=after.head_sha,
            observed_at=datetime.now(tz=UTC),
            names=tuple(sorted(observations)),
            started_at=(
                min(item for item in starts if item is not None)
                if starts and all(item is not None for item in starts)
                else None
            ),
            completed_at=(
                max(item for item in completions if item is not None)
                if completions and all(item is not None for item in completions)
                else None
            ),
        )

    def required_snapshot(self, number: int) -> CheckSnapshot:
        before = self.get_pull_request(number)
        batched = self._batched_required.pop(number, None)
        if batched is not None and batched.head_sha == before.head_sha:
            return batched
        return self._required_snapshot_live(number, before=before)

"""Bounded convergence for GitHub PR HEAD reads after a branch push."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence

from ..domain.errors import CompareAndSwapConflict
from ..domain.observations import PullRequestSnapshot

DEFAULT_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.2, 0.4, 0.8, 1.6)
MAX_TOTAL_RETRY_SECONDS = 10.0


def wait_for_pull_request_head(
    query: Callable[[int], PullRequestSnapshot],
    *,
    number: int,
    expected_head_sha: str,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    sleeper: Callable[[float], None] = time.sleep,
) -> PullRequestSnapshot:
    """Read a PR until its HEAD reflects an already verified branch push.

    Only an exact HEAD mismatch is retried. Query errors and an exhausted
    mismatch budget remain fail-closed, so this helper cannot conceal an
    external mutation or an unavailable GitHub API.
    """

    if type(number) is not int or number < 1:
        raise ValueError("pull request number must be a positive integer")
    if not isinstance(expected_head_sha, str) or not expected_head_sha:
        raise ValueError("expected pull request HEAD must be non-empty text")
    delays = tuple(retry_delays)
    if any(
        not isinstance(delay, (int, float))
        or not math.isfinite(float(delay))
        or float(delay) < 0
        for delay in delays
    ):
        raise ValueError("retry delays must be finite and non-negative")
    if sum(float(delay) for delay in delays) > MAX_TOTAL_RETRY_SECONDS:
        raise ValueError("retry delay budget is too large")

    observed_head = "<no read>"
    for attempt, delay in enumerate((0.0, *delays)):
        if attempt:
            sleeper(float(delay))
        snapshot = query(number)
        observed_head = snapshot.head_sha
        if observed_head == expected_head_sha:
            return snapshot

    raise CompareAndSwapConflict(
        "PR HEAD did not converge after branch push: "
        f"expected {expected_head_sha}, observed {observed_head}"
    )

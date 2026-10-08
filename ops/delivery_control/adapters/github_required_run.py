"""Decide whether an active exact ``pr-gate`` run is waiting or truly wedged.

A queued run is *waiting* when GitHub simply has no free runner for it (the
macOS pool is routinely saturated for hours) or when part of its jobs already
executes.  Cancelling such a run destroys green evidence and re-queues behind
the same backlog.  Only a run that is queued at the run level, has not started
a single job and has outlived a generous threshold is the wedged case this
recovery path was written for.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import AdapterPayloadError
from .timestamps import parse_optional_timestamp

DEFAULT_WEDGED_RUN_AFTER = timedelta(hours=6)
WEDGED_RUN_AFTER_ENV = "KG_DELIVERY_WEDGED_RUN_AFTER_MINUTES"
_STARTED_JOB_STATUSES = frozenset({"in_progress", "completed"})


@dataclass(frozen=True)
class JobCounts:
    total: int
    started: int


@dataclass(frozen=True)
class ActiveRunAssessment:
    wedged: bool
    reason: str


def wedged_run_after(environ: Mapping[str, str] | None = None) -> timedelta:
    """Return the configurable age after which a zero-job queued run is wedged."""

    raw = (os.environ if environ is None else environ).get(WEDGED_RUN_AFTER_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_WEDGED_RUN_AFTER
    try:
        minutes = int(raw.strip())
    except ValueError as error:
        raise AdapterPayloadError(
            f"{WEDGED_RUN_AFTER_ENV} must be a positive integer number of minutes"
        ) from error
    if minutes <= 0:
        raise AdapterPayloadError(
            f"{WEDGED_RUN_AFTER_ENV} must be a positive integer number of minutes"
        )
    return timedelta(minutes=minutes)


def run_jobs_command(*, database_id: int) -> tuple[str, ...]:
    return ("gh", "run", "view", str(database_id), "--json", "jobs")


def parse_job_counts(payload: object) -> JobCounts:
    """Count jobs of one run; any malformed evidence fails closed (no cancel)."""

    jobs = payload.get("jobs") if isinstance(payload, Mapping) else None
    if not isinstance(jobs, list):
        raise AdapterPayloadError("GitHub run jobs payload must contain a jobs list")
    started = 0
    for index, job in enumerate(jobs):
        if not isinstance(job, Mapping) or type(job.get("status")) is not str:
            raise AdapterPayloadError(f"GitHub run job[{index}] is malformed")
        began = parse_optional_timestamp(
            job.get("startedAt"), field=f"GitHub run job[{index}] startedAt"
        )
        # gh renders a never-started job's startedAt as the zero time.
        if (
            job["status"].casefold() in _STARTED_JOB_STATUSES
            or began is not None
            and began.year > 1
        ):
            started += 1
    return JobCounts(total=len(jobs), started=started)


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def assess_active_run(
    *,
    database_id: int,
    status: str,
    created_at: datetime,
    now: datetime,
    threshold: timedelta,
    load_jobs: Callable[[], JobCounts],
) -> ActiveRunAssessment:
    """Return ``wedged=True`` only for an aged, run-level queued, zero-job run."""

    age = now - created_at
    prefix = f"run {database_id} is {status} for {_minutes(age)}m"
    if status != "queued":
        return ActiveRunAssessment(
            False, f"{prefix}; non-queued active runs are never cancelled"
        )
    if age < threshold:
        return ActiveRunAssessment(
            False,
            f"{prefix}, below the {_minutes(threshold)}m wedged threshold; "
            "treating it as a legitimate runner wait",
        )
    counts = load_jobs()
    if counts.started > 0:
        return ActiveRunAssessment(
            False,
            f"{prefix}; {counts.started} of {counts.total} jobs already started, "
            "so the run is partially executing and is not cancelled",
        )
    return ActiveRunAssessment(
        True,
        f"{prefix}, past the {_minutes(threshold)}m wedged threshold with "
        f"0 of {counts.total} jobs started",
    )

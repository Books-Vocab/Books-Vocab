"""trigger_required must never kill a run that is waiting or partially running."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters import github_required_run
from delivery_control.adapters.errors import AdapterPayloadError
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.ports.process import CommandResult

HEAD = "b" * 40
LIST = (
    "gh",
    "run",
    "list",
    "--workflow",
    "pr-gate.yml",
    "--branch",
    "feat/one",
    "--event",
    "pull_request",
    "--commit",
    HEAD,
    "--limit",
    "20",
    "--json",
    "databaseId,headBranch,headSha,event,status,conclusion,createdAt",
)
JOBS = ("gh", "run", "view", "12345", "--json", "jobs")
CANCEL = ("gh", "run", "cancel", "--force", "12345")
RERUN = ("gh", "run", "rerun", "12345")
RERUN_FAILED = ("gh", "run", "rerun", "--failed", "12345")
ZERO_TIME = "0001-01-01T00:00:00Z"


class ScriptedRunner:
    """Answers by argv (FIFO per argv) so tests assert decisions, not call order."""

    def __init__(self, script: dict[tuple[str, ...], list[CommandResult]]) -> None:
        self.script = {argv: list(results) for argv, results in script.items()}
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        if argv not in self.script or not self.script[argv]:
            raise AssertionError(f"unexpected command: {argv}")
        queue = self.script[argv]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _ok(argv: tuple[str, ...], payload: object = "") -> CommandResult:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return CommandResult(argv, 0, body, "")


def _run(
    *, status: str, conclusion: str | None, age: timedelta
) -> list[dict[str, object]]:
    created = datetime.now(tz=UTC) - age
    return [
        {
            "databaseId": 12345,
            "headBranch": "feat/one",
            "headSha": HEAD,
            "event": "pull_request",
            "status": status,
            "conclusion": conclusion,
            "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    ]


def _jobs(*states: str) -> dict[str, object]:
    return {
        "jobs": [
            {
                "name": f"job-{index}",
                "status": state,
                "conclusion": "success" if state == "completed" else None,
                "startedAt": ZERO_TIME if state == "queued" else "2026-10-08T00:00:00Z",
            }
            for index, state in enumerate(states)
        ]
    }


def _trigger(runner: ScriptedRunner):
    return GitHubCliAdapter(runner=runner).trigger_required(
        number=12, branch="feat/one", base_sha="a" * 40, head_sha=HEAD
    )


def _no_mutation(runner: ScriptedRunner) -> None:
    assert CANCEL not in runner.calls
    assert RERUN not in runner.calls
    assert RERUN_FAILED not in runner.calls


def test_queued_20_minutes_with_started_jobs_is_not_cancelled() -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST,
                    _run(status="queued", conclusion=None, age=timedelta(minutes=20)),
                )
            ],
            JOBS: [_ok(JOBS, _jobs("completed", "in_progress", "queued"))],
        }
    )

    outcome = _trigger(runner)

    assert outcome.command == ()
    assert outcome.dispatched is False
    assert outcome.action == "wait"
    assert "legitimate runner wait" in outcome.reason
    _no_mutation(runner)


def test_aged_queued_run_with_started_jobs_is_not_cancelled() -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST, _run(status="queued", conclusion=None, age=timedelta(hours=9))
                )
            ],
            JOBS: [_ok(JOBS, _jobs("completed", "completed", "queued"))],
        }
    )

    outcome = _trigger(runner)

    assert outcome.action == "wait"
    assert "2 of 3 jobs already started" in outcome.reason
    _no_mutation(runner)


def test_queued_20_minutes_zero_jobs_started_on_busy_macos_queue_is_not_cancelled() -> (
    None
):
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST,
                    _run(status="queued", conclusion=None, age=timedelta(minutes=20)),
                )
            ],
        }
    )

    outcome = _trigger(runner)

    assert outcome.dispatched is False
    assert outcome.action == "wait"
    assert "below the 360m wedged threshold" in outcome.reason
    assert runner.calls == [LIST]


def test_in_progress_run_is_never_cancelled_nor_inspected() -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST,
                    _run(
                        status="in_progress", conclusion=None, age=timedelta(hours=12)
                    ),
                )
            ]
        }
    )

    outcome = _trigger(runner)

    assert outcome.action == "wait"
    assert "non-queued active runs are never cancelled" in outcome.reason
    assert runner.calls == [LIST]


def test_wedged_run_past_default_threshold_with_zero_jobs_is_recovered() -> None:
    queued = _run(status="queued", conclusion=None, age=timedelta(hours=7))
    cancelled = _run(status="completed", conclusion="cancelled", age=timedelta(hours=7))
    runner = ScriptedRunner(
        {
            LIST: [_ok(LIST, queued), _ok(LIST, cancelled)],
            JOBS: [_ok(JOBS, _jobs("queued", "queued"))],
            CANCEL: [_ok(CANCEL)],
            RERUN: [_ok(RERUN)],
        }
    )

    outcome = _trigger(runner)

    assert outcome.command == RERUN
    assert outcome.action == "recover_wedged_run"
    assert "0 of 2 jobs started" in outcome.reason
    assert runner.calls == [LIST, JOBS, CANCEL, LIST, RERUN]


def test_wedged_run_with_no_jobs_at_all_is_recovered() -> None:
    queued = _run(status="queued", conclusion=None, age=timedelta(hours=7))
    cancelled = _run(status="completed", conclusion="cancelled", age=timedelta(hours=7))
    runner = ScriptedRunner(
        {
            LIST: [_ok(LIST, queued), _ok(LIST, cancelled)],
            JOBS: [_ok(JOBS, {"jobs": []})],
            CANCEL: [_ok(CANCEL)],
            RERUN: [_ok(RERUN)],
        }
    )

    assert _trigger(runner).action == "recover_wedged_run"


def test_wedged_threshold_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(github_required_run.WEDGED_RUN_AFTER_ENV, "30")
    queued = _run(status="queued", conclusion=None, age=timedelta(minutes=45))
    cancelled = _run(
        status="completed", conclusion="cancelled", age=timedelta(minutes=45)
    )
    runner = ScriptedRunner(
        {
            LIST: [_ok(LIST, queued), _ok(LIST, cancelled)],
            JOBS: [_ok(JOBS, _jobs("queued"))],
            CANCEL: [_ok(CANCEL)],
            RERUN: [_ok(RERUN)],
        }
    )

    outcome = _trigger(runner)

    assert outcome.action == "recover_wedged_run"
    assert "past the 30m wedged threshold" in outcome.reason


def test_raised_threshold_protects_a_run_the_default_would_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(github_required_run.WEDGED_RUN_AFTER_ENV, "1440")
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST, _run(status="queued", conclusion=None, age=timedelta(hours=7))
                )
            ]
        }
    )

    outcome = _trigger(runner)

    assert outcome.action == "wait"
    assert "below the 1440m wedged threshold" in outcome.reason
    _no_mutation(runner)


@pytest.mark.parametrize("raw", ["0", "-5", "six", "1.5"])
def test_invalid_threshold_fails_closed_before_any_cancel(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(github_required_run.WEDGED_RUN_AFTER_ENV, raw)
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST, _run(status="queued", conclusion=None, age=timedelta(hours=9))
                )
            ]
        }
    )

    with pytest.raises(AdapterPayloadError, match="positive integer"):
        _trigger(runner)

    _no_mutation(runner)


def test_malformed_jobs_evidence_fails_closed_without_cancel() -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST, _run(status="queued", conclusion=None, age=timedelta(hours=9))
                )
            ],
            JOBS: [_ok(JOBS, {"jobs": "nope"})],
        }
    )

    with pytest.raises(AdapterPayloadError, match="jobs list"):
        _trigger(runner)

    _no_mutation(runner)


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_terminal_failure_prefers_rerun_failed_jobs(conclusion: str) -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST,
                    _run(
                        status="completed",
                        conclusion=conclusion,
                        age=timedelta(hours=1),
                    ),
                )
            ],
            RERUN_FAILED: [_ok(RERUN_FAILED)],
        }
    )

    outcome = _trigger(runner)

    assert outcome.command == RERUN_FAILED
    assert outcome.action == "rerun_failed_jobs"
    assert conclusion in outcome.reason
    assert runner.calls == [LIST, RERUN_FAILED]


def test_terminal_non_job_failure_falls_back_to_full_rerun() -> None:
    runner = ScriptedRunner(
        {
            LIST: [
                _ok(
                    LIST,
                    _run(
                        status="completed",
                        conclusion="startup_failure",
                        age=timedelta(hours=1),
                    ),
                )
            ],
            RERUN: [_ok(RERUN)],
        }
    )

    outcome = _trigger(runner)

    assert outcome.command == RERUN
    assert outcome.action == "rerun"

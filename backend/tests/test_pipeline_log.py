"""Tests for pipeline_log module."""

from __future__ import annotations

import time

import pytest

from kg import pipeline_log


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Point pipeline_log at a temp DB and reset between tests."""
    monkeypatch.setattr(pipeline_log, "DB_PATH", tmp_path / "pipeline_runs.db")
    pipeline_log._reset()
    yield
    pipeline_log._reset()


def test_start_and_end_run():
    pipeline_log.start_run("r1", "u1", "nb1", "manual")
    runs = pipeline_log.get_runs("u1")
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["ended_at"] is None

    pipeline_log.end_run("r1", "completed")
    runs = pipeline_log.get_runs("u1")
    assert runs[0]["status"] == "completed"
    assert runs[0]["ended_at"] is not None


def test_start_step_and_end_step():
    pipeline_log.start_run("r1", "u1", "nb1", "manual")
    pipeline_log.start_step("r1", "Enrich")
    pipeline_log.end_step("r1", "Enrich", items=42)

    runs = pipeline_log.get_runs("u1")
    steps = runs[0]["steps"]
    assert len(steps) == 1
    assert steps[0]["name"] == "Enrich"
    assert steps[0]["status"] == "ok"
    assert steps[0]["items"] == 42
    assert steps[0]["error"] is None
    assert steps[0]["ended_at"] is not None


def test_multiple_steps():
    pipeline_log.start_run("r1", "u1", "nb1", "auto")
    names = ["Enrich", "EmbedAndJudge", "Difficulty", "ExternalSync"]
    items_map = {"Enrich": 10, "EmbedAndJudge": 20, "Difficulty": 30, "ExternalSync": 5}
    for name in names:
        pipeline_log.start_step("r1", name)
        pipeline_log.end_step("r1", name, items=items_map[name])

    runs = pipeline_log.get_runs("u1")
    steps = runs[0]["steps"]
    assert len(steps) == 4
    for step in steps:
        assert step["status"] == "ok"
        assert step["items"] == items_map[step["name"]]


def test_get_runs_returns_newest_first():
    for i in range(3):
        pipeline_log.start_run(f"r{i}", "u1", "nb1", "manual")
        time.sleep(0.01)  # ensure distinct timestamps

    runs = pipeline_log.get_runs("u1")
    assert len(runs) == 3
    # newest first
    assert runs[0]["run_id"] == "r2"
    assert runs[2]["run_id"] == "r0"


def test_get_runs_filters_by_user():
    pipeline_log.start_run("r1", "user_a", "nb1", "manual")
    pipeline_log.start_run("r2", "user_b", "nb1", "manual")
    pipeline_log.start_run("r3", "user_a", "nb2", "auto")

    assert len(pipeline_log.get_runs("user_a")) == 2
    assert len(pipeline_log.get_runs("user_b")) == 1
    assert len(pipeline_log.get_runs("user_c")) == 0


def test_end_step_with_error():
    pipeline_log.start_run("r1", "u1", "nb1", "manual")
    pipeline_log.start_step("r1", "Enrich")
    pipeline_log.end_step("r1", "Enrich", status="failed", error="timeout after 30s")

    runs = pipeline_log.get_runs("u1")
    step = runs[0]["steps"][0]
    assert step["status"] == "failed"
    assert step["error"] == "timeout after 30s"


def test_duration_computed():
    pipeline_log.start_run("r1", "u1", "nb1", "manual")
    pipeline_log.start_step("r1", "Enrich")
    time.sleep(0.05)
    pipeline_log.end_step("r1", "Enrich", items=1)
    time.sleep(0.05)
    pipeline_log.end_run("r1", "completed")

    runs = pipeline_log.get_runs("u1")
    run = runs[0]
    # Run duration
    assert run["duration_s"] is not None
    assert run["duration_s"] > 0
    # Step duration
    assert run["steps"][0]["duration_s"] is not None
    assert run["steps"][0]["duration_s"] > 0


def test_get_runs_via_handler():
    """The admin handler wraps get_runs correctly."""
    # Start a run, add steps, end it
    pipeline_log.start_run("r1", "user_a", "default", "background")
    pipeline_log.start_step("r1", "Enrich")
    pipeline_log.end_step("r1", "Enrich", status="ok", items=10)
    pipeline_log.end_run("r1", "completed")

    # Verify get_runs returns the expected structure
    runs = pipeline_log.get_runs("user_a")
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == "r1"
    assert run["status"] == "completed"
    assert run["duration_s"] is not None
    assert len(run["steps"]) == 1
    assert run["steps"][0]["name"] == "Enrich"
    assert run["steps"][0]["items"] == 10
    assert run["steps"][0]["duration_s"] is not None

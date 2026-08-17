"""Contracts for the local timing ledger and ETA core."""

from __future__ import annotations

import json
import sqlite3
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))
from lib import test_timing_store as store  # noqa: E402
import test_timing  # noqa: E402


def _record(db: Path, duration: float, *, status: str = "pass", **kwargs):
    values = dict(
        db_path=db, run_id="run-1", bundle_id="bundle-1",
        command_key="ops.orchestrator.gate", selector="gate.py::test",
        suite="worktree-orchestrator", tier="S1", host="oscar",
        runtime_version="python-3.13", xcode_or_device=None, dataset=None,
        head_sha="a" * 40, resource_class="ops-python",
        started_at="2026-08-17T00:00:00+00:00",
        finished_at="2026-08-17T00:00:01+00:00", duration_s=duration,
        status=status, exit_code=0 if status == "pass" else 1,
        cache_status="warm", timing_source="pytest",
    )
    values.update(kwargs)
    return store.record_measurement(**values)


def test_schema_contains_required_fields_and_no_raw_argv(tmp_path):
    db = tmp_path / "timing.sqlite3"
    store.initialize(db)
    with store.connection(db) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(measurements)")}
    assert {
        "measurement_id", "run_id", "bundle_id", "command_key", "measurement_scope", "selector", "suite",
        "tier", "host", "runtime_version", "xcode_or_device", "dataset", "head_sha",
        "resource_class", "started_at", "finished_at", "duration_s", "status",
        "exit_code", "cache_status", "timing_source",
    } <= columns
    assert "raw_argv" not in columns


def test_three_normal_samples_get_medium_confidence_and_timeout_is_excluded(tmp_path):
    db = tmp_path / "timing.sqlite3"
    for duration in (10.0, 12.0, 18.0):
        assert _record(db, duration)["recorded"] is True
    assert _record(db, 999.0, status="timeout", duration_status="interrupted")["recorded"]
    estimate = store.estimate(
        "ops.orchestrator.gate", db_path=db, selector="gate.py::test",
        suite="worktree-orchestrator", tier="S1", host="oscar",
        runtime_version="python-3.13", resource_class="ops-python",
        cache_status="warm",
    )
    assert estimate["confidence"] == "medium"
    assert estimate["sample_count"] == 3
    assert estimate["p90_s"] < 999
    assert estimate["lower_s"] <= estimate["estimate_s"] <= estimate["upper_s"]


def test_missing_exact_dimensions_use_low_confidence_same_command_fallback(tmp_path):
    db = tmp_path / "timing.sqlite3"
    _record(db, 7.0)
    estimate = store.estimate(
        "ops.orchestrator.gate", db_path=db, host="felix",
        runtime_version="python-3.14", resource_class="ops-python",
    )
    assert estimate["confidence"] == "low"
    assert estimate["sample_count"] == 1
    assert "fallback" in estimate["basis"]


def test_command_and_per_test_samples_never_mix_in_eta(tmp_path):
    db = tmp_path / "timing.sqlite3"
    _record(db, 10.0)
    _record(db, 0.001, measurement_scope="test")
    estimate = store.estimate(
        "ops.orchestrator.gate", db_path=db, selector="gate.py::test",
        suite="worktree-orchestrator", tier="S1", host="oscar",
        runtime_version="python-3.13", resource_class="ops-python",
        cache_status="warm",
    )
    assert estimate["estimate_s"] == 10.0
    assert estimate["sample_count"] == 1


def test_bundle_eta_is_unknown_when_any_task_has_no_history(tmp_path):
    db = tmp_path / "timing.sqlite3"
    _record(db, 7.0)
    estimate = store.estimate_bundle([
        {"id": "known", "command_key": "ops.orchestrator.gate", "selector": "gate.py::test"},
        {"id": "unknown", "command_key": "ops.orchestrator.missing"},
    ], db_path=db)
    assert estimate["estimate_s"] is None
    assert estimate["unknown_tasks"] == ["unknown"]


def test_bundle_eta_preserves_selector_suite_and_tier_dimensions(tmp_path):
    db = tmp_path / "timing.sqlite3"
    common = dict(
        db_path=db, run_id="run", bundle_id="bundle", suite="suite", tier="S1", host="oscar",
        runtime_version="python-3.13", xcode_or_device=None, dataset=None, head_sha="b" * 40,
        resource_class="ops-python", started_at="2026-08-17T00:00:00+00:00",
        finished_at="2026-08-17T00:00:01+00:00", status="pass", exit_code=0,
        cache_status="warm", timing_source="test",
    )
    store.record_measurement(command_key="ops.bundle", selector="A", duration_s=1.0, **common)
    store.record_measurement(command_key="ops.bundle", selector="B", duration_s=100.0, **common)
    estimate = store.estimate_bundle([
        {"id": "a", "command_key": "ops.bundle", "selector": "A", "suite": "suite", "tier": "S1",
         "host": "oscar", "runtime_version": "python-3.13", "resource_class": "ops-python",
         "cache_status": "warm"},
    ], db_path=db)
    assert estimate["estimate_s"] == 1.0


def test_concurrent_writes_are_transactional(tmp_path):
    db = tmp_path / "timing.sqlite3"
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda value: _record(db, float(value)), range(24)))
    assert all(result["recorded"] for result in results)
    with store.connection(db) as conn:
        assert conn.execute("SELECT count(*) FROM measurements").fetchone()[0] == 24


def test_corrupt_store_is_non_blocking_evidence(tmp_path):
    db = tmp_path / "timing.sqlite3"
    db.write_bytes(b"not sqlite")
    estimate = store.estimate("unknown.command", db_path=db)
    assert estimate["available"] is False
    assert estimate["estimate_s"] is None


def test_prune_keeps_aggregated_rollup(tmp_path):
    db = tmp_path / "timing.sqlite3"
    _record(db, 11.0)
    with store.connection(db) as conn:
        conn.execute("UPDATE measurements SET created_at = '2020-01-01T00:00:00+00:00'")
    result = store.prune(db)
    assert result["removed"] == 1
    assert result["rollups"] == 1
    with store.connection(db) as conn:
        assert conn.execute("SELECT count(*) FROM timing_rollups").fetchone()[0] == 1
    estimate = store.estimate("ops.orchestrator.gate", db_path=db, selector="gate.py::test",
                              suite="worktree-orchestrator", tier="S1", host="oscar",
                              runtime_version="python-3.13", resource_class="ops-python",
                              cache_status="warm")
    assert estimate["sample_count"] == 1


def test_prune_initializes_empty_store_and_corrupt_store_is_non_blocking(tmp_path):
    db = tmp_path / "new.sqlite3"
    assert store.prune(db)["available"] is True
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not sqlite")
    assert store.prune(corrupt)["available"] is False


def test_weighted_rollup_survives_multiple_prunes_without_batch_bias(tmp_path):
    db = tmp_path / "timing.sqlite3"
    for index in range(1000):
        _record(db, 10.0, run_id=f"old-{index}")
    with store.connection(db) as conn:
        conn.execute("UPDATE measurements SET created_at = '2020-01-01T00:00:00+00:00'")
    assert store.prune(db)["rollups"] == 1

    for index in range(2):
        _record(db, 100.0, run_id=f"new-{index}")
    with store.connection(db) as conn:
        conn.execute("UPDATE measurements SET created_at = '2020-01-01T00:00:00+00:00'")
    assert store.prune(db)["rollups"] == 1

    with store.connection(db) as conn:
        row = conn.execute("SELECT sample_count, weighted_samples_json FROM timing_rollups").fetchone()
    assert row["sample_count"] == 1002
    weighted = json.loads(row["weighted_samples_json"])
    assert sum(float(item[1]) for item in weighted) == pytest.approx(1002.0)
    estimate = store.estimate(
        "ops.orchestrator.gate", db_path=db, selector="gate.py::test",
        suite="worktree-orchestrator", tier="S1", host="oscar",
        runtime_version="python-3.13", resource_class="ops-python", cache_status="warm",
    )
    assert estimate["sample_count"] == 1002
    assert estimate["estimate_s"] == 10.0


def test_legacy_rollup_migration_preserves_representative_weight(tmp_path):
    db = tmp_path / "timing.sqlite3"
    store.initialize(db)
    old_dimensions = [
        "ops.orchestrator.gate", "gate.py::test", "worktree-orchestrator", "S1",
        "oscar", "python-3.13", None, None, "ops-python", "warm",
    ]
    rollup_key = json.dumps(old_dimensions, ensure_ascii=False, separators=(",", ":"))
    with store.connection(db) as conn:
        conn.execute(
            """INSERT INTO timing_rollups (
                rollup_key, command_key, resource_class, sample_count, sum_s,
                min_s, max_s, p50_s, p90_s, durations_json,
                weighted_samples_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollup_key, "ops.orchestrator.gate", "ops-python", 1000, 50000.0,
                10.0, 100.0, 10.0, 100.0, json.dumps([10.0, 100.0]),
                "[]", "2020-01-01T00:00:00+00:00",
            ),
        )
    estimate = store.estimate(
        "ops.orchestrator.gate", db_path=db, selector="gate.py::test",
        suite="worktree-orchestrator", tier="S1", host="oscar",
        runtime_version="python-3.13", resource_class="ops-python",
        cache_status="warm",
    )
    assert estimate["sample_count"] == 1000
    assert estimate["estimate_s"] == 10.0


def test_bundle_eta_serializes_same_resource_lane(tmp_path):
    db = tmp_path / "timing.sqlite3"
    _record(db, 10.0)
    tasks = [
        {"command_key": "ops.orchestrator.gate", "resource_class": "ops-python"},
        {"command_key": "ops.orchestrator.gate", "resource_class": "ops-python"},
    ]
    sequential = store.estimate_bundle(tasks, db_path=db)
    parallel = store.estimate_bundle(tasks, db_path=db, parallel=True)
    assert sequential["estimate_s"] >= parallel["estimate_s"]
    assert "resource lanes" in parallel["basis"]


def test_parallel_eta_lower_bound_uses_slowest_resource_lane(tmp_path):
    db = tmp_path / "timing.sqlite3"
    common = dict(
        db_path=db, run_id="run", bundle_id="bundle", suite="suite", tier="S1", host="oscar",
        runtime_version="python-3.13", xcode_or_device=None, dataset=None, head_sha="b" * 40,
        started_at="2026-08-17T00:00:00+00:00", finished_at="2026-08-17T00:00:01+00:00",
        selector=None, status="pass", exit_code=0, cache_status="warm", timing_source="bundle",
    )
    store.record_measurement(command_key="ops.fast", resource_class="lane-fast",
                             duration_s=1.0, **common)
    store.record_measurement(command_key="ops.slow", resource_class="lane-slow",
                             duration_s=10.0, **common)
    estimate = store.estimate_bundle([
        {"command_key": "ops.fast", "resource_class": "lane-fast"},
        {"command_key": "ops.slow", "resource_class": "lane-slow"},
    ], db_path=db, parallel=True)
    assert estimate["lower_s"] == 10.0


def test_status_and_wait_cli_read_atomic_status(tmp_path, capsys):
    status_dir = tmp_path / ".cache" / "test_runs"
    status_dir.mkdir(parents=True)
    (status_dir / "run-1.json").write_text(
        json.dumps({"run_id": "run-1", "status": "passed"})
    )
    args = Namespace(run_id="run-1", repo=str(tmp_path), json=True)
    assert test_timing.cmd_status(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_status_rejects_path_traversal_and_wait_timeout_is_bounded(tmp_path, capsys, monkeypatch):
    args = Namespace(run_id="../escape", repo=str(tmp_path), json=True)
    assert test_timing.cmd_status(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    sleeps = []
    monkeypatch.setattr(test_timing.time, "sleep", lambda seconds: sleeps.append(seconds))
    clock = iter((0.0, 0.0, 0.0, 0.2))
    monkeypatch.setattr(test_timing.time, "monotonic", lambda: next(clock))
    args = Namespace(run_id="run-missing", repo=str(tmp_path), json=True,
                     interval_s=60.0, timeout_s=0.1)
    assert test_timing.cmd_wait(args) == 1
    assert all(seconds <= 0.1 for seconds in sleeps)


def test_unknown_timing_command_is_rejected():
    with pytest.raises(SystemExit) as exc:
        test_timing.build_parser().parse_args(["unknown"])
    assert exc.value.code == 2

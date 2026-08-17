"""Contracts for per-test plugin output and the timing bundle runner."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))
import test_timing  # noqa: E402


def _manifest(tmp_path: Path, tasks: list[dict]) -> Path:
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({
        "schema": "kg.test.bundle.v1",
        "bundle_id": "timing-test-bundle",
        "tier": "S1",
        "tasks": tasks,
    }))
    return path


def _command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_pytest_plugin_emits_per_test_jsonl(tmp_path):
    test_file = tmp_path / "sample_test.py"
    test_file.write_text("def test_one(): pass\ndef test_two(): assert 1 == 1\n")
    output = tmp_path / "measurements.jsonl"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "ops" / "lib"))
    result = __import__("subprocess").run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "pytest_timing_plugin",
            "--kg-timing-output", str(output), "--kg-timing-command-key", "pytest.sample",
            str(test_file),
        ], cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["command_key"] == "pytest.sample" for row in rows)
    assert all(row["duration_s"] >= 0 for row in rows)


def test_bundle_runner_observes_dependencies_and_resource_lanes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    manifest = _manifest(tmp_path, [
        {"id": "a", "command_key": "command.a", "command": _command("print('a')"),
         "resource_class": "lane-a"},
        {"id": "b", "command_key": "command.b", "command": _command("print('b')"),
         "depends_on": ["a"], "resource_class": "lane-a"},
        {"id": "c", "command_key": "command.c", "command": _command("print('c')"),
         "resource_class": "lane-c"},
    ])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-deps", json=True)
    assert test_timing.cmd_run_bundle(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert {row["id"] for row in payload["tasks"]} == {"a", "b", "c"}
    assert all(row["timing_recorded"] for row in payload["tasks"])
    saved = json.loads((tmp_path / ".cache" / "test_runs" / "run-deps.json").read_text())
    assert saved["status"] == "passed"


def test_bundle_warning_failure_does_not_fail_verdict(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    manifest = _manifest(tmp_path, [{
        "id": "warn", "command_key": "command.warn", "command": _command("raise SystemExit(3)"),
        "failure_policy": "warn", "resource_class": "lane",
    }])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-warn", json=True)
    assert test_timing.cmd_run_bundle(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["verdict"] == "warn"
    assert payload["warnings"] == ["warn"]


def test_bundle_rejects_unknown_failure_policy(tmp_path, capsys):
    manifest = _manifest(tmp_path, [{
        "id": "bad-policy", "command_key": "command.bad", "command": _command("pass"),
        "failure_policy": "blocK",
    }])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-bad-policy", json=True)
    assert test_timing.cmd_run_bundle(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_bundle_unknown_command_marks_task_error_not_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    manifest = _manifest(tmp_path, [{"id": "unknown", "command_key": "command.unknown"}])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-unknown", json=True)
    assert test_timing.cmd_run_bundle(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["tasks"][0]["status"] == "error"


def test_bundle_ingests_and_cleans_xdist_sidecar_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    base = tmp_path / "timing.jsonl"
    sidecar = tmp_path / "timing.jsonl.gw0"
    row = {"command_key": "pytest.xdist", "selector": "test_one", "suite": "pytest",
           "duration_s": 0.1, "status": "pass", "exit_code": 0}
    base.write_text(json.dumps(row) + "\n")
    sidecar.write_text(json.dumps({**row, "selector": "test_two"}) + "\n")
    count = test_timing._ingest_plugin_output(
        base, run_id="run-xdist", bundle_id="bundle", task={"resource_class": "lane"},
        started_at="2026-08-17T00:00:00+00:00", finished_at="2026-08-17T00:00:01+00:00",
    )
    assert count == 2
    assert not base.exists()
    assert not sidecar.exists()


def test_bundle_timeout_is_terminal_and_not_a_normal_sample(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    manifest = _manifest(tmp_path, [{
        "id": "slow", "command_key": "command.slow",
        "command": _command("import time; time.sleep(0.3)"),
        "timeout_s": 0.05, "resource_class": "lane",
    }])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-timeout", json=True)
    assert test_timing.cmd_run_bundle(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["tasks"][0]["status"] == "timeout"
    estimate = test_timing.store.estimate("command.slow", db_path=tmp_path / "timing.sqlite3")
    assert estimate["sample_count"] == 0


def test_bundle_retries_failed_task_and_records_each_attempt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("KG_TEST_TIMING_DB", str(tmp_path / "timing.sqlite3"))
    marker = tmp_path / "attempts.txt"
    code = (
        "from pathlib import Path; "
        f"p=Path({str(marker)!r}); n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); import sys; sys.exit(3) if n == 0 else None"
    )
    manifest = _manifest(tmp_path, [{
        "id": "retry", "command_key": "command.retry", "command": _command(code),
        "retry": 1, "resource_class": "lane",
    }])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-retry", json=True)
    assert test_timing.cmd_run_bundle(args) == 0
    payload = json.loads(capsys.readouterr().out)
    row = payload["tasks"][0]
    assert row["status"] == "passed"
    assert row["attempts"] == 2
    assert [attempt["status"] for attempt in row["attempt_results"]] == ["failed", "passed"]
    assert test_timing.store.estimate("command.retry", db_path=tmp_path / "timing.sqlite3")["sample_count"] == 2


def test_bundle_keyboard_interrupt_marks_pending_and_running_tasks_cancelled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KG_TASK_REGISTRY_PATH", str(tmp_path / "tasks.json"))
    manifest = _manifest(tmp_path, [{
        "id": "cancel", "command_key": "command.cancel", "command": _command("print('never')"),
        "resource_class": "lane",
    }])

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(test_timing, "_run_bundle_task", interrupt)
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-cancel", json=True)
    assert test_timing.cmd_run_bundle(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "cancelled"
    assert payload["verdict"] == "cancelled"
    assert payload["tasks"][0]["status"] == "cancelled"


def test_bundle_rejects_negative_retry_count(tmp_path, capsys):
    manifest = _manifest(tmp_path, [{
        "id": "bad-retry", "command_key": "command.bad", "command": _command("pass"),
        "retry": -1,
    }])
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-bad-retry", json=True)
    assert test_timing.cmd_run_bundle(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"


def test_invalid_bundle_is_rejected_without_starting_a_task(tmp_path, capsys):
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps({"schema": "wrong", "tasks": []}))
    args = Namespace(bundle=str(manifest), repo=str(tmp_path), run_id="run-bad", json=True)
    assert test_timing.cmd_run_bundle(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"

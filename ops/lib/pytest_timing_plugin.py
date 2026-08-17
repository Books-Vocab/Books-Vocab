"""Optional pytest plugin that emits per-test timing evidence.

The plugin is intentionally output-file based.  A worker can write its own JSONL file
and a parent runner can merge it later; a timing failure therefore never changes the
pytest exit status.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


_STATE: dict[str, Any] | None = None


def pytest_addoption(parser):
    group = parser.getgroup("kg-timing")
    group.addoption(
        "--kg-timing-output", action="store", default=None,
        help="write per-test timing JSONL evidence to this path",
    )
    group.addoption(
        "--kg-timing-command-key", action="store", default=None,
        help="stable semantic command key for the timing evidence",
    )


def _worker_path(path: Path) -> Path:
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return path
    return path.with_name(f"{path.name}.{worker}")


def pytest_configure(config):
    global _STATE
    try:
        raw_path = config.getoption("--kg-timing-output")
        if not raw_path:
            _STATE = None
            config._kg_timing = None
            return
        _STATE = {
            "path": _worker_path(Path(raw_path).expanduser().resolve()),
            "command_key": config.getoption("--kg-timing-command-key")
            or os.environ.get("KG_TEST_TIMING_COMMAND_KEY")
            or "pytest.selector",
            "tests": {},
            "error": None,
        }
        config._kg_timing = _STATE
    except Exception as exc:  # timing evidence must never alter the test verdict
        _STATE = {"path": None, "tests": {}, "error": str(exc)}
        config._kg_timing = _STATE


def pytest_runtest_logreport(report):
    state = _STATE
    if not state or state.get("path") is None:
        return
    try:
        item = state["tests"].setdefault(
            report.nodeid,
            {"nodeid": report.nodeid, "duration_s": 0.0, "status": "pass", "phases": {}},
        )
        duration = max(float(getattr(report, "duration", 0.0)), 0.0)
        item["duration_s"] += duration
        item["phases"][report.when] = duration
        if report.failed:
            item["status"] = "fail"
        elif report.skipped and item["status"] == "pass":
            item["status"] = "inconclusive"
    except Exception as exc:  # pragma: no cover - defensive instrumentation boundary
        state["error"] = f"{type(exc).__name__}: {exc}"


def _atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def pytest_sessionfinish(session, exitstatus):
    state = getattr(session.config, "_kg_timing", None)
    if not state or state.get("path") is None:
        return
    try:
        rows = []
        for item in state["tests"].values():
            rows.append({
                "schema": "kg.test.timing.measurement.v1",
                "command_key": state["command_key"],
                "selector": item["nodeid"],
                "suite": "pytest",
                "duration_s": round(float(item["duration_s"]), 6),
                "duration_status": "complete",
                "status": item["status"],
                "exit_code": int(exitstatus) if item["status"] != "pass" else 0,
                "timing_source": "pytest-plugin",
                "phases": item["phases"],
            })
        _atomic_jsonl(state["path"], rows)
    except Exception as exc:  # pragma: no cover - defensive instrumentation boundary
        state["error"] = f"{type(exc).__name__}: {exc}"

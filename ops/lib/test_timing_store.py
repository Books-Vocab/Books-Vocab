"""Local, gitignored timing ledger and conservative ETA calculations."""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = "kg.test.timing.v1"
RETENTION_DAYS = 90
NORMAL_STATUSES = frozenset({"pass", "fail", "inconclusive"})
EXCLUDED_STATUSES = frozenset({"timeout", "interrupted", "cancelled"})
DIMENSION_COLUMNS = (
    "command_key",
    "selector",
    "suite",
    "tier",
    "host",
    "runtime_version",
    "xcode_or_device",
    "dataset",
    "resource_class",
    "cache_status",
)
_SCHEMA_LOCK = threading.Lock()


class TimingStoreError(RuntimeError):
    """The timing store is unavailable; this is never a test verdict."""


def default_db_path(repo_root: str | Path | None = None) -> Path:
    override = os.environ.get("KG_TEST_TIMING_DB")
    if override:
        return Path(override).expanduser().resolve()
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    return root / ".cache" / "test_timing.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _connect(path: str | Path) -> sqlite3.Connection:
    db = Path(path).expanduser().resolve()
    db.parent.mkdir(parents=True, exist_ok=True)
    last_error: sqlite3.Error | None = None
    for attempt in range(12):
        connection = None
        try:
            connection = sqlite3.connect(db, timeout=10.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            return connection
        except sqlite3.OperationalError as exc:
            last_error = exc
            if connection is not None:
                connection.close()
            if "locked" not in str(exc).lower() or attempt == 11:
                break
            time.sleep(0.02 * (attempt + 1))
        except sqlite3.Error as exc:
            last_error = exc
            if connection is not None:
                connection.close()
            break
    assert last_error is not None
    raise TimingStoreError(f"timing store unavailable: {last_error}") from last_error


@contextmanager
def connection(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path or default_db_path())
    try:
        yield conn
    finally:
        conn.close()


def initialize(path: str | Path | None = None) -> Path:
    db = Path(path or default_db_path()).expanduser().resolve()
    with _SCHEMA_LOCK:
        with connection(db) as conn:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS measurements (
                measurement_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                bundle_id TEXT,
                command_key TEXT NOT NULL,
                selector TEXT,
                suite TEXT,
                tier TEXT,
                host TEXT,
                runtime_version TEXT,
                xcode_or_device TEXT,
                dataset TEXT,
                head_sha TEXT,
                resource_class TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_s REAL NOT NULL,
                status TEXT NOT NULL,
                exit_code INTEGER,
                cache_status TEXT,
                timing_source TEXT NOT NULL,
                duration_status TEXT NOT NULL DEFAULT 'complete',
                sample_eligible INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_measurements_lookup
                ON measurements(command_key, resource_class, host, created_at);
            CREATE TABLE IF NOT EXISTS timing_rollups (
                rollup_key TEXT PRIMARY KEY,
                command_key TEXT NOT NULL,
                resource_class TEXT,
                sample_count INTEGER NOT NULL,
                sum_s REAL NOT NULL,
                min_s REAL NOT NULL,
                max_s REAL NOT NULL,
                p50_s REAL NOT NULL,
                p90_s REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
                """
            )
    return db


def _eligible(status: str, duration_status: str, duration_s: float) -> bool:
    return (
        status in NORMAL_STATUSES
        and duration_status == "complete"
        and duration_s >= 0
    )


def record_measurement(
    *,
    db_path: str | Path | None = None,
    run_id: str,
    bundle_id: str | None,
    command_key: str,
    selector: str | None,
    suite: str | None,
    tier: str | None,
    host: str | None,
    runtime_version: str | None,
    xcode_or_device: str | None,
    dataset: str | None,
    head_sha: str | None,
    resource_class: str | None,
    started_at: str,
    finished_at: str,
    duration_s: float,
    status: str,
    exit_code: int | None,
    cache_status: str | None,
    timing_source: str,
    duration_status: str = "complete",
) -> dict[str, Any]:
    """Best-effort write; a ledger error is returned as evidence, not raised."""
    measurement_id = str(uuid.uuid4())
    eligible = _eligible(status, duration_status, float(duration_s))
    values = (
        measurement_id, run_id, bundle_id, command_key, selector, suite, tier, host,
        runtime_version, xcode_or_device, dataset, head_sha, resource_class,
        started_at, finished_at, float(duration_s), status, exit_code, cache_status,
        timing_source, duration_status, int(eligible), _iso(),
    )
    try:
        initialize(db_path)
        with connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO measurements (
                    measurement_id, run_id, bundle_id, command_key, selector, suite,
                    tier, host, runtime_version, xcode_or_device, dataset, head_sha,
                    resource_class, started_at, finished_at, duration_s, status,
                    exit_code, cache_status, timing_source, duration_status,
                    sample_eligible, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            conn.commit()
        return {
            "recorded": True,
            "measurement_id": measurement_id,
            "sample_eligible": eligible,
        }
    except (OSError, sqlite3.Error, TimingStoreError) as exc:
        return {
            "recorded": False,
            "sample_eligible": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["sample_eligible = 1"]
    args: list[Any] = []
    for key, value in filters.items():
        if value is None or key not in DIMENSION_COLUMNS:
            continue
        clauses.append(f"{key} = ?")
        args.append(value)
    return " AND ".join(clauses), args


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def _estimate_payload(
    durations: list[float], *, confidence: str, sample_count: int, basis: str,
    resource_wait_estimate_s: float = 0.0,
) -> dict[str, Any]:
    p50 = _percentile(durations, 0.50)
    p90 = _percentile(durations, 0.90)
    lower = max(0.0, _percentile(durations, 0.10))
    upper = max(p90, p50 * 1.25, lower)
    return {
        "schema": SCHEMA,
        "estimate_s": round(p50 + resource_wait_estimate_s, 2),
        "lower_s": round(lower, 2),
        "upper_s": round(upper + resource_wait_estimate_s, 2),
        "confidence": confidence,
        "sample_count": sample_count,
        "p50_s": round(p50, 2),
        "p90_s": round(p90, 2),
        "resource_wait_estimate_s": round(resource_wait_estimate_s, 2),
        "basis": basis,
    }


def estimate(
    command_key: str,
    *,
    db_path: str | Path | None = None,
    selector: str | None = None,
    suite: str | None = None,
    tier: str | None = None,
    host: str | None = None,
    runtime_version: str | None = None,
    xcode_or_device: str | None = None,
    dataset: str | None = None,
    resource_class: str | None = None,
    cache_status: str | None = None,
    resource_wait_estimate_s: float = 0.0,
) -> dict[str, Any]:
    filters = {
        "command_key": command_key, "selector": selector, "suite": suite,
        "tier": tier, "host": host, "runtime_version": runtime_version,
        "xcode_or_device": xcode_or_device, "dataset": dataset,
        "resource_class": resource_class, "cache_status": cache_status,
    }
    try:
        initialize(db_path)
        with connection(db_path) as conn:
            where, args = _where(filters)
            rows = conn.execute(
                f"SELECT duration_s FROM measurements WHERE {where} "
                "ORDER BY finished_at ASC", args,
            ).fetchall()
            basis = "exact command/environment samples"
            if not rows:
                fallback_filters = {
                    "command_key": command_key,
                    "resource_class": resource_class,
                }
                fallback_where, fallback_args = _where(fallback_filters)
                rows = conn.execute(
                    f"SELECT duration_s FROM measurements WHERE {fallback_where} "
                    "ORDER BY finished_at ASC", fallback_args,
                ).fetchall()
                basis = "same command/resource-class fallback"
            durations = [float(row["duration_s"]) for row in rows]
        if not durations:
            return _estimate_payload(
                [1.0], confidence="low", sample_count=0,
                basis="no history; one-second placeholder, measure this command",
                resource_wait_estimate_s=resource_wait_estimate_s,
            ) | {"estimate_s": None, "lower_s": None, "upper_s": None}
        confidence = "medium" if len(durations) >= 3 else "low"
        return _estimate_payload(
            durations, confidence=confidence, sample_count=len(durations), basis=basis,
            resource_wait_estimate_s=resource_wait_estimate_s,
        )
    except (OSError, sqlite3.Error, TimingStoreError) as exc:
        return {
            "schema": SCHEMA,
            "available": False,
            "estimate_s": None,
            "lower_s": None,
            "upper_s": None,
            "confidence": "low",
            "sample_count": 0,
            "p50_s": None,
            "p90_s": None,
            "resource_wait_estimate_s": resource_wait_estimate_s,
            "basis": "timing store unavailable; do not block the test verdict",
            "error": f"{type(exc).__name__}: {exc}",
        }


def estimate_bundle(
    tasks: list[dict[str, Any]],
    *,
    db_path: str | Path | None = None,
    parallel: bool = False,
    startup_cost_s: float = 0.0,
) -> dict[str, Any]:
    estimates = [
        estimate(
            str(task["command_key"]), db_path=db_path,
            resource_class=task.get("resource_class"),
            host=task.get("host"), runtime_version=task.get("runtime_version"),
            xcode_or_device=task.get("xcode_or_device"), dataset=task.get("dataset"),
            cache_status=task.get("cache_status"),
        )
        for task in tasks
    ]
    known = [item for item in estimates if item.get("estimate_s") is not None]
    if not known:
        return {
            "schema": SCHEMA, "estimate_s": None, "lower_s": None, "upper_s": None,
            "confidence": "low", "sample_count": 0, "basis": "no task history",
            "tasks": estimates,
        }
    if parallel:
        lanes: dict[str, list[dict[str, Any]]] = {}
        for task, item in zip(tasks, estimates):
            lanes.setdefault(str(task.get("resource_class") or "default"), []).append(item)
        lane_upper = [sum(float(x.get("upper_s") or 0) for x in lane) for lane in lanes.values()]
        lane_lower = [sum(float(x.get("lower_s") or 0) for x in lane) for lane in lanes.values()]
        lane_estimate = [sum(float(x.get("estimate_s") or 0) for x in lane) for lane in lanes.values()]
        lower, upper, estimate_s = min(lane_lower), max(lane_upper), max(lane_estimate)
        basis = "parallel resource lanes; same resource class serialized"
    else:
        lower = sum(float(x.get("lower_s") or 0) for x in known)
        upper = sum(float(x.get("upper_s") or 0) for x in known)
        estimate_s = sum(float(x.get("estimate_s") or 0) for x in known)
        basis = "sequential task estimates"
    return {
        "schema": SCHEMA, "estimate_s": round(estimate_s + startup_cost_s, 2),
        "lower_s": round(lower + startup_cost_s, 2),
        "upper_s": round(upper + startup_cost_s, 2),
        "confidence": "medium" if all(x.get("confidence") == "medium" for x in known) else "low",
        "sample_count": sum(int(x.get("sample_count") or 0) for x in known),
        "basis": basis, "tasks": estimates,
    }


def prune(path: str | Path | None = None, *, now: datetime | None = None) -> dict[str, int]:
    """Roll old normal samples into coarse aggregates, then remove raw rows."""
    cutoff = (now or _utc_now()) - timedelta(days=RETENTION_DAYS)
    removed = 0
    rollups = 0
    with connection(path or default_db_path()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM measurements WHERE created_at < ?", (_iso(cutoff),)
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            if not row["sample_eligible"]:
                continue
            key_values = [row[column] for column in DIMENSION_COLUMNS]
            key = json.dumps(key_values, ensure_ascii=False, separators=(",", ":"))
            groups.setdefault(key, []).append(row)
        for key, group in groups.items():
            durations = [float(row["duration_s"]) for row in group]
            first = group[0]
            conn.execute(
                """INSERT INTO timing_rollups (
                    rollup_key, command_key, resource_class, sample_count, sum_s,
                    min_s, max_s, p50_s, p90_s, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(rollup_key) DO UPDATE SET
                    sample_count=timing_rollups.sample_count + excluded.sample_count,
                    sum_s=timing_rollups.sum_s + excluded.sum_s,
                    min_s=min(timing_rollups.min_s, excluded.min_s),
                    max_s=max(timing_rollups.max_s, excluded.max_s),
                    p50_s=excluded.p50_s, p90_s=excluded.p90_s,
                    updated_at=excluded.updated_at""",
                (key, first["command_key"], first["resource_class"], len(group),
                 sum(durations), min(durations), max(durations),
                 _percentile(durations, .5), _percentile(durations, .9), _iso()),
            )
            rollups += 1
        conn.execute("DELETE FROM measurements WHERE created_at < ?", (_iso(cutoff),))
        removed = len(rows)
        conn.commit()
    return {"removed": removed, "rollups": rollups}

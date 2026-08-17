#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Command line access to the local test timing ledger and run status files."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import platform
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import test_timing_store as store
from lib.streaming_command import run_streamed_command


BUNDLE_SCHEMA = "kg.test.bundle.v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FAILURE_POLICIES = frozenset({"block", "warn"})


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_bundle(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != BUNDLE_SCHEMA:
        raise ValueError(f"bundle must declare {BUNDLE_SCHEMA}")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("bundle tasks must be a non-empty list")
    ids = [task.get("id") for task in tasks if isinstance(task, dict)]
    if len(ids) != len(tasks) or len(set(ids)) != len(ids) or any(not value for value in ids):
        raise ValueError("bundle task ids must be unique and non-empty")
    known = set(ids)
    for task in tasks:
        if not isinstance(task.get("id"), str) or not _SAFE_ID.fullmatch(task["id"]):
            raise ValueError(f"task id {task.get('id')!r} is not a safe opaque id")
        if not isinstance(task.get("command_key"), str) or not task["command_key"]:
            raise ValueError(f"task {task.get('id')!r} lacks command_key")
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list) or any(value not in known for value in dependencies):
            raise ValueError(f"task {task['id']!r} has an unknown dependency")
        if not isinstance(task.get("resource_class", "default"), str):
            raise ValueError(f"task {task['id']!r} has invalid resource_class")
        if task.get("failure_policy", "block") not in _FAILURE_POLICIES:
            raise ValueError(f"task {task['id']!r} has invalid failure_policy")
        retry = task.get("retry", 0)
        if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
            raise ValueError(f"task {task['id']!r} has invalid retry count")
        for field in ("timeout_s", "heartbeat_interval_s"):
            value = task.get(field)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or float(value) <= 0
            ):
                raise ValueError(f"task {task['id']!r} has invalid {field}")
    return payload


def _status_path(root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id):
        raise ValueError("run_id must be a safe opaque id")
    directory = (root / ".cache" / "test_runs").resolve()
    path = (directory / f"{run_id}.json").resolve()
    path.relative_to(directory)
    return path


def _task_command(task: dict[str, Any], timing_output: Path) -> tuple[list[str], dict[str, str]]:
    explicit = task.get("command")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit or any(not isinstance(x, str) for x in explicit):
            raise ValueError(f"task {task['id']!r} command must be a non-empty string list")
        command = list(explicit)
    elif task["command_key"] == "pytest.selector":
        selector = task.get("selector")
        if not isinstance(selector, str) or not selector:
            raise ValueError(f"task {task['id']!r} pytest.selector requires selector")
        command = [
            "uv", "run", "--no-project", "--python", "3.13", "--with", "pytest",
            "pytest", "-q", selector,
        ]
    else:
        raise ValueError(
            f"task {task['id']!r} has no executable mapping for command_key="
            f"{task['command_key']!r}"
        )
    environment = dict(os.environ)
    # A bundle is the xdist controller.  Inheriting a parent worker marker makes
    # the nested plugin write a misleading `.gwN` path and leaves evidence behind.
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_TESTRUNUID", "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    if any(Path(value).name == "pytest" for value in command):
        ops_lib = str(Path(__file__).resolve().parent / "lib")
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = ops_lib + (os.pathsep + existing if existing else "")
        command.extend([
            "-p", "pytest_timing_plugin",
            "--kg-timing-output", str(timing_output),
            "--kg-timing-command-key", task["command_key"],
        ])
    return command, environment


def _ingest_plugin_output(
    path: Path, *, run_id: str, bundle_id: str, task: dict[str, Any],
    started_at: str, finished_at: str,
) -> int:
    paths = [path, *sorted(path.parent.glob(path.name + ".*"))]
    count = 0
    seen: set[tuple[str | None, str | None, float]] = set()
    for candidate in paths:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                identity = (row.get("command_key"), row.get("selector"), float(row["duration_s"]))
                if identity in seen:
                    continue
                seen.add(identity)
                result = store.record_measurement(
                    run_id=run_id, bundle_id=bundle_id,
                    command_key=str(row["command_key"]), selector=row.get("selector"),
                    suite=row.get("suite"), tier=task.get("tier"), host=platform.node(),
                    runtime_version=platform.python_version(),
                    xcode_or_device=task.get("xcode_or_device"), dataset=task.get("dataset"),
                    head_sha=os.environ.get("KG_TEST_TIMING_HEAD_SHA"),
                    resource_class=task.get("resource_class", "default"),
                    started_at=started_at, finished_at=finished_at,
                    duration_s=identity[2], status=str(row["status"]),
                    exit_code=row.get("exit_code"), cache_status=task.get("cache_status"),
                    timing_source="pytest-plugin", duration_status=row.get("duration_status", "complete"),
                )
                count += int(result.get("recorded", False))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        candidate.unlink(missing_ok=True)
    return count


def _run_bundle_task(
    task: dict[str, Any], *, root: Path, run_id: str, bundle_id: str,
) -> dict[str, Any]:
    attempt_rows: list[dict[str, Any]] = []
    max_attempts = 1 + int(task.get("retry", 0))
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        started_at = _iso_now()
        timing_output = root / ".cache" / "test_runs" / f"{run_id}.{task['id']}.attempt-{attempt}.jsonl"
        try:
            command, environment = _task_command(task, timing_output)
            result = run_streamed_command(
                command, cwd=root, label_key="bundle-task", label=str(task["id"]),
                progress_prefix="[test-timing]", heartbeat_interval=float(task.get("heartbeat_interval_s", 20.0)),
                timeout_seconds=task.get("timeout_s"), env=environment,
                task_session_id=f"bundle:{run_id}", task_campaign=bundle_id,
                task_worktree=root,
            )
            status = "timeout" if getattr(result, "timed_out", False) else (
                "passed" if result.returncode == 0 else "failed"
            )
            exit_code = result.returncode
            error = None
        except KeyboardInterrupt:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            status, exit_code, error = "error", None, f"{type(exc).__name__}: {exc}"
        finished_at = _iso_now()
        duration_s = time.monotonic() - started
        recorded = store.record_measurement(
            run_id=run_id, bundle_id=bundle_id, command_key=task["command_key"],
            selector=task.get("selector"), suite=task.get("suite", "bundle"),
            tier=task.get("tier"), host=platform.node(), runtime_version=platform.python_version(),
            xcode_or_device=task.get("xcode_or_device"), dataset=task.get("dataset"),
            head_sha=os.environ.get("KG_TEST_TIMING_HEAD_SHA"),
            resource_class=task.get("resource_class", "default"), started_at=started_at,
            finished_at=finished_at, duration_s=duration_s, status=(
                "pass" if status == "passed" else
                "fail" if status == "failed" else
                "inconclusive"
            ), exit_code=exit_code, cache_status=task.get("cache_status"),
            timing_source="bundle-runner",
            duration_status="interrupted" if status == "timeout" else "complete",
        )
        plugin_count = _ingest_plugin_output(
            timing_output, run_id=run_id, bundle_id=bundle_id, task=task,
            started_at=started_at, finished_at=finished_at,
        )
        attempt_rows.append({
            "attempt": attempt, "status": status, "exit_code": exit_code,
            "duration_s": round(duration_s, 3), "timing_recorded": bool(recorded.get("recorded")),
            "per_test_measurements": plugin_count, "error": error,
        })
        if status == "passed" or attempt == max_attempts:
            break
    final = attempt_rows[-1]
    return {
        "id": task["id"], "command_key": task["command_key"],
        "selector": task.get("selector"), "resource_class": task.get("resource_class", "default"),
        "status": final["status"], "exit_code": final["exit_code"], "duration_s": final["duration_s"],
        "attempts": len(attempt_rows), "attempt_results": attempt_rows,
        "timing_recorded": any(row["timing_recorded"] for row in attempt_rows),
        "per_test_measurements": sum(row["per_test_measurements"] for row in attempt_rows),
        "error": final["error"],
    }


def cmd_run_bundle(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    bundle_path = Path(args.bundle).resolve()
    try:
        bundle = _load_bundle(bundle_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _emit({"schema": BUNDLE_SCHEMA, "status": "error", "error": str(exc)}, args.json)
        return 2
    run_id = args.run_id or f"run-{uuid.uuid4().hex}"
    try:
        status_path = _status_path(root, run_id)
    except ValueError as exc:
        _emit({"schema": BUNDLE_SCHEMA, "status": "error", "run_id": run_id, "error": str(exc)}, args.json)
        return 2
    if status_path.exists():
        _emit({"schema": BUNDLE_SCHEMA, "status": "error", "run_id": run_id,
               "error": "run_id already exists; use a new run_id"}, args.json)
        return 2
    tasks_by_id = {task["id"]: task for task in bundle["tasks"]}
    task_rows = {
        task_id: {
            "id": task_id, "command_key": task["command_key"],
            "selector": task.get("selector"), "resource_class": task.get("resource_class", "default"),
            "status": "pending",
        }
        for task_id, task in tasks_by_id.items()
    }
    payload = {
        "schema": BUNDLE_SCHEMA, "run_id": run_id, "bundle_id": bundle.get("bundle_id", bundle_path.stem),
        "tier": bundle.get("tier"), "status": "running", "started_at": _iso_now(),
        "finished_at": None, "tasks": list(task_rows.values()), "warnings": [],
    }
    _atomic_json(status_path, payload)
    completed: dict[str, str] = {}
    pending = set(tasks_by_id)
    futures: dict[concurrent.futures.Future, str] = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(4, len(pending))))
    cancelled = False
    try:
        while pending or futures:
            for task_id in sorted(list(pending)):
                task = tasks_by_id[task_id]
                dependencies = task.get("depends_on", [])
                if any(dep in completed and completed[dep] != "passed" for dep in dependencies):
                    task_rows[task_id]["status"] = "blocked"
                    completed[task_id] = "blocked"
                    pending.remove(task_id)
                    continue
                if not all(dep in completed for dep in dependencies):
                    continue
                resource = task.get("resource_class", "default")
                if any(tasks_by_id[running_id].get("resource_class", "default") == resource
                       for running_id in futures.values()):
                    continue
                task_rows[task_id]["status"] = "running"
                futures[executor.submit(
                    _run_bundle_task, task, root=root, run_id=run_id, bundle_id=payload["bundle_id"]
                )] = task_id
                pending.remove(task_id)
            _atomic_json(status_path, {**payload, "tasks": list(task_rows.values())})
            if not futures:
                if pending:
                    raise ValueError("bundle dependency cycle or unsatisfied resource state")
                break
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                task_id = futures.pop(future)
                try:
                    row = future.result()
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    row = {
                        "id": task_id, "command_key": tasks_by_id[task_id]["command_key"],
                        "selector": tasks_by_id[task_id].get("selector"),
                        "resource_class": tasks_by_id[task_id].get("resource_class", "default"),
                        "status": "error", "exit_code": None, "duration_s": 0.0,
                        "attempts": 0, "attempt_results": [], "timing_recorded": False,
                        "per_test_measurements": 0, "error": f"{type(exc).__name__}: {exc}",
                    }
                task_rows[task_id] = row
                completed[task_id] = "passed" if row["status"] == "passed" else row["status"]
                _atomic_json(status_path, {**payload, "tasks": list(task_rows.values())})
    except KeyboardInterrupt:
        cancelled = True
        for future in futures:
            future.cancel()
        for row in task_rows.values():
            if row["status"] in {"pending", "running"}:
                row["status"] = "cancelled"
        payload.update({"status": "cancelled", "verdict": "cancelled", "finished_at": _iso_now(),
                       "tasks": list(task_rows.values())})
        _atomic_json(status_path, payload)
        _emit(payload, args.json)
        return 1
    except Exception as exc:
        payload.update({"status": "error", "finished_at": _iso_now(), "error": str(exc), "tasks": list(task_rows.values())})
        _atomic_json(status_path, payload)
        _emit(payload, args.json)
        return 2
    finally:
        # TaskRegistry owns child-process cleanup.  A cancellation request must
        # not invent a second kill path; do not wait for already-running tasks.
        executor.shutdown(wait=not cancelled, cancel_futures=True)
    hard_failures = [row for row in task_rows.values() if row.get("status") in {"failed", "timeout", "error", "blocked"}
                     and tasks_by_id[row["id"]].get("failure_policy", "block") == "block"]
    warnings = [row["id"] for row in task_rows.values() if row.get("status") not in {"passed", "pending", "running"}
                and tasks_by_id[row["id"]].get("failure_policy", "block") != "block"]
    payload.update({
        "status": "failed" if hard_failures else "passed", "verdict": "block" if hard_failures else ("warn" if warnings else "pass"),
        "warnings": warnings, "finished_at": _iso_now(), "tasks": list(task_rows.values()),
    })
    _atomic_json(status_path, payload)
    _emit(payload, args.json)
    return 1 if hard_failures else 0


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_status_path(run_id: str, repo: str | None) -> Path:
    root = Path(repo).resolve() if repo else Path.cwd().resolve()
    return _status_path(root, run_id)


def cmd_estimate(args: argparse.Namespace) -> int:
    payload = store.estimate(
        args.command_key,
        db_path=args.db,
        selector=args.selector,
        suite=args.suite,
        tier=args.tier,
        host=args.host,
        runtime_version=args.runtime_version,
        xcode_or_device=args.xcode_or_device,
        dataset=args.dataset,
        resource_class=args.resource_class,
        cache_status=args.cache_status,
        resource_wait_estimate_s=args.resource_wait_estimate_s,
    )
    _emit(payload, args.json)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        path = _run_status_path(args.run_id, args.repo)
    except ValueError as exc:
        _emit({"schema": BUNDLE_SCHEMA, "run_id": args.run_id,
               "status": "error", "error": str(exc)}, args.json)
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status payload must be an object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        payload = {
            "schema": "kg.test.bundle.v1",
            "run_id": args.run_id,
            "status": "not_found",
            "error": f"{type(exc).__name__}: {exc}",
        }
    _emit(payload, args.json)
    return 0 if payload.get("status") in {"passed"} else 1


def cmd_wait(args: argparse.Namespace) -> int:
    if (
        not isinstance(args.interval_s, (int, float))
        or not isinstance(args.timeout_s, (int, float))
        or not math.isfinite(float(args.interval_s))
        or not math.isfinite(float(args.timeout_s))
        or args.interval_s <= 0
        or args.timeout_s < 0
    ):
        _emit({"schema": BUNDLE_SCHEMA, "run_id": args.run_id,
               "status": "error", "error": "interval/timeout must be finite and non-negative"}, args.json)
        return 2
    try:
        status_path = _run_status_path(args.run_id, args.repo)
    except ValueError as exc:
        _emit({"schema": BUNDLE_SCHEMA, "run_id": args.run_id,
               "status": "error", "error": str(exc)}, args.json)
        return 2
    deadline = time.monotonic() + args.timeout_s
    while True:
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("status payload must be an object")
        except (OSError, json.JSONDecodeError):
            payload = {"run_id": args.run_id, "status": "pending"}
        except ValueError as exc:
            payload = {"run_id": args.run_id, "status": "error", "error": str(exc)}
        status = payload.get("status")
        if status in {"passed", "failed", "cancelled", "error", "timeout"}:
            _emit(payload, args.json)
            return 0 if status == "passed" else 1
        if time.monotonic() >= deadline:
            payload = {**payload, "run_id": args.run_id, "status": "timeout"}
            _emit(payload, args.json)
            return 1
        time.sleep(min(args.interval_s, max(0.0, deadline - time.monotonic())))


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit one JSON object")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    estimate = sub.add_parser("estimate")
    estimate.add_argument("--command-key", required=True)
    for name in ("selector", "suite", "tier", "host", "runtime-version",
                 "xcode-or-device", "dataset", "resource-class", "cache-status"):
        estimate.add_argument(f"--{name}", dest=name.replace("-", "_"))
    estimate.add_argument("--resource-wait-estimate-s", type=float, default=0.0)
    estimate.add_argument("--db")
    _add_json(estimate)
    estimate.set_defaults(func=cmd_estimate)

    run = sub.add_parser("run")
    run.add_argument("--bundle", required=True)
    run.add_argument("--repo")
    run.add_argument("--run-id")
    _add_json(run)
    run.set_defaults(func=cmd_run_bundle)

    for verb, func in (("status", cmd_status), ("wait", cmd_wait)):
        command = sub.add_parser(verb)
        command.add_argument("--run-id", required=True)
        command.add_argument("--repo")
        if verb == "wait":
            command.add_argument("--interval-s", type=float, default=1.0)
            command.add_argument("--timeout-s", type=float, default=3600.0)
        _add_json(command)
        command.set_defaults(func=func)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    raise SystemExit(parsed.func(parsed))

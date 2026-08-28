#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Bounded attribution of the KG project and every physical Git worktree.

The report deliberately separates logical bytes from allocated bytes.  Linked
worktrees share Git objects, so summing lane directories is not a filesystem
quota; the accounting section makes the shared/unassigned part explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "kg.disk.lane-usage.v1"
BLOCKED_EXIT = 75
GIB = 1024**3
LIVE_REGISTRY_STATUSES = {"active", "published", "cleanup_pending"}
TERMINAL_REGISTRY_STATUSES = {"merged", "abandoned"}
DEFAULT_TIME_BUDGET_SECONDS = 30.0


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _allocated_bytes(stat_result: os.stat_result) -> int:
    blocks = getattr(stat_result, "st_blocks", 0)
    return int(blocks) * 512 if blocks else int(stat_result.st_size)


def measure_tree(
    root: Path,
    *,
    excluded: set[Path] | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Measure one bounded tree without following symlinked directories."""

    root = _path(root)
    excluded = {_path(item) for item in (excluded or set())}
    if not root.exists() or not root.is_dir():
        return {
            "logical_bytes": 0,
            "allocated_bytes": 0,
            "files": 0,
            "complete": False,
            "error": "path-missing",
        }

    logical = 0
    allocated = 0
    files = 0
    seen_files: set[tuple[int, int]] = set()
    pending = [root]
    complete = True
    errors: list[str] = []

    def budget_expired() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def record_budget_expiry() -> None:
        nonlocal complete
        complete = False
        if "measurement-time-budget-exceeded" not in errors:
            errors.append("measurement-time-budget-exceeded")

    while pending:
        if budget_expired():
            record_budget_expiry()
            break
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            complete = False
            errors.append(f"{directory}: {exc.__class__.__name__}")
            continue
        for entry in entries:
            if budget_expired():
                record_budget_expiry()
                break
            entry_path = _path(entry.path)
            if entry_path in excluded:
                continue
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as exc:
                complete = False
                errors.append(f"{entry_path}: {exc.__class__.__name__}")
                continue
            allocated += _allocated_bytes(stat_result)
            if entry.is_symlink():
                logical += int(stat_result.st_size)
                files += 1
            elif entry.is_dir(follow_symlinks=False):
                pending.append(entry_path)
            elif entry.is_file(follow_symlinks=False):
                identity = (int(stat_result.st_dev), int(stat_result.st_ino))
                if identity not in seen_files:
                    seen_files.add(identity)
                    logical += int(stat_result.st_size)
                    files += 1
    result: dict[str, Any] = {
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "files": files,
        "complete": complete,
    }
    if errors:
        result["errors"] = sorted(errors)[:20]
    return result


def _parse_worktrees(workspace: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return [], f"git-worktree-list:{exc.__class__.__name__}"
    if completed.returncode != 0:
        return [], f"git-worktree-list:exit-{completed.returncode}"

    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = {"path": _path(line.removeprefix("worktree ").strip())}
        elif current is None:
            continue
        elif line.startswith("HEAD "):
            current["head"] = line.removeprefix("HEAD ").strip()
        elif line.startswith("branch "):
            ref = line.removeprefix("branch ").strip()
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line == "detached":
            current["detached"] = True
    if current is not None:
        records.append(current)
    return records, None


def _load_registry(state_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "registry-missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], f"registry-unreadable:{exc.__class__.__name__}"
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return [], "registry-records-invalid"
    records = [item for item in payload["records"] if isinstance(item, dict)]
    return records, None


def _scope_paths(record: dict[str, Any]) -> list[str]:
    scope = record.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("files"), list):
        return []
    return sorted(
        {
            str(item.get("path"))
            for item in scope["files"]
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
    )


def _lane_key(branch: str, path: Path, index: int | None = None) -> str:
    suffix = "" if index is None else f"\0{index}"
    return hashlib.sha256(f"{branch}\0{path}{suffix}".encode()).hexdigest()[:16]


def _lane_entry(
    *,
    branch: str,
    path: Path,
    lane_kind: str,
    registry: dict[str, Any] | None,
    registry_index: int | None,
    physical: dict[str, Any] | None,
    deadline: float | None = None,
) -> dict[str, Any]:
    if physical is not None and path.is_dir():
        measured = measure_tree(path, deadline=deadline)
        exists = True
        physical_state = "present"
        head = physical.get("head")
        observed_branch = physical.get("branch")
    else:
        measured = {
            "logical_bytes": 0,
            "allocated_bytes": 0,
            "files": 0,
            "complete": False,
            "error": "path-missing",
        }
        exists = path.is_dir()
        physical_state = "present-unregistered" if exists else "missing"
        head = None
        observed_branch = None
    entry: dict[str, Any] = {
        "lane_key": _lane_key(branch, path, registry_index),
        "lane_kind": lane_kind,
        "branch": branch,
        "path": str(path),
        "exists": exists,
        "physical_state": physical_state,
        "logical_bytes": measured["logical_bytes"],
        "allocated_bytes": measured["allocated_bytes"],
        "files": measured["files"],
        "measurement_complete": measured["complete"],
        "ownership": "registered" if registry is not None else "unregistered",
        "registry_status": registry.get("status") if registry else None,
        "registry_index": registry_index,
        "external_ids": sorted(
            str(item) for item in (registry or {}).get("external_ids", []) if str(item)
        ),
        "scope": _scope_paths(registry or {}),
    }
    if head:
        entry["head"] = head
    if observed_branch and observed_branch != branch:
        entry["observed_branch"] = observed_branch
    if "error" in measured:
        entry["measurement_error"] = measured["error"]
    if measured.get("errors"):
        entry["measurement_errors"] = measured["errors"]
        if "measurement-time-budget-exceeded" in measured["errors"]:
            entry["measurement_error"] = "measurement-time-budget-exceeded"
    return entry


def build_report(
    workspace: Path,
    state_path: Path,
    *,
    time_budget_seconds: float | None = None,
) -> dict[str, Any]:
    measurement_started = time.monotonic()
    deadline = (
        None
        if time_budget_seconds is None
        else measurement_started + max(0.0, time_budget_seconds)
    )
    workspace = _path(workspace)
    state_path = _path(state_path)
    registry_records, registry_error = _load_registry(state_path)
    physical_records, git_error = _parse_worktrees(workspace)
    physical_by_path = {item["path"]: item for item in physical_records}

    registry_entries: list[dict[str, Any]] = []
    registry_by_path: dict[Path, list[tuple[int, dict[str, Any]]]] = {}
    status_counts: dict[str, int] = {}
    malformed_registry_records = 0
    for index, record in enumerate(registry_records):
        status = str(record.get("status") or "(missing)")
        status_counts[status] = status_counts.get(status, 0) + 1
        record_path = record.get("path")
        branch = str(record.get("branch") or "")
        if not isinstance(record_path, str) or not record_path.strip() or not branch:
            malformed_registry_records += 1
            continue
        if status not in LIVE_REGISTRY_STATUSES:
            continue
        normalized = _path(record_path)
        registry_by_path.setdefault(normalized, []).append((index, record))
        physical = physical_by_path.get(normalized)
        lane_kind = "canonical-main" if normalized == workspace else "lane"
        registry_entries.append(
            _lane_entry(
                branch=branch,
                path=normalized,
                lane_kind=lane_kind,
                registry=record,
                registry_index=index,
                physical=physical,
                deadline=deadline,
            )
        )

    for physical in physical_records:
        physical_path = physical["path"]
        if physical_path in registry_by_path:
            continue
        branch = str(physical.get("branch") or "(detached)")
        lane_kind = "canonical-main" if physical_path == workspace else "lane"
        registry_entries.append(
            _lane_entry(
                branch=branch,
                path=physical_path,
                lane_kind=lane_kind,
                registry=None,
                registry_index=None,
                physical=physical,
                deadline=deadline,
            )
        )

    lanes = sorted(
        registry_entries,
        key=lambda item: (
            item["lane_kind"],
            item["path"],
            item["branch"],
            item["registry_index"] or -1,
        ),
    )
    nested_worktrees = {
        _path(item["path"])
        for item in physical_records
        if _path(item["path"]) != workspace
        and _relative_to(_path(item["path"]), workspace)
    }
    workspace_measurement = measure_tree(
        workspace,
        excluded=nested_worktrees,
        deadline=deadline,
    )
    physical_lanes_by_path = {
        Path(item["path"]): item
        for item in lanes
        if item["lane_kind"] == "lane" and item["exists"]
    }
    physical_lanes = list(physical_lanes_by_path.values())
    lane_allocated = sum(int(item["allocated_bytes"]) for item in physical_lanes)
    lane_logical = sum(int(item["logical_bytes"]) for item in physical_lanes)
    missing_active = sorted(
        {
            str(item["branch"])
            for item in lanes
            if item["ownership"] == "registered"
            and item["registry_status"] in LIVE_REGISTRY_STATUSES
            and not item["exists"]
        }
    )
    unregistered = sorted(
        str(item["path"])
        for item in physical_lanes
        if item["ownership"] == "unregistered"
    )
    try:
        per_lane_budget = (
            int(os.environ.get("KG_DISK_GUARD_LANE_BUDGET_GIB", "2")) * GIB
        )
    except ValueError:
        per_lane_budget = 2 * GIB
    try:
        total_lane_budget = (
            int(os.environ.get("KG_DISK_GUARD_LANE_TOTAL_BUDGET_GIB", "8")) * GIB
        )
    except ValueError:
        total_lane_budget = 8 * GIB
    over_lane = sorted(
        {
            str(item["branch"])
            for item in physical_lanes
            if int(item["allocated_bytes"]) > per_lane_budget
        }
    )
    reasons: list[str] = []
    if registry_error:
        reasons.append(registry_error)
    if git_error:
        reasons.append(git_error)
    if missing_active:
        reasons.append("missing-registered-lane")
    if not workspace_measurement["complete"]:
        reasons.append("workspace-measurement-incomplete")
    if not all(item["measurement_complete"] for item in physical_lanes):
        reasons.append("lane-measurement-incomplete")
    measurement_entries = [workspace_measurement]
    measurement_entries.extend(
        {
            "errors": item.get("measurement_errors", []),
        }
        for item in lanes
        if item.get("measurement_errors")
    )
    measurement_budget_exhausted = any(
        "measurement-time-budget-exceeded" in item.get("errors", [])
        for item in measurement_entries
    )
    if measurement_budget_exhausted:
        reasons.append("measurement-time-budget-exceeded")
    if over_lane:
        reasons.extend(f"lane-budget-exceeded:{branch}" for branch in over_lane)
    if lane_allocated > total_lane_budget:
        reasons.append("lane-total-budget-exceeded")
    blocking_reasons = [reason for reason in reasons if reason != "registry-missing"]
    # An absent registry is itself a hard attribution failure; the special
    # spelling above is only retained so the report explains the evidence.
    if (
        registry_error == "registry-missing"
        and "registry-missing" not in blocking_reasons
    ):
        blocking_reasons.append("registry-missing")
    if blocking_reasons:
        verdict = "block"
    elif unregistered:
        verdict = "warning"
        reasons.append("unregistered-physical-worktree")
    else:
        verdict = "pass"
    try:
        filesystem = shutil.disk_usage(workspace)
        filesystem_payload = {
            "total_bytes": int(filesystem.total),
            "used_bytes": int(filesystem.used),
            "free_bytes": int(filesystem.free),
        }
    except OSError as exc:
        filesystem_payload = {"error": f"filesystem-usage:{exc.__class__.__name__}"}
        verdict = "block"
        reasons.append("filesystem-usage-unknown")

    return {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "registry": str(state_path),
        "measurement": {
            "budget_seconds": time_budget_seconds,
            "elapsed_seconds": round(time.monotonic() - measurement_started, 3),
            "budget_exhausted": measurement_budget_exhausted,
        },
        "lanes": lanes,
        "lane_count": len([item for item in lanes if item["lane_kind"] == "lane"]),
        "history": {
            "records": len(registry_records),
            "terminal_records": sum(
                count
                for status, count in status_counts.items()
                if status in TERMINAL_REGISTRY_STATUSES
            ),
            "by_status": dict(sorted(status_counts.items())),
            "malformed_records": malformed_registry_records,
        },
        "accounting": {
            "measurement": "st_blocks",
            "fields": ["logical_bytes", "allocated_bytes"],
            "workspace_unassigned_logical_bytes": workspace_measurement[
                "logical_bytes"
            ],
            "workspace_unassigned_allocated_bytes": workspace_measurement[
                "allocated_bytes"
            ],
            "physical_lane_logical_bytes": lane_logical,
            "physical_lane_allocated_bytes": lane_allocated,
            "managed_logical_bytes": workspace_measurement["logical_bytes"]
            + lane_logical,
            "managed_allocated_bytes": workspace_measurement["allocated_bytes"]
            + lane_allocated,
            "nested_worktrees_excluded_from_workspace": sorted(
                str(item) for item in nested_worktrees
            ),
        },
        "filesystem": filesystem_payload,
        "policy": {
            "verdict": verdict,
            "per_lane_budget_bytes": per_lane_budget,
            "total_lane_budget_bytes": total_lane_budget,
            "reasons": sorted(set(reasons)),
            "missing_active_lanes": missing_active,
            "unregistered_physical_worktrees": unregistered,
            "lane_budget_exceeded": over_lane,
        },
    }


def _write_atomic(path: Path, report: dict[str, Any]) -> None:
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--state")
    parser.add_argument("--output")
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=DEFAULT_TIME_BUDGET_SECONDS,
        help="maximum recursive measurement time before returning a fail-closed report",
    )
    args = parser.parse_args(argv)
    workspace = _path(args.workspace)
    state = (
        _path(args.state) if args.state else workspace / ".cache/worktree_registry.json"
    )
    report = build_report(
        workspace,
        state,
        time_budget_seconds=args.time_budget_seconds,
    )
    if args.output:
        _write_atomic(_path(args.output), report)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["policy"]["verdict"] != "block" else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())

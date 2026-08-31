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
KNOWN_REGISTRY_STATUSES = LIVE_REGISTRY_STATUSES | TERMINAL_REGISTRY_STATUSES
DEFAULT_TIME_BUDGET_SECONDS = 30.0
DEFAULT_CODEX_WORKTREE_ROOT = Path.home() / ".codex" / "worktrees"


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
            # ``os.scandir`` yields absolute paths when the parent is absolute.
            # Avoid resolving every entry: this scan is itself bounded by the
            # disk attribution deadline, and per-file ``Path.resolve`` makes
            # large worktrees consume the entire safety budget.
            entry_path = Path(entry.path)
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


def _parse_worktrees(
    workspace: Path, *, deadline: float | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    if deadline is not None and time.monotonic() >= deadline:
        return [], "measurement-time-budget-exceeded"
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

    for record in records:
        path = record["path"]
        if not path.is_dir():
            record.update(
                {
                    "inspection_complete": False,
                    "inspection_error": "path-missing",
                    "worktree_state": "missing",
                }
            )
            continue
        if deadline is not None and time.monotonic() >= deadline:
            record.update(
                {
                    "inspection_complete": False,
                    "inspection_error": "measurement-time-budget-exceeded",
                    "worktree_state": "unknown",
                }
            )
            continue
        try:
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(path),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            record.update(
                {
                    "inspection_complete": False,
                    "inspection_error": f"git-status:{exc.__class__.__name__}",
                    "worktree_state": "unknown",
                }
            )
            continue
        if status.returncode != 0:
            record.update(
                {
                    "inspection_complete": False,
                    "inspection_error": f"git-status:exit-{status.returncode}",
                    "worktree_state": "unknown",
                }
            )
            continue
        dirty = bool(status.stdout.strip())
        record.update(
            {
                "inspection_complete": True,
                "dirty": dirty,
                "worktree_state": "dirty" if dirty else "clean",
            }
        )
    return records, None


def _topology_roots(workspace: Path) -> list[Path]:
    """Return the bounded worktree roots that this report observes."""

    configured_codex_root = os.environ.get("KG_DISK_USAGE_CODEX_WORKTREE_ROOT")
    roots = [
        workspace / ".claude" / "worktrees",
        _path(configured_codex_root)
        if configured_codex_root
        else _path(DEFAULT_CODEX_WORKTREE_ROOT),
    ]
    unique: list[Path] = []
    for root in roots:
        normalized = _path(root)
        if normalized not in unique:
            unique.append(normalized)
    return unique


def _topology_candidates(
    root: Path, *, deadline: float | None = None, max_depth: int = 2
) -> tuple[list[Path], str | None]:
    """Enumerate only shallow checkout roots; never walk their project files."""

    root = _path(root)
    if not root.is_dir():
        return [], None
    candidates: list[Path] = []
    pending: list[tuple[Path, int]] = [(root, 0)]
    try:
        while pending:
            if deadline is not None and time.monotonic() >= deadline:
                return candidates, "measurement-time-budget-exceeded"
            directory, depth = pending.pop()
            for entry in sorted(os.scandir(directory), key=lambda item: item.name):
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    continue
                entry_path = Path(entry.path)
                if (entry_path / ".git").exists():
                    candidates.append(entry_path)
                elif depth < max_depth:
                    pending.append((entry_path, depth + 1))
    except OSError as exc:
        return candidates, f"topology-scan:{exc.__class__.__name__}"
    return candidates, None


def _git_output(path: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _inspect_topology_worktree(path: Path) -> dict[str, Any] | None:
    """Read identity/status for a topology checkout not returned by git list."""

    head = _git_output(path, "rev-parse", "HEAD")
    common_dir = _git_output(path, "rev-parse", "--git-common-dir")
    if head is None or common_dir is None:
        return None
    branch = _git_output(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return {
            "path": path,
            "head": head,
            "branch": branch or "(detached)",
            "inspection_complete": False,
            "inspection_error": "git-status:OSError",
            "worktree_state": "unknown",
        }
    if status.returncode != 0:
        return {
            "path": path,
            "head": head,
            "branch": branch or "(detached)",
            "inspection_complete": False,
            "inspection_error": f"git-status:exit-{status.returncode}",
            "worktree_state": "unknown",
        }
    return {
        "path": path,
        "head": head,
        "branch": branch or "(detached)",
        "inspection_complete": True,
        "dirty": bool(status.stdout.strip()),
        "worktree_state": "dirty" if status.stdout.strip() else "clean",
    }


def _topology_name(path: Path, roots: list[Path]) -> str | None:
    for root in roots:
        if _relative_to(path, root):
            return (
                "codex"
                if root.name == "worktrees" and ".codex" in root.parts
                else "claude"
            )
    return None


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
    excluded: bool = False,
    physical_state_override: str | None = None,
    registry_match_count: int = 1,
    registry_statuses: list[str] | None = None,
    topology: str | None = None,
) -> dict[str, Any]:
    if path.is_dir():
        measured = measure_tree(path, deadline=deadline)
        exists = True
    else:
        measured = {
            "logical_bytes": 0,
            "allocated_bytes": 0,
            "files": 0,
            "complete": False,
            "error": "path-missing",
        }
        exists = False
    if physical is not None:
        head = physical.get("head")
        observed_branch = physical.get("branch")
        physical_state = physical.get("worktree_state", "unknown")
        if not exists:
            physical_state = "missing"
        elif physical_state == "clean":
            physical_state = "present"
        elif physical_state == "dirty":
            physical_state = "dirty"
        else:
            physical_state = "unknown"
    else:
        head = None
        observed_branch = None
        physical_state = "unverified" if exists else "missing"
    if physical_state_override is not None:
        physical_state = physical_state_override
    if excluded and exists:
        physical_state = "excluded"
    ownership = (
        "excluded"
        if excluded
        else "registered"
        if registry is not None
        else "unregistered"
    )
    registry_status = registry.get("status") if registry else None
    if registry_status in TERMINAL_REGISTRY_STATUSES:
        lane_state = "terminal"
    elif registry_status in LIVE_REGISTRY_STATUSES:
        lane_state = "live"
    elif registry is not None:
        lane_state = "unknown"
    elif excluded:
        lane_state = "excluded"
    else:
        lane_state = "physical"
    entry: dict[str, Any] = {
        "lane_key": _lane_key(branch, path, registry_index),
        "lane_kind": lane_kind,
        "branch": branch,
        "path": str(path),
        "exists": exists,
        "physical_state": physical_state,
        "lane_state": lane_state,
        "logical_bytes": measured["logical_bytes"],
        "allocated_bytes": measured["allocated_bytes"],
        "files": measured["files"],
        "measurement_complete": measured["complete"],
        "ownership": ownership,
        "registry_status": registry_status,
        "registry_index": registry_index,
        "registry_match_count": registry_match_count,
        "registry_statuses": sorted(set(registry_statuses or [])),
        "accounted_in_aggregate": bool(lane_kind == "lane" and exists and not excluded),
        "external_ids": sorted(
            str(item) for item in (registry or {}).get("external_ids", []) if str(item)
        ),
        "scope": _scope_paths(registry or {}),
    }
    if topology is not None:
        entry["topology"] = topology
    if physical is not None:
        entry["worktree_state"] = physical.get("worktree_state", "unknown")
        entry["inspection_complete"] = bool(physical.get("inspection_complete", False))
        if physical.get("inspection_error"):
            entry["inspection_error"] = physical["inspection_error"]
        if "dirty" in physical:
            entry["dirty"] = bool(physical["dirty"])
    if head:
        entry["head"] = head
    if observed_branch:
        entry["observed_branch"] = observed_branch
    if "error" in measured:
        entry["measurement_error"] = measured["error"]
    if measured.get("errors"):
        entry["measurement_errors"] = measured["errors"]
        if "measurement-time-budget-exceeded" in measured["errors"]:
            entry["measurement_error"] = "measurement-time-budget-exceeded"
    if physical_state_override is not None and exists:
        entry["underlying_physical_state"] = (
            physical.get("worktree_state", "unknown")
            if physical is not None
            else "unverified"
        )
    if excluded:
        entry["excluded"] = True
        entry["exclusion_reason"] = "caller-supplied-supervision-worktree"
    return entry


def build_report(
    workspace: Path,
    state_path: Path,
    *,
    time_budget_seconds: float | None = None,
    supervision_worktree_paths: tuple[str | Path, ...] = (),
) -> dict[str, Any]:
    measurement_started = time.monotonic()
    deadline = (
        None
        if time_budget_seconds is None
        else measurement_started + max(0.0, time_budget_seconds)
    )
    workspace = _path(workspace)
    state_path = _path(state_path)
    requested_supervision_paths: list[Path] = []
    for value in supervision_worktree_paths:
        normalized = _path(value)
        if normalized not in requested_supervision_paths:
            requested_supervision_paths.append(normalized)

    registry_records, registry_error = _load_registry(state_path)
    physical_records, git_error = _parse_worktrees(workspace, deadline=deadline)
    topology_roots = _topology_roots(workspace)
    topology_errors: list[str] = []
    workspace_common_dir = _git_output(workspace, "rev-parse", "--git-common-dir")
    if workspace_common_dir is not None:
        workspace_common_dir = str(_path(workspace / workspace_common_dir))
    known_physical_paths = {item["path"] for item in physical_records}
    for topology_root in topology_roots:
        candidates, topology_error = _topology_candidates(
            topology_root, deadline=deadline
        )
        if topology_error:
            topology_errors.append(f"{topology_root}:{topology_error}")
        for candidate in candidates:
            if candidate in known_physical_paths:
                continue
            candidate_common_dir = _git_output(
                candidate, "rev-parse", "--git-common-dir"
            )
            if candidate_common_dir is None:
                continue
            candidate_common_dir = str(_path(candidate / candidate_common_dir))
            if candidate_common_dir != workspace_common_dir:
                continue
            inspected = _inspect_topology_worktree(candidate)
            if inspected is not None:
                physical_records.append(inspected)
                known_physical_paths.add(candidate)
    physical_by_path: dict[Path, dict[str, Any]] = {}
    physical_path_counts: dict[Path, int] = {}
    for item in physical_records:
        physical_path = item["path"]
        physical_path_counts[physical_path] = (
            physical_path_counts.get(physical_path, 0) + 1
        )
        physical_by_path.setdefault(physical_path, item)

    registry_by_path: dict[Path, list[tuple[int, dict[str, Any]]]] = {}
    status_counts: dict[str, int] = {}
    malformed_registry_records = 0
    unknown_registry_record_indices: list[int] = []
    for index, record in enumerate(registry_records):
        status_value = record.get("status")
        status = (
            status_value
            if isinstance(status_value, str) and status_value
            else "(missing)"
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        if status not in KNOWN_REGISTRY_STATUSES:
            unknown_registry_record_indices.append(index)
        record_path = record.get("path")
        branch = record.get("branch")
        if (
            not isinstance(record_path, str)
            or not record_path.strip()
            or not isinstance(branch, str)
            or not branch.strip()
        ):
            malformed_registry_records += 1
            continue
        normalized = _path(record_path)
        registry_by_path.setdefault(normalized, []).append((index, record))

    applied_exclusions: list[Path] = []
    exclusion_rejections: list[dict[str, str]] = []
    for supervision_path in requested_supervision_paths:
        if supervision_path == workspace:
            exclusion_rejections.append(
                {"path": str(supervision_path), "reason": "canonical-worktree"}
            )
        elif supervision_path in registry_by_path:
            exclusion_rejections.append(
                {
                    "path": str(supervision_path),
                    "reason": "registered-worktree",
                }
            )
        elif supervision_path not in physical_by_path:
            exclusion_rejections.append(
                {"path": str(supervision_path), "reason": "physical-worktree-missing"}
            )
        else:
            applied_exclusions.append(supervision_path)

    registry_entries: list[dict[str, Any]] = []
    for normalized, matches in registry_by_path.items():
        live_matches = [
            item for item in matches if item[1].get("status") in LIVE_REGISTRY_STATUSES
        ]
        terminal_matches = [
            item
            for item in matches
            if item[1].get("status") in TERMINAL_REGISTRY_STATUSES
        ]
        unknown_matches = [
            item
            for item in matches
            if item[1].get("status") not in KNOWN_REGISTRY_STATUSES
        ]
        selected_index, selected_record = (
            live_matches[0]
            if live_matches
            else unknown_matches[0]
            if unknown_matches
            else terminal_matches[0]
        )
        branch = str(selected_record["branch"])
        lane_kind = "canonical-main" if normalized == workspace else "lane"
        is_terminal = (
            not live_matches
            and not unknown_matches
            and selected_record.get("status") in TERMINAL_REGISTRY_STATUSES
        )
        entry = _lane_entry(
            branch=branch,
            path=normalized,
            lane_kind=lane_kind,
            registry=selected_record,
            registry_index=selected_index,
            physical=physical_by_path.get(normalized),
            deadline=deadline,
            physical_state_override=(
                "terminal-residue"
                if is_terminal and normalized in physical_by_path
                else None
            ),
            registry_match_count=len(matches),
            registry_statuses=[
                str(item[1].get("status") or "(missing)") for item in matches
            ],
            topology=_topology_name(normalized, topology_roots),
        )
        entry["registry_indices"] = sorted(item[0] for item in matches)
        entry["external_ids"] = sorted(
            {
                str(external_id)
                for _, item in matches
                for external_id in item.get("external_ids", [])
                if str(external_id)
            }
        )
        registry_entries.append(entry)

    for physical in physical_records:
        physical_path = physical["path"]
        if physical_path in registry_by_path:
            continue
        branch = str(physical.get("branch") or "(detached)")
        lane_kind = "canonical-main" if physical_path == workspace else "lane"
        is_excluded = physical_path in applied_exclusions
        entry = _lane_entry(
            branch=branch,
            path=physical_path,
            lane_kind=lane_kind,
            registry=None,
            registry_index=None,
            physical=physical,
            deadline=deadline,
            excluded=is_excluded,
            topology=_topology_name(physical_path, topology_roots),
        )
        if lane_kind == "canonical-main":
            entry["ownership"] = "canonical"
            entry["lane_state"] = "canonical"
        elif not is_excluded and entry["exists"]:
            # Keep the ownership state explicit while exposing dirty/unknown in
            # the separate worktree_state fields populated above.
            entry["physical_state"] = (
                "present-unregistered"
                if physical.get("worktree_state") in {"clean", "dirty"}
                else "unknown-unregistered"
            )
        registry_entries.append(entry)

    if not any(
        item["lane_kind"] == "canonical-main" and item["path"] == str(workspace)
        for item in registry_entries
    ):
        canonical = _lane_entry(
            branch="(canonical)",
            path=workspace,
            lane_kind="canonical-main",
            registry=None,
            registry_index=None,
            physical=physical_by_path.get(workspace),
            deadline=deadline,
            topology=_topology_name(workspace, topology_roots),
        )
        canonical["ownership"] = "canonical"
        canonical["lane_state"] = "canonical"
        registry_entries.append(canonical)

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
        for item in lanes
        if item["lane_kind"] == "lane"
        and item["exists"]
        and _path(item["path"]) != workspace
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
    accounted_lanes = [
        item for item in physical_lanes if item["accounted_in_aggregate"]
    ]
    lane_allocated = sum(int(item["allocated_bytes"]) for item in accounted_lanes)
    lane_logical = sum(int(item["logical_bytes"]) for item in accounted_lanes)
    observed_lane_allocated = sum(
        int(item["allocated_bytes"]) for item in physical_lanes
    )
    observed_lane_logical = sum(int(item["logical_bytes"]) for item in physical_lanes)
    excluded_lanes = [item for item in physical_lanes if item.get("excluded")]
    active_physical_lanes = [
        item
        for item in physical_lanes
        if item.get("registry_status") in LIVE_REGISTRY_STATUSES
    ]
    terminal_physical_lanes = [
        item
        for item in physical_lanes
        if item.get("registry_status") in TERMINAL_REGISTRY_STATUSES
    ]
    missing_active = sorted(
        {
            str(item["path"])
            for item in lanes
            if item["ownership"] == "registered"
            and item["registry_status"] in LIVE_REGISTRY_STATUSES
            and not item["exists"]
        }
    )
    missing_terminal = sorted(
        {
            str(item["path"])
            for item in lanes
            if item["ownership"] == "registered"
            and item["registry_status"] in TERMINAL_REGISTRY_STATUSES
            and not item["exists"]
        }
    )
    unregistered = sorted(
        str(item["path"])
        for item in physical_lanes
        if item["ownership"] == "unregistered"
    )
    dirty_physical = sorted(
        str(item["path"])
        for item in physical_lanes
        if item.get("worktree_state") == "dirty" and not item.get("excluded")
    )
    active_dirty_implementation = sorted(
        str(item["path"])
        for item in physical_lanes
        if item.get("worktree_state") == "dirty"
        and not item.get("excluded")
        and item.get("ownership") == "registered"
        and item.get("registry_status") == "active"
    )
    blocking_dirty_physical = sorted(
        str(item["path"])
        for item in physical_lanes
        if item.get("worktree_state") == "dirty"
        and not item.get("excluded")
        and not (
            item.get("ownership") == "registered"
            and item.get("registry_status") == "active"
        )
    )
    unknown_physical = sorted(
        str(item["path"])
        for item in physical_lanes
        if (
            not item.get("inspection_complete", True)
            and item.get("inspection_error") != "path-missing"
        )
        or item.get("worktree_state") == "unknown"
        or item.get("physical_state") in {"unverified", "unknown-unregistered"}
    )
    unknown_registry_paths = sorted(
        str(path)
        for path, matches in registry_by_path.items()
        if any(item[1].get("status") not in KNOWN_REGISTRY_STATUSES for item in matches)
    )
    physical_identity_mismatches = sorted(
        str(item["path"])
        for item in physical_lanes
        if item.get("registry_status") in KNOWN_REGISTRY_STATUSES
        and item.get("observed_branch")
        and item.get("observed_branch") != item.get("branch")
    )
    detached_registered = sorted(
        str(item["path"])
        for item in physical_lanes
        if item.get("registry_status") in KNOWN_REGISTRY_STATUSES
        and item.get("worktree_state") != "dirty"
        and item.get("observed_branch") is None
        and item.get("branch") not in {"(detached)", "(canonical)"}
        and item.get("physical_state") not in {"missing", "excluded"}
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
            str(item["path"])
            for item in accounted_lanes
            if int(item["allocated_bytes"]) > per_lane_budget
        }
    )
    blocking_reasons: list[str] = []
    warning_reasons: list[str] = []
    if registry_error:
        blocking_reasons.append(registry_error)
    if git_error:
        blocking_reasons.append(git_error)
        if git_error == "measurement-time-budget-exceeded":
            blocking_reasons.append(git_error)
    if topology_errors:
        blocking_reasons.extend(topology_errors)
    if malformed_registry_records:
        blocking_reasons.append("registry-records-invalid")
    if missing_active:
        warning_reasons.append("missing-registered-lane")
    if missing_terminal:
        warning_reasons.append("missing-terminal-lane")
    if terminal_physical_lanes:
        warning_reasons.append("terminal-physical-residue")
    if exclusion_rejections:
        warning_reasons.append("supervision-path-not-excluded")
        if any(
            item["reason"] == "registered-worktree" for item in exclusion_rejections
        ):
            blocking_reasons.append("supervision-path-registered")
    if unregistered:
        blocking_reasons.append("unregistered-physical-worktree")
    if blocking_dirty_physical:
        blocking_reasons.append("dirty-physical-worktree")
    if unknown_physical:
        blocking_reasons.append("unknown-physical-worktree")
    if unknown_registry_record_indices:
        blocking_reasons.append("unknown-registry-status")
    if physical_identity_mismatches or detached_registered:
        blocking_reasons.append("physical-identity-mismatch")
    duplicate_physical_paths = sorted(
        str(path) for path, count in physical_path_counts.items() if count > 1
    )
    if duplicate_physical_paths:
        blocking_reasons.append("duplicate-physical-worktree")
    duplicate_live_paths = sorted(
        str(path)
        for path, matches in registry_by_path.items()
        if sum(item[1].get("status") in LIVE_REGISTRY_STATUSES for item in matches) > 1
    )
    if duplicate_live_paths:
        blocking_reasons.append("duplicate-live-registry-claim")
    if not workspace_measurement["complete"]:
        blocking_reasons.append("workspace-measurement-incomplete")
    if not all(item["measurement_complete"] for item in accounted_lanes):
        blocking_reasons.append("lane-measurement-incomplete")
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
        blocking_reasons.append("measurement-time-budget-exceeded")
    if over_lane:
        blocking_reasons.extend(f"lane-budget-exceeded:{path}" for path in over_lane)
    if lane_allocated > total_lane_budget:
        blocking_reasons.append("lane-total-budget-exceeded")
    if blocking_reasons:
        verdict = "block"
    elif warning_reasons:
        verdict = "warning"
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
        blocking_reasons.append("filesystem-usage-unknown")
        verdict = "block"

    reasons = sorted({*blocking_reasons, *warning_reasons})
    product_lanes = [item for item in lanes if item["lane_kind"] == "lane"]
    lane_accounting = [
        {
            "lane_key": item["lane_key"],
            "branch": item["branch"],
            "path": item["path"],
            "exists": item["exists"],
            "ownership": item["ownership"],
            "registry_status": item["registry_status"],
            "lane_state": item["lane_state"],
            "physical_state": item["physical_state"],
            "logical_bytes": item["logical_bytes"],
            "allocated_bytes": item["allocated_bytes"],
            "files": item["files"],
            "measurement_complete": item["measurement_complete"],
            "measurement_error": item.get("measurement_error"),
            "measurement_errors": item.get("measurement_errors", []),
            "accounted_in_aggregate": item["accounted_in_aggregate"],
        }
        for item in product_lanes
    ]

    classification_items: dict[str, list[dict[str, Any]]] = {
        "active": [],
        "active_but_missing": [],
        "physical_but_unregistered": [],
        "terminal_residue": [],
        "unknown": [],
    }
    for item in product_lanes:
        if item["registry_status"] in LIVE_REGISTRY_STATUSES:
            classification = "active" if item["exists"] else "active_but_missing"
        elif item["registry_status"] in TERMINAL_REGISTRY_STATUSES:
            classification = "terminal_residue" if item["exists"] else "unknown"
        elif item["ownership"] == "unregistered":
            classification = "physical_but_unregistered"
        else:
            classification = "unknown"
        classification_items[classification].append(item)

    def classification_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "logical_bytes": sum(int(item["logical_bytes"]) for item in items),
            "allocated_bytes": sum(int(item["allocated_bytes"]) for item in items),
            "lane_keys": sorted(str(item["lane_key"]) for item in items),
            "paths": sorted(str(item["path"]) for item in items),
        }

    lane_attribution = {
        "product_lane_count": len(product_lanes),
        "product_lane_logical_bytes": sum(
            int(item["logical_bytes"]) for item in product_lanes
        ),
        "product_lane_allocated_bytes": sum(
            int(item["allocated_bytes"]) for item in product_lanes
        ),
        "product_lane_keys": sorted(str(item["lane_key"]) for item in product_lanes),
        "classifications": {
            name: classification_summary(classification_items[name])
            for name in sorted(classification_items)
        },
    }

    return {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "registry": str(state_path),
        "measurement": {
            "budget_seconds": time_budget_seconds,
            "elapsed_seconds": round(time.monotonic() - measurement_started, 3),
            "budget_exhausted": measurement_budget_exhausted,
        },
        "topology": {
            "roots": [str(root) for root in topology_roots],
            "observed_roots": sorted(
                str(root) for root in topology_roots if root.is_dir()
            ),
            "observed_worktree_paths": sorted(
                str(item["path"])
                for item in physical_lanes
                if item.get("topology") in {"claude", "codex"}
            ),
            "codex_worktree_paths": sorted(
                str(item["path"])
                for item in physical_lanes
                if item.get("topology") == "codex"
            ),
            "errors": sorted(topology_errors),
        },
        "lanes": lanes,
        "lane_count": len([item for item in lanes if item["lane_kind"] == "lane"]),
        "lane_attribution": lane_attribution,
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
            "physical_lane_observed_logical_bytes": observed_lane_logical,
            "physical_lane_observed_allocated_bytes": observed_lane_allocated,
            "physical_lane_excluded_logical_bytes": sum(
                int(item["logical_bytes"]) for item in excluded_lanes
            ),
            "physical_lane_excluded_allocated_bytes": sum(
                int(item["allocated_bytes"]) for item in excluded_lanes
            ),
            "active_physical_lane_count": len(active_physical_lanes),
            "terminal_physical_lane_count": len(terminal_physical_lanes),
            "excluded_physical_lane_count": len(excluded_lanes),
            "lane_accounting": lane_accounting,
            "managed_logical_bytes": workspace_measurement["logical_bytes"]
            + lane_logical,
            "managed_allocated_bytes": workspace_measurement["allocated_bytes"]
            + lane_allocated,
            "nested_worktrees_excluded_from_workspace": sorted(
                str(item) for item in nested_worktrees
            ),
            "lane_attribution": lane_attribution,
        },
        "filesystem": filesystem_payload,
        "policy": {
            "verdict": verdict,
            "per_lane_budget_bytes": per_lane_budget,
            "total_lane_budget_bytes": total_lane_budget,
            "reasons": sorted(set(reasons)),
            "blocking_reasons": sorted(set(blocking_reasons)),
            "warning_reasons": sorted(set(warning_reasons)),
            "missing_active_lanes": missing_active,
            "missing_terminal_lanes": missing_terminal,
            "unregistered_physical_worktrees": unregistered,
            "dirty_physical_worktrees": dirty_physical,
            "unknown_physical_worktrees": unknown_physical,
            "unknown_registry_paths": unknown_registry_paths,
            "unknown_registry_record_indices": unknown_registry_record_indices,
            "active_dirty_implementation_worktrees": active_dirty_implementation,
            "blocking_dirty_physical_worktrees": blocking_dirty_physical,
            "physical_identity_mismatches": sorted(
                set(physical_identity_mismatches + detached_registered)
            ),
            "terminal_physical_residue": sorted(
                str(item["path"]) for item in terminal_physical_lanes
            ),
            "excluded_physical_worktrees": sorted(
                str(item["path"]) for item in excluded_lanes
            ),
            "lane_budget_exceeded": over_lane,
        },
        "exclusions": {
            "matching": "exact-path-only",
            "supervision_worktree_paths": [
                str(item) for item in requested_supervision_paths
            ],
            "applied_paths": [str(item) for item in applied_exclusions],
            "rejected_paths": [item["path"] for item in exclusion_rejections],
            "rejections": exclusion_rejections,
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
    parser.add_argument(
        "--supervision-worktree",
        action="append",
        default=[],
        metavar="PATH",
        help="exclude this exact caller-supplied supervision worktree from managed quota",
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
        supervision_worktree_paths=tuple(args.supervision_worktree),
    )
    if args.output:
        _write_atomic(_path(args.output), report)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["policy"]["verdict"] != "block" else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())

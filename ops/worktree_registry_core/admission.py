"""Atomic ownership admission policy for external references and file Scope."""

from __future__ import annotations

from typing import Any

from lib.worktree_scope import scope_files

from .records import (
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    STATUS_PUBLISHED,
    legacy_external_ids,
    norm_path,
)

CLAIM_SELECTION_STATUSES = frozenset({STATUS_ACTIVE, STATUS_CLEANUP_PENDING})
OWNERSHIP_STATUSES = frozenset(
    {STATUS_ACTIVE, STATUS_CLEANUP_PENDING, STATUS_PUBLISHED}
)


def ownership_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for record in state.get("records", [])
        if isinstance(record, dict) and record.get("status") in OWNERSHIP_STATUSES
    ]


def ownership_conflicts(
    state: dict[str, Any],
    *,
    branch: str,
    path: str,
    external_ids: list[str],
    scope: object,
    excluded_record: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    wanted_ids = set(external_ids)
    wanted_paths = {item["path"] for item in scope_files(scope)}
    conflicts: list[dict[str, Any]] = []
    for record in ownership_records(state):
        if record is excluded_record:
            continue
        branch_overlap = record.get("branch") == branch
        local_path_overlap = norm_path(str(record.get("path") or "")) == norm_path(path)
        try:
            id_overlap = sorted(wanted_ids.intersection(legacy_external_ids(record)))
        except (TypeError, ValueError):
            id_overlap = []
        path_overlap = sorted(
            wanted_paths.intersection(
                {item["path"] for item in scope_files(record.get("scope"))}
            )
        )
        if branch_overlap or local_path_overlap or id_overlap or path_overlap:
            conflict = {
                "branch": record.get("branch"),
                "path": record.get("path"),
                "status": record.get("status"),
                "external_ids": id_overlap,
                "scope_paths": path_overlap,
            }
            if branch_overlap:
                conflict["branch_overlap"] = True
            if local_path_overlap:
                conflict["worktree_path_overlap"] = True
            conflicts.append(conflict)
    return conflicts


def select_owner_record(
    state: dict[str, Any], *, branch: str, path: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Select one existing claim without permitting branch/path cross-splicing."""
    records = [
        record
        for record in ownership_records(state)
        if record.get("status") in CLAIM_SELECTION_STATUSES
    ]
    branch_matches = [record for record in records if record.get("branch") == branch]
    path_matches = [
        record
        for record in records
        if norm_path(str(record.get("path") or "")) == norm_path(path)
    ]
    unique = {id(record): record for record in (*branch_matches, *path_matches)}
    if len(branch_matches) > 1 or len(path_matches) > 1 or len(unique) > 1:
        return None, [
            {
                "branch": record.get("branch"),
                "path": record.get("path"),
                "status": record.get("status"),
                "reason": "branch and path select different ownership claims",
            }
            for record in unique.values()
        ]
    return next(iter(unique.values()), None), []

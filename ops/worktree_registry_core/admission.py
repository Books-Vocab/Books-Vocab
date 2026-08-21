"""Atomic ownership admission policy for external references and file Scope."""

from __future__ import annotations

from typing import Any

from lib.worktree_scope import scope_files

from .records import (
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    legacy_external_ids,
    norm_path,
)

ADMISSION_STATUSES = frozenset({STATUS_ACTIVE, STATUS_CLEANUP_PENDING})


def admission_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for record in state.get("records", [])
        if isinstance(record, dict) and record.get("status") in ADMISSION_STATUSES
    ]


def ownership_conflicts(
    state: dict[str, Any],
    *,
    branch: str,
    path: str,
    external_ids: list[str],
    scope: object,
) -> list[dict[str, Any]]:
    wanted_ids = set(external_ids)
    wanted_paths = {item["path"] for item in scope_files(scope)}
    conflicts: list[dict[str, Any]] = []
    for record in admission_records(state):
        same_owner = record.get("branch") == branch or norm_path(
            str(record.get("path") or "")
        ) == norm_path(path)
        if same_owner:
            continue
        try:
            id_overlap = sorted(wanted_ids.intersection(legacy_external_ids(record)))
        except (TypeError, ValueError):
            id_overlap = []
        path_overlap = sorted(
            wanted_paths.intersection(
                {item["path"] for item in scope_files(record.get("scope"))}
            )
        )
        if id_overlap or path_overlap:
            conflicts.append(
                {
                    "branch": record.get("branch"),
                    "path": record.get("path"),
                    "status": record.get("status"),
                    "external_ids": id_overlap,
                    "scope_paths": path_overlap,
                }
            )
    return conflicts

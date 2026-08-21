"""Registry record normalization and status classification.

This module deliberately has no Git or CLI dependencies.  It preserves malformed
input as named problems so the delivery controller can fail closed instead of
silently planning from an incomplete inventory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "kg.worktree.registry.v2"
STATUS_ACTIVE = "active"
STATUS_CLEANUP_PENDING = "cleanup_pending"
STATUS_PUBLISHED = "published"
STATUS_MERGED = "merged"
STATUS_ABANDONED = "abandoned"
NON_TERMINAL_STATUSES = frozenset(
    {STATUS_ACTIVE, STATUS_CLEANUP_PENDING, STATUS_PUBLISHED}
)
TERMINAL_STATUSES = frozenset({STATUS_MERGED, STATUS_ABANDONED})
KNOWN_STATUSES = NON_TERMINAL_STATUSES | TERMINAL_STATUSES

CURRENT_RECORD_FIELDS = (
    "branch",
    "path",
    "intent",
    "base",
    "status",
    "external_ids",
    "scope",
    "codex_thread_id",
    "delegated",
    "created_at",
    "claimed_at",
    "resolved_at",
    "claim_generation",
    "base_sha",
    "handed_back_at",
    "handed_back_sha",
    "handback_claim_generation",
    "handback_seal",
    "handback_outcomes",
)


def norm_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def external_ids(value: object) -> list[str]:
    if value is None:
        return []
    raw = [value] if isinstance(value, str) else value
    if not isinstance(raw, list):
        raise TypeError("external ids must be a list of strings")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("external ids must contain non-empty strings")
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return result


def legacy_external_ids(record: dict[str, Any]) -> list[str]:
    value = record.get("external_ids")
    if value is None:
        value = record.get("backlog")
    return external_ids(value)


def normalize_record(
    value: object, *, index: int
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return None, [{"kind": "registry-record-not-object", "index": index}]
    record = dict(value)
    problems: list[dict[str, Any]] = []
    try:
        record["external_ids"] = legacy_external_ids(record)
    except (TypeError, ValueError) as exc:
        record["external_ids"] = []
        problems.append(
            {
                "kind": "registry-external-ids-invalid",
                "index": index,
                "reason": str(exc),
            }
        )
    record.pop("backlog", None)
    return record, problems


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    compacted = {key: record[key] for key in CURRENT_RECORD_FIELDS if key in record}
    try:
        compacted["external_ids"] = legacy_external_ids(record)
    except (TypeError, ValueError):
        compacted["external_ids"] = []
    compacted.pop("backlog", None)
    return compacted


def record_matches(
    record: dict[str, Any], *, branch: str | None = None, path: str | None = None
) -> bool:
    return (branch is None or record.get("branch") == branch) and (
        path is None or norm_path(str(record.get("path") or "")) == norm_path(path)
    )


def records_with_status(
    state: dict[str, Any], statuses: frozenset[str] | set[str]
) -> list[dict[str, Any]]:
    return [
        record
        for record in state.get("records", [])
        if isinstance(record, dict) and record.get("status") in statuses
    ]


def active_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return records_with_status(state, {STATUS_ACTIVE})


def retained_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every record that still participates in an in-flight transaction."""
    return records_with_status(state, NON_TERMINAL_STATUSES)

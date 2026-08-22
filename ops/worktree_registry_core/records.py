"""Registry record normalization and status classification.

This module deliberately has no Git or CLI dependencies.  It preserves malformed
input as named problems so the delivery controller can fail closed instead of
silently planning from an incomplete inventory.
"""

from __future__ import annotations

import hashlib
import json
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
TERMINAL_PROOF_SCHEMA = "kg.worktree.terminal-proof.v1"

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
    "published_base_sha",
    "published_base_recorded_at",
    "handed_back_at",
    "handed_back_sha",
    "handback_claim_generation",
    "handback_seal",
    "handback_outcomes",
    "terminal_proof",
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


def terminal_proof_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    proof = dict(body)
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    proof["digest"] = hashlib.sha256(encoded).hexdigest()
    return proof


def terminal_proof_problem(
    proof: object,
    *,
    branch: object,
    head_sha: object,
    record_external_ids: object,
) -> str | None:
    if not isinstance(proof, dict):
        return "terminal proof must be an object"
    digest = proof.get("digest")
    body = {key: value for key, value in proof.items() if key != "digest"}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if digest != hashlib.sha256(encoded).hexdigest():
        return "terminal proof digest is invalid"
    if not isinstance(record_external_ids, list):
        return "terminal proof record has invalid external ids"
    expected = {
        "schema": TERMINAL_PROOF_SCHEMA,
        "pr_state": "MERGED",
        "base_branch": "main",
        "branch": branch,
        "head_sha": head_sha,
    }
    for key, value in expected.items():
        if body.get(key) != value:
            return f"terminal proof {key} does not match exact merged PR"
    if type(body.get("pr_number")) is not int or body["pr_number"] <= 0:
        return "terminal proof PR number is invalid"
    lane_id = body.get("lane_id")
    # Direct assignments intentionally have no Issue/PR external ID.  The
    # registry parser uses the branch as their canonical lane identity, so
    # terminal proof validation must use the same fallback instead of making
    # an empty external-id list an impossible cleanup claim.
    allowed_lane_ids = record_external_ids or [branch]
    if type(lane_id) is not str or lane_id not in allowed_lane_ids:
        return "terminal proof lane does not match the registry claim"
    return None


def stored_terminal_proof_problem(record: dict[str, Any]) -> str | None:
    if "terminal_proof" not in record:
        return None
    if record.get("status") != STATUS_MERGED:
        return "terminal proof is only valid for merged disposition"
    proof = record["terminal_proof"]
    stored_head = record.get("handed_back_sha")
    if stored_head is None and isinstance(proof, dict):
        # Older exact terminal transitions may not have a hand-back receipt.
        # Their validated head remains durable inside the immutable proof.
        stored_head = proof.get("head_sha")
    return terminal_proof_problem(
        proof,
        branch=record.get("branch"),
        head_sha=stored_head,
        record_external_ids=record.get("external_ids"),
    )


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
        problems.append(
            {
                "kind": "registry-external-ids-invalid",
                "index": index,
                "branch": record.get("branch"),
                "status": record.get("status"),
                "reason": str(exc),
            }
        )
    else:
        record.pop("backlog", None)
    status = record.get("status")
    if status not in KNOWN_STATUSES:
        problems.append(
            {
                "kind": "registry-status-unknown",
                "index": index,
                "branch": record.get("branch"),
                "status": status,
            }
        )
    proof_problem = stored_terminal_proof_problem(record)
    if proof_problem:
        problems.append(
            {
                "kind": "registry-terminal-proof-invalid",
                "index": index,
                "branch": record.get("branch"),
                "status": status,
                "reason": proof_problem,
            }
        )
    return record, problems


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    compacted = {key: record[key] for key in CURRENT_RECORD_FIELDS if key in record}
    try:
        compacted["external_ids"] = legacy_external_ids(record)
    except (TypeError, ValueError):
        if "external_ids" in record:
            compacted["external_ids"] = record["external_ids"]
        elif "backlog" in record:
            compacted["backlog"] = record["backlog"]
    else:
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
    """Return every record retained by lossless registry compaction."""
    return [record for record in state.get("records", []) if isinstance(record, dict)]


def mutation_blockers(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return malformed ownership facts that make a ledger mutation unsafe."""
    return [
        problem
        for problem in state.get("problems", [])
        if isinstance(problem, dict) and problem.get("status") not in TERMINAL_STATUSES
    ]

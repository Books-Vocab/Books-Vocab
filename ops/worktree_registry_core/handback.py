"""Typed hand-back seal construction and immutable provenance checks."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from .records import legacy_external_ids, norm_path

HAND_BACK_SEAL_SCHEMA = "kg.worktree.handback.v1"
GREEN_ACCEPTANCE_STATUSES = {"pass", "passed", "green", "ok", "success"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def acceptance_status(value: object) -> str:
    return str(value or "").strip().lower()


def clear_handback(record: dict[str, Any]) -> None:
    record["handed_back_at"] = None
    record["handed_back_sha"] = None
    record.pop("handback_claim_generation", None)
    record.pop("handback_seal", None)
    record.pop("handback_outcomes", None)


def advance_claim(record: dict[str, Any]) -> None:
    generation = record.get("claim_generation", 0)
    record["claim_generation"] = generation + 1 if type(generation) is int else 1
    clear_handback(record)


def seal_body(
    record: dict[str, Any],
    *,
    base_sha: str,
    tip_sha: str,
    outcomes: list[dict[str, Any]],
    handed_back_at: str,
    origin_main_sha: str | None = None,
) -> dict[str, Any]:
    body = {
        "schema": HAND_BACK_SEAL_SCHEMA,
        "branch": record.get("branch"),
        "path": norm_path(str(record.get("path") or "")),
        "owner_thread_id": record.get("codex_thread_id"),
        "external_ids": sorted(legacy_external_ids(record)),
        "base_sha": base_sha,
        "tip_sha": tip_sha,
        "outcomes": outcomes,
        "handed_back_at": handed_back_at,
    }
    if origin_main_sha is not None:
        body["origin_main_sha"] = origin_main_sha
    return body


def seal_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    result["digest"] = hashlib.sha256(canonical_json(body)).hexdigest()
    return result


def _parse_timestamp(value: str) -> None:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")


def validate_handback_seal(
    record: dict[str, Any], *, require_green: bool = True
) -> list[dict[str, Any]]:
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        return [{"kind": "handback-seal-missing"}]
    digest = seal.get("digest")
    body = {key: value for key, value in seal.items() if key != "digest"}
    problems: list[dict[str, Any]] = []
    if seal.get("schema") != HAND_BACK_SEAL_SCHEMA:
        problems.append({"kind": "handback-seal-schema-invalid"})
    if digest != hashlib.sha256(canonical_json(body)).hexdigest():
        problems.append({"kind": "handback-seal-digest-invalid"})
    if body.get("branch") != record.get("branch"):
        problems.append({"kind": "handback-seal-branch-mismatch"})
    if body.get("owner_thread_id") != record.get("codex_thread_id"):
        problems.append({"kind": "handback-seal-owner-mismatch"})
    try:
        record_ids = sorted(legacy_external_ids(record))
    except (TypeError, ValueError):
        record_ids = []
        problems.append({"kind": "handback-record-external-ids-invalid"})
    if sorted(body.get("external_ids") or []) != record_ids:
        problems.append({"kind": "handback-seal-external-ids-mismatch"})
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        problems.append({"kind": "handback-outcomes-invalid"})
    elif require_green:
        for item in outcomes:
            if (
                not isinstance(item, dict)
                or acceptance_status(item.get("status"))
                not in GREEN_ACCEPTANCE_STATUSES
            ):
                problems.append({"kind": "handback-outcome-not-green", "outcome": item})
    return problems


def has_valid_stored_handback(record: dict[str, Any], *, is_commit_sha: Any) -> bool:
    branch = record.get("branch")
    path = record.get("path")
    handed_back_at = record.get("handed_back_at")
    handed_back_sha = record.get("handed_back_sha")
    seal = record.get("handback_seal")
    if not isinstance(branch, str) or not branch:
        return False
    if not isinstance(path, str) or not path:
        return False
    if not isinstance(handed_back_at, str) or not handed_back_at:
        return False
    if not is_commit_sha(handed_back_sha) or not isinstance(seal, dict):
        return False
    try:
        _parse_timestamp(handed_back_at)
    except (TypeError, ValueError):
        return False
    if seal.get("handed_back_at") != handed_back_at:
        return False
    if seal.get("tip_sha") != handed_back_sha:
        return False
    generation = record.get("claim_generation")
    handback_generation = record.get("handback_claim_generation")
    if (
        type(generation) is not int
        or type(handback_generation) is not int
        or generation < 0
        or generation != handback_generation
    ):
        return False
    return not validate_handback_seal(record)

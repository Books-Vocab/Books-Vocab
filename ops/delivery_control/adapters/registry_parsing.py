"""Translate worktree-registry wire payloads into delivery observations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.errors import InvalidScope
from ..domain.models import HandbackOutcome, Scope
from ..domain.observations import (
    InventoryProblem,
    RegistryCollisionClaim,
    RegistrySnapshot,
)
from .registry_seals import legacy_seal_valid, parse_initial_holds
from .timestamps import parse_optional_timestamp

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REGISTRY_STATUSES = {
    "active",
    "cleanup_pending",
    "published",
    "merged",
    "abandoned",
}
_TERMINAL_STATUSES = frozenset({"published", "merged", "abandoned"})
_IDENTITY_KINDS = frozenset({"branch", "path", "record", "unknown"})


def _reported_identity_kind(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("identity_kind")
    return value if isinstance(value, str) and value in _IDENTITY_KINDS else None


def _reported_problem_identity(raw: Mapping[str, Any], index: int) -> tuple[str, str]:
    """Recover the raw record identity carried beside a reported problem."""

    branch = raw.get("branch")
    if branch:
        return str(branch), "branch"
    path = raw.get("path")
    if path:
        return str(path), "path"
    return f"record[{index}]", "record"


def _raw_record_for_problem(
    payload: Mapping[str, Any], raw: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    index = raw.get("index") if isinstance(raw, Mapping) else None
    if type(index) is int and 0 <= index < len(records):
        record = records[index]
        if isinstance(record, Mapping):
            return record
    identity = raw.get("identity") if isinstance(raw, Mapping) else None
    identity = (
        raw.get("branch") if not identity and isinstance(raw, Mapping) else identity
    )
    if isinstance(identity, str) and identity.strip():
        for record in records:
            if isinstance(record, Mapping) and record.get("branch") == identity:
                return record
    return None


def _raw_record_path(record: Mapping[str, Any] | None) -> Path | None:
    value = record.get("path") if isinstance(record, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else None


def _raw_owner_thread_id(record: Mapping[str, Any] | None) -> str | None:
    value = record.get("codex_thread_id") if isinstance(record, Mapping) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def record_external_ids(record: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Preserve only explicit, well-formed IDs from one raw registry record."""

    values = record.get("external_ids") if isinstance(record, Mapping) else None
    if not isinstance(values, list) or any(
        type(value) is not str or not value.strip() for value in values
    ):
        return ()
    return tuple(value.strip() for value in values)


def reported_problems(payload: Mapping[str, Any]) -> tuple[InventoryProblem, ...]:
    if "problems" not in payload:
        return ()
    raw_problems = payload["problems"]
    if not isinstance(raw_problems, list):
        return (
            InventoryProblem(
                "registry",
                "problems",
                "registry problems field must be a list",
            ),
        )
    problems: list[InventoryProblem] = []
    for index, raw in enumerate(raw_problems):
        record = _raw_record_for_problem(
            payload, raw if isinstance(raw, Mapping) else None
        )
        record_path = _raw_record_path(record)
        owner_thread_id = _raw_owner_thread_id(record)
        identity = raw.get("identity") if isinstance(raw, Mapping) else None
        reason = raw.get("reason") if isinstance(raw, Mapping) else None
        record_status = (
            raw.get("status")
            if isinstance(raw, Mapping) and isinstance(raw.get("status"), str)
            else None
        )
        if record_status is None and isinstance(record, Mapping):
            raw_status = record.get("status")
            if raw_status == "active":
                record_status = raw_status
        observed_record_path = record_path if record_status == "active" else None
        observed_owner_thread_id = (
            owner_thread_id if record_status == "active" else None
        )
        if (
            isinstance(identity, str)
            and identity.strip()
            and isinstance(reason, str)
            and reason.strip()
        ):
            problems.append(
                InventoryProblem(
                    "registry",
                    identity.strip(),
                    reason.strip(),
                    identity_kind=_reported_identity_kind(raw),
                    record_status=record_status,
                    record_path=observed_record_path,
                    owner_thread_id=observed_owner_thread_id,
                    record_external_ids=record_external_ids(record),
                )
            )
            continue
        kind = raw.get("kind") if isinstance(raw, Mapping) else None
        record_index = raw.get("index") if isinstance(raw, Mapping) else None
        if isinstance(kind, str) and kind.strip():
            if type(record_index) is int and record_index >= 0:
                problem_identity, inferred_identity_kind = _reported_problem_identity(
                    raw, record_index
                )
            else:
                problem_identity = f"problem[{index}]"
                inferred_identity_kind = _reported_identity_kind(raw)
            detail = kind.strip()
            if isinstance(reason, str) and reason.strip():
                detail = f"{detail}: {reason.strip()}"
            problems.append(
                InventoryProblem(
                    "registry",
                    problem_identity,
                    detail,
                    identity_kind=(
                        _reported_identity_kind(raw) or inferred_identity_kind
                    ),
                    record_status=record_status,
                    record_path=observed_record_path,
                    owner_thread_id=observed_owner_thread_id,
                    record_external_ids=record_external_ids(record),
                )
            )
            continue
        problems.append(
            InventoryProblem(
                "registry",
                f"problem[{index}]",
                "registry problem entry is malformed",
                record_path=observed_record_path,
                owner_thread_id=observed_owner_thread_id,
                record_external_ids=record_external_ids(record),
            )
        )
    return tuple(problems)


def parse_registry_record(payload: Mapping[str, Any]) -> RegistrySnapshot:
    branch = str(payload["branch"])
    status = payload.get("status")
    if not isinstance(status, str) or status not in _REGISTRY_STATUSES:
        raise ValueError(f"unsupported registry status: {status!r}")
    path = Path(str(payload["path"])).expanduser()
    if not path.is_absolute():
        raise ValueError("registry path must be absolute")
    scope_payload = payload["scope"]
    if not isinstance(scope_payload, Mapping):
        raise InvalidScope("Scope must be an object")
    scope = Scope.from_payload(scope_payload)
    base_value = payload.get("base_sha") or payload.get("base")
    base_sha = str(base_value or "")
    if not _SHA_RE.fullmatch(base_sha) and status in _TERMINAL_STATUSES:
        seal = payload.get("handback_seal")
        sealed_base = seal.get("base_sha") if isinstance(seal, Mapping) else None
        if isinstance(sealed_base, str) and _SHA_RE.fullmatch(sealed_base):
            base_sha = sealed_base
    if not _SHA_RE.fullmatch(base_sha):
        raise ValueError("registry base must be an exact commit SHA")
    published_base = payload.get("published_base_sha")
    if published_base is not None and not _SHA_RE.fullmatch(str(published_base)):
        raise ValueError("published PR base must be an exact commit SHA")
    external_ids_payload = payload.get("external_ids")
    if external_ids_payload is not None and (
        not isinstance(external_ids_payload, list)
        or any(
            type(item) is not str or not item.strip() for item in external_ids_payload
        )
    ):
        raise ValueError("registry external_ids must be non-empty strings")
    external_ids = (
        tuple(item.strip() for item in external_ids_payload)
        if isinstance(external_ids_payload, list)
        else ()
    )
    lane_id = external_ids[0] if external_ids else branch
    handed_back_sha = payload.get("handed_back_sha")
    seal = payload.get("handback_seal")
    handback_digest = seal.get("digest") if isinstance(seal, Mapping) else None
    handback_origin = seal.get("origin_main_sha") if isinstance(seal, Mapping) else None
    claim_generation = payload.get("claim_generation")
    handback_claim_generation = payload.get("handback_claim_generation")
    if type(claim_generation) is not int or claim_generation < 0:
        raise ValueError("registry claim_generation must be a non-negative integer")
    if handback_claim_generation is not None and (
        type(handback_claim_generation) is not int or handback_claim_generation < 0
    ):
        raise ValueError(
            "registry handback_claim_generation must be a non-negative integer"
        )
    handback_valid = legacy_seal_valid(payload)
    raw_outcomes = seal.get("outcomes") if isinstance(seal, Mapping) else None
    handback_outcomes = (
        tuple(HandbackOutcome.from_payload(item) for item in raw_outcomes)
        if handback_valid and isinstance(raw_outcomes, list)
        else ()
    )
    handback_initial_holds = (
        parse_initial_holds(seal)
        if handback_valid and isinstance(seal, Mapping)
        else ()
    )
    return RegistrySnapshot(
        lane_id=lane_id,
        branch=branch,
        path=path.resolve(),
        status=status,
        scope=scope,
        base_sha=base_sha,
        published_base_sha=(
            str(published_base) if published_base is not None else None
        ),
        claim_generation=claim_generation,
        external_ids=external_ids,
        owner_thread_id=(
            str(payload["codex_thread_id"]) if payload.get("codex_thread_id") else None
        ),
        handed_back_sha=(str(handed_back_sha) if handed_back_sha else None),
        handback_claim_generation=handback_claim_generation,
        handback_valid=handback_valid,
        handback_digest=(
            str(handback_digest)
            if isinstance(handback_digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", handback_digest)
            else None
        ),
        handback_origin_main_sha=(
            str(handback_origin)
            if isinstance(handback_origin, str) and _SHA_RE.fullmatch(handback_origin)
            else None
        ),
        handed_back_at=parse_optional_timestamp(
            payload.get("handed_back_at"), field="registry handed_back_at"
        ),
        handback_outcomes=handback_outcomes,
        handback_initial_holds=handback_initial_holds,
    )


def parse_collision_claim(payload: Mapping[str, Any]) -> RegistryCollisionClaim:
    branch = str(payload["branch"])
    if not branch:
        raise ValueError("registry branch must be non-empty")
    scope_payload = payload["scope"]
    if not isinstance(scope_payload, Mapping):
        raise InvalidScope("Scope must be an object")
    external_ids = payload.get("external_ids")
    if not isinstance(external_ids, list):
        external_ids = []
    return RegistryCollisionClaim(
        lane_id=str(external_ids[0]) if external_ids else branch,
        branch=branch,
        scope=Scope.from_payload(scope_payload),
    )

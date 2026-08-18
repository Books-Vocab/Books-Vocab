"""Standalone, time-bounded reuse contract for Gate cost verdicts.

This module deliberately stops at a machine-readable contract.  It does not
import or call the existing fingerprint, execution-plan, or central-runner
surfaces.  A later Manager change may wire this verdict into those surfaces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, TypeAlias

IDENTITY_SCHEMA = "kg.gate.cost-reuse-identity.v1"
VERDICT_SCHEMA = "kg.gate.cost-reuse-verdict.v1"

_REQUIRED_IDENTITY_FIELDS = frozenset(
    {
        "schema",
        "head",
        "base",
        "changed_file_digest",
        "command_digest",
        "test_definition_digest",
        "fixture_digest",
        "toolchain",
        "scope",
        "tier",
        "issued_at",
        "expires_at",
        "ttl_seconds",
        "identity_digest",
    }
)
_COMPARABLE_FIELDS = (
    "head",
    "base",
    "changed_file_digest",
    "command_digest",
    "test_definition_digest",
    "fixture_digest",
    "toolchain",
    "scope",
    "tier",
    "ttl_seconds",
)
_PASS_VERDICTS = frozenset({"pass", "passed", "green", "ok", "success"})
_WARN_VERDICTS = frozenset({"warn", "warning"})
_UTC = timezone.utc

Timestamp: TypeAlias = str | int | float | datetime

WIRING_FOLLOW_UP: dict[str, Any] = {
    "owner": "manager",
    "next_step": (
        "connect reuse result through the existing fingerprint and "
        "execution-plan path plus central runner after this ticket lands"
    ),
    "files": ["existing-fingerprint", "existing-execution-plan", "central-runner"],
}


class ReuseContractError(ValueError):
    """Raised when a reuse identity cannot be made exact and time-bounded."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReuseContractError(f"value is not JSON-serializable: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def dumps(value: Any) -> str:
    """Serialize a contract with stable JSON suitable for a runner boundary."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_copy(value: Any, *, field: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ReuseContractError(f"{field} must be JSON-serializable") from exc


def _normalise_token(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReuseContractError(f"{field} must be a non-empty string")
    if any(character.isspace() for character in value.strip()):
        raise ReuseContractError(f"{field} must not contain whitespace")
    return value.strip()


def _normalise_tier(value: Any) -> str:
    if not isinstance(value, str):
        raise ReuseContractError("tier must be one of S0, S1, S2, S3, S4")
    tier = value.strip().upper()
    if tier not in {"S0", "S1", "S2", "S3", "S4"}:
        raise ReuseContractError("tier must be one of S0, S1, S2, S3, S4")
    return tier


def _normalise_changed_files(value: Any) -> list[Any]:
    if value is None:
        values: list[Any] = []
    elif isinstance(value, (str, Mapping)):
        values = [value]
    else:
        try:
            values = list(value)
        except TypeError as exc:
            raise ReuseContractError("changed_files must be iterable") from exc

    normalised: list[Any] = []
    for item in values:
        if isinstance(item, str):
            if not item.strip():
                raise ReuseContractError("changed_files cannot contain an empty path")
            normalised.append(item.strip())
        elif isinstance(item, Mapping):
            normalised.append(_json_copy(item, field="changed_files"))
        else:
            raise ReuseContractError("changed_files entries must be strings or objects")
    return sorted({dumps(item) for item in normalised})


def _normalise_command(value: Any) -> Any:
    if value is None:
        raise ReuseContractError("command is required")
    if isinstance(value, str):
        command = value.strip()
        if not command:
            raise ReuseContractError("command must be non-empty")
        return command
    copied = _json_copy(value, field="command")
    if copied in (None, "", [], {}):
        raise ReuseContractError("command must be non-empty")
    return copied


def _normalise_required_value(value: Any, *, field: str) -> Any:
    if value is None:
        raise ReuseContractError(f"{field} is required")
    copied = _json_copy(value, field=field)
    if copied in (None, "", [], {}):
        raise ReuseContractError(f"{field} is required")
    return copied


def _parse_timestamp(value: Timestamp, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(value, tz=_UTC)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ReuseContractError(f"{field} must be an ISO-8601 timestamp") from exc
    else:
        raise ReuseContractError(f"{field} must be an ISO-8601 timestamp")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReuseContractError(f"{field} must include a timezone")
    return parsed.astimezone(_UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat().replace("+00:00", "Z")


def _resolve_ttl(
    *,
    issued_at: Timestamp | None,
    expires_at: Timestamp | None,
    ttl_seconds: float | None,
    now: Timestamp | None,
) -> tuple[str, str, float]:
    issued = _parse_timestamp(
        issued_at if issued_at is not None else (now if now is not None else datetime.now(_UTC)),
        field="issued_at",
    )
    if ttl_seconds is not None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ReuseContractError("ttl_seconds must be a positive number")
        if ttl_seconds <= 0:
            raise ReuseContractError("ttl_seconds must be a positive number")

    if expires_at is None:
        if ttl_seconds is None:
            raise ReuseContractError("expires_at or ttl_seconds is required")
        expires = issued + timedelta(seconds=float(ttl_seconds))
    else:
        expires = _parse_timestamp(expires_at, field="expires_at")

    actual_ttl = (expires - issued).total_seconds()
    if actual_ttl <= 0:
        raise ReuseContractError("expires_at must be later than issued_at")
    if ttl_seconds is not None and abs(actual_ttl - float(ttl_seconds)) > 1e-6:
        raise ReuseContractError("ttl_seconds does not match issued_at/expires_at")
    return _format_timestamp(issued), _format_timestamp(expires), actual_ttl


def build_reuse_identity(
    *,
    head: str,
    base: str,
    changed_files: Iterable[Any] | Any,
    command: Any = None,
    test_definition: Any = None,
    fixture: Any = None,
    toolchain: Mapping[str, Any] | Any,
    scope: Any,
    tier: str,
    issued_at: Timestamp | None = None,
    expires_at: Timestamp | None = None,
    ttl_seconds: float | None = None,
    now: Timestamp | None = None,
    acceptance_command: Any = None,
    test_definitions: Any = None,
    fixtures: Any = None,
) -> dict[str, Any]:
    """Build the exact, standalone identity used by reuse evaluation.

    ``issued_at``/``expires_at`` describe the validity window of this record;
    they are intentionally not compared as content identity.  A new contract
    can therefore be issued for the same exact inputs while the prior verdict
    remains valid, without extending the prior record's TTL.
    """
    if command is None:
        command = acceptance_command
    if test_definition is None:
        test_definition = test_definitions
    if fixture is None:
        fixture = fixtures

    issued_text, expires_text, actual_ttl = _resolve_ttl(
        issued_at=issued_at,
        expires_at=expires_at,
        ttl_seconds=ttl_seconds,
        now=now,
    )
    changed = _normalise_changed_files(changed_files)
    command_value = _normalise_command(command)
    definition_value = _normalise_required_value(
        test_definition if test_definition is not None else {"files": []},
        field="test_definition",
    )
    fixture_value = _json_copy(
        fixture if fixture is not None else {"files": []},
        field="fixture",
    )
    toolchain_value = _normalise_required_value(toolchain, field="toolchain")
    scope_value = _normalise_required_value(scope, field="scope")
    tier_value = _normalise_tier(tier)

    identity: dict[str, Any] = {
        "schema": IDENTITY_SCHEMA,
        "head": _normalise_token(head, field="head"),
        "base": _normalise_token(base, field="base"),
        "changed_file_digest": _digest(changed),
        "command_digest": _digest(command_value),
        "test_definition_digest": _digest(definition_value),
        "fixture_digest": _digest(fixture_value),
        "toolchain": toolchain_value,
        "scope": scope_value,
        "tier": tier_value,
        "issued_at": issued_text,
        "expires_at": expires_text,
        "ttl_seconds": actual_ttl,
    }
    identity["identity_digest"] = _digest(identity)
    return identity


def _validated_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReuseContractError("identity is missing")
    missing = sorted(_REQUIRED_IDENTITY_FIELDS - set(value))
    if missing:
        raise ReuseContractError(f"identity is missing fields: {', '.join(missing)}")
    identity = _json_copy(value, field="identity")
    if identity.get("schema") != IDENTITY_SCHEMA:
        raise ReuseContractError("identity schema is not the reuse identity schema")
    _normalise_token(identity.get("head"), field="head")
    _normalise_token(identity.get("base"), field="base")
    _normalise_tier(identity.get("tier"))
    _normalise_required_value(identity.get("toolchain"), field="toolchain")
    _normalise_required_value(identity.get("scope"), field="scope")
    for field in (
        "changed_file_digest",
        "command_digest",
        "test_definition_digest",
        "fixture_digest",
    ):
        digest = identity.get(field)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
        ):
            raise ReuseContractError(f"{field} must be a SHA-256 digest")
    issued = _parse_timestamp(identity["issued_at"], field="issued_at")
    expires = _parse_timestamp(identity["expires_at"], field="expires_at")
    actual_ttl = (expires - issued).total_seconds()
    if actual_ttl <= 0:
        raise ReuseContractError("expires_at must be later than issued_at")
    try:
        recorded_ttl = float(identity["ttl_seconds"])
    except (TypeError, ValueError) as exc:
        raise ReuseContractError("ttl_seconds must be numeric") from exc
    if recorded_ttl <= 0 or abs(recorded_ttl - actual_ttl) > 1e-6:
        raise ReuseContractError("ttl_seconds does not match issued_at/expires_at")
    recorded_digest = identity.get("identity_digest")
    digest_payload = {key: item for key, item in identity.items() if key != "identity_digest"}
    if recorded_digest != _digest(digest_payload):
        raise ReuseContractError("identity_digest does not match identity inputs")
    return identity


def build_reuse_verdict(
    identity: Mapping[str, Any],
    *,
    verdict: str = "pass",
) -> dict[str, Any]:
    """Wrap an identity as a prior verdict without connecting any runner."""
    validated = _validated_identity(identity)
    normalised_verdict = str(verdict).strip().lower()
    if normalised_verdict not in _PASS_VERDICTS | _WARN_VERDICTS | {"block", "blocked"}:
        raise ReuseContractError("verdict must be pass, warn, or block")
    reusable = normalised_verdict in _PASS_VERDICTS
    return {
        "schema": VERDICT_SCHEMA,
        "identity": validated,
        "verdict": normalised_verdict,
        "reuse": reusable,
        "reason_code": "verdict-pass" if reusable else "verdict-not-reusable",
        "contract_ready": True,
        "runner_connected": False,
        "wiring_follow_up": deepcopy(WIRING_FOLLOW_UP),
    }


def _result(
    identity: Mapping[str, Any] | None,
    *,
    reuse: bool,
    reason_code: str,
    reason: str,
    contract_ready: bool,
    previous_verdict: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "identity": deepcopy(identity) if identity is not None else None,
        "reuse": reuse,
        "reason_code": reason_code,
        "reason": reason,
        "contract_ready": contract_ready,
        "runner_connected": False,
        "wiring_follow_up": deepcopy(WIRING_FOLLOW_UP),
    }
    if previous_verdict is not None:
        result["previous_verdict"] = previous_verdict
    return result


def _extract_previous(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    nested = value.get("identity")
    candidate = nested if nested is not None else value
    verdict = value.get("verdict")
    if verdict is None:
        verdict = value.get("status")
    if verdict is None:
        verdict = value.get("gate_verdict")
    return candidate, str(verdict).strip().lower() if verdict is not None else None


def _now_datetime(value: Timestamp | None) -> datetime:
    return _parse_timestamp(value, field="now") if value is not None else datetime.now(_UTC)


def evaluate_reuse(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    *,
    now: Timestamp | None = None,
) -> dict[str, Any]:
    """Return a fail-closed, machine-readable reuse decision."""
    try:
        current_identity = _validated_identity(current)
    except ReuseContractError as exc:
        return _result(
            None,
            reuse=False,
            reason_code="invalid-current",
            reason=str(exc),
            contract_ready=False,
        )

    previous_identity, previous_verdict = _extract_previous(previous)
    if previous_identity is None or not isinstance(previous_identity, Mapping) or not previous_identity:
        return _result(
            current_identity,
            reuse=False,
            reason_code="missing",
            reason="no prior reuse identity is available",
            contract_ready=True,
        )
    if previous_verdict in _WARN_VERDICTS:
        return _result(
            current_identity,
            reuse=False,
            reason_code="warn-not-reusable",
            reason="a warning verdict is never safe to reuse",
            contract_ready=True,
            previous_verdict=previous_verdict,
        )
    if previous_verdict is not None and previous_verdict not in _PASS_VERDICTS:
        return _result(
            current_identity,
            reuse=False,
            reason_code="verdict-not-reusable",
            reason="the prior verdict is not a passing verdict",
            contract_ready=True,
            previous_verdict=previous_verdict,
        )

    try:
        prior_identity = _validated_identity(previous_identity)
    except ReuseContractError as exc:
        message = str(exc)
        reason_code = "missing" if "missing" in message else "invalid-identity"
        return _result(
            current_identity,
            reuse=False,
            reason_code=reason_code,
            reason=message,
            contract_ready=True,
            previous_verdict=previous_verdict,
        )

    moment = _now_datetime(now)
    for identity in (prior_identity, current_identity):
        issued = _parse_timestamp(identity["issued_at"], field="issued_at")
        expires = _parse_timestamp(identity["expires_at"], field="expires_at")
        if moment >= expires:
            return _result(
                current_identity,
                reuse=False,
                reason_code="stale",
                reason="the reuse identity has expired",
                contract_ready=True,
                previous_verdict=previous_verdict,
            )
        if moment < issued:
            return _result(
                current_identity,
                reuse=False,
                reason_code="not-yet-valid",
                reason="the reuse identity has not reached its issued_at time",
                contract_ready=True,
                previous_verdict=previous_verdict,
            )

    reason_by_field = {
        "head": "head-drift",
        "base": "base-drift",
        "changed_file_digest": "changed-file-drift",
        "command_digest": "command-drift",
        "test_definition_digest": "test-definition-drift",
        "fixture_digest": "fixture-drift",
        "toolchain": "toolchain-drift",
        "scope": "scope-drift",
        "tier": "tier-drift",
        "ttl_seconds": "ttl-drift",
    }
    for field in _COMPARABLE_FIELDS:
        if prior_identity[field] != current_identity[field]:
            return _result(
                current_identity,
                reuse=False,
                reason_code=reason_by_field[field],
                reason=f"reuse identity field drifted: {field}",
                contract_ready=True,
                previous_verdict=previous_verdict,
            )

    return _result(
        current_identity,
        reuse=True,
        reason_code="identity-match",
        reason="all reusable identity fields match and the prior verdict is fresh",
        contract_ready=True,
        previous_verdict=previous_verdict,
    )

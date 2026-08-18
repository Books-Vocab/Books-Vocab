#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Build and inspect an offline Gate-cost timing ledger.

The ledger is a data contract, not a runner.  A caller must provide every
observed wave and every measurement identity; this module never reads Git,
executes a command, or invents missing historical samples.  The central Gate
runner can consume this contract in a later Manager-owned change.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

TIMING_LEDGER_SCHEMA = "kg.gate.timing-ledger.v1"
VALIDATION_SCHEMA = "kg.gate.timing-ledger.validation.v1"
SUMMARY_SCHEMA = "kg.gate.timing-ledger.summary.v1"
CONTRACT_VERSION = 1
MIN_WAVES = 10
MAX_WAVES = 20

MEASUREMENT_KINDS = (
    "packet",
    "full_gate",
    "precise_gate",
    "reuse_verdict",
)
MEASUREMENT_FIELDS = (
    "duration_s",
    "rc",
    "verdict",
    "fingerprint",
    "head_sha",
    "base_sha",
    "lease_wait_s",
)

DEFAULT_WIRING_FOLLOW_UP: dict[str, Any] = {
    "owner": "manager",
    "next_step": (
        "connect timing ledger consumption through the existing central runner "
        "after this ticket lands"
    ),
    "files": ["central-runner"],
}

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "duration_s": ("duration_s", "duration"),
    "rc": ("rc", "return_code", "exit_code"),
    "verdict": ("verdict", "status"),
    "fingerprint": ("fingerprint", "fingerprint_digest"),
    "head_sha": ("head_sha", "head", "HEAD"),
    "base_sha": ("base_sha", "base", "base_ref"),
    "lease_wait_s": (
        "lease_wait_s",
        "lease_wait",
        "lease_wait_seconds",
    ),
}
_NOT_RUN_VERDICTS = frozenset({"not-run", "not_applicable", "not-applicable"})


class LedgerContractError(ValueError):
    """Raised when timing-ledger input cannot be represented honestly."""


def _error(path: str, message: str) -> str:
    return f"{path}: {message}"


def _non_empty_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerContractError(f"{field} must be a non-empty string")
    return value.strip()


def _finite_non_negative(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise LedgerContractError(f"{field} must be a finite non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LedgerContractError(
            f"{field} must be a finite non-negative number"
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise LedgerContractError(f"{field} must be a finite non-negative number")
    return number


def _measurement_value(measurement: Mapping[str, Any], field: str) -> Any:
    for key in _FIELD_ALIASES[field]:
        if key in measurement:
            return measurement[key]
    raise LedgerContractError(f"measurement is missing {field}")


def _fingerprint(value: Any, *, field: str) -> Any:
    if value is None:
        raise LedgerContractError(f"{field} must be supplied")
    if isinstance(value, str):
        if not value.strip():
            raise LedgerContractError(f"{field} must be a non-empty string")
        return value.strip()
    if isinstance(value, Mapping):
        if not value:
            raise LedgerContractError(f"{field} must not be empty")
        return copy.deepcopy(dict(value))
    raise LedgerContractError(f"{field} must be a string or object")


def _normalise_measurement(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LedgerContractError(f"{path} must be an object")

    measurement = copy.deepcopy(dict(value))
    duration = _finite_non_negative(
        _measurement_value(value, "duration_s"),
        field=f"{path}.duration_s",
    )
    raw_rc = _measurement_value(value, "rc")
    raw_verdict = _non_empty_text(
        _measurement_value(value, "verdict"), field=f"{path}.verdict"
    )
    verdict_key = raw_verdict.casefold()
    if raw_rc is None:
        if verdict_key not in _NOT_RUN_VERDICTS:
            raise LedgerContractError(
                f"{path}.rc may be null only for a not-run measurement"
            )
        rc: int | None = None
    elif isinstance(raw_rc, bool) or not isinstance(raw_rc, int):
        raise LedgerContractError(f"{path}.rc must be an integer or null")
    else:
        rc = raw_rc

    fingerprint = _fingerprint(
        _measurement_value(value, "fingerprint"), field=f"{path}.fingerprint"
    )
    head_sha = _non_empty_text(
        _measurement_value(value, "head_sha"), field=f"{path}.head_sha"
    )
    base_sha = _non_empty_text(
        _measurement_value(value, "base_sha"), field=f"{path}.base_sha"
    )
    lease_wait = _finite_non_negative(
        _measurement_value(value, "lease_wait_s"),
        field=f"{path}.lease_wait_s",
    )

    # Canonical keys are added while unknown metadata remains intact.  This
    # makes the contract forward-compatible without allowing aliases to hide
    # a missing required value.
    measurement.update(
        {
            "duration_s": duration,
            "rc": rc,
            "verdict": raw_verdict,
            "fingerprint": fingerprint,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "lease_wait_s": lease_wait,
        }
    )
    return measurement


def _wave_id(value: Mapping[str, Any], *, path: str) -> str:
    candidate = value.get("wave_id", value.get("id"))
    return _non_empty_text(candidate, field=f"{path}.wave_id")


def _normalise_wave(value: Any, *, index: int) -> dict[str, Any]:
    path = f"waves[{index}]"
    if not isinstance(value, Mapping):
        raise LedgerContractError(f"{path} must be an object")
    wave = copy.deepcopy(dict(value))
    wave_id = _wave_id(value, path=path)
    wave["wave_id"] = wave_id
    nested = value.get("measurements")
    for kind in MEASUREMENT_KINDS:
        source = value.get(kind)
        if source is None and isinstance(nested, Mapping):
            source = nested.get(kind)
        if source is None:
            raise LedgerContractError(f"{path} is missing {kind}")
        wave[kind] = _normalise_measurement(source, path=f"{path}.{kind}")
    return wave


def _waves_from_payload(payload: Mapping[str, Any]) -> list[Any]:
    value = payload.get("waves")
    if value is None:
        value = payload.get("records")
    if value is None:
        raise LedgerContractError("ledger is missing waves")
    if not isinstance(value, list):
        raise LedgerContractError("waves must be an array")
    return value


def _normalise_waves(waves: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(waves, (str, bytes, Mapping)):
        raise LedgerContractError("waves must be an iterable of objects")
    try:
        values = list(waves)
    except TypeError as exc:
        raise LedgerContractError("waves must be an iterable of objects") from exc
    normalised = [
        _normalise_wave(value, index=index) for index, value in enumerate(values)
    ]
    identifiers = [wave["wave_id"] for wave in normalised]
    duplicates = sorted(
        wave_id for wave_id, count in Counter(identifiers).items() if count > 1
    )
    if duplicates:
        raise LedgerContractError(
            f"wave_id values must be unique: {', '.join(duplicates)}"
        )
    return normalised


def _wave_window_error(count: int) -> str:
    return f"wave_count must be between {MIN_WAVES} and {MAX_WAVES}; got {count}"


def _normalise_follow_up(value: Mapping[str, Any] | None) -> dict[str, Any]:
    source = DEFAULT_WIRING_FOLLOW_UP if value is None else value
    if not isinstance(source, Mapping):
        raise LedgerContractError("wiring_follow_up must be an object")
    owner = _non_empty_text(source.get("owner"), field="wiring_follow_up.owner")
    if owner.casefold() != "manager":
        raise LedgerContractError("wiring_follow_up.owner must be manager")
    next_step = _non_empty_text(
        source.get("next_step"), field="wiring_follow_up.next_step"
    )
    files = source.get("files")
    if (
        not isinstance(files, list)
        or not files
        or any(not isinstance(item, str) or not item.strip() for item in files)
    ):
        raise LedgerContractError(
            "wiring_follow_up.files must be a non-empty array of strings"
        )
    return {
        "owner": owner,
        "next_step": next_step,
        "files": [item.strip() for item in files],
    }


def _runner_state(
    *,
    runner_connected: bool,
    runner_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(runner_connected, bool):
        raise LedgerContractError("runner_connected must be boolean")
    if not runner_connected:
        if runner_evidence is not None:
            raise LedgerContractError(
                "runner evidence cannot be attached while runner_connected is false"
            )
        return {
            "connected": False,
            "consumed": False,
            "source": None,
            "evidence": None,
        }
    if not isinstance(runner_evidence, Mapping):
        raise LedgerContractError(
            "runner evidence is required when runner_connected is true"
        )
    source = _non_empty_text(
        runner_evidence.get("source"), field="runner evidence.source"
    )
    evidence = runner_evidence.get("evidence")
    if evidence is None:
        evidence = runner_evidence.get("receipt", runner_evidence.get("record"))
    if not isinstance(evidence, (str, Mapping)) or (
        isinstance(evidence, str) and not evidence.strip()
    ):
        raise LedgerContractError(
            "runner evidence must include a non-empty evidence, receipt, or record"
        )
    return {
        "connected": True,
        "consumed": True,
        "source": source,
        "evidence": copy.deepcopy(evidence),
    }


def _contract_descriptor() -> dict[str, Any]:
    return {
        "schema": TIMING_LEDGER_SCHEMA,
        "version": CONTRACT_VERSION,
        "wave_min": MIN_WAVES,
        "wave_max": MAX_WAVES,
        "measurement_kinds": list(MEASUREMENT_KINDS),
        "measurement_fields": list(MEASUREMENT_FIELDS),
        "historical_data": False,
    }


def new_contract() -> dict[str, Any]:
    """Return the contract shape without claiming any historical samples."""

    state = _runner_state(runner_connected=False, runner_evidence=None)
    return {
        "schema": TIMING_LEDGER_SCHEMA,
        "version": CONTRACT_VERSION,
        "contract": _contract_descriptor(),
        "contract_ready": True,
        "runner_connected": False,
        "runner_consumed": False,
        "runner_state": state,
        "wiring_follow_up": copy.deepcopy(DEFAULT_WIRING_FOLLOW_UP),
        "historical_data": False,
        "ticket": None,
        "packet": None,
        "wave_count": 0,
        "waves": [],
    }


def build_ledger(
    *,
    waves: Iterable[Mapping[str, Any]],
    ticket: str | None = None,
    packet: str | None = None,
    runner_connected: bool = False,
    runner_evidence: Mapping[str, Any] | None = None,
    wiring_follow_up: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical ledger from caller-supplied wave evidence.

    A complete timing ledger contains 10–20 waves.  The separate
    :func:`new_contract` function is the only API that returns an empty shape;
    it explicitly marks ``historical_data`` false.
    """

    normalised = _normalise_waves(waves)
    if not MIN_WAVES <= len(normalised) <= MAX_WAVES:
        raise LedgerContractError(_wave_window_error(len(normalised)))
    state = _runner_state(
        runner_connected=runner_connected,
        runner_evidence=runner_evidence,
    )
    result: dict[str, Any] = {
        "schema": TIMING_LEDGER_SCHEMA,
        "version": CONTRACT_VERSION,
        "contract": _contract_descriptor(),
        "contract_ready": True,
        "runner_connected": state["connected"],
        "runner_consumed": state["consumed"],
        "runner_state": state,
        "wiring_follow_up": _normalise_follow_up(wiring_follow_up),
        "historical_data": True,
        "ticket": None if ticket is None else _non_empty_text(ticket, field="ticket"),
        "packet": None if packet is None else _non_empty_text(packet, field="packet"),
        "wave_count": len(normalised),
        "waves": normalised,
    }
    validation = validate_ledger(result)
    if not validation["valid"]:
        raise LedgerContractError("; ".join(validation["errors"]))
    return result


def _validate_measurement(
    value: Any, *, path: str, expected_head: str | None, expected_base: str | None
) -> tuple[list[str], str | None, str | None]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return [_error(path, "must be an object")], expected_head, expected_base

    canonical: dict[str, Any] = {}
    for field in MEASUREMENT_FIELDS:
        try:
            canonical[field] = _measurement_value(value, field)
        except LedgerContractError as exc:
            errors.append(_error(path, str(exc)))

    if errors:
        return errors, expected_head, expected_base

    try:
        _finite_non_negative(canonical["duration_s"], field=f"{path}.duration_s")
    except LedgerContractError as exc:
        errors.append(str(exc))

    verdict = canonical["verdict"]
    if not isinstance(verdict, str) or not verdict.strip():
        errors.append(_error(path, "verdict must be a non-empty string"))
    verdict_key = verdict.casefold() if isinstance(verdict, str) else ""

    rc = canonical["rc"]
    if rc is None:
        if verdict_key not in _NOT_RUN_VERDICTS:
            errors.append(_error(path, "rc may be null only for a not-run measurement"))
    elif isinstance(rc, bool) or not isinstance(rc, int):
        errors.append(_error(path, "rc must be an integer or null"))

    fingerprint = canonical["fingerprint"]
    if (
        fingerprint is None
        or (isinstance(fingerprint, str) and not fingerprint.strip())
        or (isinstance(fingerprint, Mapping) and not fingerprint)
    ):
        errors.append(_error(path, "fingerprint must be non-empty"))
    elif not isinstance(fingerprint, (str, Mapping)):
        errors.append(_error(path, "fingerprint must be a string or object"))

    for field in ("head_sha", "base_sha"):
        if not isinstance(canonical[field], str) or not canonical[field].strip():
            errors.append(_error(path, f"{field} must be a non-empty string"))
    try:
        _finite_non_negative(canonical["lease_wait_s"], field=f"{path}.lease_wait_s")
    except LedgerContractError as exc:
        errors.append(str(exc))

    head = canonical["head_sha"] if isinstance(canonical["head_sha"], str) else None
    base = canonical["base_sha"] if isinstance(canonical["base_sha"], str) else None
    if head is not None and expected_head is not None and head != expected_head:
        errors.append(
            _error(
                path, f"head_sha differs from sibling measurements ({expected_head})"
            )
        )
    if base is not None and expected_base is not None and base != expected_base:
        errors.append(
            _error(
                path, f"base_sha differs from sibling measurements ({expected_base})"
            )
        )
    if expected_head is None and head is not None:
        expected_head = head
    if expected_base is None and base is not None:
        expected_base = base
    return errors, expected_head, expected_base


def validate_ledger(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a ledger and return a machine-readable verdict report."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return {
            "schema": VALIDATION_SCHEMA,
            "version": CONTRACT_VERSION,
            "valid": False,
            "errors": ["ledger must be an object"],
            "contract_ready": False,
            "runner_connected": False,
            "runner_consumed": False,
            "historical_data": False,
            "wave_count": 0,
        }

    if payload.get("schema") != TIMING_LEDGER_SCHEMA:
        errors.append(_error("schema", f"must be {TIMING_LEDGER_SCHEMA}"))
    if payload.get("version") != CONTRACT_VERSION:
        errors.append(_error("version", f"must be {CONTRACT_VERSION}"))
    if payload.get("contract_ready") is not True:
        errors.append(_error("contract_ready", "must be true"))

    runner_connected = payload.get("runner_connected")
    runner_consumed = payload.get("runner_consumed")
    if not isinstance(runner_connected, bool):
        errors.append(_error("runner_connected", "must be boolean"))
        runner_connected = False
    if not isinstance(runner_consumed, bool):
        errors.append(_error("runner_consumed", "must be boolean"))
        runner_consumed = False
    if not runner_connected and runner_consumed:
        errors.append(
            _error("runner_consumed", "cannot be true while runner_connected is false")
        )

    follow_up = payload.get("wiring_follow_up")
    if not runner_connected:
        try:
            if follow_up is None:
                raise LedgerContractError(
                    "wiring_follow_up is required while runner_connected is false"
                )
            _normalise_follow_up(follow_up)
        except LedgerContractError as exc:
            errors.append(str(exc))
    elif follow_up is not None:
        try:
            _normalise_follow_up(follow_up)
        except LedgerContractError as exc:
            errors.append(str(exc))

    state = payload.get("runner_state")
    if state is None and not runner_connected:
        # The booleans are the stable public boundary.  Older or hand-authored
        # contract inputs may omit this diagnostic projection; absence cannot
        # claim a connection because runner_connected is still false.
        state = {
            "connected": False,
            "consumed": False,
            "source": None,
            "evidence": None,
        }
    elif not isinstance(state, Mapping):
        errors.append(_error("runner_state", "must be an object"))
    else:
        if state.get("connected") is not runner_connected:
            errors.append(
                _error("runner_state.connected", "must match runner_connected")
            )
        if state.get("consumed") is not runner_consumed:
            errors.append(_error("runner_state.consumed", "must match runner_consumed"))
        if runner_connected:
            evidence = state.get("evidence")
            if not isinstance(state.get("source"), str) or not state["source"].strip():
                errors.append(
                    _error("runner_state.source", "runner evidence source is required")
                )
            if (
                evidence is None
                or (isinstance(evidence, str) and not evidence.strip())
                or (isinstance(evidence, Mapping) and not evidence)
            ):
                errors.append(
                    _error("runner_state.evidence", "runner evidence is required")
                )
        elif state.get("evidence") is not None:
            errors.append(
                _error(
                    "runner_state.evidence", "must be null when runner is disconnected"
                )
            )

    try:
        raw_waves = _waves_from_payload(payload)
    except LedgerContractError as exc:
        errors.append(str(exc))
        raw_waves = []

    if payload.get("wave_count") not in (None, len(raw_waves)):
        errors.append(_error("wave_count", f"must equal {len(raw_waves)}"))
    wave_count = len(raw_waves)
    historical_data = payload.get("historical_data")
    if historical_data is None:
        historical_data = bool(raw_waves)
    elif not isinstance(historical_data, bool):
        errors.append(_error("historical_data", "must be boolean"))
        historical_data = bool(raw_waves)
    if historical_data and wave_count == 0:
        errors.append(
            _error("waves", "historical_data is true but no waves were supplied")
        )
    if wave_count and not MIN_WAVES <= wave_count <= MAX_WAVES:
        errors.append(_wave_window_error(wave_count))

    seen: set[str] = set()
    expected_head: str | None = None
    expected_base: str | None = None
    for index, raw_wave in enumerate(raw_waves):
        path = f"waves[{index}]"
        if not isinstance(raw_wave, Mapping):
            errors.append(_error(path, "must be an object"))
            continue
        try:
            wave_id = _wave_id(raw_wave, path=path)
        except LedgerContractError as exc:
            errors.append(str(exc))
            wave_id = None
        if wave_id is not None:
            if wave_id in seen:
                errors.append(_error(path, f"duplicate wave_id {wave_id!r}"))
            seen.add(wave_id)
        for kind in MEASUREMENT_KINDS:
            measurement = raw_wave.get(kind)
            nested = raw_wave.get("measurements")
            if measurement is None and isinstance(nested, Mapping):
                measurement = nested.get(kind)
            if measurement is None:
                errors.append(_error(path, f"is missing {kind}"))
                continue
            measurement_errors, expected_head, expected_base = _validate_measurement(
                measurement,
                path=f"{path}.{kind}",
                expected_head=expected_head,
                expected_base=expected_base,
            )
            errors.extend(measurement_errors)

    descriptor = payload.get("contract")
    if descriptor is not None:
        if not isinstance(descriptor, Mapping):
            errors.append(_error("contract", "must be an object"))
        else:
            if descriptor.get("schema") != TIMING_LEDGER_SCHEMA:
                errors.append(
                    _error("contract.schema", f"must be {TIMING_LEDGER_SCHEMA}")
                )
            if descriptor.get("measurement_kinds") != list(MEASUREMENT_KINDS):
                errors.append(
                    _error("contract.measurement_kinds", "does not match the contract")
                )
            if descriptor.get("measurement_fields") != list(MEASUREMENT_FIELDS):
                errors.append(
                    _error("contract.measurement_fields", "does not match the contract")
                )

    unique_errors = list(dict.fromkeys(errors))
    return {
        "schema": VALIDATION_SCHEMA,
        "version": CONTRACT_VERSION,
        "source_schema": payload.get("schema"),
        "valid": not unique_errors,
        "errors": unique_errors,
        "contract_ready": payload.get("contract_ready") is True,
        "runner_connected": runner_connected,
        "runner_consumed": runner_consumed,
        "historical_data": historical_data,
        "wave_count": wave_count,
    }


def _require_valid(payload: Mapping[str, Any]) -> None:
    validation = validate_ledger(payload)
    if not validation["valid"]:
        raise LedgerContractError("; ".join(validation["errors"]))


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"total": 0.0, "mean": None, "min": None, "max": None}
    total = sum(values)
    return {
        "total": total,
        "mean": total / len(values),
        "min": min(values),
        "max": max(values),
    }


def summarize_ledger(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize only the measurements present in a valid ledger."""

    _require_valid(payload)
    raw_waves = _waves_from_payload(payload)
    waves = [_normalise_wave(wave, index=index) for index, wave in enumerate(raw_waves)]
    measurements: dict[str, dict[str, Any]] = {}
    for kind in MEASUREMENT_KINDS:
        rows = [wave[kind] for wave in waves]
        durations = [float(row["duration_s"]) for row in rows]
        lease_waits = [float(row["lease_wait_s"]) for row in rows]
        rc_counts = Counter(str(row["rc"]) for row in rows if row["rc"] is not None)
        verdict_counts = Counter(str(row["verdict"]).casefold() for row in rows)
        measurements[kind] = {
            "count": len(rows),
            "duration_s": _stats(durations),
            "lease_wait_s": _stats(lease_waits),
            "rc_counts": dict(sorted(rc_counts.items())),
            "verdict_counts": dict(sorted(verdict_counts.items())),
            "fingerprint_count": len(
                {json.dumps(row["fingerprint"], sort_keys=True) for row in rows}
            ),
            "head_shas": sorted({row["head_sha"] for row in rows}),
            "base_shas": sorted({row["base_sha"] for row in rows}),
        }

    full_total = measurements["full_gate"]["duration_s"]["total"]
    precise_total = measurements["precise_gate"]["duration_s"]["total"]
    reuse_rows = [wave["reuse_verdict"] for wave in waves]
    reused_count = sum(
        str(row["verdict"]).casefold() in {"reused", "reuse", "pass-reused"}
        for row in reuse_rows
    )
    return {
        "schema": SUMMARY_SCHEMA,
        "version": CONTRACT_VERSION,
        "source_schema": TIMING_LEDGER_SCHEMA,
        "contract_ready": payload["contract_ready"],
        "runner_connected": payload["runner_connected"],
        "runner_consumed": payload["runner_consumed"],
        "historical_data": bool(payload.get("historical_data", bool(waves))),
        "ticket": payload.get("ticket"),
        "packet": payload.get("packet"),
        "wave_count": len(waves),
        "measurements": measurements,
        "totals": {
            kind: measurements[kind]["duration_s"]["total"]
            for kind in MEASUREMENT_KINDS
        },
        "averages": {
            kind: measurements[kind]["duration_s"]["mean"] for kind in MEASUREMENT_KINDS
        },
        "comparisons": {
            "full_gate_minus_precise_gate_s": full_total - precise_total,
            "reuse_verdict_reused_count": reused_count,
        },
    }


# Names used by callers that refer to the contract rather than its ledger
# implementation.  They intentionally point to the same pure functions.
build_timing_ledger = build_ledger
build_contract = build_ledger
validate = validate_ledger
summarize = summarize_ledger


def _load_json(path: str | None) -> Any:
    source = (
        sys.stdin.read()
        if path in (None, "-")
        else Path(path).read_text(encoding="utf-8")
    )
    try:
        return json.loads(source)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise LedgerContractError(f"invalid JSON input: {exc}") from exc
    except OSError as exc:
        raise LedgerContractError(f"cannot read JSON input {path!r}: {exc}") from exc


def _input_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "input_pos",
        nargs="?",
        help="ledger JSON path, or - for stdin (default: stdin)",
    )
    parser.add_argument(
        "--input",
        "--ledger",
        "--file",
        dest="input_path",
        help="ledger JSON path, or - for stdin",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="emit the contract shape without historical data")

    validate_parser = sub.add_parser(
        "validate", aliases=["check"], help="validate a ledger"
    )
    _input_argument(validate_parser)

    summary_parser = sub.add_parser(
        "summarize", aliases=["summary"], help="summarize observed ledger measurements"
    )
    _input_argument(summary_parser)

    build_parser = sub.add_parser(
        "build", aliases=["create"], help="canonicalize supplied wave evidence"
    )
    _input_argument(build_parser)
    build_parser.add_argument("--ticket")
    build_parser.add_argument("--packet")
    build_parser.add_argument("--runner-connected", action="store_true")
    build_parser.add_argument("--runner-evidence-file")
    return parser


def _input_path(args: argparse.Namespace) -> str | None:
    return args.input_path or args.input_pos


def _build_from_input(args: argparse.Namespace) -> dict[str, Any]:
    source = _load_json(_input_path(args))
    if isinstance(source, list):
        source_waves = source
        metadata: Mapping[str, Any] = {}
    elif isinstance(source, Mapping):
        source_waves = source.get("waves", source.get("records"))
        metadata = source
    else:
        raise LedgerContractError("build input must be an object or wave array")
    if source_waves is None:
        raise LedgerContractError("build input is missing waves")
    runner_evidence: Mapping[str, Any] | None = None
    if args.runner_evidence_file:
        evidence = _load_json(args.runner_evidence_file)
        if not isinstance(evidence, Mapping):
            raise LedgerContractError("runner evidence JSON must be an object")
        runner_evidence = evidence
    return build_ledger(
        waves=source_waves,
        ticket=args.ticket or metadata.get("ticket"),
        packet=args.packet or metadata.get("packet"),
        runner_connected=args.runner_connected,
        runner_evidence=runner_evidence,
        wiring_follow_up=(
            metadata.get("wiring_follow_up")
            if isinstance(metadata.get("wiring_follow_up"), Mapping)
            else None
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "schema":
            result = new_contract()
        elif args.command in {"validate", "check"}:
            result = validate_ledger(_load_json(_input_path(args)))
        elif args.command in {"summarize", "summary"}:
            result = summarize_ledger(_load_json(_input_path(args)))
        else:
            result = _build_from_input(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        if args.command in {"validate", "check"} and not result["valid"]:
            return 1
        return 0
    except (LedgerContractError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"schema": TIMING_LEDGER_SCHEMA, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 64


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_WIRING_FOLLOW_UP",
    "MAX_WAVES",
    "MEASUREMENT_FIELDS",
    "MEASUREMENT_KINDS",
    "MIN_WAVES",
    "SUMMARY_SCHEMA",
    "TIMING_LEDGER_SCHEMA",
    "VALIDATION_SCHEMA",
    "LedgerContractError",
    "build_contract",
    "build_ledger",
    "build_timing_ledger",
    "main",
    "new_contract",
    "summarize",
    "summarize_ledger",
    "validate",
    "validate_ledger",
]

#!/usr/bin/env -S uv run --python 3.13 python
"""Run a bounded, read-only preflight over supplied PR review evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

INPUT_SCHEMA = "kg.review.evidence.v1"
OUTPUT_SCHEMA = "kg.review.preflight.v1"
RECEIPT_SCHEMA = "kg.review.receipt.v1"

EXIT_CODES = {
    "PASS": 0,
    "BLOCK": 1,
    "review_service_timeout": 2,
    "source_failure": 3,
}


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return value
    return None


def _opaque_text(value: object) -> bool:
    """Validate presence without interpreting or normalizing opaque identifiers."""

    return type(value) is str and bool(value)


def _slice_fields(
    value: Mapping[str, Any] | None, fields: Sequence[str]
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {field: value[field] for field in fields if field in value}


def _identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = _mapping(payload.get("target"))
    review = _mapping(payload.get("review"))
    identity: dict[str, Any] = {}
    if target is not None:
        for field in ("pr", "head"):
            if field in target:
                identity[field] = target[field]
    if review is not None:
        for field in ("reviewer", "deadline"):
            if field in review:
                identity[field] = review[field]
    return identity


def _observed(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = _mapping(payload.get("target"))
    required = _mapping(payload.get("required_snapshot"))
    review = _mapping(payload.get("review"))
    receipt = _mapping(review.get("receipt")) if review is not None else None
    receipt_observed = _slice_fields(
        receipt,
        (
            "schema",
            "status",
            "pr",
            "head",
            "reviewer",
            "deadline",
            "substantive",
        ),
    )
    observed: dict[str, Any] = {
        "target": _slice_fields(target, ("pr", "head")),
        "required_snapshot": _slice_fields(required, ("status", "pr", "head")),
        "review": _slice_fields(review, ("reviewer", "deadline")),
        "receipt": receipt_observed,
    }
    if receipt is not None and receipt_observed is not None and "evidence" in receipt:
        evidence = receipt["evidence"]
        receipt_observed["evidence_item_count"] = (
            len(evidence) if isinstance(evidence, list) else None
        )
    return observed


def _result(
    verdict: str,
    reason_code: str,
    *,
    identity: dict[str, Any],
    observed: dict[str, Any],
    blockers: Sequence[str] = (),
    details: Sequence[str] = (),
    source_status: object = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": OUTPUT_SCHEMA,
        "mode": "read-only",
        "verdict": verdict,
        "reason_code": reason_code,
        "exit_code": EXIT_CODES[verdict],
        "blockers": list(blockers),
        "details": list(details),
        "identity": identity,
        "observed": observed,
        "authority": {
            "github_review": "not_replaced",
            "required_checks": "not_replaced",
            "cm_merge": "not_replaced",
            "mutation_performed": False,
        },
    }
    if source_status is not None:
        result["source_status"] = source_status
    return result


def _source_result(
    verdict: str,
    reason_code: str,
    *,
    identity: dict[str, Any],
    observed: dict[str, Any],
    detail: str,
    source_status: object = None,
) -> dict[str, Any]:
    return _result(
        verdict,
        reason_code,
        identity=identity,
        observed=observed,
        blockers=[reason_code],
        details=[detail],
        source_status=source_status,
    )


def _target_error(payload: Mapping[str, Any]) -> str | None:
    target = _mapping(payload.get("target"))
    if target is None:
        return "target_missing"
    missing = [field for field in ("pr", "head") if not _opaque_text(target.get(field))]
    return f"target_incomplete:{','.join(missing)}" if missing else None


def _source_status(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    source = _mapping(payload.get("source"))
    if source is None:
        return None, "source_missing"
    status = source.get("status")
    if isinstance(status, str) and status in {"timeout", "review_service_timeout"}:
        return "review_service_timeout", None
    if isinstance(status, str) and status in {"failure", "source_failure"}:
        return "source_failure", None
    if status != "ok":
        return "source_failure", "source_status_unknown"
    return "ok", None


def _required_blockers(
    payload: Mapping[str, Any], target: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    required = _mapping(payload.get("required_snapshot"))
    if required is None:
        if "required_snapshot" not in payload:
            return ["required_snapshot_missing"], []
        return ["required_snapshot_incomplete"], ["required_snapshot must be an object"]

    missing = [field for field in ("status", "pr", "head") if field not in required]
    if missing:
        return ["required_snapshot_incomplete"], [
            f"required snapshot missing field(s): {', '.join(missing)}"
        ]

    if (
        required["status"] != "SUCCESS"
        or required["pr"] != target["pr"]
        or required["head"] != target["head"]
    ):
        return ["required_snapshot_stale"], [
            "required snapshot is not SUCCESS for the exact target PR/HEAD"
        ]
    return [], []


def _receipt_blockers(
    payload: Mapping[str, Any], target: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    review = _mapping(payload.get("review"))
    if review is None:
        if "review" not in payload:
            return ["receipt_missing"], []
        return ["receipt_incomplete"], ["review evidence must be an object"]

    blockers: list[str] = []
    details: list[str] = []
    for field in ("reviewer", "deadline"):
        if not _opaque_text(review.get(field)):
            blockers.append(f"{field}_missing")
            details.append(f"review evidence missing {field}")

    receipt = _mapping(review.get("receipt"))
    if receipt is None:
        if "receipt" not in review:
            blockers.append("receipt_missing")
        else:
            blockers.append("receipt_incomplete")
            details.append("review receipt must be an object")
        return blockers, details

    required_fields = (
        "schema",
        "status",
        "pr",
        "head",
        "reviewer",
        "deadline",
        "substantive",
        "evidence",
    )
    missing = [field for field in required_fields if field not in receipt]
    if missing:
        blockers.append("receipt_incomplete")
        details.append(f"review receipt missing field(s): {', '.join(missing)}")
        return blockers, details

    if receipt["schema"] != RECEIPT_SCHEMA:
        blockers.append("receipt_incomplete")
        details.append("review receipt schema is unsupported")
    if receipt["pr"] != target["pr"]:
        blockers.append("exact_pr_mismatch")
    if receipt["head"] != target["head"]:
        blockers.append("exact_head_mismatch")
    if (
        _opaque_text(review.get("reviewer"))
        and receipt["reviewer"] != review["reviewer"]
    ):
        blockers.append("reviewer_mismatch")
    if (
        _opaque_text(review.get("deadline"))
        and receipt["deadline"] != review["deadline"]
    ):
        blockers.append("deadline_mismatch")
    if receipt["status"] != "PASS":
        blockers.append("review_not_pass")
    if receipt["substantive"] is not True:
        blockers.append("receipt_not_substantive")

    evidence = receipt["evidence"]
    if not isinstance(evidence, list) or not evidence:
        blockers.append("receipt_incomplete")
        details.append("substantive review receipt must contain evidence")
    else:
        invalid_evidence = False
        for item in evidence:
            item_map = _mapping(item)
            if (
                item_map is None
                or not _opaque_text(item_map.get("kind"))
                or not _opaque_text(item_map.get("detail"))
            ):
                invalid_evidence = True
                break
        if not invalid_evidence:
            return blockers, details
        blockers.append("receipt_incomplete")
        details.append("each review evidence item needs non-empty kind and detail")
    return blockers, details


def evaluate(payload: object) -> dict[str, Any]:
    """Evaluate one supplied evidence envelope without network or persistence."""

    if not isinstance(payload, Mapping):
        return _source_result(
            "source_failure",
            "source_failure",
            identity={},
            observed={},
            detail="input evidence must be a JSON object",
        )

    payload_map = payload
    identity = _identity(payload_map)
    observed = _observed(payload_map)
    source_status, source_error = _source_status(payload_map)
    if source_error is not None:
        return _source_result(
            "source_failure",
            "source_failure",
            identity=identity,
            observed=observed,
            detail=source_error,
        )
    if source_status == "review_service_timeout":
        return _source_result(
            "review_service_timeout",
            "review_service_timeout",
            identity=identity,
            observed=observed,
            detail="review service did not return within its bounded attempt",
            source_status=source_status,
        )
    if source_status == "source_failure":
        return _source_result(
            "source_failure",
            "source_failure",
            identity=identity,
            observed=observed,
            detail="review evidence source reported failure",
            source_status=source_status,
        )

    if payload_map.get("schema") != INPUT_SCHEMA:
        return _source_result(
            "source_failure",
            "source_failure",
            identity=identity,
            observed=observed,
            detail="input_schema_unsupported",
            source_status=source_status,
        )

    target_error = _target_error(payload_map)
    if target_error is not None:
        return _source_result(
            "source_failure",
            "source_failure",
            identity=identity,
            observed=observed,
            detail=target_error,
            source_status=source_status,
        )
    target = _mapping(payload_map["target"])
    assert target is not None  # guarded by _target_error

    required_blockers, required_details = _required_blockers(payload_map, target)
    if required_blockers:
        return _result(
            "BLOCK",
            required_blockers[0],
            identity=identity,
            observed=observed,
            blockers=required_blockers,
            details=required_details,
            source_status=source_status,
        )

    receipt_blockers, receipt_details = _receipt_blockers(payload_map, target)
    if receipt_blockers:
        return _result(
            "BLOCK",
            receipt_blockers[0],
            identity=identity,
            observed=observed,
            blockers=receipt_blockers,
            details=receipt_details,
            source_status=source_status,
        )

    return _result(
        "PASS",
        "evidence_sufficient",
        identity=identity,
        observed=observed,
        source_status=source_status,
    )


def _read_input(path: Path | None) -> tuple[object | None, str | None]:
    try:
        raw = (
            sys.stdin.read()
            if path is None or str(path) == "-"
            else path.read_text(encoding="utf-8")
        )
    except OSError as error:
        return None, f"input_unreadable: {error}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as error:
        return None, f"input_invalid_json: {error.msg}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="JSON evidence envelope path; use '-' or omit to read stdin",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the machine-readable kg.review.preflight.v1 result (default)",
    )
    args = parser.parse_args(argv)

    payload, input_error = _read_input(args.input)
    if input_error is not None:
        result = _source_result(
            "source_failure",
            "source_failure",
            identity={},
            observed={},
            detail=input_error,
        )
    else:
        result = evaluate(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())

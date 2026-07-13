#!/usr/bin/env python3
"""Closed contract validator for catalog appearance evidence.

The iOS producer, catalog lifecycle, review selector, and App Review gate all
consume the same fail-closed shape.  Keep policy here so a producer/consumer
rename cannot silently create a blessable but unsubmittable artifact.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


APPEARANCE_SCHEMA = "kg.catalog.appearance.v1"
APPEARANCE_TOP_KEYS = {
    "schema",
    "verdict",
    "sourceCommit",
    "datasetID",
    "datasetSHA256",
    "fixedClock",
    "observedAt",
    "captures",
}
APPEARANCE_VERDICT_KEYS = {"status", "proofCount"}
APPEARANCE_CAPTURE_KEYS = {
    "id",
    "requestedAppearance",
    "actualAppearance",
    "pixelSHA256",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _issue(code: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {"code": code, "expected": expected, "actual": actual}


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_appearance_proof(
    proof: Any,
    *,
    source_commit: str | None = None,
    dataset_id: str | None = None,
    dataset_sha256: str | None = None,
    fixed_clock: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not isinstance(proof, dict):
        return {
            "status": "block",
            "issues": [_issue("appearance.shape", "JSON object", type(proof).__name__)],
            "proofCount": 0,
        }

    if set(proof) != APPEARANCE_TOP_KEYS:
        issues.append(_issue("appearance.shape", sorted(APPEARANCE_TOP_KEYS), sorted(proof)))
    if proof.get("schema") != APPEARANCE_SCHEMA:
        issues.append(_issue("appearance.schema", APPEARANCE_SCHEMA, proof.get("schema")))

    verdict = proof.get("verdict")
    captures = proof.get("captures") if isinstance(proof.get("captures"), list) else []
    if not isinstance(verdict, dict) or set(verdict) != APPEARANCE_VERDICT_KEYS:
        issues.append(
            _issue(
                "appearance.verdict.shape",
                sorted(APPEARANCE_VERDICT_KEYS),
                sorted(verdict) if isinstance(verdict, dict) else verdict,
            )
        )
    if (
        not isinstance(verdict, dict)
        or verdict.get("status") != "pass"
        or verdict.get("proofCount") != len(captures)
        or not captures
    ):
        issues.append(
            _issue(
                "appearance.verdict",
                {"status": "pass", "proofCount": ">0 == len(captures)"},
                verdict,
            )
        )

    bindings = {
        "sourceCommit": source_commit,
        "datasetID": dataset_id,
        "datasetSHA256": dataset_sha256,
        "fixedClock": fixed_clock,
    }
    if not isinstance(proof.get("sourceCommit"), str) or not _COMMIT_RE.fullmatch(proof["sourceCommit"]):
        issues.append(_issue("appearance.sourceCommit.format", "40 lowercase hex", proof.get("sourceCommit")))
    if not isinstance(proof.get("datasetID"), str) or not proof["datasetID"].strip():
        issues.append(_issue("appearance.datasetID.format", "non-empty string", proof.get("datasetID")))
    if not isinstance(proof.get("datasetSHA256"), str) or not _SHA_RE.fullmatch(proof["datasetSHA256"]):
        issues.append(_issue("appearance.datasetSHA256.format", "64 lowercase hex", proof.get("datasetSHA256")))
    if not isinstance(proof.get("fixedClock"), str) or not proof["fixedClock"].strip():
        issues.append(_issue("appearance.fixedClock.format", "non-empty string", proof.get("fixedClock")))
    if not _valid_timestamp(proof.get("observedAt")):
        issues.append(_issue("appearance.observedAt", "RFC3339 UTC timestamp", proof.get("observedAt")))
    for field, expected in bindings.items():
        if expected is not None and proof.get(field) != expected:
            issues.append(_issue(f"appearance.{field}", expected, proof.get(field)))

    capture_ids: list[str] = []
    for index, capture in enumerate(captures):
        prefix = f"appearance.capture.{index}"
        if not isinstance(capture, dict) or set(capture) != APPEARANCE_CAPTURE_KEYS:
            issues.append(
                _issue(
                    f"{prefix}.shape",
                    sorted(APPEARANCE_CAPTURE_KEYS),
                    sorted(capture) if isinstance(capture, dict) else capture,
                )
            )
        capture_id = capture.get("id") if isinstance(capture, dict) else None
        if not isinstance(capture_id, str) or not _SAFE_ID_RE.fullmatch(capture_id):
            issues.append(_issue(f"{prefix}.id", "safe id", capture_id))
        else:
            capture_ids.append(capture_id)
        requested = capture.get("requestedAppearance") if isinstance(capture, dict) else None
        actual = capture.get("actualAppearance") if isinstance(capture, dict) else None
        if requested not in {"light", "dark"} or actual != requested:
            issues.append(
                _issue(
                    f"{prefix}.appearance",
                    {"requested": "light|dark", "actual": requested},
                    {"requested": requested, "actual": actual},
                )
            )
        pixel_sha = capture.get("pixelSHA256") if isinstance(capture, dict) else None
        if not isinstance(pixel_sha, str) or not _SHA_RE.fullmatch(pixel_sha):
            issues.append(_issue(f"{prefix}.pixel-sha256", "64 lowercase hex", pixel_sha))
    if len(set(capture_ids)) != len(captures):
        issues.append(_issue("appearance.capture-ids", "unique", capture_ids))

    return {
        "status": "pass" if not issues else "block",
        "issues": issues,
        "proofCount": len(captures),
    }


def load_and_validate_appearance_proof(
    path: Path,
    *,
    source_commit: str | None = None,
    dataset_id: str | None = None,
    dataset_sha256: str | None = None,
    fixed_clock: str | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "status": "block",
            "issues": [_issue("appearance.missing", str(path), "missing")],
            "proofCount": 0,
        }
    try:
        proof = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "status": "block",
            "issues": [_issue("appearance.invalid", "valid JSON", str(exc))],
            "proofCount": 0,
        }
    return validate_appearance_proof(
        proof,
        source_commit=source_commit,
        dataset_id=dataset_id,
        dataset_sha256=dataset_sha256,
        fixed_clock=fixed_clock,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate catalog appearance evidence.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--fixed-clock", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = load_and_validate_appearance_proof(
        args.path,
        source_commit=args.source_commit,
        dataset_id=args.dataset_id,
        dataset_sha256=args.dataset_sha256,
        fixed_clock=args.fixed_clock,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

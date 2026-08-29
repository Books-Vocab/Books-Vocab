from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(OPS))
from review_preflight import evaluate

SCRIPT = OPS / "review_preflight.py"


def _payload() -> dict[str, object]:
    return {
        "schema": "kg.review.evidence.v1",
        "source": {"status": "ok", "provider": "opaque-review-service"},
        "target": {"pr": "PR-opaque-42", "head": "HEAD-opaque-current"},
        "required_snapshot": {
            "status": "SUCCESS",
            "pr": "PR-opaque-42",
            "head": "HEAD-opaque-current",
        },
        "review": {
            "reviewer": "reviewer-opaque-7",
            "deadline": "deadline-opaque-2026-08-29T12:00:00Z",
            "receipt": {
                "schema": "kg.review.receipt.v1",
                "status": "PASS",
                "pr": "PR-opaque-42",
                "head": "HEAD-opaque-current",
                "reviewer": "reviewer-opaque-7",
                "deadline": "deadline-opaque-2026-08-29T12:00:00Z",
                "substantive": True,
                "evidence": [
                    {
                        "kind": "review-summary",
                        "detail": "checked exact diff and evidence contract",
                    }
                ],
            },
        },
    }


def test_matching_substantive_receipt_passes_and_preserves_opaque_identity() -> None:
    payload = _payload()

    result = evaluate(payload)

    assert result["verdict"] == "PASS"
    assert result["reason_code"] == "evidence_sufficient"
    assert result["blockers"] == []
    assert result["identity"] == {
        "pr": "PR-opaque-42",
        "head": "HEAD-opaque-current",
        "reviewer": "reviewer-opaque-7",
        "deadline": "deadline-opaque-2026-08-29T12:00:00Z",
    }
    assert result["observed"]["required_snapshot"] == {
        "status": "SUCCESS",
        "pr": "PR-opaque-42",
        "head": "HEAD-opaque-current",
    }
    assert result["observed"]["receipt"]["head"] == "HEAD-opaque-current"


def test_exact_head_mismatch_is_blocked_and_keeps_both_heads_opaque() -> None:
    payload = _payload()
    payload["review"]["receipt"]["head"] = "HEAD-opaque-old"  # type: ignore[index]

    result = evaluate(payload)

    assert result["verdict"] == "BLOCK"
    assert "exact_head_mismatch" in result["blockers"]
    assert result["identity"]["head"] == "HEAD-opaque-current"
    assert result["observed"]["receipt"]["head"] == "HEAD-opaque-old"


def test_stale_required_snapshot_is_blocked_before_review_pass() -> None:
    payload = _payload()
    payload["required_snapshot"]["head"] = "HEAD-opaque-old"  # type: ignore[index]

    result = evaluate(payload)

    assert result["verdict"] == "BLOCK"
    assert "required_snapshot_stale" in result["blockers"]


def test_missing_required_snapshot_is_distinct_from_stale_snapshot() -> None:
    payload = _payload()
    del payload["required_snapshot"]

    result = evaluate(payload)

    assert result["verdict"] == "BLOCK"
    assert result["reason_code"] == "required_snapshot_missing"
    assert result["blockers"] == ["required_snapshot_missing"]


@pytest.mark.parametrize(
    ("change", "reason_code"),
    (
        (lambda payload: payload["review"].pop("receipt"), "receipt_missing"),  # type: ignore[index]
        (
            lambda payload: payload["review"]["receipt"].pop("evidence"),  # type: ignore[index]
            "receipt_incomplete",
        ),
    ),
)
def test_missing_or_incomplete_receipt_is_blocked(change, reason_code: str) -> None:
    payload = _payload()
    change(payload)

    result = evaluate(payload)

    assert result["verdict"] == "BLOCK"
    assert result["reason_code"] == reason_code
    assert reason_code in result["blockers"]


def test_review_service_timeout_is_not_a_block_or_source_failure() -> None:
    payload = _payload()
    payload["source"] = {"status": "timeout", "error": "opaque timeout"}

    result = evaluate(payload)

    assert result["verdict"] == "review_service_timeout"
    assert result["reason_code"] == "review_service_timeout"
    assert result["exit_code"] == 2
    assert result["identity"]["pr"] == "PR-opaque-42"


def test_source_failure_is_separate_from_review_service_timeout() -> None:
    payload = _payload()
    payload["source"] = {"status": "failure", "error": "opaque source failure"}

    result = evaluate(payload)

    assert result["verdict"] == "source_failure"
    assert result["reason_code"] == "source_failure"
    assert result["exit_code"] == 3


def test_unknown_input_schema_is_a_source_failure() -> None:
    payload = _payload()
    payload["schema"] = "kg.review.evidence.unknown"

    result = evaluate(payload)

    assert result["verdict"] == "source_failure"
    assert result["reason_code"] == "source_failure"
    assert result["details"] == ["input_schema_unsupported"]


def test_mismatched_reviewer_and_deadline_are_blockers_not_normalized() -> None:
    payload = _payload()
    payload["review"]["receipt"]["reviewer"] = "reviewer-opaque-other"  # type: ignore[index]
    payload["review"]["receipt"]["deadline"] = "deadline-opaque-other"  # type: ignore[index]

    result = evaluate(payload)

    assert result["verdict"] == "BLOCK"
    assert "reviewer_mismatch" in result["blockers"]
    assert "deadline_mismatch" in result["blockers"]
    assert result["observed"]["receipt"]["reviewer"] == "reviewer-opaque-other"
    assert result["observed"]["receipt"]["deadline"] == "deadline-opaque-other"


def test_cli_emits_json_and_maps_block_to_exit_one(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    payload = copy.deepcopy(_payload())
    payload["review"]["receipt"]["head"] = "HEAD-opaque-old"  # type: ignore[index]
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(evidence_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["verdict"] == "BLOCK"
    assert "exact_head_mismatch" in output["blockers"]

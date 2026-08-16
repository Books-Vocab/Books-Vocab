from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
import ios_ui_review_matrix as module  # noqa: E402


def test_record_many_is_fail_closed_before_visual_attestation() -> None:
    data = module.load_matrix(Path(__file__).resolve().parents[1] / "fixtures" / "ios_ui_review_matrix.json")
    summary = {
        "schema": "kg.ios.ui-run-many.v1",
        "status": "passed_unattested",
        "executions": [{"status": "passed_unattested", "requirementID": "P3"}],
    }
    # A summary without a real evidenceRoot cannot be recorded. This assertion
    # protects the boundary where machine pass must still meet visual evidence.
    try:
        module.record_many(data, summary=summary, root=Path(__file__).resolve().parents[2])
    except module.UIReviewMatrixError as error:
        assert "selector" in str(error) or "--selector" in str(error)
    else:
        raise AssertionError("record-many accepted incomplete evidence")

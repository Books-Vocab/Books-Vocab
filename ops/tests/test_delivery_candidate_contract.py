from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.candidate_issues import CandidateSeverity, CandidateSpec
from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.services.candidate_contract import (
    parse_candidate_body,
    render_candidate_body,
)


def _spec() -> CandidateSpec:
    return CandidateSpec(
        severity=CandidateSeverity.P2,
        priority=20,
        scope=Scope.from_paths(
            modify=("ops/example.py", "ops/tests/test_example.py")
        ),
        acceptance=("Regression is reproduced.", "Focused proof is green."),
    )


def test_candidate_spec_from_payload_none_currently_leaks_type_error() -> None:
    with pytest.raises(TypeError):
        CandidateSpec.from_payload(None)  # type: ignore[arg-type]


def test_candidate_body_round_trips_exact_metadata() -> None:
    spec = _spec()

    body = render_candidate_body(spec)

    assert "## Severity" in body
    assert "## Scope" in body
    assert "## Acceptance" in body
    assert parse_candidate_body(body) == spec


@pytest.mark.parametrize(
    "body",
    (
        "",
        "<!-- kg.delivery.candidate.v1\n{}\n-->",
        "<!-- kg.delivery.candidate.v1\nnot-json\n-->",
    ),
)
def test_candidate_body_fails_closed_when_contract_is_missing_or_invalid(
    body: str,
) -> None:
    with pytest.raises(PolicyViolation):
        parse_candidate_body(body)

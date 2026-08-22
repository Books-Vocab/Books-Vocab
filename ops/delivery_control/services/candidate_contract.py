"""Canonical machine-readable contract for dispatchable GitHub candidate Issues."""

from __future__ import annotations

import json
from collections.abc import Mapping

from ..domain.candidate_issues import CandidateSpec
from ..domain.errors import PolicyViolation

_BEGIN = "<!-- kg.delivery.candidate.v1\n"
_END = "\n-->"


def parse_candidate_body(body: str) -> CandidateSpec:
    if type(body) is not str or body.count(_BEGIN) != 1:
        raise PolicyViolation("Issue body must contain one typed candidate contract")
    start = body.index(_BEGIN) + len(_BEGIN)
    finish = body.find(_END, start)
    if finish < 0 or _BEGIN in body[finish:]:
        raise PolicyViolation("Issue body typed candidate contract is malformed")
    try:
        payload = json.loads(body[start:finish])
    except json.JSONDecodeError as error:
        raise PolicyViolation("Issue body typed candidate contract is invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise PolicyViolation("Issue body typed candidate contract must be an object")
    try:
        return CandidateSpec.from_payload(payload)
    except ValueError as error:
        raise PolicyViolation(f"Issue body typed candidate contract is invalid: {error}") from error


def render_candidate_body(spec: CandidateSpec) -> str:
    scope = "\n".join(
        f"- `{item.operation.value}` `{item.path}`" for item in spec.scope.files
    )
    acceptance = "\n".join(f"- {item}" for item in spec.acceptance)
    initial_holds = (
        ", ".join(f"`{item}`" for item in spec.initial_holds) or "none declared"
    )
    machine = json.dumps(
        spec.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        "## Severity\n"
        f"`{spec.severity.value}`\n\n"
        "## Priority\n"
        f"`{spec.priority}`\n\n"
        "## Scope\n"
        f"{scope}\n\n"
        "## Acceptance\n"
        f"{acceptance}\n\n"
        "## Initial hard holds\n"
        f"{initial_holds}\n\n"
        f"{_BEGIN}{machine}{_END}\n"
    )

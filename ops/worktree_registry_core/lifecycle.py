"""Allowed local disposition transitions and retention policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .records import (
    DISCARD_PROOF_DISPOSITION,
    DISCARD_PROOF_SCHEMA,
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    STATUS_MERGED,
    STATUS_PUBLISHED,
    TERMINAL_PROOF_SCHEMA,  # noqa: F401 - compatibility export for registry facade
    terminal_proof_problem,
    terminal_proof_with_digest,  # noqa: F401 - compatibility export for registry facade
)
from .records import discard_proof_problem, discard_proof_with_digest

PUBLIC_RESOLVE_STATUSES = (
    STATUS_CLEANUP_PENDING,
    STATUS_PUBLISHED,
    STATUS_ABANDONED,
)
INTERNAL_TERMINAL_STATUSES = frozenset({STATUS_MERGED})

__all__ = [
    "DISCARD_PROOF_DISPOSITION",
    "DISCARD_PROOF_SCHEMA",
    "PUBLIC_RESOLVE_STATUSES",
    "TransitionRequest",
    "TransitionResult",
    "discard_record",
    "discard_proof_problem",
    "discard_proof_with_digest",
    "source_statuses",
    "requires_stored_handback",
    "validate_terminal_proof",
    "transition_record",
]


def source_statuses(target: str) -> set[str]:
    return {
        STATUS_CLEANUP_PENDING: {STATUS_ACTIVE, STATUS_PUBLISHED},
        STATUS_PUBLISHED: {STATUS_CLEANUP_PENDING},
        STATUS_ABANDONED: {STATUS_ACTIVE, STATUS_PUBLISHED},
        STATUS_MERGED: {
            STATUS_ACTIVE,
            STATUS_PUBLISHED,
            STATUS_CLEANUP_PENDING,
        },
    }[target]


def requires_stored_handback(target: str, source: object) -> bool:
    return target == STATUS_PUBLISHED or (
        target == STATUS_CLEANUP_PENDING and source == STATUS_PUBLISHED
    )


@dataclass(frozen=True)
class TransitionRequest:
    branch: str | None
    path: str | None
    target: str
    expected_generation: int
    expected_head_sha: str


@dataclass(frozen=True)
class TransitionResult:
    record: dict[str, Any] | None
    reason: str | None = None


def discard_record(
    state: dict[str, Any],
    *,
    branch: str | None,
    path: str | None,
    expected_generation: int,
    expected_head_sha: str,
    operator: str,
    reason: str,
    claim_generation: Callable[[dict[str, Any], str], int | None],
    record_matches: Callable[..., bool],
    is_commit_sha: Callable[[object], bool],
) -> TransitionResult:
    """Attach one explicit discard proof to an abandoned handback claim.

    This is deliberately separate from ``resolve``: an abandoned claim is
    already terminal, and resolving it again would blur the distinction
    between owner recovery and an intentional discard decision.
    """

    if not operator.strip() or not reason.strip():
        return TransitionResult(None, "discard proof requires operator and reason")
    matches = [
        record
        for record in state.get("records", [])
        if isinstance(record, dict)
        and record.get("status") == STATUS_ABANDONED
        and record_matches(record, branch=branch, path=path)
        and claim_generation(record, "claim_generation") == expected_generation
    ]
    if len(matches) != 1:
        return TransitionResult(
            None, "no unique abandoned registry record matches discard"
        )
    record = matches[0]
    handed_back_sha = record.get("handed_back_sha")
    if not is_commit_sha(handed_back_sha) or handed_back_sha != expected_head_sha:
        return TransitionResult(None, "discard HEAD does not match the stored handback")
    existing = record.get("discard_proof")
    if existing is not None:
        if discard_proof_problem(record) is not None:
            return TransitionResult(None, "existing discard proof is invalid")
        if existing.get("operator") != operator or existing.get("reason") != reason:
            return TransitionResult(
                None, "existing discard proof differs from requested proof"
            )
        return TransitionResult(record)
    external_ids = record.get("external_ids")
    lane_id = (
        external_ids[0]
        if isinstance(external_ids, list) and external_ids
        else record.get("branch")
    )
    seal = record.get("handback_seal")
    handback_digest = seal.get("digest") if isinstance(seal, dict) else None
    proof = discard_proof_with_digest(
        {
            "schema": DISCARD_PROOF_SCHEMA,
            "disposition": DISCARD_PROOF_DISPOSITION,
            "lane_id": lane_id,
            "branch": record.get("branch"),
            "head_sha": expected_head_sha,
            "claim_generation": expected_generation,
            "base_sha": record.get("base_sha"),
            "handback_digest": handback_digest,
            "operator": operator,
            "reason": reason,
        }
    )
    candidate = dict(record)
    candidate["discard_proof"] = proof
    if (problem := discard_proof_problem(candidate)) is not None:
        return TransitionResult(None, problem)
    record["discard_proof"] = proof
    return TransitionResult(record)


def validate_terminal_proof(
    proof: object,
    *,
    record: dict[str, Any],
    request: TransitionRequest,
) -> str | None:
    if request.target != STATUS_MERGED:
        return (
            "terminal proof is only valid for merged disposition"
            if proof is not None
            else None
        )
    if proof is None:
        return "merged disposition requires a typed terminal proof"
    return terminal_proof_problem(
        proof,
        branch=record.get("branch"),
        head_sha=request.expected_head_sha,
        record_external_ids=record.get("external_ids"),
    )


def transition_record(
    state: dict[str, Any],
    request: TransitionRequest,
    *,
    claim_generation: Callable[[dict[str, Any], str], int | None],
    record_matches: Callable[..., bool],
    is_commit_sha: Callable[[object], bool],
    branch_head: Callable[[str], str | None],
    has_valid_handback: Callable[[dict[str, Any]], bool],
    has_valid_stored_handback: Callable[[dict[str, Any]], bool],
) -> TransitionResult:
    newer_live_claims = [
        record
        for record in state.get("records", [])
        if isinstance(record, dict)
        and record.get("status") in {STATUS_ACTIVE, STATUS_CLEANUP_PENDING}
        and (
            (request.branch is not None and record.get("branch") == request.branch)
            or (request.path is not None and record_matches(record, path=request.path))
        )
        and (generation := claim_generation(record, "claim_generation")) is not None
        and generation > request.expected_generation
    ]
    if newer_live_claims:
        return TransitionResult(
            None, "newer registry claim blocks historical transition"
        )

    matches = [
        record
        for record in state.get("records", [])
        if isinstance(record, dict)
        and record.get("status") in source_statuses(request.target)
        and record_matches(record, branch=request.branch, path=request.path)
        and claim_generation(record, "claim_generation") == request.expected_generation
    ]
    exact_matches: list[dict[str, Any]] = []
    for record in matches:
        expected_head = record.get("handed_back_sha")
        if not is_commit_sha(expected_head):
            branch = record.get("branch")
            if isinstance(branch, str) and branch:
                expected_head = branch_head(branch)
        if not is_commit_sha(expected_head):
            expected_head = record.get("base_sha")
        if expected_head == request.expected_head_sha:
            exact_matches.append(record)
    if not exact_matches:
        return TransitionResult(None, "no exact registry record matches transition")
    if len(exact_matches) != 1:
        return TransitionResult(None, "registry transition selector is ambiguous")

    record = exact_matches[0]
    stored_required = requires_stored_handback(request.target, record.get("status"))
    valid_handback = (
        has_valid_stored_handback(record)
        if stored_required
        else has_valid_handback(record)
    )
    if (
        request.target in {STATUS_CLEANUP_PENDING, STATUS_PUBLISHED}
        and not valid_handback
    ):
        required_kind = "stored" if stored_required else "physical"
        return TransitionResult(
            None,
            f"{request.target} transition requires a valid {required_kind} hand-back",
        )
    return TransitionResult(record)

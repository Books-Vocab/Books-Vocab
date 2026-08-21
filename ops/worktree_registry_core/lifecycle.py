"""Allowed local disposition transitions and retention policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .records import (
    STATUS_ABANDONED,
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    STATUS_MERGED,
    STATUS_PUBLISHED,
)

PUBLIC_RESOLVE_STATUSES = (
    STATUS_CLEANUP_PENDING,
    STATUS_PUBLISHED,
    STATUS_ABANDONED,
)
INTERNAL_TERMINAL_STATUSES = frozenset({STATUS_MERGED})
TERMINAL_PROOF_SCHEMA = "kg.worktree.terminal-proof.v1"


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


def terminal_proof_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    proof = dict(body)
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    proof["digest"] = hashlib.sha256(encoded).hexdigest()
    return proof


def validate_terminal_proof(
    proof: object,
    *,
    record: dict[str, Any],
    request: TransitionRequest,
) -> str | None:
    if request.target != STATUS_MERGED:
        return "terminal proof is only valid for merged disposition" if proof else None
    if not isinstance(proof, dict):
        return "merged disposition requires a typed terminal proof"
    digest = proof.get("digest")
    body = {key: value for key, value in proof.items() if key != "digest"}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if digest != hashlib.sha256(encoded).hexdigest():
        return "terminal proof digest is invalid"
    external_ids = record.get("external_ids")
    if not isinstance(external_ids, list):
        return "terminal proof record has invalid external ids"
    expected = {
        "schema": TERMINAL_PROOF_SCHEMA,
        "pr_state": "MERGED",
        "base_branch": "main",
        "branch": record.get("branch"),
        "head_sha": request.expected_head_sha,
    }
    for key, value in expected.items():
        if body.get(key) != value:
            return f"terminal proof {key} does not match exact merged PR"
    if type(body.get("pr_number")) is not int or body["pr_number"] <= 0:
        return "terminal proof PR number is invalid"
    lane_id = body.get("lane_id")
    if type(lane_id) is not str or lane_id not in external_ids:
        return "terminal proof lane does not match the registry claim"
    return None


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

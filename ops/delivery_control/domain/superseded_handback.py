"""Typed evidence for an abandoned handback superseded by a merged PR."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SUPERSEDED_PROOF_SCHEMA = "kg.worktree.superseded-handback-proof.v1"
SUPERSEDED_PROOF_DISPOSITION = "superseded_by_merged_pr"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_TEXT = (
    "lane_id",
    "branch",
    "merged_pr_state",
    "merged_pr_base_branch",
    "merged_pr_branch",
    "operator",
    "reason",
)
_REQUIRED_SHA = (
    "handback_sha",
    "base_sha",
    "merged_pr_head_sha",
    "merged_pr_base_sha",
)


def _text(value: object, field: str) -> str | None:
    if type(value) is not str or not value.strip():
        return f"superseded proof {field} must be non-empty text"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return f"superseded proof {field} contains control characters"
    return None


def validate_superseded_proof_shape(payload: object) -> str | None:
    """Validate proof shape before matching it to one registry record."""

    if not isinstance(payload, Mapping):
        return "superseded proof must be an object"
    if payload.get("schema") != SUPERSEDED_PROOF_SCHEMA:
        return f"superseded proof schema must be {SUPERSEDED_PROOF_SCHEMA}"
    if payload.get("disposition") != SUPERSEDED_PROOF_DISPOSITION:
        return "superseded proof disposition is invalid"
    for field in _REQUIRED_TEXT:
        if (problem := _text(payload.get(field), field)) is not None:
            return problem
    for field in _REQUIRED_SHA:
        if type(payload.get(field)) is not str or not _SHA_RE.fullmatch(payload[field]):
            return f"superseded proof {field} must be a lowercase commit SHA"
    if (
        type(payload.get("claim_generation")) is not int
        or payload["claim_generation"] < 0
    ):
        return "superseded proof claim_generation must be a non-negative integer"
    if type(payload.get("handback_digest")) is not str or not _DIGEST_RE.fullmatch(
        payload["handback_digest"]
    ):
        return "superseded proof handback_digest must be a SHA-256 digest"
    if (
        type(payload.get("merged_pr_number")) is not int
        or payload["merged_pr_number"] <= 0
    ):
        return "superseded proof merged_pr_number must be positive"
    if payload.get("merged_pr_state") != "MERGED":
        return "superseded proof merged_pr_state must be MERGED"
    if payload.get("merged_pr_base_branch") != "main":
        return "superseded proof merged_pr_base_branch must be main"
    fingerprint = payload.get("patch_fingerprint")
    if type(fingerprint) is not str or not _DIGEST_RE.fullmatch(fingerprint):
        return "superseded proof patch_fingerprint must be a SHA-256 digest"
    paths = payload.get("scope_paths")
    if type(paths) is not list or any(_text(item, "scope_paths") for item in paths):
        return "superseded proof scope_paths must be a list of text paths"
    if tuple(sorted(set(paths))) != tuple(paths):
        return "superseded proof scope_paths must be sorted and unique"
    return None


def superseded_proof_with_digest(body: Mapping[str, Any]) -> dict[str, Any]:
    """Add the canonical digest to a proof body."""

    import hashlib
    import json

    normalized = dict(body)
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    normalized["digest"] = hashlib.sha256(encoded).hexdigest()
    return normalized


def superseded_proof_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "digest"}


__all__ = [
    "SUPERSEDED_PROOF_DISPOSITION",
    "SUPERSEDED_PROOF_SCHEMA",
    "superseded_proof_body",
    "superseded_proof_with_digest",
    "validate_superseded_proof_shape",
]

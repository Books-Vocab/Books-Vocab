"""Validation for legacy worktree-registry hand-back seals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_GREEN = {"pass", "passed", "green", "ok", "success"}
_INITIAL_HOLDS = frozenset({"p0", "p1", "security"})


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def legacy_seal_valid(record: Mapping[str, Any]) -> bool:
    seal = record.get("handback_seal")
    if not isinstance(seal, Mapping):
        return False
    body = {key: value for key, value in seal.items() if key != "digest"}
    if seal.get("schema") != "kg.worktree.handback.v1":
        return False
    if seal.get("digest") != hashlib.sha256(_canonical_json(body)).hexdigest():
        return False
    if seal.get("branch") != record.get("branch"):
        return False
    if seal.get("owner_thread_id") != record.get("codex_thread_id"):
        return False
    if (
        Path(str(seal.get("path", ""))).expanduser().resolve()
        != Path(str(record.get("path", ""))).expanduser().resolve()
    ):
        return False
    if sorted(seal.get("external_ids") or []) != sorted(record.get("external_ids") or []):
        return False
    if seal.get("tip_sha") != record.get("handed_back_sha"):
        return False
    if seal.get("handed_back_at") != record.get("handed_back_at"):
        return False
    if record.get("claim_generation") != record.get("handback_claim_generation"):
        return False
    outcomes = seal.get("outcomes")
    return isinstance(outcomes, list) and not any(
        not isinstance(item, Mapping) or str(item.get("status", "")).strip().lower() not in _GREEN for item in outcomes
    )


def parse_initial_holds(seal: Mapping[str, Any]) -> tuple[str, ...]:
    raw_holds = seal.get("initial_holds", [])
    if (
        not isinstance(raw_holds, list)
        or any(type(item) is not str or item not in _INITIAL_HOLDS for item in raw_holds)
        or len(set(raw_holds)) != len(raw_holds)
    ):
        raise ValueError("registry handback initial_holds must be a unique list of supported holds")
    return tuple(sorted(raw_holds))

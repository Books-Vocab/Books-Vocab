"""Exact published-claim validation and fresh active-claim registration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import worktree_registry as registry

from .domain import RegistryPreflight, commit_sha, declared_operations
from .errors import ReanchorRefused

# An active claim may already have a typed hand-back when an owner resumes
# after an interrupted transport.  It is reanchorable only through the same
# immutable-seal and CAS checks as published claims.
_PUBLISHED_CLAIM_STATUSES = frozenset({"active", "published", "cleanup_pending"})


def _select_original(
    state: dict[str, Any], *, lane_id: str, claim_generation: int
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for record in state.get("records", []):
        if (
            not isinstance(record, dict)
            or record.get("status") not in _PUBLISHED_CLAIM_STATUSES
        ):
            continue
        try:
            external_ids = registry._legacy_external_ids(record)
        except (TypeError, ValueError):
            continue
        lane_matches = lane_id in external_ids or (
            not external_ids and record.get("branch") == lane_id
        )
        if lane_matches and record.get("claim_generation") == claim_generation:
            matches.append(record)
    if len(matches) != 1:
        raise ReanchorRefused(
            "published selector must match exactly one original claim",
            lane_id=lane_id,
            claim_generation=claim_generation,
            matches=len(matches),
        )
    return matches[0]


def _fingerprint(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plan_registration(
    state: dict[str, Any],
    *,
    original: dict[str, Any],
    target: Path,
    replacement_base: str,
    replacement_base_sha: str,
    allow_unhanded_active: bool = False,
) -> dict[str, Any]:
    trial = copy.deepcopy(state)
    try:
        original_index = next(
            index
            for index, record in enumerate(state.get("records", []))
            if record is original
        )
        trial_original = trial["records"][original_index]
    except (KeyError, StopIteration, TypeError) as exc:
        raise ReanchorRefused("original claim is not part of registry state") from exc
    return _replace_published(
        trial,
        original=trial_original,
        target=target,
        replacement_base=replacement_base,
        replacement_base_sha=replacement_base_sha,
        allow_unhanded_active=allow_unhanded_active,
    )


def _is_unhanded_active(record: dict[str, Any]) -> bool:
    """Identify a fresh active claim with no partial hand-back evidence."""

    return (
        record.get("status") == "active"
        and record.get("handed_back_at") is None
        and record.get("handed_back_sha") is None
        and record.get("handback_claim_generation") is None
        and "handback_seal" not in record
    )


def _replace_published(
    state: dict[str, Any],
    *,
    original: dict[str, Any],
    target: Path,
    replacement_base: str,
    replacement_base_sha: str,
    allow_unhanded_active: bool = False,
) -> dict[str, Any]:
    if original.get("status") not in _PUBLISHED_CLAIM_STATUSES:
        raise ReanchorRefused("original claim is no longer resumable")
    if not (
        allow_unhanded_active and _is_unhanded_active(original)
    ) and not registry._has_valid_stored_handback(original):
        raise ReanchorRefused("original published claim lacks a valid typed hand-back")
    _, resolved_at = registry.resolve_now()
    original["status"] = "abandoned"
    original["resolved_at"] = resolved_at
    rc, candidate = registry._register_record(
        state,
        branch=str(original["branch"]),
        path=str(target),
        intent=str(original["intent"]),
        base=replacement_base,
        external_ids=registry._legacy_external_ids(original),
        scope=original.get("scope"),
        codex_thread_id=original.get("codex_thread_id"),
        delegated=original.get("delegated"),
    )
    if rc != registry.EXIT_OK:
        raise ReanchorRefused(
            f"new active same-owner claim refused: {candidate.get('reason', candidate)}",
            registry=candidate,
        )
    expected_generation = int(original["claim_generation"]) + 1
    if (
        candidate.get("status") != registry.STATUS_ACTIVE
        or candidate.get("claim_generation") != expected_generation
        or candidate.get("branch") != original.get("branch")
        or candidate.get("intent") != original.get("intent")
        or candidate.get("base") != replacement_base
        or candidate.get("codex_thread_id") != original.get("codex_thread_id")
        or candidate.get("delegated") != original.get("delegated")
        or candidate.get("external_ids") != registry._legacy_external_ids(original)
        or candidate.get("scope") != original.get("scope")
        or Path(str(candidate.get("path"))).resolve() != target
    ):
        raise ReanchorRefused(
            "new claim would not preserve the exact original owner/claim/Scope",
            candidate=candidate,
        )
    candidate["base_sha"] = replacement_base_sha
    published_base_sha = original.get("published_base_sha")
    if published_base_sha is not None:
        candidate["published_base_sha"] = commit_sha(
            published_base_sha,
            label="published PR base",
        )
    return candidate


def _preflight_published(
    *,
    state_path: Path,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_remote_head: str,
    target: Path,
    previous_handback: str | None = None,
    replacement_base: str | None = None,
    replacement_base_sha: str | None = None,
    allow_unhanded_active: bool = False,
) -> RegistryPreflight:
    state = registry.load_state(state_path)
    original = _select_original(
        state, lane_id=lane_id, claim_generation=claim_generation
    )
    if original.get("branch") != branch:
        raise ReanchorRefused("caller branch differs from the exact original claim")
    if original.get("codex_thread_id") != owner_thread_id:
        raise ReanchorRefused("caller owner differs from the exact original owner")
    remote_source_active = allow_unhanded_active and _is_unhanded_active(original)
    if not remote_source_active:
        expected_original_head = previous_handback or expected_remote_head
        if original.get("handed_back_sha") != expected_original_head:
            raise ReanchorRefused(
                "expected remote HEAD differs from original hand-back"
            )
        if not registry._has_valid_stored_handback(original):
            raise ReanchorRefused(
                "original published claim lacks a valid typed hand-back"
            )
    recorded_path = Path(str(original["path"])).expanduser().resolve()
    requested_path = target.expanduser().resolve()
    if requested_path != recorded_path:
        raise ReanchorRefused(
            "resume target path differs from exact original claim path",
            recorded_path=str(recorded_path),
            requested_path=str(requested_path),
        )
    if not lane_id.strip() or claim_generation < 0:
        raise ReanchorRefused(
            "lane and claim generation must identify one original claim"
        )
    recorded_base = original.get("base")
    if not isinstance(recorded_base, str) or not recorded_base.strip():
        raise ReanchorRefused("original recorded base is missing or invalid")
    # Registry v2 records written before the typed base_sha field was added
    # still carry the exact commit in `base`. Preserve their resumability while
    # keeping the same full-SHA validation and exact owner/Scope checks.
    base_sha = commit_sha(
        original.get("base_sha") or recorded_base,
        label="original base",
    )
    # Older registry records may preserve the human-readable ``base`` ref
    # (for example ``origin/main``) while the exact handback commit lives in
    # ``base_sha``.  Published PR provenance must use that exact commit until
    # ``published_base_sha`` is recorded; otherwise a valid published claim is
    # rejected before GitHub lifecycle verification can even run.
    published_base_sha = commit_sha(
        original.get("published_base_sha") or base_sha,
        label="published PR base",
    )
    declared = declared_operations(original.get("scope"))
    planned_base = replacement_base if replacement_base is not None else recorded_base
    planned_base_sha = replacement_base_sha or base_sha
    _plan_registration(
        state,
        original=original,
        target=target,
        replacement_base=planned_base,
        replacement_base_sha=planned_base_sha,
        allow_unhanded_active=allow_unhanded_active,
    )
    return RegistryPreflight(
        original=original,
        fingerprint=_fingerprint(original),
        base_sha=base_sha,
        published_base_sha=published_base_sha,
        declared=declared,
    )


def preflight(
    *,
    state_path: Path,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_remote_head: str,
    live_main: str,
    target: Path,
) -> RegistryPreflight:
    result = _preflight_published(
        state_path=state_path,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_remote_head=expected_remote_head,
        target=target,
        replacement_base=live_main,
        replacement_base_sha=live_main,
        allow_unhanded_active=True,
    )
    base_sha = result.base_sha
    if base_sha == live_main:
        raise ReanchorRefused("original claim is already based on exact live main")
    return result


def preflight_resume(
    *,
    state_path: Path,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_remote_head: str,
    target: Path,
    previous_handback: str | None = None,
) -> RegistryPreflight:
    return _preflight_published(
        state_path=state_path,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_remote_head=expected_remote_head,
        target=target,
        previous_handback=previous_handback,
    )


def _register_from_published(
    *,
    state_path: Path,
    preflight_result: RegistryPreflight,
    target: Path,
    replacement_base: str,
    replacement_base_sha: str,
    lane_id: str,
    claim_generation: int,
    action: str,
    allow_unhanded_active: bool = False,
) -> dict[str, Any]:
    with registry._ledger_lock(state_path):
        state = registry.load_state(state_path)
        current = _select_original(
            state, lane_id=lane_id, claim_generation=claim_generation
        )
        if _fingerprint(current) != preflight_result.fingerprint:
            raise ReanchorRefused(f"original registry claim changed during {action}")
        active = _replace_published(
            state,
            original=current,
            target=target,
            replacement_base=replacement_base,
            replacement_base_sha=replacement_base_sha,
            allow_unhanded_active=allow_unhanded_active,
        )
        registry.save_state(state_path, state)
    return active


def register_active(
    *,
    state_path: Path,
    preflight_result: RegistryPreflight,
    target: Path,
    live_main: str,
    lane_id: str,
    claim_generation: int,
) -> dict[str, Any]:
    return _register_from_published(
        state_path=state_path,
        preflight_result=preflight_result,
        target=target,
        replacement_base=live_main,
        replacement_base_sha=live_main,
        lane_id=lane_id,
        claim_generation=claim_generation,
        action="reanchor",
        allow_unhanded_active=True,
    )


def register_resumed(
    *,
    state_path: Path,
    preflight_result: RegistryPreflight,
    target: Path,
    lane_id: str,
    claim_generation: int,
) -> dict[str, Any]:
    original = preflight_result.original
    return _register_from_published(
        state_path=state_path,
        preflight_result=preflight_result,
        target=target,
        replacement_base=str(original["base"]),
        replacement_base_sha=preflight_result.base_sha,
        lane_id=lane_id,
        claim_generation=claim_generation,
        action="resume-published",
    )

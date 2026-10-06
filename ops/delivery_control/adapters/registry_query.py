"""Read-only queries over worktree-registry command payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.errors import InvalidScope
from ..domain.models import Scope
from ..domain.observations import (
    InventoryProblem,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
)
from ..ports.process import CommandRunnerPort
from ..ports.registry import LegacyTerminalClaim
from .errors import AdapterCommandError, AdapterPayloadError
from .registry_parsing import (
    parse_collision_claim,
    parse_registry_record,
    record_external_ids,
    reported_problems,
)

_COLLISION_TERMINAL_STATUSES = frozenset({"published", "merged", "abandoned"})
_COLLISION_ACTIVE_STATUSES = frozenset({"active", "cleanup_pending"})
_CURRENT_DURABLE_CLAIM_STATUSES = frozenset({"active", "published", "cleanup_pending"})
_SCOPED_CLAIM_PROBLEM_PREFIX = "registry-claim-generation-invalid"


def _registry_identity(raw: Mapping[str, Any], index: int) -> tuple[str, str]:
    """Return an identity and its source field without guessing later."""

    branch = raw.get("branch")
    if branch:
        return str(branch), "branch"
    path = raw.get("path")
    if path:
        return str(path), "path"
    return f"record[{index}]", "record"


def _registry_parse_error(error: Exception) -> str:
    """Turn parser exceptions into stable operator-facing diagnostics."""

    if isinstance(error, KeyError) and error.args:
        missing = error.args[0]
        if isinstance(missing, str) and missing:
            return f"registry record is missing required field: {missing}"
    return str(error)


def _problem_signature(reason: str) -> str:
    """Normalize one known low-level/parser wording pair for deduplication."""

    text = reason.strip()
    if text.startswith("registry-") and ": " in text:
        text = text.split(": ", 1)[1]
    text = text.removeprefix("registry ")
    return text


def _reported_problem_covers(
    reported: list[InventoryProblem], candidate: InventoryProblem
) -> bool:
    """Avoid duplicating a fact already emitted by registry normalization.

    This is deliberately identity/status/reason scoped.  A second, different
    diagnostic for the same malformed record remains visible.
    """

    candidate_signature = _problem_signature(candidate.reason)
    return any(
        problem.identity == candidate.identity
        and problem.identity_kind == candidate.identity_kind
        and problem.record_status == candidate.record_status
        and _problem_signature(problem.reason) == candidate_signature
        for problem in reported
    )


def load_registry_list(
    runner: CommandRunnerPort, argv: tuple[str, ...]
) -> Mapping[str, Any]:
    result = runner.run(argv)
    if result.exit_code != 0:
        raise AdapterCommandError(result)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AdapterPayloadError("registry list returned invalid JSON") from error
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise AdapterPayloadError("registry list payload is malformed")
    return payload


def registry_inventory(payload: Mapping[str, Any]) -> RegistryInventory:
    records: list[RegistrySnapshot] = []
    problems = list(reported_problems(payload))
    for index, raw in enumerate(payload["records"]):
        if not isinstance(raw, Mapping):
            problems.append(
                InventoryProblem(
                    "registry",
                    f"record[{index}]",
                    "record is not an object",
                    identity_kind="record",
                )
            )
            continue
        identity, identity_kind = _registry_identity(raw, index)
        try:
            records.append(parse_registry_record(raw))
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            raw_path = raw.get("path")
            record_path = None
            if isinstance(raw_path, str) and raw_path.strip():
                candidate_path = Path(raw_path).expanduser()
                if candidate_path.is_absolute():
                    record_path = candidate_path.resolve()
            raw_owner = raw.get("codex_thread_id")
            raw_status = (
                raw.get("status") if isinstance(raw.get("status"), str) else None
            )
            candidate = InventoryProblem(
                "registry",
                identity,
                _registry_parse_error(error),
                identity_kind=identity_kind,
                record_status=raw_status,
                record_path=(record_path if raw_status == "active" else None),
                owner_thread_id=(
                    raw_owner.strip()
                    if raw_status == "active"
                    and isinstance(raw_owner, str)
                    and raw_owner.strip()
                    else None
                ),
                record_external_ids=record_external_ids(raw),
            )
            if not _reported_problem_covers(problems, candidate):
                problems.append(candidate)
    return RegistryInventory(records=tuple(records), problems=tuple(problems))


def collision_inventory(payload: Mapping[str, Any]) -> RegistryCollisionInventory:
    records: list[RegistryCollisionClaim] = []
    reported = list(reported_problems(payload))
    problems: list[InventoryProblem] = []
    for index, raw in enumerate(payload["records"]):
        if not isinstance(raw, Mapping):
            problems.append(
                InventoryProblem(
                    "registry",
                    f"record[{index}]",
                    "record is not an object",
                    identity_kind="record",
                )
            )
            continue
        identity, identity_kind = _registry_identity(raw, index)
        status = raw.get("status")
        if status in {"merged", "abandoned", "published"}:
            continue
        if status not in {"active", "cleanup_pending"}:
            problems.append(
                InventoryProblem(
                    "registry",
                    identity,
                    "registry status is not collision-safe",
                    identity_kind=identity_kind,
                )
            )
            continue
        try:
            records.append(parse_collision_claim(raw))
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            problems.append(
                InventoryProblem(
                    "registry",
                    identity,
                    _registry_parse_error(error),
                    identity_kind=identity_kind,
                )
            )
    parsed_branches = {record.branch for record in records}
    for problem in reported:
        if problem.record_status in _COLLISION_TERMINAL_STATUSES:
            continue
        if (
            problem.reason.startswith(_SCOPED_CLAIM_PROBLEM_PREFIX)
            and problem.record_status in _COLLISION_ACTIVE_STATUSES
            and problem.identity_kind == "branch"
            and problem.identity in parsed_branches
        ):
            # The collision projection has independently recovered the exact
            # branch and Scope. Claim-generation repair remains visible in the
            # full registry inventory, but it must not become a global
            # publisher blocker for disjoint lanes.
            continue
        problems.append(problem)
    return RegistryCollisionInventory(records=tuple(records), problems=tuple(problems))


def active_record(
    inventory: RegistryInventory, lane_id: str
) -> RegistrySnapshot | None:
    matches = [
        item
        for item in inventory.records
        if item.lane_id == lane_id and item.status == "active"
    ]
    if len(matches) > 1:
        raise AdapterPayloadError(
            f"multiple active registry records found for {lane_id}"
        )
    return matches[0] if matches else None


def exact_claim(
    payload: Mapping[str, Any],
    *,
    lane_id: str,
    branch: str,
    path: Path,
    claim_generation: int,
) -> RegistrySnapshot | None:
    expected_path = path.expanduser().resolve()
    matches: list[RegistrySnapshot] = []
    for raw in payload["records"]:
        if not isinstance(raw, Mapping) or raw.get("branch") != branch:
            continue
        external_ids = raw.get("external_ids")
        if external_ids is not None and not isinstance(external_ids, list):
            raise AdapterPayloadError("exact registry claim is malformed")
        raw_lane = (
            str(external_ids[0])
            if isinstance(external_ids, list) and external_ids
            else branch
        )
        if raw_lane != lane_id:
            continue
        try:
            raw_path_value = raw["path"]
            if not isinstance(raw_path_value, str) or not raw_path_value:
                raise ValueError("registry path must be non-empty text")
            raw_path = Path(raw_path_value).expanduser()
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterPayloadError(
                "exact registry claim path is malformed"
            ) from error
        if not raw_path.is_absolute():
            raise AdapterPayloadError("exact registry claim path is malformed")
        if raw_path.resolve() != expected_path:
            continue
        try:
            record = parse_registry_record(raw)
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            raise AdapterPayloadError("exact registry claim is malformed") from error
        if record.claim_generation == claim_generation:
            matches.append(record)
    if len(matches) > 1:
        raise AdapterPayloadError("multiple exact registry claims found")
    return matches[0] if matches else None


def published_claim(
    payload: Mapping[str, Any],
    *,
    lane_id: str,
    branch: str,
    path: Path,
    owner_thread_id: str,
    head_sha: str,
    scope: Scope,
) -> RegistrySnapshot | None:
    """Find one current durable claim by stable handback identity.

    The caller already has an older receipt, so claim generation is deliberately
    not part of the selector.  Only the exact branch/path/owner/head identity
    plus a current Scope contained by the older requested Scope may bridge
    that generation drift; unrelated malformed records do not become global
    blockers, while a malformed matching record is fatal.
    """

    expected_path = path.expanduser().resolve()
    matches: list[RegistrySnapshot] = []
    for raw in payload["records"]:
        if not isinstance(raw, Mapping) or raw.get("branch") != branch:
            continue
        if raw.get("status") not in _CURRENT_DURABLE_CLAIM_STATUSES:
            continue
        external_ids = raw.get("external_ids")
        if external_ids is not None and not isinstance(external_ids, list):
            raise AdapterPayloadError("published registry claim is malformed")
        raw_lane_id = (
            str(external_ids[0])
            if isinstance(external_ids, list) and external_ids
            else branch
        )
        if raw_lane_id != lane_id:
            continue
        if raw.get("codex_thread_id") != owner_thread_id:
            continue
        if raw.get("handed_back_sha") != head_sha:
            continue
        raw_path = raw.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise AdapterPayloadError("published registry claim is malformed")
        candidate_path = Path(raw_path).expanduser()
        if not candidate_path.is_absolute():
            raise AdapterPayloadError("published registry claim is malformed")
        if candidate_path.resolve() != expected_path:
            continue
        try:
            record = parse_registry_record(raw)
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            raise AdapterPayloadError(
                "published registry claim is malformed"
            ) from error
        if not set(record.scope.files).issubset(scope.files):
            raise AdapterPayloadError("published registry claim Scope differs")
        matches.append(record)
    if len(matches) > 1:
        raise AdapterPayloadError("multiple current published registry claims found")
    return matches[0] if matches else None


def terminal_claim(
    payload: Mapping[str, Any], *, branch: str
) -> RegistrySnapshot | LegacyTerminalClaim | None:
    """Resolve one terminal claim without parsing unrelated broken records.

    Legacy cleanup is deliberately narrower than full inventory: unrelated
    malformed records must not prevent a proven terminal branch from being
    released, while duplicate or malformed records for the target branch still
    fail closed.
    """

    matches: list[RegistrySnapshot | LegacyTerminalClaim] = []
    for raw in payload["records"]:
        if not isinstance(raw, Mapping) or raw.get("branch") != branch:
            continue
        try:
            record = parse_registry_record(raw)
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            if raw.get("status") != "merged":
                raise AdapterPayloadError(
                    "terminal registry claim is malformed"
                ) from error
            try:
                record = _parse_legacy_terminal_claim(raw)
            except (KeyError, TypeError, ValueError, InvalidScope) as legacy_error:
                raise AdapterPayloadError(
                    "terminal registry claim is malformed"
                ) from legacy_error
        matches.append(record)
    if len(matches) <= 1:
        return matches[0] if matches else None

    # A branch can legitimately have terminal history from more than one
    # abandoned claim generation.  A published legacy PR still carries one
    # durable hand-back tip, so use that proof to select the record that the
    # caller can validate against the live PR.  If history contains more than
    # one hand-back-bearing claim, or none at all, the evidence remains
    # ambiguous and must stay fail-closed.
    if any(isinstance(record, LegacyTerminalClaim) for record in matches):
        raise AdapterPayloadError("multiple registry claims found for terminal branch")
    handed_back = [record for record in matches if record.handed_back_sha]
    if len(handed_back) == 1:
        return handed_back[0]
    raise AdapterPayloadError("multiple registry claims found for terminal branch")


def _parse_legacy_terminal_claim(raw: Mapping[str, Any]) -> LegacyTerminalClaim:
    """Project only the narrow legacy shape needed by merged cleanup."""

    if raw.get("status") != "merged":
        raise ValueError("legacy terminal claim must be merged")
    branch = raw.get("branch")
    path_value = raw.get("path")
    if not isinstance(branch, str) or not branch.strip():
        raise ValueError("legacy terminal claim branch is malformed")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("legacy terminal claim path is malformed")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise ValueError("legacy terminal claim path is malformed")

    base_value = raw.get("base_sha")
    if base_value is None:
        base_value = raw.get("base")
    if base_value not in (None, "main"):
        raise ValueError("legacy terminal claim base is not symbolic main")

    handed_back_sha = raw.get("handed_back_sha")
    if handed_back_sha is not None and (
        not isinstance(handed_back_sha, str)
        or len(handed_back_sha) != 40
        or any(char not in "0123456789abcdef" for char in handed_back_sha)
    ):
        raise ValueError("legacy terminal claim hand-back is malformed")

    scope = Scope.from_payload(raw["scope"])
    external_ids = raw.get("external_ids")
    lane_id = branch
    if external_ids is not None and not isinstance(external_ids, list):
        raise ValueError("legacy terminal claim external IDs are malformed")
    if isinstance(external_ids, list) and external_ids:
        if not all(isinstance(value, str) and value.strip() for value in external_ids):
            raise ValueError("legacy terminal claim external IDs are malformed")
        lane_id = external_ids[0].strip()
    return LegacyTerminalClaim(
        lane_id=lane_id,
        branch=branch,
        path=path.resolve(),
        status="merged",
        scope=scope,
        base_sha=base_value or None,
        handed_back_sha=handed_back_sha,
    )

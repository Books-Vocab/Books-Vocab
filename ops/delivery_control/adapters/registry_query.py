"""Read-only queries over worktree-registry command payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.errors import InvalidScope
from ..domain.observations import (
    InventoryProblem,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
)
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError
from .registry_parsing import (
    parse_collision_claim,
    parse_registry_record,
    reported_problems,
)


def load_registry_list(runner: CommandRunnerPort, argv: tuple[str, ...]) -> Mapping[str, Any]:
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
            problems.append(InventoryProblem("registry", f"record[{index}]", "record is not an object"))
            continue
        identity = str(raw.get("branch") or raw.get("path") or f"record[{index}]")
        try:
            records.append(parse_registry_record(raw))
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            problems.append(InventoryProblem("registry", identity, str(error)))
    return RegistryInventory(records=tuple(records), problems=tuple(problems))


def collision_inventory(payload: Mapping[str, Any]) -> RegistryCollisionInventory:
    records: list[RegistryCollisionClaim] = []
    problems = list(reported_problems(payload))
    for index, raw in enumerate(payload["records"]):
        if not isinstance(raw, Mapping):
            problems.append(InventoryProblem("registry", f"record[{index}]", "record is not an object"))
            continue
        identity = str(raw.get("branch") or raw.get("path") or f"record[{index}]")
        status = raw.get("status")
        if status in {"merged", "abandoned", "published"}:
            continue
        if status not in {"active", "cleanup_pending"}:
            problems.append(InventoryProblem("registry", identity, "registry status is not collision-safe"))
            continue
        try:
            records.append(parse_collision_claim(raw))
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            problems.append(InventoryProblem("registry", identity, str(error)))
    return RegistryCollisionInventory(records=tuple(records), problems=tuple(problems))


def active_record(inventory: RegistryInventory, lane_id: str) -> RegistrySnapshot | None:
    matches = [item for item in inventory.records if item.lane_id == lane_id and item.status == "active"]
    if len(matches) > 1:
        raise AdapterPayloadError(f"multiple active registry records found for {lane_id}")
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
        raw_lane = str(external_ids[0]) if isinstance(external_ids, list) and external_ids else branch
        if raw_lane != lane_id:
            continue
        try:
            raw_path_value = raw["path"]
            if not isinstance(raw_path_value, str) or not raw_path_value:
                raise ValueError("registry path must be non-empty text")
            raw_path = Path(raw_path_value).expanduser()
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterPayloadError("exact registry claim path is malformed") from error
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


def terminal_claim(
    payload: Mapping[str, Any], *, branch: str
) -> RegistrySnapshot | None:
    """Resolve one terminal claim without parsing unrelated broken records.

    Legacy cleanup is deliberately narrower than full inventory: unrelated
    malformed records must not prevent a proven terminal branch from being
    released, while duplicate or malformed records for the target branch still
    fail closed.
    """

    matches: list[RegistrySnapshot] = []
    for raw in payload["records"]:
        if not isinstance(raw, Mapping) or raw.get("branch") != branch:
            continue
        try:
            record = parse_registry_record(raw)
        except (KeyError, TypeError, ValueError, InvalidScope) as error:
            raise AdapterPayloadError("terminal registry claim is malformed") from error
        matches.append(record)
    if len(matches) <= 1:
        return matches[0] if matches else None

    # A branch can legitimately have terminal history from more than one
    # abandoned claim generation.  A published legacy PR still carries one
    # durable hand-back tip, so use that proof to select the record that the
    # caller can validate against the live PR.  If history contains more than
    # one hand-back-bearing claim, or none at all, the evidence remains
    # ambiguous and must stay fail-closed.
    handed_back = [record for record in matches if record.handed_back_sha]
    if len(handed_back) == 1:
        return handed_back[0]
    raise AdapterPayloadError("multiple registry claims found for terminal branch")

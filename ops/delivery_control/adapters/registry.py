from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from worktree_registry_core.lifecycle import (
    TERMINAL_PROOF_SCHEMA,
    terminal_proof_with_digest,
)

from ..domain.errors import CompareAndSwapConflict, InvalidScope
from ..domain.models import MergedPullRequestProof, Scope
from ..domain.observations import (
    InventoryProblem,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
)
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError
from .subprocess_runner import SubprocessCommandRunner
from .timestamps import parse_optional_timestamp

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GREEN = {"pass", "passed", "green", "ok", "success"}
_REGISTRY_STATUSES = {
    "active",
    "cleanup_pending",
    "published",
    "merged",
    "abandoned",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _legacy_seal_valid(record: Mapping[str, Any]) -> bool:
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
    if sorted(seal.get("external_ids") or []) != sorted(
        record.get("external_ids") or []
    ):
        return False
    if seal.get("tip_sha") != record.get("handed_back_sha"):
        return False
    if seal.get("handed_back_at") != record.get("handed_back_at"):
        return False
    if record.get("claim_generation") != record.get("handback_claim_generation"):
        return False
    outcomes = seal.get("outcomes")
    return isinstance(outcomes, list) and not any(
        not isinstance(item, Mapping)
        or str(item.get("status", "")).strip().lower() not in _GREEN
        for item in outcomes
    )


class RegistryCliAdapter:
    def __init__(
        self,
        *,
        script_path: Path,
        state_path: Path | None = None,
        runner: CommandRunnerPort | None = None,
    ) -> None:
        self.script_path = script_path
        self.state_path = state_path
        self.runner = runner or SubprocessCommandRunner()

    def _argv(self, *arguments: str) -> tuple[str, ...]:
        argv = [str(self.script_path), *arguments]
        if self.state_path is not None:
            argv.extend(("--state", str(self.state_path)))
        return tuple(argv)

    def _list_payload(self) -> Mapping[str, Any]:
        result = self.runner.run(self._argv("list", "--json"))
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError("registry list returned invalid JSON") from error
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("records"), list
        ):
            raise AdapterPayloadError("registry list payload is malformed")
        return payload

    @staticmethod
    def _reported_problems(
        payload: Mapping[str, Any],
    ) -> tuple[InventoryProblem, ...]:
        if "problems" not in payload:
            return ()
        raw_problems = payload["problems"]
        if not isinstance(raw_problems, list):
            return (
                InventoryProblem(
                    "registry",
                    "problems",
                    "registry problems field must be a list",
                ),
            )
        problems: list[InventoryProblem] = []
        for index, raw in enumerate(raw_problems):
            identity = raw.get("identity") if isinstance(raw, Mapping) else None
            reason = raw.get("reason") if isinstance(raw, Mapping) else None
            if (
                isinstance(identity, str)
                and identity.strip()
                and isinstance(reason, str)
                and reason.strip()
            ):
                problems.append(
                    InventoryProblem(
                        "registry",
                        identity.strip(),
                        reason.strip(),
                    )
                )
                continue
            kind = raw.get("kind") if isinstance(raw, Mapping) else None
            record_index = raw.get("index") if isinstance(raw, Mapping) else None
            if isinstance(kind, str) and kind.strip():
                problem_identity = (
                    f"record[{record_index}]"
                    if type(record_index) is int and record_index >= 0
                    else f"problem[{index}]"
                )
                detail = kind.strip()
                if isinstance(reason, str) and reason.strip():
                    detail = f"{detail}: {reason.strip()}"
                problems.append(InventoryProblem("registry", problem_identity, detail))
                continue
            problems.append(
                InventoryProblem(
                    "registry",
                    f"problem[{index}]",
                    "registry problem entry is malformed",
                )
            )
        return tuple(problems)

    @staticmethod
    def _record(payload: Mapping[str, Any]) -> RegistrySnapshot:
        branch = str(payload["branch"])
        status = payload.get("status")
        if not isinstance(status, str) or status not in _REGISTRY_STATUSES:
            raise ValueError(f"unsupported registry status: {status!r}")
        path = Path(str(payload["path"])).expanduser()
        if not path.is_absolute():
            raise ValueError("registry path must be absolute")
        scope_payload = payload["scope"]
        if not isinstance(scope_payload, Mapping):
            raise InvalidScope("Scope must be an object")
        scope = Scope.from_payload(scope_payload)
        base_sha = str(payload.get("base_sha") or payload.get("base") or "")
        if not _SHA_RE.fullmatch(base_sha):
            raise ValueError("registry base must be an exact commit SHA")
        external_ids = payload.get("external_ids")
        if not isinstance(external_ids, list):
            external_ids = []
        lane_id = str(external_ids[0]) if external_ids else branch
        handed_back_sha = payload.get("handed_back_sha")
        seal = payload.get("handback_seal")
        handback_digest = seal.get("digest") if isinstance(seal, Mapping) else None
        handback_origin = (
            seal.get("origin_main_sha") if isinstance(seal, Mapping) else None
        )
        claim_generation = payload.get("claim_generation")
        handback_claim_generation = payload.get("handback_claim_generation")
        if type(claim_generation) is not int or claim_generation < 0:
            raise ValueError("registry claim_generation must be a non-negative integer")
        if handback_claim_generation is not None and (
            type(handback_claim_generation) is not int or handback_claim_generation < 0
        ):
            raise ValueError(
                "registry handback_claim_generation must be a non-negative integer"
            )
        return RegistrySnapshot(
            lane_id=lane_id,
            branch=branch,
            path=path.resolve(),
            status=status,
            scope=scope,
            base_sha=base_sha,
            claim_generation=claim_generation,
            owner_thread_id=(
                str(payload["codex_thread_id"])
                if payload.get("codex_thread_id")
                else None
            ),
            handed_back_sha=(str(handed_back_sha) if handed_back_sha else None),
            handback_claim_generation=handback_claim_generation,
            handback_valid=_legacy_seal_valid(payload),
            handback_digest=(
                str(handback_digest)
                if isinstance(handback_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", handback_digest)
                else None
            ),
            handback_origin_main_sha=(
                str(handback_origin)
                if isinstance(handback_origin, str)
                and _SHA_RE.fullmatch(handback_origin)
                else None
            ),
            handed_back_at=parse_optional_timestamp(
                payload.get("handed_back_at"), field="registry handed_back_at"
            ),
        )

    def list_records(self) -> RegistryInventory:
        payload = self._list_payload()
        records: list[RegistrySnapshot] = []
        problems = list(self._reported_problems(payload))
        for index, raw in enumerate(payload["records"]):
            if not isinstance(raw, Mapping):
                problems.append(
                    InventoryProblem(
                        "registry", f"record[{index}]", "record is not an object"
                    )
                )
                continue
            identity = str(raw.get("branch") or raw.get("path") or f"record[{index}]")
            try:
                records.append(self._record(raw))
            except (KeyError, TypeError, ValueError, InvalidScope) as error:
                problems.append(InventoryProblem("registry", identity, str(error)))
        return RegistryInventory(records=tuple(records), problems=tuple(problems))

    @staticmethod
    def _collision_claim(payload: Mapping[str, Any]) -> RegistryCollisionClaim:
        branch = str(payload["branch"])
        if not branch:
            raise ValueError("registry branch must be non-empty")
        scope_payload = payload["scope"]
        if not isinstance(scope_payload, Mapping):
            raise InvalidScope("Scope must be an object")
        external_ids = payload.get("external_ids")
        if not isinstance(external_ids, list):
            external_ids = []
        return RegistryCollisionClaim(
            lane_id=str(external_ids[0]) if external_ids else branch,
            branch=branch,
            scope=Scope.from_payload(scope_payload),
        )

    def list_collision_claims(self) -> RegistryCollisionInventory:
        payload = self._list_payload()
        records: list[RegistryCollisionClaim] = []
        problems = list(self._reported_problems(payload))
        for index, raw in enumerate(payload["records"]):
            if not isinstance(raw, Mapping):
                problems.append(
                    InventoryProblem(
                        "registry", f"record[{index}]", "record is not an object"
                    )
                )
                continue
            identity = str(raw.get("branch") or raw.get("path") or f"record[{index}]")
            status = raw.get("status")
            if status in {"merged", "abandoned", "published"}:
                continue
            if status not in {"active", "cleanup_pending"}:
                problems.append(
                    InventoryProblem(
                        "registry", identity, "registry status is not collision-safe"
                    )
                )
                continue
            try:
                records.append(self._collision_claim(raw))
            except (KeyError, TypeError, ValueError, InvalidScope) as error:
                problems.append(InventoryProblem("registry", identity, str(error)))
        return RegistryCollisionInventory(
            records=tuple(records), problems=tuple(problems)
        )

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        matches = [
            item
            for item in self.list_records().records
            if item.lane_id == lane_id and item.status == "active"
        ]
        if len(matches) > 1:
            raise AdapterPayloadError(
                f"multiple active registry records found for {lane_id}"
            )
        return matches[0] if matches else None

    def find_exact_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        claim_generation: int,
    ) -> RegistrySnapshot | None:
        expected_path = path.expanduser().resolve()
        matches: list[RegistrySnapshot] = []
        for raw in self._list_payload()["records"]:
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
                record = self._record(raw)
            except (KeyError, TypeError, ValueError, InvalidScope) as error:
                raise AdapterPayloadError(
                    "exact registry claim is malformed"
                ) from error
            if record.claim_generation == claim_generation:
                matches.append(record)
        if len(matches) > 1:
            raise AdapterPayloadError("multiple exact registry claims found")
        return matches[0] if matches else None

    def resolve(
        self,
        lane_id: str,
        disposition: str,
        *,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        terminal_proof: MergedPullRequestProof | None = None,
    ) -> None:
        argv = self._argv(
            "resolve",
            "--json",
            "--branch",
            expected_branch,
            "--path",
            expected_path,
            "--status",
            disposition,
            "--expected-generation",
            str(expected_claim_generation),
            "--expected-head-sha",
            expected_head_sha,
        )
        if terminal_proof is not None:
            proof_payload = terminal_proof_with_digest(
                {
                    "schema": TERMINAL_PROOF_SCHEMA,
                    "lane_id": terminal_proof.lane_id,
                    "pr_number": terminal_proof.pr_number,
                    "pr_state": terminal_proof.pr_state,
                    "base_branch": terminal_proof.base_branch,
                    "branch": terminal_proof.branch,
                    "head_sha": terminal_proof.head_sha,
                }
            )
            argv = (
                *argv,
                "--terminal-proof",
                json.dumps(proof_payload, sort_keys=True),
            )
        result = self.runner.run(argv)
        if result.exit_code != 0:
            raise CompareAndSwapConflict(
                f"registry transition failed for {lane_id}: {result.stderr or result.stdout}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError(
                "registry resolve returned invalid JSON"
            ) from error
        if (
            not isinstance(payload, Mapping)
            or payload.get("status") != disposition
            or not isinstance(payload.get("records"), list)
            or len(payload["records"]) != 1
        ):
            raise AdapterPayloadError("registry resolve readback is not exact")

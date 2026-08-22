from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..domain.models import MergedPullRequestProof
from ..domain.observations import (
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
)
from ..ports.process import CommandRunnerPort
from .registry_command import resolve_registry
from .registry_parsing import (
    parse_collision_claim,
    parse_registry_record,
    reported_problems,
)
from .registry_query import (
    active_record,
    collision_inventory,
    exact_claim,
    load_registry_list,
    registry_inventory,
)
from .subprocess_runner import SubprocessCommandRunner


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
        return load_registry_list(self.runner, self._argv("list", "--json"))

    _reported_problems = staticmethod(reported_problems)
    _record = staticmethod(parse_registry_record)
    _collision_claim = staticmethod(parse_collision_claim)

    def list_records(self) -> RegistryInventory:
        return registry_inventory(self._list_payload())

    def list_collision_claims(self) -> RegistryCollisionInventory:
        return collision_inventory(self._list_payload())

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return active_record(self.list_records(), lane_id)

    def find_exact_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        claim_generation: int,
    ) -> RegistrySnapshot | None:
        return exact_claim(
            self._list_payload(),
            lane_id=lane_id,
            branch=branch,
            path=path,
            claim_generation=claim_generation,
        )

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
        resolve_registry(
            runner=self.runner,
            argv=self._argv(
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
            ),
            lane_id=lane_id,
            disposition=disposition,
            terminal_proof=terminal_proof,
        )

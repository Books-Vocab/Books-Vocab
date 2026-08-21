from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.domain.observations import (
    InventoryProblem,
)
from delivery_control.ports.process import CommandResult


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)


def test_registry_adapter_targets_explicit_state_file(tmp_path: Path) -> None:
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": []}), "")]
    )
    state_path = tmp_path / "registry.json"

    RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"),
        state_path=state_path,
        runner=runner,
    ).list_records()

    assert runner.calls == [
        (
            "/repo/ops/worktree_registry.py",
            "list",
            "--json",
            "--state",
            str(state_path),
        )
    ]


def test_registry_adapter_surfaces_malformed_records_without_hiding_valid_ones(
    tmp_path: Path,
) -> None:
    valid = {
        "branch": "feat/one",
        "path": str(tmp_path / "one"),
        "status": "active",
        "external_ids": ["#1"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-1",
        "claim_generation": 4,
    }
    malformed = {"branch": "feat/bad", "path": "relative", "status": "active"}
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "list"),
                exit_code=0,
                stdout=json.dumps({"records": [valid, malformed]}),
                stderr="",
            )
        ]
    )
    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert [record.lane_id for record in inventory.records] == ["#1"]
    assert inventory.records[0].claim_generation == 4
    assert inventory.problems[0].identity == "feat/bad"


def test_registry_adapter_fails_closed_on_unusable_terminal_history(
    tmp_path: Path,
) -> None:
    terminal = {
        "branch": "feat/old",
        "path": str(tmp_path / "old"),
        "status": "merged",
    }
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [terminal]}), "")]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert inventory.records == ()
    assert inventory.problems == (InventoryProblem("registry", "feat/old", "'scope'"),)


def test_collision_inventory_uses_scope_from_active_legacy_record(
    tmp_path: Path,
) -> None:
    legacy_active = {
        "branch": "feat/legacy-active",
        "path": str(tmp_path / "legacy-active"),
        "status": "active",
        "external_ids": ["#legacy"],
        "base": "origin/main",
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/legacy.py"}],
        },
        "claim_generation": None,
    }
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [legacy_active]}), "")]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    assert inventory.problems == ()
    assert inventory.records[0].lane_id == "#legacy"
    assert inventory.records[0].scope.paths == ("ops/legacy.py",)


def test_collision_inventory_blocks_active_record_with_unusable_scope(
    tmp_path: Path,
) -> None:
    active = {
        "branch": "feat/unknown-scope",
        "path": str(tmp_path / "unknown-scope"),
        "status": "active",
        "scope": "not-structured",
    }
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [active]}), "")]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    assert inventory.records == ()
    assert inventory.problems == (
        InventoryProblem("registry", "feat/unknown-scope", "Scope must be an object"),
    )


def test_collision_inventory_ignores_malformed_terminal_history(
    tmp_path: Path,
) -> None:
    terminal = {
        "branch": "feat/old",
        "path": str(tmp_path / "old"),
        "status": "merged",
    }
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [terminal]}), "")]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    assert inventory.records == ()
    assert inventory.problems == ()


def test_exact_claim_query_ignores_unrelated_malformed_history(
    tmp_path: Path,
) -> None:
    exact = {
        "branch": "feat/exact",
        "path": str(tmp_path / "exact"),
        "status": "cleanup_pending",
        "external_ids": ["#exact"],
        "base_sha": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-exact",
        "claim_generation": 7,
    }
    unrelated = {"branch": "feat/old", "status": "merged"}
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps({"records": [unrelated, exact]}),
                "",
            )
        ]
    )

    record = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).find_exact_claim(
        lane_id="#exact",
        branch="feat/exact",
        path=tmp_path / "exact",
        claim_generation=7,
    )

    assert record is not None
    assert record.status == "cleanup_pending"
    assert record.claim_generation == 7


def test_registry_adapter_exposes_exact_legacy_handback_transport_fields(
    tmp_path: Path,
) -> None:
    seal = {
        "schema": "kg.worktree.handback.v1",
        "branch": "feat/one",
        "path": str(tmp_path / "one"),
        "external_ids": ["#1"],
        "owner_thread_id": "thread-1",
        "tip_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "origin_main_sha": "a" * 40,
        "outcomes": [{"status": "passed"}],
    }
    seal["digest"] = hashlib.sha256(
        json.dumps(
            seal, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    payload = {
        "branch": "feat/one",
        "path": str(tmp_path / "one"),
        "status": "active",
        "external_ids": ["#1"],
        "base_sha": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-1",
        "claim_generation": 4,
        "handback_claim_generation": 4,
        "handed_back_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "handback_seal": seal,
    }

    record = RegistryCliAdapter._record(payload)

    assert record.handback_valid
    assert record.handback_digest == seal["digest"]
    assert record.handback_origin_main_sha == "a" * 40


def test_registry_get_ignores_terminal_history_for_same_lane(tmp_path: Path) -> None:
    active = {
        "branch": "feat/current",
        "path": str(tmp_path / "current"),
        "status": "active",
        "external_ids": ["#1"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-current",
        "claim_generation": 2,
    }
    terminal = {
        **active,
        "branch": "feat/historical",
        "path": str(tmp_path / "historical"),
        "status": "merged",
        "codex_thread_id": "thread-historical",
        "claim_generation": 1,
    }
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",), 0, json.dumps({"records": [terminal, active]}), ""
            )
        ]
    )

    record = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).get("#1")

    assert record is not None
    assert record.branch == "feat/current"

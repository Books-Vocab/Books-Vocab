from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.errors import AdapterPayloadError  # noqa: E402
from delivery_control.adapters.registry import RegistryCliAdapter  # noqa: E402
from delivery_control.domain.models import MergedPullRequestProof  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    InventoryProblem,
)
from delivery_control.ports.process import CommandResult  # noqa: E402


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)


def test_registry_adapter_attaches_typed_terminal_proof_for_merged() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps({"status": "merged", "records": [{}]}),
                "",
            )
        ]
    )
    adapter = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    )

    adapter.resolve(
        "ISSUE-1",
        "merged",
        expected_claim_generation=3,
        expected_branch="feat/one",
        expected_path="/repo/one",
        expected_head_sha="b" * 40,
        terminal_proof=MergedPullRequestProof(
            lane_id="ISSUE-1",
            pr_number=42,
            branch="feat/one",
            head_sha="b" * 40,
        ),
    )

    argv = runner.calls[0]
    proof = json.loads(argv[argv.index("--terminal-proof") + 1])
    assert proof["schema"] == "kg.worktree.terminal-proof.v1"
    assert proof["pr_number"] == 42
    assert proof["base_branch"] == "main"
    assert len(proof["digest"]) == 64


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


def test_registry_adapter_records_published_base_with_exact_cas_arguments(
    tmp_path: Path,
) -> None:
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "record-published-base"),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "status": "published-base-recorded",
                        "records": [{"published_base_sha": "d" * 40}],
                    }
                ),
                stderr="",
            )
        ]
    )
    adapter = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"),
        state_path=tmp_path / "registry.json",
        runner=runner,
    )

    adapter.record_published_base(
        lane_id="DIRECT-1",
        expected_claim_generation=3,
        expected_branch="feat/one",
        expected_path="/repo/one",
        expected_head_sha="b" * 40,
        expected_handback_base_sha="a" * 40,
        published_base_sha="d" * 40,
    )

    assert runner.calls == [
        (
            "/repo/ops/worktree_registry.py",
            "record-published-base",
            "--json",
            "--lane",
            "DIRECT-1",
            "--branch",
            "feat/one",
            "--path",
            "/repo/one",
            "--expected-generation",
            "3",
            "--expected-head-sha",
            "b" * 40,
            "--expected-handback-base-sha",
            "a" * 40,
            "--published-base-sha",
            "d" * 40,
            "--state",
            str(tmp_path / "registry.json"),
        )
    ]


def test_registry_adapter_records_discard_proof_with_exact_cas_arguments(
    tmp_path: Path,
) -> None:
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "discard"),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "action": "discard",
                        "status": "abandoned",
                        "records": [{"discard_proof": {"schema": "discard"}}],
                    }
                ),
                stderr="",
            )
        ]
    )
    adapter = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"),
        state_path=tmp_path / "registry.json",
        runner=runner,
    )

    adapter.discard(
        lane_id="DIRECT-1",
        expected_claim_generation=3,
        expected_branch="feat/orphan",
        expected_path="/repo/orphan",
        expected_head_sha="b" * 40,
        operator="supervisor",
        reason="ownerless clean handback explicitly discarded",
    )

    assert runner.calls == [
        (
            "/repo/ops/worktree_registry.py",
            "discard",
            "--json",
            "--branch",
            "feat/orphan",
            "--path",
            "/repo/orphan",
            "--expected-generation",
            "3",
            "--expected-head-sha",
            "b" * 40,
            "--operator",
            "supervisor",
            "--reason",
            "ownerless clean handback explicitly discarded",
            "--state",
            str(tmp_path / "registry.json"),
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
    assert inventory.records[0].external_ids == ("#1",)
    assert inventory.problems[0].identity == "feat/bad"
    assert inventory.problems[0].record_status == "active"


@pytest.mark.parametrize("owner_thread_id", [None, "owner-thread"])
def test_registry_adapter_preserves_malformed_active_owner_observation(
    tmp_path: Path, owner_thread_id: str | None
) -> None:
    branch = "debug/malformed-owner"
    path = tmp_path / "malformed-owner"
    record = {
        "branch": branch,
        "path": str(path),
        "status": "active",
        "external_ids": ["DIRECT-1"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": owner_thread_id,
        "claim_generation": None,
    }
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "list"),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "records": [record],
                        "problems": [
                            {
                                "kind": "registry-claim-generation-invalid",
                                "index": 0,
                                "branch": branch,
                                "status": "active",
                                "reason": "claim_generation must be a non-negative integer",
                            }
                        ],
                    }
                ),
                stderr="",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    # The low-level registry report and the delivery parser observe the same
    # malformed claim.  The adapter must preserve that fact once, rather than
    # counting the parser's equivalent exception as a second problem.
    assert len(inventory.problems) == 1
    assert {problem.identity for problem in inventory.problems} == {branch}
    assert all(problem.record_status == "active" for problem in inventory.problems)
    assert all(problem.record_path == path.resolve() for problem in inventory.problems)
    assert {problem.owner_thread_id for problem in inventory.problems} == {
        owner_thread_id
    }


def test_registry_adapter_keeps_distinct_reported_facts_for_one_record(
    tmp_path: Path,
) -> None:
    branch = "debug/malformed-multiple-facts"
    record = {
        "branch": branch,
        "path": str(tmp_path / "malformed-multiple-facts"),
        "status": "active",
        "external_ids": ["DIRECT-MULTIPLE-FACTS"],
        "base": "not-a-commit-sha",
        "claim_generation": 0,
    }
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "list"),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "records": [record],
                        "problems": [
                            {
                                "kind": "registry-record-missing-field",
                                "index": 0,
                                "branch": branch,
                                "status": "active",
                                "reason": "registry record is missing required field: scope",
                            },
                            {
                                "kind": "registry-base-invalid",
                                "index": 0,
                                "branch": branch,
                                "status": "active",
                                "reason": "registry base must be an exact commit SHA",
                            },
                        ],
                    }
                ),
                stderr="",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert len(inventory.problems) == 2
    assert {problem.reason for problem in inventory.problems} == {
        "registry-record-missing-field: registry record is missing required field: scope",
        "registry-base-invalid: registry base must be an exact commit SHA",
    }


def test_registry_adapter_surfaces_reported_problems_and_unknown_statuses(
    tmp_path: Path,
) -> None:
    unknown = {
        "branch": "feat/unknown",
        "path": str(tmp_path / "unknown"),
        "status": "legacy-migrating",
        "external_ids": ["#unknown"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "claim_generation": 1,
    }
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps(
                    {
                        "records": [unknown],
                        "problems": [
                            {
                                "kind": "registry-record-not-object",
                                "index": 0,
                            }
                        ],
                    }
                ),
                "",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert inventory.records == ()
    assert inventory.problems == (
        InventoryProblem(
            "registry",
            "record[0]",
            "registry-record-not-object",
            identity_kind="record",
        ),
        InventoryProblem(
            "registry",
            "feat/unknown",
            "unsupported registry status: 'legacy-migrating'",
            identity_kind="branch",
            record_status="legacy-migrating",
        ),
    )


@pytest.mark.parametrize("status", ["merged", "active"])
def test_registry_adapter_preserves_reported_record_identity_and_status(
    status: str,
) -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps(
                    {
                        "records": [],
                        "problems": [
                            {
                                "kind": "registry-claim-generation-invalid",
                                "index": 36,
                                "branch": "feat/terminal-history",
                                "status": status,
                                "reason": "claim_generation must be a non-negative integer",
                            }
                        ],
                    }
                ),
                "",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert inventory.problems == (
        InventoryProblem(
            "registry",
            "feat/terminal-history",
            "registry-claim-generation-invalid: claim_generation must be a non-negative integer",
            identity_kind="branch",
            record_status=status,
        ),
    )


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
    assert inventory.problems == (
        InventoryProblem(
            "registry",
            "feat/old",
            "registry record is missing required field: scope",
            identity_kind="branch",
            record_status="merged",
        ),
    )


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


def test_collision_inventory_normalizes_missing_scope_diagnostic(
    tmp_path: Path,
) -> None:
    malformed = {
        "branch": "feat/malformed",
        "path": str(tmp_path / "malformed"),
        "status": "active",
    }
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps({"records": [malformed]}),
                "",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    assert inventory.records == ()
    assert inventory.problems == (
        InventoryProblem(
            "registry",
            "feat/malformed",
            "registry record is missing required field: scope",
            identity_kind="branch",
        ),
    )


def _legacy_terminal_with_exact_seal_base(tmp_path: Path) -> dict[str, object]:
    branch = "feat/legacy-terminal"
    path = tmp_path / "legacy-terminal"
    base_sha = "a" * 40
    seal: dict[str, object] = {
        "schema": "kg.worktree.handback.v1",
        "branch": branch,
        "path": str(path),
        "external_ids": [],
        "base_sha": base_sha,
        "tip_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "origin_main_sha": base_sha,
        "outcomes": [{"status": "passed"}],
    }
    seal["digest"] = hashlib.sha256(
        json.dumps(
            seal, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "branch": branch,
        "path": str(path),
        "status": "abandoned",
        "external_ids": [],
        "base": "origin/main",
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/legacy.py"}],
        },
        "codex_thread_id": None,
        "claim_generation": 0,
        "handback_claim_generation": 0,
        "handed_back_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "handback_seal": seal,
    }


def test_terminal_claim_uses_exact_base_from_valid_legacy_handback(
    tmp_path: Path,
) -> None:
    terminal = _legacy_terminal_with_exact_seal_base(tmp_path)
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [terminal]}), "")]
    )

    record = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).find_terminal_claim(branch="feat/legacy-terminal")

    assert record is not None
    assert record.base_sha == "a" * 40
    assert record.handback_valid


def test_active_claim_does_not_fallback_from_legacy_base_alias(
    tmp_path: Path,
) -> None:
    terminal = _legacy_terminal_with_exact_seal_base(tmp_path)
    terminal["status"] = "active"
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [terminal]}), "")]
    )

    with pytest.raises(
        AdapterPayloadError, match="terminal registry claim is malformed"
    ):
        RegistryCliAdapter(
            script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
        ).find_terminal_claim(branch="feat/legacy-terminal")


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
        InventoryProblem(
            "registry",
            "feat/unknown-scope",
            "Scope must be an object",
            identity_kind="branch",
        ),
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


@pytest.mark.parametrize(
    ("status", "collision_problem_expected"),
    [
        ("merged", False),
        ("abandoned", False),
        ("published", False),
        ("active", True),
        ("cleanup_pending", True),
    ],
)
def test_collision_inventory_projects_reported_claim_status(
    status: str, collision_problem_expected: bool
) -> None:
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps(
                    {
                        "records": [],
                        "problems": [
                            {
                                "kind": "registry-claim-generation-invalid",
                                "index": 36,
                                "branch": "feat/malformed-claim",
                                "status": status,
                                "reason": "claim_generation must be a non-negative integer",
                            }
                        ],
                    }
                ),
                "",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    if collision_problem_expected:
        assert inventory.problems == (
            InventoryProblem(
                "registry",
                "feat/malformed-claim",
                "registry-claim-generation-invalid: claim_generation must be a non-negative integer",
                identity_kind="branch",
                record_status=status,
            ),
        )
    else:
        assert inventory.problems == ()


def test_collision_inventory_scopes_claim_generation_problem_to_valid_claim(
    tmp_path: Path,
) -> None:
    active = {
        "branch": "feat/malformed-active-claim",
        "path": str(tmp_path / "malformed-active-claim"),
        "status": "active",
        "external_ids": ["#1187"],
        "base": "a" * 40,
        "claim_generation": None,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/occupied.py"}],
        },
    }
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps(
                    {
                        "records": [active],
                        "problems": [
                            {
                                "kind": "registry-claim-generation-invalid",
                                "index": 0,
                                "branch": active["branch"],
                                "status": "active",
                                "reason": "claim_generation must be a non-negative integer",
                            }
                        ],
                    }
                ),
                "",
            )
        ]
    )

    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_collision_claims()

    assert inventory.problems == ()
    assert inventory.records[0].branch == active["branch"]
    assert inventory.records[0].scope.paths == ("ops/occupied.py",)


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


def test_exact_claim_query_rejects_malformed_target_but_ignores_unrelated_history(
    tmp_path: Path,
) -> None:
    unrelated = {"branch": "feat/old", "status": "merged"}
    malformed_target = {
        "branch": "feat/exact",
        "path": "relative/exact",
        "status": "cleanup_pending",
        "external_ids": ["#exact"],
        "claim_generation": 7,
    }
    runner = StaticRunner(
        [
            CommandResult(
                ("registry",),
                0,
                json.dumps({"records": [unrelated, malformed_target]}),
                "",
            )
        ]
    )

    with pytest.raises(
        AdapterPayloadError, match="exact registry claim path is malformed"
    ):
        RegistryCliAdapter(
            script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
        ).find_exact_claim(
            lane_id="#exact",
            branch="feat/exact",
            path=tmp_path / "exact",
            claim_generation=7,
        )


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
    assert record.handed_back_at is not None
    assert record.handed_back_at.isoformat() == "2026-08-21T00:00:00+00:00"
    assert record.handback_initial_holds == ()


def _payload_with_initial_holds(
    tmp_path: Path, initial_holds: object, *, valid_digest: bool = True
) -> dict[str, object]:
    seal: dict[str, object] = {
        "schema": "kg.worktree.handback.v1",
        "branch": "feat/holds",
        "path": str(tmp_path / "holds"),
        "external_ids": ["#holds"],
        "owner_thread_id": "thread-holds",
        "tip_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "origin_main_sha": "a" * 40,
        "outcomes": [{"status": "success"}],
        "initial_holds": initial_holds,
    }
    seal["digest"] = hashlib.sha256(
        json.dumps(
            seal, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if not valid_digest:
        seal["digest"] = "0" * 64
    return {
        "branch": "feat/holds",
        "path": str(tmp_path / "holds"),
        "status": "active",
        "external_ids": ["#holds"],
        "base_sha": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-holds",
        "claim_generation": 4,
        "handback_claim_generation": 4,
        "handed_back_sha": "b" * 40,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "handback_seal": seal,
    }


def test_registry_adapter_parses_supported_initial_holds_from_valid_seal(
    tmp_path: Path,
) -> None:
    record = RegistryCliAdapter._record(
        _payload_with_initial_holds(tmp_path, ["security", "p0"])
    )

    assert record.handback_valid
    assert record.handback_initial_holds == ("p0", "security")


@pytest.mark.parametrize(
    "initial_holds",
    (
        "security",
        ["p0", "p0"],
        ["urgent"],
        [1],
    ),
)
def test_registry_adapter_rejects_malformed_initial_holds_on_valid_seal(
    tmp_path: Path, initial_holds: object
) -> None:
    with pytest.raises(ValueError, match="initial_holds"):
        RegistryCliAdapter._record(_payload_with_initial_holds(tmp_path, initial_holds))


def test_registry_adapter_ignores_initial_holds_from_invalid_seal(
    tmp_path: Path,
) -> None:
    record = RegistryCliAdapter._record(
        _payload_with_initial_holds(tmp_path, "security", valid_digest=False)
    )

    assert not record.handback_valid
    assert record.handback_initial_holds == ()


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

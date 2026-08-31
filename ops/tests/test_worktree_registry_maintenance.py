from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry
from worktree_registry_core.records import (
    mutation_blockers,
    mutation_blockers_for_target,
    superseded_proof_problem,
)


def _git(worktree: Path, *args: str) -> str:
    return_code, output = registry._git(list(args), worktree)
    assert return_code == 0, output
    return output


def _reanchor_record(tmp_path: Path) -> tuple[dict[str, object], str, str, str]:
    worktree = tmp_path / "published-base-reanchor"
    worktree.mkdir()
    _git(worktree, "init", "--quiet", "-b", "main")
    _git(worktree, "config", "user.email", "test@example.com")
    _git(worktree, "config", "user.name", "Test User")

    (worktree / "base.txt").write_text("old\n", encoding="utf-8")
    _git(worktree, "add", "base.txt")
    _git(worktree, "commit", "--quiet", "-m", "old published base")
    previous_published_base = _git(worktree, "rev-parse", "HEAD")

    (worktree / "main.txt").write_text("new live main\n", encoding="utf-8")
    _git(worktree, "add", "main.txt")
    _git(worktree, "commit", "--quiet", "-m", "new live main")
    live_main = _git(worktree, "rev-parse", "HEAD")

    (worktree / "worker.txt").write_text("owner change\n", encoding="utf-8")
    _git(worktree, "add", "worker.txt")
    _git(worktree, "commit", "--quiet", "-m", "owner handback")
    handback_head = _git(worktree, "rev-parse", "HEAD")

    record: dict[str, object] = {
        "branch": "debug/published-base-reanchor",
        "path": str(worktree),
        "intent": "record reanchored published PR target",
        "base": live_main,
        "base_sha": live_main,
        "status": "active",
        "external_ids": ["DIRECT-PUBLISHED-BASE-REANCHOR"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [
                {
                    "path": "ops/worktree_registry_core/published_base.py",
                    "operation": "modify",
                },
                {
                    "path": "ops/tests/test_worktree_registry_maintenance.py",
                    "operation": "modify",
                },
            ],
        },
        "codex_thread_id": "owner-thread",
        "delegated": True,
        "claim_generation": 2,
        "handed_back_at": "2026-09-01T00:00:00Z",
        "handed_back_sha": handback_head,
        "handback_claim_generation": 2,
        "published_base_sha": previous_published_base,
    }
    record["handback_seal"] = registry._seal_with_digest(
        registry._seal_body(
            record,
            base_sha=live_main,
            tip_sha=handback_head,
            outcomes=[{"name": "focused", "status": "success"}],
            handed_back_at="2026-09-01T00:00:00Z",
            origin_main_sha=live_main,
        )
    )
    return record, previous_published_base, live_main, handback_head


def _record_published_base_argv(
    state: Path,
    record: dict[str, object],
    *,
    expected_head: str,
    handback_base: str,
    published_base: str,
) -> list[str]:
    return [
        "record-published-base",
        "--state",
        str(state),
        "--lane",
        "DIRECT-PUBLISHED-BASE-REANCHOR",
        "--branch",
        str(record["branch"]),
        "--path",
        str(record["path"]),
        "--expected-generation",
        "2",
        "--expected-head-sha",
        expected_head,
        "--expected-handback-base-sha",
        handback_base,
        "--published-base-sha",
        published_base,
        "--at",
        "2026-09-01T00:01:00Z",
        "--json",
    ]


def test_record_published_base_allows_exact_reanchor_advance_and_is_deterministic(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    record, previous, live_main, handback_head = _reanchor_record(tmp_path)
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    argv = _record_published_base_argv(
        state_path,
        record,
        expected_head=handback_head,
        handback_base=live_main,
        published_base=live_main,
    )

    assert registry.main(argv) == registry.EXIT_OK
    first = registry.load_state(state_path)["records"][0]
    assert first["base_sha"] == live_main
    assert first["published_base_sha"] == live_main
    assert first["handback_seal"] == record["handback_seal"]
    assert first["published_base_recorded_at"] == "2026-09-01T00:01:00Z"
    assert previous != live_main

    assert registry.main(argv) == registry.EXIT_OK
    second = registry.load_state(state_path)["records"][0]
    assert second == first


@pytest.mark.parametrize("status", ["active", "published", "cleanup_pending"])
def test_record_published_base_allows_live_descendant_of_handback_and_recorded_base(
    tmp_path: Path, status: str
) -> None:
    state_path = tmp_path / "registry.json"
    record, previous, handback_base, handback_head = _reanchor_record(tmp_path)
    worktree = Path(str(record["path"]))
    (worktree / "current-main.txt").write_text("current live main\n", encoding="utf-8")
    _git(worktree, "add", "current-main.txt")
    _git(worktree, "commit", "--quiet", "-m", "current live main")
    current_live_main = _git(worktree, "rev-parse", "HEAD")
    record["status"] = status
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    assert (
        _git(worktree, "merge-base", "--is-ancestor", previous, current_live_main) == ""
    )
    assert (
        _git(
            worktree,
            "merge-base",
            "--is-ancestor",
            handback_base,
            current_live_main,
        )
        == ""
    )

    argv = _record_published_base_argv(
        state_path,
        record,
        expected_head=handback_head,
        handback_base=handback_base,
        published_base=current_live_main,
    )
    assert registry.main(argv) == registry.EXIT_OK
    updated = registry.load_state(state_path)["records"][0]
    assert updated["status"] == status
    assert updated["base_sha"] == handback_base
    assert updated["published_base_sha"] == current_live_main
    assert updated["handback_seal"] == record["handback_seal"]


def test_record_published_base_rejects_reanchor_with_stale_pr_base(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    record, previous, live_main, handback_head = _reanchor_record(tmp_path)
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    original = state_path.read_text(encoding="utf-8")

    assert (
        registry.main(
            _record_published_base_argv(
                state_path,
                record,
                expected_head=handback_head,
                handback_base=live_main,
                published_base=previous,
            )
        )
        == registry.EXIT_CLAIMED
    )
    assert state_path.read_text(encoding="utf-8") == original


def test_record_published_base_rejects_non_ancestor_reanchor_base(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    record, _previous, live_main, handback_head = _reanchor_record(tmp_path)
    worktree = Path(str(record["path"]))
    _git(worktree, "switch", "--quiet", "--orphan", "unrelated")
    _git(worktree, "commit", "--quiet", "--allow-empty", "-m", "unrelated base")
    unrelated_base = _git(worktree, "rev-parse", "HEAD")
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    original = state_path.read_text(encoding="utf-8")

    assert (
        registry.main(
            _record_published_base_argv(
                state_path,
                record,
                expected_head=handback_head,
                handback_base=live_main,
                published_base=unrelated_base,
            )
        )
        == registry.EXIT_CLAIMED
    )
    assert state_path.read_text(encoding="utf-8") == original


def test_record_published_base_requires_live_main_handback_evidence(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    record, previous, live_main, handback_head = _reanchor_record(tmp_path)
    seal = dict(record["handback_seal"])
    seal.pop("digest")
    seal["origin_main_sha"] = previous
    record["handback_seal"] = registry._seal_with_digest(seal)
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})
    original = state_path.read_text(encoding="utf-8")

    assert (
        registry.main(
            _record_published_base_argv(
                state_path,
                record,
                expected_head=handback_head,
                handback_base=live_main,
                published_base=live_main,
            )
        )
        == registry.EXIT_CLAIMED
    )
    assert state_path.read_text(encoding="utf-8") == original


def _terminal_proof(record: dict) -> dict:
    return registry.terminal_proof_with_digest(
        {
            "schema": registry.TERMINAL_PROOF_SCHEMA,
            "lane_id": record["external_ids"][0],
            "pr_number": 42,
            "pr_state": "MERGED",
            "base_branch": "main",
            "branch": record["branch"],
            "head_sha": record["handed_back_sha"],
        }
    )


def test_load_state_surfaces_lossy_legacy_migration(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    "not-an-object",
                    {
                        "branch": "feat/bad-ids",
                        "path": str(tmp_path / "bad-ids"),
                        "status": "active",
                        "external_ids": {"bad": True},
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    state = registry.load_state(state_path)

    assert state["records"][0] == "not-an-object"
    assert state["records"][1]["external_ids"] == {"bad": True}
    assert [problem["kind"] for problem in state["problems"]] == [
        "registry-record-not-object",
        "registry-external-ids-invalid",
    ]


def test_load_state_preserves_malformed_legacy_backlog(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-backlog",
                        "path": str(tmp_path / "bad-backlog"),
                        "status": "active",
                        "backlog": {"bad": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    state = registry.load_state(state_path)

    assert state["records"][0]["backlog"] == {"bad": True}
    assert "external_ids" not in state["records"][0]
    assert state["problems"][0]["kind"] == "registry-external-ids-invalid"


def test_list_surfaces_malformed_facts_without_crashing_or_rewriting(
    tmp_path: Path, capsys
) -> None:
    state_path = tmp_path / "registry.json"
    original = (
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-ids",
                        "path": str(tmp_path / "bad-ids"),
                        "status": "active",
                        "external_ids": {"bad": True},
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    state_path.write_text(original, encoding="utf-8")

    rc = registry.main(["list", "--state", str(state_path), "--json"])

    assert rc == registry.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"][0]["external_ids"] == []
    assert payload["problems"][0]["kind"] == "registry-external-ids-invalid"
    assert state_path.read_text(encoding="utf-8") == original


def test_malformed_ownership_facts_block_mutation_without_data_loss(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    original = (
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-ids",
                        "path": str(tmp_path / "bad-ids"),
                        "status": "active",
                        "external_ids": {"bad": True},
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    state_path.write_text(original, encoding="utf-8")

    rc = registry.main(
        [
            "register",
            "--state",
            str(state_path),
            "--branch",
            "feat/bad-ids",
            "--path",
            str(tmp_path / "bad-ids"),
            "--intent",
            "repair",
            "--external-id",
            "ISSUE-BAD-IDS",
            "--json",
        ]
    )

    assert rc == registry.EXIT_CLAIMED
    assert state_path.read_text(encoding="utf-8") == original
    reloaded = registry.load_state(state_path)
    assert reloaded["records"][0]["external_ids"] == {"bad": True}
    assert reloaded["problems"][0]["kind"] == "registry-external-ids-invalid"


def test_disjoint_register_is_not_blocked_by_malformed_active_claim(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-claim",
                        "path": str(tmp_path / "bad-claim"),
                        "status": "active",
                        "external_ids": ["ISSUE-BAD"],
                        "claim_generation": None,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [
                                {"path": "ops/bad_claim.py", "operation": "modify"}
                            ],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = registry.main(
        [
            "register",
            "--state",
            str(state_path),
            "--branch",
            "feat/disjoint",
            "--path",
            str(tmp_path / "disjoint"),
            "--intent",
            "new",
            "--base",
            "b" * 40,
            "--external-id",
            "ISSUE-DISJOINT",
            "--scope",
            json.dumps(
                {
                    "schema": "kg.worktree.scope.v1",
                    "files": [{"path": "ops/disjoint.py", "operation": "modify"}],
                }
            ),
            "--json",
        ]
    )

    assert rc == registry.EXIT_OK
    state = registry.load_state(state_path)
    assert len(state["records"]) == 2
    assert state["records"][1]["branch"] == "feat/disjoint"
    assert len(state["problems"]) == 1


def test_target_scoped_blocker_preserves_exact_malformed_claim_boundary(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-claim",
                        "path": str(tmp_path / "bad-claim"),
                        "status": "active",
                        "external_ids": ["ISSUE-BAD"],
                        "claim_generation": None,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [
                                {"path": "ops/bad_claim.py", "operation": "modify"}
                            ],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = registry.load_state(state_path)
    problem = state["problems"][0]

    assert mutation_blockers(state) == [problem]
    assert (
        mutation_blockers_for_target(
            state,
            branch="feat/disjoint",
            path=str(tmp_path / "disjoint"),
            external_ids_value=["ISSUE-DISJOINT"],
            scope={
                "schema": "kg.worktree.scope.v1",
                "files": [{"path": "ops/disjoint.py", "operation": "modify"}],
            },
        )
        == []
    )
    assert mutation_blockers_for_target(
        state,
        branch="feat/bad-claim",
        path=str(tmp_path / "other-path"),
        external_ids_value=["ISSUE-DISJOINT"],
        scope={
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/disjoint.py", "operation": "modify"}],
        },
    ) == [problem]


def test_scope_set_on_malformed_claim_remains_fail_closed_without_repair(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    original = {
        "records": [
            {
                "branch": "feat/bad-claim",
                "path": str(tmp_path / "bad-claim"),
                "status": "active",
                "external_ids": ["ISSUE-BAD"],
                "claim_generation": None,
                "scope": {
                    "schema": "kg.worktree.scope.v1",
                    "files": [{"path": "ops/bad_claim.py", "operation": "modify"}],
                },
            }
        ]
    }
    state_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    rc = registry.main(
        [
            "scope-set",
            "--state",
            str(state_path),
            "--branch",
            "feat/bad-claim",
            "--scope",
            json.dumps(
                {
                    "schema": "kg.worktree.scope.v1",
                    "files": [{"path": "ops/other.py", "operation": "modify"}],
                }
            ),
            "--json",
        ]
    )

    assert rc == registry.EXIT_CLAIMED
    assert (
        state_path.read_text(encoding="utf-8") == json.dumps(original, indent=2) + "\n"
    )


@pytest.mark.parametrize("claim_generation", [None, -1, True, 1.5, "1"])
def test_invalid_claim_generation_is_visible_and_blocks_only_matching_mutation(
    tmp_path: Path, capsys, claim_generation: object
) -> None:
    state_path = tmp_path / "registry.json"
    original = (
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/bad-claim-generation",
                        "path": str(tmp_path / "bad-claim-generation"),
                        "status": "active",
                        "external_ids": ["ISSUE-BAD-CLAIM"],
                        "claim_generation": claim_generation,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    state_path.write_text(original, encoding="utf-8")

    state = registry.load_state(state_path)

    problem = {
        "kind": "registry-claim-generation-invalid",
        "index": 0,
        "branch": "feat/bad-claim-generation",
        "status": "active",
        "reason": "claim_generation must be a non-negative integer",
    }
    assert state["records"][0]["claim_generation"] == claim_generation
    assert state["problems"] == [problem]
    assert mutation_blockers(state) == [problem]

    rc = registry.main(
        [
            "list",
            "--state",
            str(state_path),
            "--active-only",
            "--json",
        ]
    )

    assert rc == registry.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"][0]["claim_generation"] == claim_generation
    assert payload["problems"] == [problem]

    register_rc = registry.main(
        [
            "register",
            "--state",
            str(state_path),
            "--branch",
            "feat/new-while-claim-invalid",
            "--path",
            str(tmp_path / "new-while-claim-invalid"),
            "--intent",
            "new",
            "--base",
            "b" * 40,
            "--external-id",
            "ISSUE-NEW-WHILE-CLAIM-INVALID",
            "--scope",
            json.dumps(
                {
                    "schema": "kg.worktree.scope.v1",
                    "files": [{"operation": "modify", "path": "ops/b.py"}],
                }
            ),
            "--json",
        ]
    )

    assert register_rc == registry.EXIT_OK
    updated = registry.load_state(state_path)
    assert updated["records"][0]["claim_generation"] == claim_generation
    assert updated["records"][1]["branch"] == "feat/new-while-claim-invalid"
    assert updated["problems"] == [problem]


def test_invalid_terminal_claim_generation_is_audit_only(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/merged-bad-claim",
                        "path": str(tmp_path / "merged-bad-claim"),
                        "status": "merged",
                        "external_ids": ["ISSUE-MERGED-BAD-CLAIM"],
                        "claim_generation": None,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    },
                    {
                        "branch": "feat/abandoned-bad-claim",
                        "path": str(tmp_path / "abandoned-bad-claim"),
                        "status": "abandoned",
                        "external_ids": ["ISSUE-ABANDONED-BAD-CLAIM"],
                        "claim_generation": "old",
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/b.py"}],
                        },
                    },
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state = registry.load_state(state_path)

    assert len(state["problems"]) == 2
    assert mutation_blockers(state) == []


def test_active_only_list_scopes_terminal_diagnostics_but_keeps_unknown_facts(
    tmp_path: Path, capsys
) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/active-bad-claim",
                        "path": str(tmp_path / "active-bad-claim"),
                        "status": "active",
                        "external_ids": ["ISSUE-ACTIVE-BAD-CLAIM"],
                        "claim_generation": None,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    },
                    {
                        "branch": "feat/terminal-bad-base",
                        "path": str(tmp_path / "terminal-bad-base"),
                        "status": "abandoned",
                        "external_ids": ["ISSUE-TERMINAL-BAD-BASE"],
                        "claim_generation": 0,
                        "base": "not-a-commit-sha",
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/b.py"}],
                        },
                    },
                    "unknown-record",
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = registry.main(
        [
            "list",
            "--state",
            str(state_path),
            "--active-only",
            "--json",
        ]
    )

    assert rc == registry.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert [record["branch"] for record in payload["records"]] == [
        "feat/active-bad-claim"
    ]
    assert payload["problems"] == [
        {
            "kind": "registry-claim-generation-invalid",
            "index": 0,
            "branch": "feat/active-bad-claim",
            "status": "active",
            "reason": "claim_generation must be a non-negative integer",
        },
        {"kind": "registry-record-not-object", "index": 2},
    ]


def test_missing_claim_generation_on_persisted_claim_is_invalid(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/missing-claim-generation",
                        "path": str(tmp_path / "missing-claim-generation"),
                        "status": "active",
                        "external_ids": ["ISSUE-MISSING-CLAIM"],
                        "created_at": "2026-08-20T03:57:00Z",
                        "claimed_at": "2026-08-20T03:57:00Z",
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    state = registry.load_state(state_path)

    assert state["problems"] == [
        {
            "kind": "registry-claim-generation-invalid",
            "index": 0,
            "branch": "feat/missing-claim-generation",
            "status": "active",
            "reason": "claim_generation must be a non-negative integer",
        }
    ]
    assert mutation_blockers(state) == state["problems"]


def test_valid_claim_generation_does_not_create_problem(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    state_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/good-claim",
                        "path": str(tmp_path / "good-claim"),
                        "status": "active",
                        "external_ids": ["ISSUE-GOOD-CLAIM"],
                        "claim_generation": 0,
                        "base": "a" * 40,
                        "scope": {
                            "schema": "kg.worktree.scope.v1",
                            "files": [{"operation": "modify", "path": "ops/a.py"}],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    state = registry.load_state(state_path)

    assert state.get("problems", []) == []


def test_list_surfaces_scope_and_base_facts_without_rewriting_or_blocking_terminal(
    tmp_path: Path, capsys
) -> None:
    state_path = tmp_path / "registry.json"
    active_missing_scope = {
        "branch": "feat/missing-scope",
        "path": str(tmp_path / "missing-scope"),
        "status": "active",
        "external_ids": ["DIRECT-MISSING-SCOPE"],
        "base": "a" * 40,
        "claim_generation": 0,
    }
    terminal_bad_base = {
        "branch": "feat/bad-terminal-base",
        "path": str(tmp_path / "bad-terminal-base"),
        "status": "abandoned",
        "external_ids": ["DIRECT-BAD-BASE"],
        "base": "not-a-commit-sha",
        "claim_generation": 0,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    original = (
        json.dumps({"records": [active_missing_scope, terminal_bad_base]}, indent=2)
        + "\n"
    )
    state_path.write_text(original, encoding="utf-8")

    state = registry.load_state(state_path)

    assert [problem["kind"] for problem in state["problems"]] == [
        "registry-record-missing-field",
        "registry-base-invalid",
    ]
    assert state["problems"][0] == {
        "kind": "registry-record-missing-field",
        "index": 0,
        "branch": "feat/missing-scope",
        "status": "active",
        "field": "scope",
        "reason": "registry record is missing required field: scope",
    }
    assert state["problems"][1] == {
        "kind": "registry-base-invalid",
        "index": 1,
        "branch": "feat/bad-terminal-base",
        "status": "abandoned",
        "reason": "registry base must be an exact commit SHA",
    }
    assert mutation_blockers(state) == [state["problems"][0]]
    assert state_path.read_text(encoding="utf-8") == original

    rc = registry.main(["list", "--state", str(state_path), "--json"])

    assert rc == registry.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] == state["problems"]
    assert payload["records"][0]["base"] == state["records"][0]["base"]
    assert payload["records"][1]["base"] == state["records"][1]["base"]


def test_compact_refuses_unknown_status_without_data_loss(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    original = (
        json.dumps(
            {
                "records": [
                    {
                        "branch": "feat/legacy",
                        "path": str(tmp_path / "legacy"),
                        "status": "legacy-migrating",
                        "external_ids": ["ISSUE-LEGACY"],
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    state_path.write_text(original, encoding="utf-8")

    rc = registry.main(["compact", "--state", str(state_path), "--commit", "--json"])

    assert rc == registry.EXIT_USAGE
    assert state_path.read_text(encoding="utf-8") == original
    assert registry.load_state(state_path)["records"][0]["status"] == "legacy-migrating"


def test_compact_preserves_in_flight_and_terminal_audit_records(
    tmp_path: Path, capsys
) -> None:
    state_path = tmp_path / "registry.json"
    in_flight = [
        {
            "branch": f"feat/{status}",
            "path": str(tmp_path / status),
            "status": status,
            "external_ids": [status],
            "base": "a" * 40,
            "scope": {
                "schema": "kg.worktree.scope.v1",
                "files": [{"operation": "modify", "path": "ops/a.py"}],
            },
        }
        for status in (
            "active",
            "cleanup_pending",
            "published",
        )
    ]
    merged = {
        "branch": "feat/merged",
        "path": str(tmp_path / "merged"),
        "status": "merged",
        "external_ids": ["ISSUE-MERGED"],
        "handed_back_sha": "b" * 40,
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    exact_proof = _terminal_proof(merged)
    merged["terminal_proof"] = exact_proof
    legacy_abandoned = {
        "branch": "feat/abandoned",
        "path": str(tmp_path / "abandoned"),
        "status": "abandoned",
        "external_ids": ["ISSUE-LEGACY"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/b.py"}],
        },
    }
    records = [*in_flight, merged, legacy_abandoned]
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": records})

    rc = registry.main(["compact", "--state", str(state_path), "--commit", "--json"])

    assert rc == registry.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["terminal_records_preserved"] == 2
    reloaded = registry.load_state(state_path)
    assert [record["status"] for record in reloaded["records"]] == [
        "active",
        "cleanup_pending",
        "published",
        "merged",
        "abandoned",
    ]
    assert reloaded["records"][3]["terminal_proof"] == exact_proof
    assert "terminal_proof" not in reloaded["records"][4]

    assert (
        registry.main(["list", "--state", str(state_path), "--json"])
        == registry.EXIT_OK
    )
    visible = json.loads(capsys.readouterr().out)
    assert visible["records"][3]["terminal_proof"] == exact_proof
    assert visible["records"][4]["status"] == "abandoned"
    assert "terminal_proof" not in visible["records"][4]


def test_load_state_surfaces_tampered_terminal_proof_without_rewriting(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "registry.json"
    merged = {
        "branch": "feat/merged",
        "path": str(tmp_path / "merged"),
        "status": "merged",
        "external_ids": ["ISSUE-MERGED"],
        "handed_back_sha": "b" * 40,
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    tampered = _terminal_proof(merged)
    tampered["pr_number"] = 99
    merged["terminal_proof"] = tampered
    legacy = {
        "branch": "feat/legacy-merged",
        "path": str(tmp_path / "legacy-merged"),
        "status": "merged",
        "external_ids": ["ISSUE-LEGACY"],
        "handed_back_sha": "c" * 40,
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/b.py"}],
        },
    }
    original = json.dumps({"records": [merged, legacy]}, indent=2) + "\n"
    state_path.write_text(original, encoding="utf-8")

    state = registry.load_state(state_path)

    assert state["records"][0]["terminal_proof"] == tampered
    assert "terminal_proof" not in state["records"][1]
    assert state["problems"] == [
        {
            "kind": "registry-terminal-proof-invalid",
            "index": 0,
            "branch": "feat/merged",
            "status": "merged",
            "reason": "terminal proof digest is invalid",
        }
    ]
    assert state_path.read_text(encoding="utf-8") == original


def test_discard_proof_is_losslessly_retained_and_validated(tmp_path: Path) -> None:
    record = {
        "branch": "feat/discarded-handback",
        "path": str(tmp_path / "discarded-handback"),
        "status": "abandoned",
        "external_ids": ["DIRECT-1"],
        "claim_generation": 2,
        "base_sha": "a" * 40,
        "handed_back_sha": "b" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    record["discard_proof"] = registry.discard_proof_with_digest(
        {
            "schema": "kg.worktree.discard-proof.v1",
            "disposition": "abandoned_handback_discarded",
            "lane_id": "DIRECT-1",
            "branch": record["branch"],
            "head_sha": record["handed_back_sha"],
            "claim_generation": 2,
            "base_sha": record["base_sha"],
            "handback_digest": None,
            "operator": "supervisor",
            "reason": "ownerless clean handback explicitly discarded",
        }
    )
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    assert (
        registry.main(["compact", "--state", str(state_path), "--commit", "--json"])
        == registry.EXIT_OK
    )
    persisted = registry.load_state(state_path)
    assert persisted.get("problems", []) == []
    assert persisted["records"][0]["discard_proof"] == record["discard_proof"]

    tampered = json.loads(state_path.read_text(encoding="utf-8"))
    tampered["records"][0]["discard_proof"]["operator"] = "other"
    state_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    reloaded = registry.load_state(state_path)
    assert reloaded["problems"][0]["kind"] == "registry-discard-proof-invalid"


def test_superseded_proof_is_losslessly_retained_and_validated(tmp_path: Path) -> None:
    record = {
        "branch": "feat/superseded-handback",
        "path": str(tmp_path / "superseded-handback"),
        "status": "abandoned",
        "external_ids": ["DIRECT-SUPERSEDED"],
        "claim_generation": 2,
        "base_sha": "a" * 40,
        "handed_back_sha": "b" * 40,
        "handback_seal": {"base_sha": "a" * 40, "digest": "f" * 64},
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    record["superseded_proof"] = registry.superseded_proof_with_digest(
        {
            "schema": "kg.worktree.superseded-handback-proof.v1",
            "disposition": "superseded_by_merged_pr",
            "lane_id": "DIRECT-SUPERSEDED",
            "branch": record["branch"],
            "handback_sha": record["handed_back_sha"],
            "claim_generation": 2,
            "base_sha": record["base_sha"],
            "handback_digest": "f" * 64,
            "merged_pr_number": 42,
            "merged_pr_state": "MERGED",
            "merged_pr_base_branch": "main",
            "merged_pr_branch": record["branch"],
            "merged_pr_head_sha": "c" * 40,
            "merged_pr_base_sha": "d" * 40,
            "patch_fingerprint": "e" * 64,
            "scope_paths": ["ops/a.py"],
            "operator": "supervisor",
            "reason": "merged PR contains the same exact patch",
        }
    )
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    assert (
        registry.main(["compact", "--state", str(state_path), "--commit", "--json"])
        == registry.EXIT_OK
    )
    persisted = registry.load_state(state_path)
    assert persisted.get("problems", []) == []
    assert persisted["records"][0]["superseded_proof"] == record["superseded_proof"]

    tampered = json.loads(state_path.read_text(encoding="utf-8"))
    tampered["records"][0]["superseded_proof"]["merged_pr_number"] = 99
    state_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    reloaded = registry.load_state(state_path)
    assert reloaded["problems"][0]["kind"] == "registry-superseded-proof-invalid"


def _superseded_record_for_base_validation(
    tmp_path: Path,
    *,
    status: str = "abandoned",
    raw_base_sha: object = None,
    seal_base_sha: object = "a" * 40,
    proof_base_sha: str = "a" * 40,
) -> dict[str, object]:
    record: dict[str, object] = {
        "branch": "feat/superseded-base-validation",
        "path": str(tmp_path / "superseded-base-validation"),
        "status": status,
        "external_ids": ["DIRECT-SUPERSEDED-BASE"],
        "claim_generation": 2,
        "base_sha": raw_base_sha,
        "handed_back_sha": "b" * 40,
        "handback_seal": {
            "base_sha": seal_base_sha,
            "digest": "f" * 64,
        },
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
    }
    record["superseded_proof"] = registry.superseded_proof_with_digest(
        {
            "schema": "kg.worktree.superseded-handback-proof.v1",
            "disposition": "superseded_by_merged_pr",
            "lane_id": "DIRECT-SUPERSEDED-BASE",
            "branch": record["branch"],
            "handback_sha": record["handed_back_sha"],
            "claim_generation": 2,
            "base_sha": proof_base_sha,
            "handback_digest": "f" * 64,
            "merged_pr_number": 42,
            "merged_pr_state": "MERGED",
            "merged_pr_base_branch": "main",
            "merged_pr_branch": record["branch"],
            "merged_pr_head_sha": "c" * 40,
            "merged_pr_base_sha": "d" * 40,
            "patch_fingerprint": "e" * 64,
            "scope_paths": ["ops/a.py"],
            "operator": "supervisor",
            "reason": "merged PR contains the same exact patch",
        }
    )
    return record


def test_superseded_proof_uses_immutable_seal_base_when_raw_base_cleared(
    tmp_path: Path,
) -> None:
    record = _superseded_record_for_base_validation(tmp_path)

    assert superseded_proof_problem(record) is None


@pytest.mark.parametrize(
    ("status", "raw_base_sha", "seal_base_sha", "proof_base_sha"),
    [
        ("active", None, "a" * 40, "a" * 40),
        ("published", None, "a" * 40, "a" * 40),
        ("abandoned", None, "b" * 40, "a" * 40),
        ("abandoned", None, "not-a-sha", "a" * 40),
        ("abandoned", None, "a" * 40, "b" * 40),
        ("abandoned", "a" * 40, "b" * 40, "a" * 40),
        ("abandoned", "a" * 40, "not-a-sha", "a" * 40),
    ],
)
def test_superseded_proof_base_validation_remains_fail_closed(
    tmp_path: Path,
    status: str,
    raw_base_sha: object,
    seal_base_sha: object,
    proof_base_sha: str,
) -> None:
    record = _superseded_record_for_base_validation(
        tmp_path,
        status=status,
        raw_base_sha=raw_base_sha,
        seal_base_sha=seal_base_sha,
        proof_base_sha=proof_base_sha,
    )

    assert superseded_proof_problem(record) is not None

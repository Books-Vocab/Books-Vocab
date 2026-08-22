from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


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
            "feat/new",
            "--path",
            str(tmp_path / "new"),
            "--intent",
            "new",
            "--external-id",
            "ISSUE-NEW",
            "--json",
        ]
    )

    assert rc == registry.EXIT_CLAIMED
    assert state_path.read_text(encoding="utf-8") == original
    reloaded = registry.load_state(state_path)
    assert reloaded["records"][0]["external_ids"] == {"bad": True}
    assert reloaded["problems"][0]["kind"] == "registry-external-ids-invalid"


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
    }
    exact_proof = _terminal_proof(merged)
    merged["terminal_proof"] = exact_proof
    legacy_abandoned = {
        "branch": "feat/abandoned",
        "path": str(tmp_path / "abandoned"),
        "status": "abandoned",
        "external_ids": ["ISSUE-LEGACY"],
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

    assert registry.main(["list", "--state", str(state_path), "--json"]) == registry.EXIT_OK
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

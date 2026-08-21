from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


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


def test_compact_preserves_every_non_terminal_transaction(tmp_path: Path) -> None:
    state_path = tmp_path / "registry.json"
    records = [
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
            "merged",
            "abandoned",
        )
    ]
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": records})

    rc = registry.main(["compact", "--state", str(state_path), "--commit", "--json"])

    assert rc == registry.EXIT_OK
    assert [
        record["status"] for record in registry.load_state(state_path)["records"]
    ] == [
        "active",
        "cleanup_pending",
        "published",
    ]

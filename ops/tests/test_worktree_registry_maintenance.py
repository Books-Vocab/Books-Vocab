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

    assert state["records"][0]["external_ids"] == []
    assert [problem["kind"] for problem in state["problems"]] == [
        "registry-record-not-object",
        "registry-external-ids-invalid",
    ]


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

from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


def _published_record(tmp_path: Path) -> dict:
    return {
        "branch": "feat/merged-proof",
        "path": str(tmp_path / "merged-proof"),
        "status": "published",
        "external_ids": ["ISSUE-1"],
        "claim_generation": 3,
        "handed_back_sha": "b" * 40,
    }


def _proof(record: dict, *, lane_id: str = "ISSUE-1") -> dict:
    return registry.terminal_proof_with_digest(
        {
            "schema": registry.TERMINAL_PROOF_SCHEMA,
            "lane_id": lane_id,
            "pr_number": 42,
            "pr_state": "MERGED",
            "base_branch": "main",
            "branch": record["branch"],
            "head_sha": record["handed_back_sha"],
        }
    )


def _resolve_args(state_path: Path, record: dict) -> list[str]:
    return [
        "resolve",
        "--state",
        str(state_path),
        "--branch",
        record["branch"],
        "--path",
        record["path"],
        "--status",
        "merged",
        "--expected-generation",
        "3",
        "--expected-head-sha",
        record["handed_back_sha"],
        "--json",
    ]


def test_merged_transition_requires_typed_exact_pr_proof(tmp_path: Path) -> None:
    record = _published_record(tmp_path)
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    missing = registry.main(_resolve_args(state_path, record))
    tampered_proof = _proof(record)
    tampered_proof["base_branch"] = "release"
    tampered = registry.main(
        _resolve_args(state_path, record)
        + ["--terminal-proof", json.dumps(tampered_proof)]
    )
    exact_proof = _proof(record)
    exact = registry.main(
        _resolve_args(state_path, record)
        + ["--terminal-proof", json.dumps(exact_proof)]
    )

    assert missing == registry.EXIT_CLAIMED
    assert tampered == registry.EXIT_CLAIMED
    assert exact == registry.EXIT_OK
    resolved = registry.load_state(state_path)["records"][0]
    assert resolved["status"] == "merged"
    assert resolved["terminal_proof"] == exact_proof


def test_direct_assignment_merged_transition_uses_branch_as_lane_identity(
    tmp_path: Path,
) -> None:
    record = _published_record(tmp_path)
    record["external_ids"] = []
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": [record]})

    proof = _proof(record, lane_id=record["branch"])
    result = registry.main(
        _resolve_args(state_path, record)
        + ["--terminal-proof", json.dumps(proof)]
    )

    assert result == registry.EXIT_OK
    resolved = registry.load_state(state_path)["records"][0]
    assert resolved["status"] == "merged"
    assert resolved["terminal_proof"] == proof

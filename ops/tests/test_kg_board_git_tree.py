import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.kg_board.git_tree import SCHEMA, normalize_snapshot


def test_normalize_snapshot_merges_duplicate_commit_metadata_and_keeps_refs():
    payload = normalize_snapshot({
        "at": "2026-08-10T20:00:00+08:00",
        "host": "oscar",
        "refs": [{
            "branch": "feat/reader",
            "head": "abcdef0123456789",
            "kind": "child",
            "integration_owner": "feat/integration",
            "backlog": ["APP-1"],
        }],
        "commits": [
            {"sha": "abcdef0123456789", "parents": ["1234567890abcdef"],
             "subject": "first", "files": ["ios/A.swift"]},
            {"sha": "abcdef0123456789", "parents": [],
             "author": "Max", "files": ["ios/B.swift"]},
        ],
    })

    assert payload["schema"] == SCHEMA
    assert payload["refs"][0]["tickets"] == [{
        "id": "APP-1", "brief": None, "severity": None,
    }]
    assert payload["commits"] == [{
        "sha": "abcdef0123456789",
        "parents": ["1234567890abcdef"],
        "subject": "first",
        "author": "Max",
        "committer": None,
        "authored_at": None,
        "committed_at": None,
        "insertions": None,
        "deletions": None,
        "files": ["ios/A.swift", "ios/B.swift"],
    }]


def test_normalize_snapshot_rejects_malformed_records_without_crashing():
    payload = normalize_snapshot({
        "complete": False,
        "error": "ledger unavailable",
        "refs": [{"branch": "missing-head"}, "bad"],
        "commits": [{"subject": "missing-sha"}, None],
    })

    assert payload["schema"] == SCHEMA
    assert payload["complete"] is False
    assert payload["error"] == "ledger unavailable"
    assert payload["refs"] == []
    assert payload["commits"] == []

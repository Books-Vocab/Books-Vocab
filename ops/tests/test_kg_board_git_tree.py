import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.kg_board.git_tree import SCHEMA, normalize_snapshot, project_snapshot
from ops.kg_board import server


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


def test_normalize_snapshot_is_fail_closed_for_string_collections_and_invalid_shas():
    payload = normalize_snapshot({
        "complete": "false",
        "refs": "not-a-list",
        "commits": [{
            "sha": "not-a-sha",
            "parents": "1234567",
            "files": "ios/App.swift",
        }],
    })

    assert payload["complete"] is False
    assert payload["refs"] == []
    assert payload["commits"] == []


def test_normalize_snapshot_rejects_numeric_sha_and_malformed_parent():
    payload = normalize_snapshot({
        "refs": [{"branch": "feat/a", "head": "1234567"}],
        "commits": [{"sha": "abcdef0", "parents": [1234567]}],
    })

    assert payload["error"]
    assert payload["commits"][0]["sha"] == "abcdef0"
    assert payload["commits"][0]["parents"] == []
    assert payload["refs"] == [{
        "id": "ref-0", "branch": "feat/a", "kind": "child", "base": "main",
        "base_sha": None, "head": "1234567", "path": None, "host": None,
        "status": "active", "live_state": "unknown", "worktree_present": None,
        "integration_owner": None, "claimed_at": None, "handed_back_sha": None,
        "tickets": [],
    }]


def test_project_snapshot_enriches_ticket_leaves_and_reports_missing_parents():
    projected = project_snapshot({
        "refs": [{"branch": "feat/a", "head": "abcdef0123456789", "backlog": ["IMP-1"]}],
        "commits": [{"sha": "abcdef0123456789", "parents": ["1234567890abcdef"], "subject": "tip"}],
    }, {"IMP-1": {"brief": "修正看板", "severity": "high"}})

    assert projected["complete"] is False
    assert projected["missing_parents"] == ["1234567890abcdef"]
    assert projected["dangling_refs"] == []
    assert projected["refs"][0]["tickets"] == [{
        "id": "IMP-1", "brief": "修正看板", "severity": "high",
    }]
    assert projected["commits"][0]["refs"] == ["feat/a"]


def test_project_snapshot_marks_dangling_ref_incomplete():
    projected = project_snapshot({
        "refs": [{"branch": "feat/a", "head": "abcdef0123456789"}],
        "commits": [],
    })

    assert projected["complete"] is False
    assert projected["dangling_refs"] == ["abcdef0123456789"]


def test_server_git_tree_payload_reads_mirror_and_canonical_ticket_briefs(monkeypatch, tmp_path):
    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({"git_tree": {
        "at": "now",
        "refs": [{"branch": "feat/a", "head": "abcdef0123456789", "backlog": ["IMP-1"]}],
        "commits": [{"sha": "abcdef0123456789", "parents": [], "subject": "tip"}],
    }}), encoding="utf-8")
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(server, "read_entries", lambda: {
        "entries": [{"id": "IMP-1", "brief": "修正看板", "severity": "high"}],
    })
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})

    payload = server.git_tree_payload()

    assert payload["schema"] == SCHEMA
    assert payload["complete"] is True
    assert payload["refs"][0]["tickets"][0]["brief"] == "修正看板"

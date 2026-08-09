from __future__ import annotations

import json
import subprocess
import sys
from types import MethodType
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.kg_board import server


def _ticket(ticket_id: str, *, blocked_by: list[str] | None = None) -> dict:
    return {
        "id": ticket_id,
        "status": "open",
        "severity": "med",
        "stream": "IMP",
        "category": "tool",
        "date": "2026-08-10",
        "plan": "plan",
        "acceptance": "acceptance",
        "groomed_by": "test",
        "blocked_by": blocked_by or [],
    }


def test_dispatch_uses_canonical_ids_ignores_snooze_and_subtracts_mirror_claims():
    blocked = [_ticket(f"BLOCKED-{index}", blocked_by=["WAITING-ON"]) for index in range(6)]
    entries = [*blocked, _ticket("CANONICAL"), _ticket("CLAIMED")]
    canonical_ids = {"CANONICAL", "CLAIMED"}

    payload = server.project(
        entries,
        {"CANONICAL": {"snooze_until": "2099-01-01"}},
        {"CLAIMED": {"branch": "feat/already-held"}},
        canonical_dispatch_ids=canonical_ids,
        dispatch_meta={
            "clauses": ["groomed", "unresolved", "unclaimed", "unblocked"],
            "withheld_blocked": [
                {"id": row["id"], "waiting_on": row["blocked_by"]} for row in blocked
            ],
        },
    )

    assert [row["id"] for row in payload["dispatch"]] == ["CANONICAL"]
    assert payload["counts"]["canonical_dispatch"] == 2
    assert payload["counts"]["mirror_claims_subtracted"] == 1
    assert len(payload["dispatch_meta"]["withheld_blocked"]) == 6
    assert not canonical_ids.intersection(row["id"] for row in blocked)


def test_read_entries_reads_list_and_canonical_dispatch_from_clone(monkeypatch, tmp_path):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        subcommand = command[-2]
        if subcommand == "list":
            body = {"schema": "kg.backlog.list.v1", "entries": [_ticket("A"), _ticket("B")]}
        elif subcommand == "dispatch":
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A")],
                "dispatch": {
                    "clauses": ["groomed", "unresolved", "unclaimed", "unblocked"],
                    "withheld_blocked": [{"id": "B", "waiting_on": ["A"]}],
                },
            }
        else:  # pragma: no cover - makes an unexpected CLI call self-explanatory
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "abc123")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {"sha": None, "entries": [], "dispatch_ids": [], "dispatch_meta": {}, "read_at": None, "error": None},
    )

    snapshot = server.read_entries(force=True)

    assert [call[-2:] for call in calls] == [("list", "--json"), ("dispatch", "--json")]
    assert snapshot["dispatch_ids"] == ["A"]
    assert snapshot["dispatch_meta"]["withheld_blocked"] == [{"id": "B", "waiting_on": ["A"]}]


def test_successful_empty_store_replaces_cached_rows(monkeypatch, tmp_path):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "new-sha")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"schema": "kg.backlog.list.v1", "entries": [], "dispatch": {}}),
            "",
        ),
    )
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "sha": "old-sha",
            "entries": [_ticket("STALE")],
            "dispatch_ids": ["STALE"],
            "dispatch_meta": {},
            "read_at": "old",
            "error": None,
        },
    )

    snapshot = server.read_entries(force=True)

    assert snapshot["sha"] == "new-sha"
    assert snapshot["entries"] == []
    assert snapshot["dispatch_ids"] == []
    assert snapshot["error"] is None


def test_freshness_reports_measured_lag_and_preserves_unknown(monkeypatch, tmp_path):
    mirror_path = tmp_path / "mirror.json"
    mirror_path.write_text(
        json.dumps({"sync_state": {"ahead_count": 4, "local_main_sha": "local", "at": datetime.now(server.TZ).isoformat()}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "MIRROR_PATH", mirror_path)
    monkeypatch.setattr(
        server,
        "_cache",
        {"sha": "clone", "entries": [], "dispatch_ids": [], "dispatch_meta": {}, "read_at": "now", "error": None},
    )
    monkeypatch.setattr(
        server,
        "_git",
        lambda args: subprocess.CompletedProcess(args, 0, "3\n", "")
        if args == ["rev-list", "--count", "HEAD..origin/main"]
        else subprocess.CompletedProcess(args, 1, "", "missing"),
    )

    measured = server.freshness()
    assert measured["clone_behind_origin"] == 3
    assert measured["local_ahead"] == 4

    mirror_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        server,
        "_git",
        lambda args: subprocess.CompletedProcess(args, 1, "", "missing"),
    )
    unknown = server.freshness()
    assert unknown["clone_behind_origin"] is None
    assert unknown["local_ahead"] is None


def test_freshness_converts_git_exception_to_explicit_unknown(monkeypatch, tmp_path):
    mirror_path = tmp_path / "mirror.json"
    mirror_path.write_text(json.dumps({"sync_state": {"ahead_count": 0}}), encoding="utf-8")
    monkeypatch.setattr(server, "MIRROR_PATH", mirror_path)
    monkeypatch.setattr(
        server,
        "_cache",
        {"sha": "clone", "entries": [], "dispatch_ids": [], "dispatch_meta": {}, "read_at": "now", "error": None},
    )
    monkeypatch.setattr(server, "_git", lambda _args: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 120)))

    state = server.freshness()

    assert state["clone_behind_origin"] is None
    assert state["freshness_state"] == "error"
    assert "TimeoutExpired" in state["clone_lag_error"]


def test_board_api_and_health_payload_share_freshness_state(monkeypatch):
    state = {
        "clone_behind_origin": 2,
        "local_ahead": 5,
        "read_error": None,
        "refresh": {"last_error": None},
    }
    monkeypatch.setattr(server, "freshness", lambda: dict(state))
    monkeypatch.setattr(
        server,
        "read_entries",
        lambda: {
            "entries": [_ticket("A")],
            "dispatch_ids": ["A"],
            "dispatch_meta": {"withheld_blocked": []},
        },
    )
    monkeypatch.setattr(server, "load_overlay", lambda _known: {})
    monkeypatch.setattr(server, "held_claims", lambda: {})

    board = server.board_payload()
    health = server.health_payload()

    assert board["freshness"]["clone_behind_origin"] == health["clone_behind_origin"] == 2
    assert board["freshness"]["local_ahead"] == health["local_ahead"] == 5


def test_healthz_requires_token_when_all_reads_require_token(monkeypatch):
    monkeypatch.setattr(server, "REQUIRE_TOKEN_FOR_READS", True)
    monkeypatch.setattr(server, "TOKEN", "secret")
    handler = object.__new__(server.Handler)
    handler.path = "/healthz"
    handler.headers = {}
    responses = []
    handler._json = MethodType(lambda _self, code, payload: responses.append((code, payload)), handler)

    handler.do_GET()

    assert responses == [(401, {"error": "token required for reads (KG_BOARD_REQUIRE_TOKEN=1)"})]

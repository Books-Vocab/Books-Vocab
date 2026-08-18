from __future__ import annotations

import inspect
import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import MethodType

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.kg_board import server
from ops.kg_board.model import classify_decision, scope_audit


def _ticket(
    ticket_id: str, *, blocked_by: list[str] | None = None, groomed: bool = True
) -> dict:
    row = {
        "id": ticket_id,
        "status": "open",
        "severity": "med",
        "stream": "IMP",
        "category": "tool",
        "date": "2026-08-10",
        "blocked_by": blocked_by or [],
    }
    if groomed:
        row.update(plan="plan", acceptance="acceptance", groomed_by="test")
    return row


def _request(command) -> str:
    return "ungroomed" if "--ungroomed" in command else command[-2]


def test_delivery_model_separates_grooming_contract_and_dependency_states():
    entries = [
        {**_ticket("GROOM"), "groomed_by": ""},
        {**_ticket("CONTRACT"), "contract_status": "blocked"},
        {**_ticket("DEPENDENCY")},
        {**_ticket("DISPATCH"), "contract_status": "ready", "contract_baseline": "red",
         "contract_checked_at": "2026-08-17", "contract_checked_by": "test",
         "contract_evidence": "red"},
    ]
    assert classify_decision(entries[0], held_ids=set(), dispatch_ids=set(),
                             blocked_ids=set(), ungroomed_ids={"GROOM"}) == "needs-grooming"
    assert classify_decision(entries[1], held_ids=set(), dispatch_ids=set(),
                             blocked_ids=set(), ungroomed_ids=set()) == "contract-not-ready"
    assert classify_decision(entries[2], held_ids=set(), dispatch_ids=set(),
                             blocked_ids={"DEPENDENCY"}, ungroomed_ids=set()) == "dependency-blocked"
    assert classify_decision(entries[3], held_ids=set(), dispatch_ids={"DISPATCH"},
                             blocked_ids=set(), ungroomed_ids=set()) == "dispatchable"


def test_scope_audit_does_not_treat_legacy_prose_as_file_scope():
    entries = [
        {"id": "STRUCTURED", "status": "open", "scope": {"files": [{"path": "ops/a.py", "operation": "modify"}]}},
        {"id": "LEGACY", "status": "open", "scope": "one script and its test"},
        {"id": "MISSING", "status": "open"},
        {"id": "FIXED", "status": "fixed", "scope": "old"},
    ]
    assert scope_audit(entries) == {
        "total": 4,
        "unresolved": 3,
        "structured": 1,
        "legacy_text": 2,
        "missing": 1,
        "unresolved_structured": 1,
        "unresolved_legacy_text": 1,
        "unresolved_missing": 1,
    }


def test_model_payload_uses_the_same_live_decision_partition(monkeypatch):
    contract = {
        **_ticket("DISPATCH"),
        "contract_status": "ready",
        "contract_baseline": "red",
        "contract_checked_at": "2026-08-17",
        "contract_checked_by": "test",
        "contract_evidence": "red",
        "scope": {"files": [{"path": "ops/a.py", "operation": "modify"}]},
    }
    entries = [
        {**_ticket("GROOM"), "groomed_by": ""},
        {**_ticket("BLOCKED"), "scope": "legacy"},
        {**_ticket("HELD"), "scope": {"files": [{"path": "ops/h.py", "operation": "modify"}]}},
        contract,
        {**_ticket("CONTRACT"), "scope": "legacy"},
    ]
    monkeypatch.setattr(server, "read_entries", lambda: {
        "sha": "abc123", "read_at": "now", "entries": entries,
        "dispatch_ids": ["DISPATCH"], "ungroomed_ids": ["GROOM"],
        "local_held": {"HELD": {"branch": "feat/held"}},
        "dispatch_meta": {
            "withheld_blocked": [{"id": "BLOCKED", "waiting_on": ["WAIT"]}],
            "withheld_contract": [{"id": "CONTRACT", "problems": [{"kind": "contract-evidence-missing"}]}],
        },
    })
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})

    payload = server.model_payload()

    assert payload["schema"] == "kg.board.model.v1"
    assert payload["live"]["decision_ids"] == {
        "needs-grooming": ["GROOM"],
        "dependency-blocked": ["BLOCKED"],
        "held": ["HELD"],
        "dispatchable": ["DISPATCH"],
        "contract-not-ready": ["CONTRACT"],
    }
    assert payload["live"]["lifecycle_ids"]["queued"] == ["BLOCKED", "CONTRACT", "DISPATCH"]
    assert payload["live"]["counts"]["unresolved"] == 5
    assert payload["live"]["scope_audit"]["unresolved_legacy_text"] == 2


def test_projection_rejects_a_missing_partition_when_cli_explicitly_returns_empty():
    # An empty withheld_contract list is authoritative. Treating it as falsey
    # would silently classify the unexplained remainder as contract debt and
    # hide a CLI/API partition drift.
    with pytest.raises(ValueError, match="canonical decision partition missing ticket"):
        server.project(
            [_ticket("UNEXPLAINED")],
            canonical_dispatch_ids=set(),
            canonical_ungroomed_ids=set(),
            dispatch_meta={"withheld_blocked": [], "withheld_contract": []},
        )


@pytest.fixture(autouse=True)
def stable_registry_fingerprint(monkeypatch):
    original = server._registry_fingerprint
    monkeypatch.setattr(
        server,
        "_registry_fingerprint",
        lambda: ((False, None, None, None), None),
    )
    return original


def test_dispatch_uses_canonical_ids_and_subtracts_mirror_claims():
    blocked = [_ticket(f"BLOCKED-{index}", blocked_by=["WAITING-ON"]) for index in range(6)]
    entries = [*blocked, _ticket("CANONICAL"), _ticket("CLAIMED")]
    canonical_ids = {"CANONICAL", "CLAIMED"}

    payload = server.project(
        entries,
        {"CLAIMED": {"branch": "feat/already-held"}},
        canonical_dispatch_ids=canonical_ids,
        canonical_ungroomed_ids=set(),
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
        subcommand = _request(command)
        if subcommand == "list":
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A"), _ticket("B"), _ticket("C"), _ticket("D")],
                "held": {},
            }
        elif subcommand == "ungroomed":
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("D")],
                "held": {},
            }
        elif subcommand == "dispatch":
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A")],
                "held": {"C": {"branch": "feat/local", "claimed_at": "now"}},
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

    assert [call[-2:] for call in calls] == [
        ("list", "--json"), ("dispatch", "--json"), ("--ungroomed", "--json")
    ]
    assert snapshot["dispatch_ids"] == ["A"]
    assert snapshot["local_held"] == {"C": {"branch": "feat/local", "claimed_at": "now"}}
    assert snapshot["ungroomed_ids"] == ["D"]
    assert snapshot["dispatch_meta"]["withheld_blocked"] == [{"id": "B", "waiting_on": ["A"]}]


def test_read_entries_refreshes_claim_projection_when_head_is_unchanged(monkeypatch, tmp_path):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    calls = {"list": 0, "dispatch": 0, "ungroomed": 0}

    def fake_run(command, **_kwargs):
        subcommand = _request(command)
        calls[subcommand] += 1
        if subcommand == "list":
            body = {"schema": "kg.backlog.list.v1", "entries": [_ticket("A")], "held": {}}
        elif subcommand == "ungroomed":
            body = {"schema": "kg.backlog.list.v1", "entries": [], "held": {}}
        elif calls["dispatch"] == 1:
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A")],
                "held": {},
                "dispatch": {"withheld_blocked": []},
            }
        else:
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [],
                "held": {"A": {"branch": "feat/new-claim", "claimed_at": "now"}},
                "dispatch": {"withheld_blocked": []},
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    fingerprints = iter([
        ((True, 1, 10, 100), None),
        ((True, 1, 10, 100), None),
        ((True, 1, 20, 120), None),
        ((True, 1, 20, 120), None),
    ])
    monkeypatch.setattr(server, "_registry_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "sha": None, "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    before = server.read_entries(force=True)
    after = server.read_entries()

    assert before["dispatch_ids"] == ["A"]
    assert after["dispatch_ids"] == []
    assert after["local_held"] == {
        "A": {"branch": "feat/new-claim", "claimed_at": "now"}
    }
    assert after["ungroomed_ids"] == []
    assert calls == {"list": 1, "dispatch": 2, "ungroomed": 2}


def test_read_entries_warm_same_head_and_registry_skips_all_backlog_subprocesses(
    monkeypatch, tmp_path
):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    calls: list[str] = []

    def fake_run(command, **_kwargs):
        calls.append(_request(command))
        if _request(command) == "ungroomed":
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [],
                "held": {},
                "dispatch": {"withheld_blocked": []},
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(body), "")
        body = {
            "schema": "kg.backlog.list.v1",
            "entries": [_ticket("A")],
            "held": {"HELD": {"branch": "feat/held"}},
            "dispatch": {"withheld_blocked": []},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "valid": False, "sha": None, "registry_fingerprint": None,
            "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    warm = server.read_entries(force=True)
    hit = server.read_entries()

    assert hit == warm
    assert calls == ["list", "dispatch", "ungroomed"]


def test_registry_mutation_during_dispatch_is_not_cached_as_new_fingerprint(
    monkeypatch, tmp_path
):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    fingerprints = iter([
        ((True, 1, 10, 100), None),
        ((True, 1, 10, 100), None),
        ((True, 1, 20, 120), None),
        ((True, 2, 30, 140), None),
        ((True, 2, 30, 140), None),
        ((True, 2, 30, 140), None),
    ])
    dispatch_calls = 0
    list_calls = 0

    def fake_run(command, **_kwargs):
        nonlocal dispatch_calls, list_calls
        subcommand = _request(command)
        if subcommand == "list":
            list_calls += 1
            body = {"schema": "kg.backlog.list.v1", "entries": [_ticket("A")]}
        elif subcommand == "ungroomed":
            body = {"schema": "kg.backlog.list.v1", "entries": []}
        else:
            dispatch_calls += 1
            held = {} if dispatch_calls == 1 else {
                "A": {"branch": f"feat/claim-{dispatch_calls}"}
            }
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [] if held else [_ticket("A")],
                "held": held,
                "dispatch": {"withheld_blocked": []},
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    monkeypatch.setattr(server, "_registry_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "valid": False, "sha": None, "registry_fingerprint": None,
            "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    warm = server.read_entries(force=True)
    raced = server.read_entries()
    recovered = server.read_entries()

    assert raced["local_held"] == warm["local_held"] == {}
    assert "registry changed during canonical read" in raced["error"]
    assert recovered["local_held"] == {"A": {"branch": "feat/claim-3"}}
    assert recovered["error"] is None
    assert list_calls == 1
    assert dispatch_calls == 3


def test_registry_fingerprint_uses_git_common_dir_and_tracks_missing_ledger(
    monkeypatch, tmp_path, stable_registry_fingerprint
):
    common_dir = tmp_path / ".git"
    common_dir.mkdir()
    git_calls = []

    def fake_git(args):
        git_calls.append(args)
        return subprocess.CompletedProcess(args, 0, f"{common_dir}\n", "")

    monkeypatch.setattr(server, "_registry_fingerprint", stable_registry_fingerprint)
    monkeypatch.setattr(server, "_git", fake_git)

    missing, missing_error = server._registry_fingerprint()
    ledger = tmp_path / ".cache" / "worktree_registry.json"
    ledger.parent.mkdir()
    ledger.write_text("{}\n", encoding="utf-8")
    present, present_error = server._registry_fingerprint()
    stat = ledger.stat()

    assert missing == (False, None, None, None)
    assert missing_error is None
    assert present == (True, stat.st_ino, stat.st_mtime_ns, stat.st_size)
    assert present_error is None
    assert git_calls == [
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
    ]


def test_registry_fingerprint_error_preserves_warm_snapshot_then_recovers(
    monkeypatch, tmp_path
):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    fingerprints = iter([
        ((False, None, None, None), None),
        ((False, None, None, None), None),
        (None, "registry fingerprint failed: OSError: unavailable"),
        ((True, 2, 30, 140), None),
        ((True, 2, 30, 140), None),
    ])
    calls = 0

    def fake_run(command, **_kwargs):
        nonlocal calls
        calls += 1
        body = {
            "schema": "kg.backlog.list.v1", "entries": [_ticket("A")],
            "held": {}, "dispatch": {"withheld_blocked": []},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    monkeypatch.setattr(server, "_registry_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "valid": False, "sha": None, "registry_fingerprint": None,
            "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    warm = server.read_entries(force=True)
    stale = server.read_entries()
    recovered = server.read_entries()

    assert stale["entries"] == warm["entries"]
    assert "registry fingerprint failed" in stale["error"]
    assert recovered["error"] is None
    assert recovered["registry_fingerprint"] == (True, 2, 30, 140)
    assert calls == 5


def test_refresh_loop_does_not_force_unchanged_canonical_projection(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "refresh_clone", lambda: None)
    monkeypatch.setattr(server, "read_entries", lambda force=False: calls.append(force))
    monkeypatch.setattr(
        server.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(RuntimeError("stop loop")),
    )

    with pytest.raises(RuntimeError, match="stop loop"):
        server.refresh_loop()

    assert calls == [False]


def test_refresh_loop_publishes_when_clone_head_changes(monkeypatch):
    heads = iter(("old-head", "new-head"))
    events = []
    calls = []
    monkeypatch.setattr(server, "clone_head", lambda: next(heads))
    monkeypatch.setattr(server, "refresh_clone", lambda: None)
    monkeypatch.setattr(server, "read_entries", lambda force=False: calls.append(force))
    monkeypatch.setattr(server, "publish_event", events.append)
    monkeypatch.setattr(
        server.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(RuntimeError("stop loop")),
    )

    with pytest.raises(RuntimeError, match="stop loop"):
        server.refresh_loop()

    assert calls == [False]
    assert events == ["clone"]


@pytest.mark.parametrize("failure_type", (subprocess.TimeoutExpired, OSError))
def test_read_entries_preserves_warm_snapshot_when_dispatch_invocation_fails(
    monkeypatch, tmp_path, failure_type
):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    dispatch_calls = 0

    def fake_run(command, **_kwargs):
        nonlocal dispatch_calls
        subcommand = _request(command)
        if subcommand == "list":
            body = {"schema": "kg.backlog.list.v1", "entries": [_ticket("A")]}
        elif subcommand == "ungroomed":
            body = {"schema": "kg.backlog.list.v1", "entries": []}
        else:
            dispatch_calls += 1
            if dispatch_calls == 2:
                if failure_type is subprocess.TimeoutExpired:
                    raise failure_type(command, 180)
                raise failure_type("registry unavailable")
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A")],
                "held": {"HELD": {"branch": "feat/held"}},
                "dispatch": {"withheld_blocked": []},
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    fingerprints = iter([
        ((True, 1, 10, 100), None),
        ((True, 1, 10, 100), None),
        ((True, 1, 20, 120), None),
    ])
    monkeypatch.setattr(server, "_registry_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "sha": None, "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    warm = server.read_entries(force=True)
    stale = server.read_entries()

    assert stale["entries"] == warm["entries"]
    assert stale["dispatch_ids"] == warm["dispatch_ids"] == ["A"]
    assert stale["local_held"] == warm["local_held"] == {
        "HELD": {"branch": "feat/held"}
    }
    assert failure_type.__name__ in stale["error"]


@pytest.mark.parametrize("failure_type", (subprocess.TimeoutExpired, OSError))
def test_read_entries_preserves_warm_snapshot_when_initial_head_probe_fails(
    monkeypatch, tmp_path, failure_type
):
    warm = {
        "sha": "warm-head",
        "entries": [_ticket("WARM")],
        "dispatch_ids": ["WARM"],
        "dispatch_meta": {"withheld_blocked": []},
        "local_held": {"HELD": {"branch": "feat/warm"}},
        "ungroomed_ids": [],
        "read_at": "warm-read",
        "error": None,
    }

    def failing_git(args):
        if failure_type is subprocess.TimeoutExpired:
            raise failure_type(["git", *args], 120)
        raise failure_type("git unavailable")

    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({"sync_state": {"ahead_count": 0}}), encoding="utf-8")
    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(server, "_git", failing_git)
    monkeypatch.setattr(server, "_cache", dict(warm))

    stale = server.read_entries()
    state = server.freshness()

    assert stale["entries"] == warm["entries"]
    assert stale["dispatch_ids"] == warm["dispatch_ids"]
    assert stale["local_held"] == warm["local_held"]
    assert failure_type.__name__ in stale["error"]
    assert state["freshness_state"] == "error"
    assert state["read_error"] == stale["error"]


def test_read_entries_preserves_successful_empty_warm_snapshot_on_head_failure(
    monkeypatch, tmp_path
):
    warm = {
        "sha": "empty-warm-head",
        "entries": [],
        "dispatch_ids": [],
        "dispatch_meta": {"clauses": ["warm-empty"]},
        "local_held": {},
        "ungroomed_ids": [],
        "read_at": "empty-warm-read",
        "error": None,
    }
    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({"sync_state": {"ahead_count": 0}}), encoding="utf-8")
    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(
        server, "_git", lambda _args: (_ for _ in ()).throw(OSError("git unavailable"))
    )
    monkeypatch.setattr(server, "_cache", dict(warm))

    stale = server.read_entries()
    state = server.freshness()

    assert stale["sha"] == warm["sha"]
    assert stale["read_at"] == warm["read_at"]
    assert stale["dispatch_meta"] == warm["dispatch_meta"]
    assert "OSError" in stale["error"]
    assert state["freshness_state"] == "error"
    assert state["read_error"] == stale["error"]


@pytest.mark.parametrize("failure_type", (subprocess.TimeoutExpired, OSError))
def test_read_entries_preserves_warm_snapshot_when_final_head_probe_fails(
    monkeypatch, tmp_path, failure_type
):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    head_calls = 0
    warm = {
        "sha": "warm-head",
        "entries": [_ticket("WARM")],
        "dispatch_ids": ["WARM"],
        "dispatch_meta": {"withheld_blocked": []},
        "local_held": {"HELD": {"branch": "feat/warm"}},
        "ungroomed_ids": [],
        "read_at": "warm-read",
        "error": None,
    }

    def fake_git(args):
        nonlocal head_calls
        if args == ["rev-parse", "HEAD"]:
            head_calls += 1
            if head_calls == 2:
                if failure_type is subprocess.TimeoutExpired:
                    raise failure_type(["git", *args], 120)
                raise failure_type("git unavailable")
            return subprocess.CompletedProcess(args, 0, "new-head\n", "")
        return subprocess.CompletedProcess(args, 0, "0\n", "")

    def fake_run(command, **_kwargs):
        body = {
            "schema": "kg.backlog.list.v1",
            "entries": [_ticket("NEW")],
            "held": {},
            "dispatch": {"withheld_blocked": []},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({"sync_state": {"ahead_count": 0}}), encoding="utf-8")
    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(server, "_git", fake_git)
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "_cache", dict(warm))

    stale = server.read_entries(force=True)
    state = server.freshness()

    assert stale["entries"] == warm["entries"]
    assert stale["dispatch_ids"] == warm["dispatch_ids"]
    assert stale["local_held"] == warm["local_held"]
    assert failure_type.__name__ in stale["error"]
    assert state["freshness_state"] == "error"
    assert state["read_error"] == stale["error"]


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


def test_read_entries_rejects_a_cross_revision_canonical_snapshot(monkeypatch, tmp_path):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    heads = iter(("before", "after"))

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: next(heads))
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            json.dumps({
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("MIXED")],
                "dispatch": {"withheld_blocked": []},
            }),
            "",
        ),
    )
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "sha": None, "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    snapshot = server.read_entries(force=True)

    assert snapshot["entries"] == []
    assert "clone changed during canonical read" in snapshot["error"]
    assert "with _clone_lock" in inspect.getsource(server.refresh_clone)
    assert "with _clone_lock" in inspect.getsource(server.read_entries)


def test_clone_lock_blocks_refresh_between_list_and_dispatch(monkeypatch, tmp_path):
    tool = tmp_path / "ops" / "backlog.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    list_started = threading.Event()
    release_list = threading.Event()
    refresh_attempted = threading.Event()
    refresh_git_entered = threading.Event()
    errors: list[BaseException] = []

    class ObservedRLock:
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.current_thread().name == "refresh-probe":
                refresh_attempted.set()
            self.lock.acquire()
            return self

        def __exit__(self, *_args):
            self.lock.release()

    def fake_run(command, **_kwargs):
        subcommand = _request(command)
        if subcommand == "list":
            list_started.set()
            assert release_list.wait(2), "test failed to release list command"
            body = {"schema": "kg.backlog.list.v1", "entries": [_ticket("A")], "held": {}}
        elif subcommand == "ungroomed":
            body = {"schema": "kg.backlog.list.v1", "entries": []}
        else:
            body = {
                "schema": "kg.backlog.list.v1",
                "entries": [_ticket("A")],
                "dispatch": {"withheld_blocked": []},
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    def fake_git(args):
        refresh_git_entered.set()
        return subprocess.CompletedProcess(args, 0, "", "")

    def capture(call):
        try:
            call()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(server, "CLONE", tmp_path)
    monkeypatch.setattr(server, "clone_head", lambda: "same-head")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "_git", fake_git)
    monkeypatch.setattr(server, "_clone_lock", ObservedRLock())
    monkeypatch.setattr(
        server,
        "_cache",
        {
            "sha": None, "entries": [], "dispatch_ids": [], "dispatch_meta": {},
            "local_held": {}, "ungroomed_ids": [], "read_at": None, "error": None,
        },
    )

    reader = threading.Thread(target=lambda: capture(lambda: server.read_entries(force=True)))
    reader.start()
    assert list_started.wait(1)
    refresher = threading.Thread(
        name="refresh-probe", target=lambda: capture(server.refresh_clone)
    )
    refresher.start()
    assert refresh_attempted.wait(1)
    assert not refresh_git_entered.is_set()

    release_list.set()
    reader.join(2)
    refresher.join(2)
    assert not reader.is_alive() and not refresher.is_alive()
    assert refresh_git_entered.is_set()
    assert errors == []


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
            "local_held": {},
            "ungroomed_ids": [],
        },
    )
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})

    board = server.board_payload()
    health = server.health_payload()

    assert board["freshness"]["clone_behind_origin"] == health["clone_behind_origin"] == 2
    assert board["freshness"]["local_ahead"] == health["local_ahead"] == 5


def test_local_and_mirror_claims_are_merged_and_classified():
    held = server.merge_held_claims(
        {
            "LOCAL": {"branch": "feat/local"},
            "BOTH": {"branch": "feat/local-both"},
        },
        {
            "MIRROR": {"branch": "feat/mirror"},
            "BOTH": {"branch": "feat/mirror-both"},
        },
    )

    assert held["LOCAL"]["sources"] == ["local"]
    assert held["MIRROR"]["sources"] == ["mirror"]
    assert held["BOTH"]["sources"] == ["local", "mirror"]
    assert held["BOTH"]["branch"] == "feat/local-both"

    payload = server.project(
        [_ticket(ticket_id) for ticket_id in ("LOCAL", "MIRROR", "BOTH")],
        held,
        canonical_dispatch_ids={"MIRROR"},
        canonical_ungroomed_ids=set(),
    )
    assert payload["counts"]["decision"]["inflight"] == 3
    assert payload["counts"]["held_sources"] == {"local": 1, "mirror": 1, "both": 1}
    assert payload["dispatch"] == []


def test_projection_consumes_canonical_ungroomed_ids_instead_of_reimplementing_groom():
    assert not hasattr(server, "READY_FIELDS")
    assert not hasattr(server, "is_ready")
    entries = [_ticket("CANONICAL-GROOMED", groomed=False), _ticket("CANONICAL-UNGROOMED")]
    payload = server.project(
        entries,
        canonical_dispatch_ids={"CANONICAL-GROOMED"},
        canonical_ungroomed_ids={"CANONICAL-UNGROOMED"},
    )
    by_id = {row["id"]: row for row in payload["board"]}

    assert by_id["CANONICAL-GROOMED"]["ready"] is True
    assert by_id["CANONICAL-UNGROOMED"]["ready"] is False
    assert payload["counts"]["decision"]["ungroomed"] == 1


def test_scope_matrix_marks_only_queued_tickets_with_active_file_collisions():
    scope = lambda *files: {
        "files": [
            {"path": path, "operation": operation}
            for path, operation in files
        ]
    }
    entries = [
        {**_ticket("ACTIVE"), "scope": scope(("ops/shared.py", "modify"))},
        {**_ticket("QUEUED-COLLISION"), "scope": scope(("ops/shared.py", "modify"))},
        {**_ticket("QUEUED-CLEAR"), "scope": scope(("ops/new.py", "add"))},
        {**_ticket("QUEUED-UNKNOWN"), "scope": "one file, details pending"},
        {**_ticket("QUEUED-SAME-QUEUE"), "scope": scope(("ops/queued.py", "modify"))},
    ]

    payload = server.project_scope_matrix(
        entries,
        {"ACTIVE": {"branch": "feat/active"}},
        canonical_dispatch_ids={
            "QUEUED-COLLISION", "QUEUED-CLEAR", "QUEUED-UNKNOWN", "QUEUED-SAME-QUEUE",
        },
    )

    worktrees = {row["id"]: row for row in payload["worktrees"]}
    assert worktrees["worktree:feat/active"]["kind"] == "ticketed"
    assert worktrees["worktree:feat/active"]["ticket_ids"] == ["ACTIVE"]
    queued = {row["id"]: row for row in payload["queued_tickets"]}
    assert queued["QUEUED-COLLISION"]["collision"] == {
        "status": "hard",
        "with_worktrees": ["worktree:feat/active"],
        "paths": ["ops/shared.py"],
    }
    assert queued["QUEUED-CLEAR"]["collision"] == {
        "status": "clear", "with_worktrees": [], "paths": [],
    }
    assert queued["QUEUED-SAME-QUEUE"]["collision"]["status"] == "clear"
    assert queued["QUEUED-UNKNOWN"]["scope_status"] == "unknown"
    assert queued["QUEUED-UNKNOWN"]["collision"] is None
    assert payload["unknown_ticket_ids"] == ["QUEUED-UNKNOWN"]

    shared = next(row for row in payload["files"] if row["path"] == "ops/shared.py")
    cells = {
        cell.get("ticket_id") or cell.get("worktree_id"): cell
        for cell in shared["cells"]
    }
    assert cells["worktree:feat/active"] == {
        "column_type": "worktree",
        "worktree_id": "worktree:feat/active",
        "ticket_ids": ["ACTIVE"],
        "operation": "modify",
        "operations": ["modify"],
        "state": "active",
        "collision": False,
    }
    assert cells["QUEUED-COLLISION"]["collision"] is True
    queued = next(row for row in payload["files"] if row["path"] == "ops/queued.py")
    assert queued["cells"] == [{
        "column_type": "ticket", "ticket_id": "QUEUED-SAME-QUEUE",
        "operation": "modify", "operations": ["modify"], "state": "queued",
        "collision": False,
    }]


def test_scope_matrix_does_not_turn_unknown_scope_into_unknown_collision():
    payload = server.project_scope_matrix(
        [{**_ticket("QUEUED"), "scope": "not a file list"}],
        {},
        canonical_dispatch_ids={"QUEUED"},
    )

    ticket = payload["queued_tickets"][0]
    assert ticket["scope_status"] == "unknown"
    assert ticket["collision"] is None
    assert payload["files"] == []


def test_scope_matrix_uses_worktrees_as_active_columns_and_groups_related_tickets():
    scope = lambda *files: {
        "schema": "kg.backlog.scope.v1",
        "files": [
            {"path": path, "operation": operation}
            for path, operation in files
        ],
    }
    entries = [
        {**_ticket("ACTIVE-ONE"), "scope": scope(("ops/shared.py", "modify"))},
        {**_ticket("ACTIVE-TWO"), "scope": scope(("ops/new.py", "add"))},
        {**_ticket("QUEUED"), "scope": scope(("ops/direct.py", "modify"))},
    ]
    refs = [
        {
            "branch": "feat/ticketed",
            "path": "/tmp/ticketed",
            "host": "oscar",
            "status": "active",
            "tickets": ["ACTIVE-ONE", "ACTIVE-TWO"],
        },
        {
            "branch": "feat/direct",
            "path": "/tmp/direct",
            "host": "oscar",
            "status": "active",
            "tickets": [],
            "scope": scope(("ops/direct.py", "modify")),
        },
    ]

    payload = server.project_scope_matrix(
        entries,
        {
            "ACTIVE-ONE": {"branch": "feat/ticketed"},
            "ACTIVE-TWO": {"branch": "feat/ticketed"},
        },
        canonical_dispatch_ids={"QUEUED"},
        worktree_refs=refs,
    )

    worktrees = {row["id"]: row for row in payload["worktrees"]}
    assert [row["kind"] for row in payload["worktrees"]] == ["ticketed", "direct"]
    assert worktrees["worktree:feat/ticketed"]["ticket_ids"] == ["ACTIVE-ONE", "ACTIVE-TWO"]
    assert worktrees["worktree:feat/ticketed"]["scope_status"] == "known"
    assert worktrees["worktree:feat/direct"]["ticket_ids"] == []
    assert worktrees["worktree:feat/direct"]["scope_status"] == "known"

    queued = payload["queued_tickets"][0]
    assert queued["id"] == "QUEUED"
    assert queued["collision"] == {
        "status": "hard",
        "with_worktrees": ["worktree:feat/direct"],
        "paths": ["ops/direct.py"],
    }
    assert payload["active_worktree_ids"] == [
        "worktree:feat/ticketed", "worktree:feat/direct",
    ]
    assert payload["queued_ticket_ids"] == ["QUEUED"]

    shared = next(row for row in payload["files"] if row["path"] == "ops/shared.py")
    assert shared["cells"] == [{
        "column_type": "worktree",
        "worktree_id": "worktree:feat/ticketed",
        "ticket_ids": ["ACTIVE-ONE"],
        "operation": "modify",
        "operations": ["modify"],
        "state": "active",
        "collision": False,
    }]


def test_scope_matrix_keeps_direct_worktree_visible_when_its_scope_is_unknown():
    payload = server.project_scope_matrix(
        [{**_ticket("QUEUED"), "scope": {"files": [{"path": "ops/x.py", "operation": "modify"}]} }],
        {},
        canonical_dispatch_ids={"QUEUED"},
        worktree_refs=[{
            "branch": "feat/direct",
            "path": "/tmp/direct",
            "status": "active",
            "tickets": [],
        }],
    )

    worktree = payload["worktrees"][0]
    assert worktree["kind"] == "direct"
    assert worktree["scope_status"] == "unknown"
    assert worktree["files"] == []
    assert payload["unknown_worktree_ids"] == ["worktree:feat/direct"]
    assert payload["queued_tickets"][0]["collision"] is None


def test_scope_matrix_projects_codex_thread_title_for_each_worktree():
    thread_id = "thread-agent-a"
    payload = server.project_scope_matrix(
        [],
        {},
        worktree_refs=[{
            "branch": "feat/direct",
            "path": "/tmp/direct",
            "status": "active",
            "tickets": [],
            "codex_thread_id": thread_id,
        }],
        thread_mirror={"threads": [{
            "thread_id": thread_id,
            "title": "交付看板 Agent",
            "role": "subagent",
            "status": "active",
        }]},
    )

    assert payload["worktrees"][0]["agent"] == {
        "thread_id": thread_id,
        "title": "交付看板 Agent",
        "role": "subagent",
        "status": "active",
    }


def test_one_agent_title_is_reused_across_direct_and_ticketed_worktrees():
    thread_id = "thread-shared"
    payload = server.project_scope_matrix(
        [{**_ticket("ACTIVE-TICKET"),
          "scope": {"files": [{"path": "ops/ticket.py", "operation": "modify"}]} }],
        {"ACTIVE-TICKET": {"branch": "feat/ticketed"}},
        worktree_refs=[
            {"branch": "feat/direct", "path": "/tmp/direct", "status": "active",
             "tickets": [], "codex_thread_id": thread_id},
            {"branch": "feat/ticketed", "path": "/tmp/ticketed", "status": "active",
             "tickets": [{"id": "ACTIVE-TICKET"}], "codex_thread_id": thread_id},
        ],
        thread_mirror={"threads": [{"thread_id": thread_id, "title": "同一 Agent",
                                     "status": "active"}]},
    )

    assert {row["agent"]["title"] for row in payload["worktrees"]} == {"同一 Agent"}
    assert {row["kind"] for row in payload["worktrees"]} == {"direct", "ticketed"}


def test_scope_matrix_falls_back_to_newer_claim_owner_when_git_tree_ref_is_stale():
    thread_id = "thread-newer-claim"
    payload = server.project_scope_matrix(
        [{**_ticket("ACTIVE-TICKET"),
          "scope": {"files": [{"path": "ops/ticket.py", "operation": "modify"}]}}],
        {"ACTIVE-TICKET": {
            "branch": "feat/ticketed", "codex_thread_id": thread_id,
        }},
        worktree_refs=[{
            "branch": "feat/ticketed", "path": "/tmp/ticketed", "status": "active",
            "tickets": ["ACTIVE-TICKET"],
        }],
        thread_mirror={"threads": [{"thread_id": thread_id, "title": "較新的 Agent",
                                     "status": "active"}]},
    )

    assert payload["worktrees"][0]["agent"] == {
        "thread_id": thread_id, "title": "較新的 Agent", "status": "active",
    }


def test_scope_matrix_payload_projects_direct_worktree_refs_from_git_tree(monkeypatch, tmp_path):
    scope = {"files": [{"path": "ops/direct.py", "operation": "modify"}]}
    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({
        "git_tree": {
            "complete": True,
            "refs": [{
                "branch": "feat/direct",
                "head": "abcdef0",
                "status": "active",
                "tickets": [],
                "scope": scope,
            }],
            "commits": [],
        },
    }), encoding="utf-8")
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(server, "read_entries", lambda: {
        "entries": [{**_ticket("QUEUED"), "scope": scope}],
        "dispatch_ids": ["QUEUED"],
        "local_held": {},
    })
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})

    payload = server.scope_matrix_payload()

    assert payload["schema"] == "kg.board.scope-matrix.v2"
    assert payload["worktrees"][0]["kind"] == "direct"
    assert payload["worktrees"][0]["scope_status"] == "known"
    assert payload["queued_tickets"][0]["collision"] == {
        "status": "hard",
        "with_worktrees": ["worktree:feat/direct"],
        "paths": ["ops/direct.py"],
    }


def test_scope_matrix_payload_surfaces_live_worktree_dirty_status(monkeypatch, tmp_path):
    mirror = tmp_path / "mirror.json"
    mirror.write_text(json.dumps({
        "git_tree": {
            "complete": True,
            "refs": [{
                "branch": "feat/direct", "head": "abcdef0", "status": "active",
                "tickets": [],
            }],
            "commits": [],
        },
        "worktree_status": {
            "schema": "kg.board.worktree-status.v1",
            "complete": True,
            "records": [{
                "branch": "feat/direct", "path": "/tmp/direct", "present": True,
                "dirty": True, "dirty_files": ["ops/direct.py"],
                "dirty_file_count": 1,
            }],
        },
    }), encoding="utf-8")
    monkeypatch.setattr(server, "MIRROR_PATH", mirror)
    monkeypatch.setattr(server, "read_entries", lambda: {
        "entries": [], "dispatch_ids": [], "local_held": {},
    })
    monkeypatch.setattr(server, "mirror_held_claims", lambda: {})
    monkeypatch.setattr(server, "freshness", lambda: {"freshness_state": "current"})

    payload = server.scope_matrix_payload()

    assert payload["worktrees"][0]["dirty"] is True
    assert payload["worktrees"][0]["dirty_file_count"] == 1


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

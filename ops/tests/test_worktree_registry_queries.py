"""Focused contract tests for compact worktree-registry list queries.

The legacy ``list --json`` payload remains the compatibility path.  Query flags
must instead filter the ledger before any live git/classifier work and return a
small, explicit projection suitable for coordinators reading large ledgers.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_registry_queries_target", ROOT / "ops" / "worktree_registry.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _record(tmp_path: Path, index: int, *, active: bool) -> dict[str, object]:
    status = "active" if active else "merged"
    path = tmp_path / f"wt-{index:02d}"
    record: dict[str, object] = {
        "path": str(path),
        "branch": f"feat/query-{index:02d}",
        "intent": f"query fixture {index}",
        "base": "main",
        "created_at": "2026-08-12T00:00:00+00:00",
        "status": status,
        "resolved_at": None if active else "2026-08-12T01:00:00+00:00",
        "backlog": [f"IMP-FIX-{index:02d}"] if active and index % 4 == 0 else [],
        "claimed_at": "2026-08-12T00:00:00+00:00" if active and index % 4 == 0 else None,
        "delegated": False,
    }
    if not active:
        record["handed_back_sha"] = f"deadbeef{index:02d}"
    return record


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    state = {
        "schema": MODULE.SCHEMA,
        "records": [_record(tmp_path, i, active=i % 2 == 0) for i in range(60)],
        "campaign_reservations": [],
    }
    path = tmp_path / "worktree_registry.json"
    path.write_text(json.dumps(state))
    return path


def _run(ledger: Path, *args: str) -> tuple[int, dict[str, object], str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = MODULE.main(["list", "--state", str(ledger), "--json", *args])
    raw = out.getvalue()
    return rc, json.loads(raw) if raw else {}, raw


def test_active_projection_and_no_liveness_skip_all_git_facts(ledger, monkeypatch):
    calls = 0

    def forbidden(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("--no-liveness must not build git facts")

    monkeypatch.setattr(MODULE, "build_facts", forbidden)
    rc, payload, raw = _run(
        ledger,
        "--active-only",
        "--no-liveness",
        "--fields",
        "branch,status,path",
    )

    assert rc == MODULE.EXIT_OK
    assert calls == 0
    assert payload["records"]
    assert len(payload["records"]) == 30
    assert all(item["status"] == "active" for item in payload["records"])
    assert all(set(item) == {"branch", "status", "path"} for item in payload["records"])
    assert all(Path(item["path"]).is_absolute() for item in payload["records"])
    assert "query" in payload
    assert len(raw) < 20_000


def test_exact_selectors_summary_and_fail_closed_negative_controls(ledger, monkeypatch):
    calls = 0

    def forbidden(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("selector query is explicitly no-liveness")

    monkeypatch.setattr(MODULE, "build_facts", forbidden)

    rc, payload, _ = _run(
        ledger,
        "--branch",
        "feat/query-22",
        "--no-liveness",
        "--fields",
        "branch,status",
    )
    assert rc == MODULE.EXIT_OK
    assert calls == 0
    assert [item["branch"] for item in payload["records"]] == ["feat/query-22"]

    rc, payload, _ = _run(ledger, "--summary", "--no-liveness")
    assert rc == MODULE.EXIT_OK
    assert payload["summary"] == {
        "active": 30,
        "held": 15,
        "handed_back": 30,
        "conflicts": [],
    }

    for invalid in (("--fields", "unknown"), ("--branch", "")):
        rc, _, raw = _run(ledger, *invalid)
        assert rc == MODULE.EXIT_USAGE
        assert "records" not in raw

    rc, _, raw = _run(ledger, "--summary", "--conflicts")
    assert rc == MODULE.EXIT_USAGE
    assert "records" not in raw


def test_active_only_classifies_only_the_filtered_records(ledger, monkeypatch):
    calls = 0

    def fake_facts(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {
            "landed_in_base": False,
            "name": kwargs.get("name"),
            "has_worktree": False,
        }

    monkeypatch.setattr(MODULE, "build_facts", fake_facts)
    monkeypatch.setattr(MODULE.ws, "classify", lambda facts: SimpleNamespace(value="ACTIVE"))
    rc, payload, _ = _run(ledger, "--active-only", "--fields", "branch,live_state")

    assert rc == MODULE.EXIT_OK
    assert calls == 30
    assert len(payload["records"]) == 30
    assert all(item["live_state"] == "ACTIVE" for item in payload["records"])


def test_slug_path_and_zero_match_selectors_are_exact(ledger, monkeypatch):
    monkeypatch.setattr(MODULE, "build_facts", lambda *args, **kwargs: pytest.fail("no-liveness expected"))
    rc, payload, _ = _run(
        ledger,
        "--slug",
        "query-22",
        "--path",
        str(ledger.parent / "wt-22"),
        "--no-liveness",
        "--fields",
        "slug,branch,path",
    )
    assert rc == MODULE.EXIT_OK
    assert payload["records"] == [{
        "slug": "query-22",
        "branch": "feat/query-22",
        "path": str((ledger.parent / "wt-22").resolve()),
    }]

    rc, payload, _ = _run(
        ledger,
        "--branch",
        "feat/query-does-not-exist",
        "--no-liveness",
        "--fields",
        "branch",
    )
    assert rc == MODULE.EXIT_OK
    assert payload["records"] == []


def test_conflicts_mode_returns_named_duplicate_claims_without_ledger_dump(ledger):
    state = json.loads(ledger.read_text())
    state["records"][4]["backlog"] = ["IMP-FIX-00"]
    ledger.write_text(json.dumps(state))

    rc, payload, raw = _run(ledger, "--conflicts", "--no-liveness")

    assert rc == MODULE.EXIT_OK
    assert payload["conflicts"] == [{
        "ticket": "IMP-FIX-00",
        "owners": [
            {"branch": "feat/query-00", "path": str((ledger.parent / "wt-00").resolve())},
            {"branch": "feat/query-04", "path": str((ledger.parent / "wt-04").resolve())},
        ],
    }]
    assert "records" not in payload
    assert "query fixture" not in raw


def test_legacy_list_json_shape_remains_unchanged_without_query_flags(ledger, monkeypatch):
    monkeypatch.setattr(MODULE, "build_facts", lambda *args, **kwargs: {
        "landed_in_base": True,
    })
    monkeypatch.setattr(MODULE.ws, "classify", lambda facts: SimpleNamespace(value="MERGED"))
    out = io.StringIO()
    with redirect_stdout(out):
        rc = MODULE.main(["list", "--state", str(ledger), "--json"])

    payload = json.loads(out.getvalue())
    assert rc == MODULE.EXIT_OK
    assert payload["schema"] == MODULE.SCHEMA
    assert "query" not in payload
    assert "campaign_reservations" in payload
    first = payload["records"][0]
    assert set(first) == {
        "path", "branch", "intent", "base", "created_at", "status", "resolved_at",
        "backlog", "claimed_at", "delegated", "live_state", "landed", "worktree_present",
    }

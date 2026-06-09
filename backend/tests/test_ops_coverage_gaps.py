"""Coverage-gap filler — batch tests for previously untested CLI subcommands.

These tests aim to *execute* every uncovered ops_edit / ops_cli entry point
at least once (happy path + one error path).  Quality assertions are minimal;
the goal is to eliminate "never called" lines so future refactors have baseline
coverage.  High-quality behavioural tests should replace these over time.
"""
from __future__ import annotations

import json
from pathlib import Path

from ops_helpers import run_ops_cli as _cli
from ops_helpers import run_ops_edit as _edit


def _mk_user(tmp_path: Path, uid: str = "demo") -> str:
    r = _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return uid


# ── ops_edit card commands ───────────────────────────────────────────────

class TestCardSetReview:
    def test_card_set_review_to_reviewed(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "apple", "--meaning", "蘋果",
                     "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-set-review", uid, "apple",
                  "--state", "reviewed", "--interval", "24",
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["result"]["card"]["content"] == "apple"

    def test_card_set_review_rejects_invalid_state(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-set-review", uid, "apple",
                  "--state", "bogus", "--commit", "--json")
        assert r.returncode != 0


class TestCardImport:
    def test_card_import_csv_happy_path(self, tmp_path):
        uid = _mk_user(tmp_path)
        csv = tmp_path / "import.csv"
        csv.write_text("content,meaning,pos,notebook\napple,蘋果,n.,default\n")
        r = _edit(str(tmp_path), "card-import", uid, str(csv),
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        # Key varies by version: 'imported', 'added', or 'actually_new'
        result = d.get("result", {})
        count = result.get("imported", result.get("added",
                       result.get("actually_new", 0)))
        assert count == 1

    def test_card_import_rejects_missing_file(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-import", uid, "/nonexistent.csv",
                  "--commit", "--json")
        assert r.returncode != 0


# ── ops_edit notebook commands ───────────────────────────────────────────

class TestNotebookCommands:
    def test_notebook_create_and_delete_roundtrip(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "notebook-create", uid, "TestNB",
                  "--color", "#ff0000", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        nb_id = json.loads(r.stdout)["result"]["notebook"]["id"]

        r2 = _edit(str(tmp_path), "notebook-update", uid, nb_id,
                   "--name", "Updated", "--commit", "--json")
        assert r2.returncode == 0, r2.stderr

        r3 = _edit(str(tmp_path), "notebook-delete", uid, nb_id,
                   "--commit", "--json")
        assert r3.returncode == 0, r3.stderr

    def test_notebook_delete_rejects_default(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "notebook-delete", uid, "default",
                  "--commit", "--json")
        assert r.returncode != 0


# ── ops_edit user commands ───────────────────────────────────────────────

class TestUserCommands:
    def test_user_create_already_exists_error(self, tmp_path):
        uid = "test_u1"
        r1 = _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
        assert r1.returncode == 0, r1.stderr
        r2 = _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
        # Second call should fail with "already exists"
        assert r2.returncode != 0
        assert "exists" in (r2.stdout + r2.stderr).lower()

    def test_list_backups_empty(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "list-backups", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        result = d.get("result", {})
        assert result.get("backups", []) == []

    def test_restore_rejects_missing_backup(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "restore", uid, "--backup", "bogus",
                  "--commit", "--json")
        assert r.returncode != 0


# ── ops_cli costs ────────────────────────────────────────────────────────

class TestCliCosts:
    def test_cost_empty_db(self, tmp_path):
        _mk_user(tmp_path)
        r = _cli(str(tmp_path), "cost", "demo", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["user_id"] == "demo"

    def test_fleet_overview_empty(self, tmp_path):
        r = _cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "users" in d
        assert d["count"] == 0


# ── ops_cli observability ────────────────────────────────────────────────

class TestCliObservability:
    def test_timeseries_empty(self, tmp_path):
        r = _cli(str(tmp_path), "timeseries", "cost", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "count" in d

    def test_trends_empty(self, tmp_path):
        r = _cli(str(tmp_path), "trends", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "days" in d

    def test_llm_errors_empty(self, tmp_path):
        r = _cli(str(tmp_path), "llm-errors", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "by_day" in d


# ── ops_cli queries (remaining gaps) ─────────────────────────────────────

class TestCliQueriesRemaining:
    def test_world_state_json(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _cli(str(tmp_path), "world-state", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["schema"] == "kg.ops_world_state.v1"

    def test_world_diff_no_spec(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _cli(str(tmp_path), "world-diff", uid, "/nonexistent.json")
        assert r.returncode != 0

    def test_sync_trace_empty(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _cli(str(tmp_path), "sync-trace", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "events" in d

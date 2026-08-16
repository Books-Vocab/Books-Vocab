"""Focused tests for the backlog query seam."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location(
    "backlog_query_under_test", OPS / "backlog_query.py"
)
assert SPEC and SPEC.loader
QUERY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUERY
SPEC.loader.exec_module(QUERY)


def test_query_seam_reads_entries_and_keeps_date_id_order(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "b.json").write_text(
        json.dumps({"id": "IMP-0002", "date": "2026-08-02"}), encoding="utf-8"
    )
    (store / "a.json").write_text(
        json.dumps({"id": "IMP-0001", "date": "2026-08-01"}), encoding="utf-8"
    )
    assert [entry["id"] for entry in QUERY.iter_entries(store)] == [
        "IMP-0001", "IMP-0002"
    ]
    assert QUERY.sort_key({"id": "IMP-0002", "date": "2026-08-02"}) > QUERY.sort_key(
        {"id": "IMP-0001", "date": "2026-08-01"}
    )


def test_query_facade_preserves_traversal_sort_and_refusal_contracts(tmp_path):
    class Error(Exception):
        pass

    entries = [{"id": "b", "date": "2026-08-02"}, {"id": "a", "date": "2026-08-01"}]
    deps = QUERY.QueryDeps(
        backlog_error=Error,
        iter_entries_fn=lambda _store: iter(entries),
        sort_key_fn=lambda payload: (payload["id"] == "a",),
        brief_fields=(),
        acceptance_green_expected="acceptance_green_expected",
        date_re=QUERY.re.compile(r"^\d{4}-\d{2}-\d{2}$"),
        today=lambda: "2026-08-16",
        days_before=lambda day, days: day,
        held_tickets=lambda: {},
        blocking_ids=lambda _payload: [],
        contract_preflight=lambda *_args, **_kwargs: [],
        worst_first_key=lambda payload: (payload["id"],),
    )
    assert [entry["id"] for entry in QUERY.list_entries(tmp_path, deps=deps)] == ["b", "a"]
    with pytest.raises(Error, match=r"--status fixed"):
        QUERY.list_entries(tmp_path, deps=deps, ungroomed=True, status="fixed")

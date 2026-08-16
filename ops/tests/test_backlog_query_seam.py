"""Focused tests for the backlog query seam."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


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

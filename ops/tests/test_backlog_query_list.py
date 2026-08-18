"""Focused tests for the backlog list/query contract.

The broad backlog suite remains responsible for the rest of the store and CLI
coverage. Keeping this bounded query seam in its own stdlib-only module makes
the focused acceptance command easier to inspect without changing product
code, fixtures, or backlog semantics.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKLOG_PATH = ROOT / "ops" / "backlog.py"
SPEC = importlib.util.spec_from_file_location(
    "backlog_query_list_under_test", BACKLOG_PATH)
assert SPEC and SPEC.loader
BACKLOG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BACKLOG
SPEC.loader.exec_module(BACKLOG)

DEFAULT_CATEGORY = {"IMP": "cli", "APP": "ux"}


def _entry_kwargs(**overrides):
    stream = overrides.get("stream", "IMP")
    base = dict(
        stream=stream,
        date="2026-08-05",
        source="test",
        # The two streams have disjoint category vocabularies, so the default
        # has to follow the stream or every APP case below would be rejected
        # for using an IMP category.
        category=DEFAULT_CATEGORY[stream],
        severity="med",
        status="open",
        detail="a tool reports success while doing nothing",
        resolution="",
    )
    base.update(overrides)
    return base


def _add(store: Path, **overrides) -> dict:
    return BACKLOG.add_entry(store, **_entry_kwargs(**overrides))


# --------------------------------------------------------------------------
# list / show
# --------------------------------------------------------------------------

def test_list_filters_by_status(tmp_path):
    store = tmp_path / "backlog"
    _add(store, detail="still broken", status="open")
    _add(store, detail="already handled", status="fixed")

    open_ids = [e["id"] for e in BACKLOG.list_entries(store, status="open")]
    assert len(open_ids) == 1
    assert BACKLOG.load_entry(store, open_ids[0])["detail"] == "still broken"


def test_list_filters_by_stream(tmp_path):
    store = tmp_path / "backlog"
    _add(store, stream="IMP", detail="tooling friction")
    _add(store, stream="APP", detail="reader loses scroll position")

    app = BACKLOG.list_entries(store, stream="APP")
    assert [e["detail"] for e in app] == ["reader loses scroll position"]


def test_list_filters_compose(tmp_path):
    store = tmp_path / "backlog"
    _add(store, stream="APP", severity="high", status="open", detail="data loss on sync")
    _add(store, stream="APP", severity="low", status="open", detail="label truncated")
    _add(store, stream="IMP", severity="high", status="open", detail="gate false green")

    hits = BACKLOG.list_entries(store, stream="APP", severity="high")
    assert [e["detail"] for e in hits] == ["data loss on sync"]


def test_list_is_deterministically_ordered(tmp_path):
    """Ordering must not depend on filesystem enumeration order, or the
    generated view churns between machines."""
    store = tmp_path / "backlog"
    for i in range(6):
        _add(store, detail=f"problem {i}", date=f"2026-08-0{i + 1}")

    once = [e["id"] for e in BACKLOG.list_entries(store)]
    twice = [e["id"] for e in BACKLOG.list_entries(store)]
    assert once == twice
    assert once == sorted(once, key=BACKLOG.entry_sort_key_by_id(store))


def test_list_on_empty_store_returns_empty(tmp_path):
    assert BACKLOG.list_entries(tmp_path / "does-not-exist") == []


def test_load_entry_raises_for_unknown_id(tmp_path):
    store = tmp_path / "backlog"
    _add(store)
    with pytest.raises(KeyError):
        BACKLOG.load_entry(store, "IMP-0404")

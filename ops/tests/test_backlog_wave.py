from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_wave import AnchorDeps, WaveDeps, cmd_anchor, cmd_unstage


def test_cmd_anchor_isolated_dry_run_needs_no_write_dependencies(tmp_path, capsys):
    entry_id = "IMP-20260816-abc123"
    rows = [{
        "id": entry_id,
        "verdict": "CONFIRMED-FIXED",
        "by": "agent:test",
        "evidence": "pytest -q",
        "status": "fixed",
        "landed_sha": "abc1234",
    }]
    queue = tmp_path / "backlog-queue.jsonl"
    store = tmp_path / "backlog-store"
    args = SimpleNamespace(
        queue=queue,
        store=store,
        branches=[],
        commit=False,
        json=True,
    )

    result = cmd_anchor(
        args,
        deps=AnchorDeps(
            queue_path=lambda explicit: explicit,
            queue_lock=lambda path: nullcontext(),
            read_queue=lambda path: rows,
            entry_path=lambda store, item_id: store / f"{item_id}.json",
            load_entry=lambda store, item_id: {"id": item_id, "status": "open"},
            validate_entry=lambda entry, **kwargs: [],
            closure_changes=lambda **kwargs: {},
            merged_and_validated=lambda current, changes, item_id: current,
        ),
    )

    assert result == 0
    payload = capsys.readouterr().out
    assert f'"would_apply": ["{entry_id}"]' in payload


def test_cmd_anchor_commit_requires_write_dependencies(tmp_path):
    args = SimpleNamespace(
        queue=tmp_path / "backlog-queue.jsonl",
        store=tmp_path / "backlog-store",
        branches=[],
        commit=True,
        json=True,
    )

    with pytest.raises(RuntimeError, match="complete queue"):
        cmd_anchor(
            args,
            deps=AnchorDeps(
                queue_path=lambda explicit: explicit,
                queue_lock=lambda path: nullcontext(),
                read_queue=lambda path: [],
                entry_path=lambda store, item_id: store / f"{item_id}.json",
                load_entry=lambda store, item_id: {},
                validate_entry=lambda entry, **kwargs: [],
                closure_changes=lambda **kwargs: {},
                merged_and_validated=lambda current, changes, item_id: current,
            ),
        )


def test_cmd_unstage_isolated_dry_run_does_not_write_queue(capsys):
    rows = [{"id": "IMP-20260816-abc123", "verdict": "CONFIRMED-OPEN"}]
    writes = []
    args = SimpleNamespace(
        id=rows[0]["id"],
        queue=Path("/tmp/backlog-queue.jsonl"),
        commit=False,
        json=True,
    )

    result = cmd_unstage(
        args,
        deps=WaveDeps(
            read_queue=lambda path: rows,
            write_queue=lambda path, next_rows: writes.append((path, next_rows)),
            queue_path=lambda explicit: explicit,
            queue_lock=lambda path: __import__("contextlib").nullcontext(),
        ),
    )

    assert result == 0
    assert writes == []
    assert '"mode": "dry-run"' in capsys.readouterr().out

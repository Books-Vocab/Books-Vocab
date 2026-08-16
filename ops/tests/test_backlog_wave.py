from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_wave import WaveDeps, cmd_unstage


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

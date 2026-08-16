from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_mutations import MutationDeps, cmd_groom, cmd_update


def test_cmd_update_isolated_dry_run_uses_injected_mutation_seams(capsys):
    entry = {"id": "IMP-20260816-abcdef", "status": "open", "severity": "med"}
    calls = []

    def merged(before, changes, entry_id, *, clear_fields=()):
        calls.append(("merge", before, changes, entry_id, clear_fields))
        return {**before, **changes}

    args = SimpleNamespace(
        command="update",
        id=entry["id"],
        store=Path("/tmp/backlog-test"),
        commit=False,
        json=True,
        status="triaged",
        _clear_fields=(),
    )
    result = cmd_update(
        args,
        deps=MutationDeps(
            root=Path("/tmp"),
            load_entry=lambda store, entry_id: entry,
            merged_and_validated=merged,
            gate_closure=lambda before, changes, commit: None,
            update_entry=lambda *a, **kw: calls.append(("write", a, kw)),
            mutable_fields=("status",),
            refused_update_fields=(),
            digest_fields=("stream",),
        ),
    )

    assert result == 0
    assert calls == [("merge", entry, {"status": "triaged"}, entry["id"], ())]
    assert '"mode": "dry-run"' in capsys.readouterr().out


def test_cmd_groom_threads_the_update_callback_and_stamps_triaged():
    args = SimpleNamespace(
        commit=False,
        store=Path("/tmp/backlog-test"),
        id="IMP-20260816-abcdef",
        acceptance_cmd="pytest -q",
        acceptance_manual="",
        groomed_against=None,
        acceptance_cmd_static=None,
        acceptance_expect_rc=None,
        acceptance_green_expected=None,
        groomed_at=None,
    )
    calls = []
    deps = MutationDeps(
        root=Path("/tmp"),
        load_entry=lambda store, entry_id: {"id": entry_id, "status": "open"},
        merged_and_validated=lambda *args, **kwargs: {},
        gate_closure=lambda *args: None,
        update_entry=lambda *args, **kwargs: {},
        mutable_fields=("status",),
        refused_update_fields=(),
        digest_fields=("stream",),
        held_tickets=lambda: {},
        today=lambda: "2026-08-16",
        update_command=lambda update_args, lock_held=False: calls.append(
            (update_args, lock_held)
        ) or 0,
    )

    assert cmd_groom(args, deps=deps) == 0
    assert calls[0][1] is False
    assert args.status == "triaged"
    assert args.groomed_at == "2026-08-16"
    assert args._clear_fields == (
        "acceptance_manual",
        "acceptance_cmd_static",
        "acceptance_expect_rc",
        "acceptance_green_expected",
    )

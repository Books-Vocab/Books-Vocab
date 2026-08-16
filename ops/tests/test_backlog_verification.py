from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_verification import VerificationDeps, cmd_verify


def test_cmd_verify_isolated_dry_run_uses_injected_validation_seams(capsys):
    entry = {"id": "IMP-20260816-123abc", "status": "open"}
    args = SimpleNamespace(
        static_only=False,
        verdict="CONFIRMED-OPEN",
        by="reviewer",
        evidence="the current source still reproduces it",
        at=None,
        status=None,
        fixed_by=None,
        fixed_elsewhere=False,
        contract_status=None,
        contract_baseline=None,
        contract_checked_at=None,
        contract_checked_by=None,
        contract_evidence=None,
        commit=False,
        json=True,
        id=entry["id"],
        store=Path("/tmp/backlog-test"),
    )

    result = cmd_verify(
        args,
        deps=VerificationDeps(
            load_entry=lambda store, entry_id: entry,
            closure_changes=lambda **changes: {
                "verdict": changes["verdict"],
                "by": changes["by"],
                "evidence": changes["evidence"],
            },
            merged_and_validated=lambda before, changes, entry_id: {
                **before,
                **changes,
            },
            gate_closure=lambda before, changes, commit: None,
            check_acceptance_cmd=lambda entry: [],
            run_static_acceptance=lambda entry_id, cmd: {},
            entry_path=lambda store, entry_id: store / f"{entry_id}.json",
            write_atomic=lambda path, text: None,
            dumps=lambda payload: "",
        ),
    )

    assert result == 0
    assert '"schema": "kg.backlog.verify.v1"' in capsys.readouterr().out

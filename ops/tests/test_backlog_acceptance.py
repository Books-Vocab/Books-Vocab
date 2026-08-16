from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_acceptance import AcceptanceDeps, acceptance_gate


def test_acceptance_gate_uses_injected_runner_without_importing_backlog(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="criterion passed\n", stderr="",
                               timed_out=False)

    result = acceptance_gate(
        {"id": "IMP-20260816-abcdef", "acceptance_cmd": "echo ok"},
        True,
        deps=AcceptanceDeps(root=tmp_path, run_streamed_command=runner),
    )

    assert result["kind"] == "ran"
    assert result["ok"] is True
    assert calls[0][0] == ["bash", "-c", "echo ok"]
    assert calls[0][1]["cwd"] == tmp_path

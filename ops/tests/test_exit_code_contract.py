"""Executable contract for the public KG ops exit-code vocabulary."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXIT_CODES = ROOT / "ops" / "lib" / "exit_codes.py"


def _load_exit_codes():
    spec = importlib.util.spec_from_file_location("kg_exit_codes", EXIT_CODES)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "ops")},
        check=False,
    )


def test_shared_vocabulary_is_stable_and_distinguishes_outcomes():
    codes = _load_exit_codes()

    assert codes.EXIT_OK == 0
    assert codes.EXIT_TOOL_ERROR == 1
    assert codes.EXIT_BLOCK == 2
    assert codes.EXIT_WARN == 3
    assert codes.EXIT_USAGE == 64
    assert codes.EXIT_CLAIMED == 75
    assert codes.EXIT_STRUCTURAL_BLOCK == 77
    # Existing registry callers use this name for an operational partial
    # failure; keep it as a compatibility alias for the tool-error class.
    assert codes.EXIT_PARTIAL == codes.EXIT_TOOL_ERROR


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (("bash", "ops/docs_lint.sh", "--not-a-real-option"), 64),
        (("bash", "ops/branch_audit.sh", "--not-a-real-option"), 64),
        ((sys.executable, "ops/app_review_gate.py", "--not-a-real-option"), 64),
        ((sys.executable, "ops/app_review_evidence.py", "--not-a-real-option"), 64),
        ((sys.executable, "ops/app_review_gate.py", "dry-run"), 64),
        (
            (
                sys.executable,
                "ops/app_review_evidence.py",
                "status",
                "--spec",
                "/tmp/kg-no-such-spec.json",
            ),
            1,
        ),
        (("bash", "ops/ios_ops.sh", "gate", "--not-a-real-option"), 64),
    ],
)
def test_invalid_invocation_is_usage_not_block_or_tool_error(command, expected):
    result = _run(*command)
    assert result.returncode == expected, (command, result.stdout, result.stderr)


@pytest.mark.parametrize(
    "command",
    [
        (shutil.which("bash") or "/bin/bash", "ops/branch_audit.sh", "--no-fetch"),
    ],
)
def test_missing_jq_is_tool_error_not_usage(command, tmp_path):
    # Do not assume /bin lacks jq: Ubuntu links /bin to /usr/bin and CI images
    # commonly install jq there.  An empty PATH is deterministic while the shell
    # executable itself is resolved before replacing PATH.
    env = {
        **os.environ,
        "PATH": str(tmp_path),
        "PYTHONPATH": str(ROOT / "ops"),
        "KG_BRANCH_AUDIT_ROOT": str(ROOT),
    }
    result = subprocess.run(
        list(command), cwd=ROOT, text=True, capture_output=True, env=env, check=False
    )
    assert result.returncode == 1, (command, result.stdout, result.stderr)


def test_shell_verdicts_use_block_two_and_warning_three():
    branch = (ROOT / "ops/branch_audit.sh").read_text(encoding="utf-8")
    docs = (ROOT / "ops/docs_lint.sh").read_text(encoding="utf-8")
    ios_release = (ROOT / "ops/lib/ios_ops_release.sh").read_text(encoding="utf-8")

    assert 'exit "$EXIT_BLOCK"' in branch
    assert 'exit "$EXIT_WARN"' in branch
    assert '[ "$errors" -gt 0 ] && exit "$EXIT_BLOCK"' in docs
    assert '[ "$warnings" -gt 0 ] && exit "$EXIT_WARN"' in docs
    assert 'then 2 elif .verdict=="warn" then 3 else 0 end' in ios_release


def test_structural_guard_exit_is_distinct_from_the_retryable_75():
    codes = _load_exit_codes()
    shell = (ROOT / "ops/lib/ios_disk_budget.sh").read_text(encoding="utf-8")

    # 75 means "temporary, retry"; a structural guard block never clears by
    # waiting, so the shell library must use the same 77 as the shared vocabulary.
    assert codes.EXIT_STRUCTURAL_BLOCK != codes.EXIT_CLAIMED
    assert f"KG_IOS_DISK_STRUCTURAL_EXIT={codes.EXIT_STRUCTURAL_BLOCK}" in shell
    assert f"KG_IOS_DISK_BUDGET_EXIT={codes.EXIT_CLAIMED}" in shell


def test_in_lock_preflight_callers_propagate_the_preflight_exit():
    # The in-lock preflight can return 77 (structural); a caller that discards its
    # rc and exits the hardcoded 75 turns a non-retryable block back into the
    # temporary code agents poll on.
    for script in ("ops/ios_build.sh", "ops/ios_test.sh", "ops/ios_release.sh"):
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "|| preflight_rc=$?" in text, script
        assert 'kg_ios_disk_budget_blocked_hint' in text, script
        assert '"$KG_IOS_DISK_BUDGET_EXIT"' not in text, script


def test_contract_test_is_registered_in_default_dispatch_and_ci_coverage():
    dispatcher = (ROOT / "ops/test_ops.sh").read_text(encoding="utf-8")
    coverage = (ROOT / "ops/tests/test_ops_ci_coverage.sh").read_text(encoding="utf-8")

    assert "exit-code-contract" in dispatcher
    assert "ops/tests/test_exit_code_contract.py" in dispatcher
    assert "exit-code-contract" in coverage

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "ops/tests/test_ops_ci_coverage.sh"


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def excluded_groups_from_source() -> list[str]:
    text = TABLE.read_text()
    body = text.split("EXCLUDED_GROUPS=(", 1)[1].split("\n)", 1)[0]
    groups: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        groups.append(line.split('"', 2)[1].split("|", 1)[0])
    return groups


def make_runner(tmp_path: Path, rc: int) -> Path:
    runner = tmp_path / "runner.sh"
    runner.write_text(f"#!/bin/sh\nexit {rc}\n")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    return runner


def test_print_excluded_groups_lists_every_exclusion() -> None:
    result = run("./ops/tests/test_ops_ci_coverage.sh", "--print-excluded-groups")
    assert result.returncode == 0, result.stderr
    got = [line for line in result.stdout.splitlines() if line]
    want = excluded_groups_from_source()
    assert got == want
    assert len(got) >= 9


def test_all_exclusions_failing_is_a_green_gate(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, 1)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert result.returncode == 0, result.stderr


def test_a_surviving_exclusion_turns_the_gate_red(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, 0)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert result.returncode == 1
    assert "gate-can-fail" in result.stderr
    assert "ios-ops" in result.stderr


def test_the_red_message_frames_the_result_as_a_hypothesis(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, 0)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert "假設不是判決" in result.stderr


def test_workflow_and_linux_repro_both_run_the_expected_fail_script() -> None:
    workflow = (ROOT / ".github/workflows/ops-suite.yml").read_text()
    repro = (ROOT / "ops/ci_linux_repro.sh").read_text()
    assert "ops/ci_expected_fail_exclusions.sh" in workflow
    assert "ops/ci_expected_fail_exclusions.sh" in repro


def test_coverage_gate_registers_the_expected_fail_test() -> None:
    dispatcher = (ROOT / "ops/test_ops.sh").read_text()
    section = dispatcher.split("ops-ci-coverage)", 1)[1].split(";;", 1)[0]
    assert "ops/tests/test_ci_expected_fail_exclusions.py" in section

from __future__ import annotations

import os
import shlex
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


def mac_groups_from_source() -> list[str]:
    text = TABLE.read_text()
    body = text.split("MAC_GROUPS=(", 1)[1].split("\n)", 1)[0]
    groups: list[str] = []
    for line in body.splitlines():
        groups.extend(line.split("#", 1)[0].split())
    return groups


def make_runner(
    tmp_path: Path,
    rc: int,
    *,
    invocation_log: Path | None = None,
) -> Path:
    runner = tmp_path / "runner.sh"
    lines = ["#!/bin/sh"]
    if invocation_log is not None:
        lines.append(f"printf '%s\\n' \"$1\" >> {shlex.quote(str(invocation_log))}")
    lines.append(f"exit {rc}")
    runner.write_text("\n".join(lines) + "\n")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    return runner


def test_print_mac_groups_lists_every_non_linux_group() -> None:
    result = run("./ops/tests/test_ops_ci_coverage.sh", "--print-mac-groups")
    assert result.returncode == 0, result.stderr
    got = [line for line in result.stdout.splitlines() if line]
    want = mac_groups_from_source()
    assert got == want
    assert len(got) == 3


def test_an_executed_expected_platform_failure_is_a_green_gate(tmp_path: Path) -> None:
    invocation_log = tmp_path / "invocations.log"
    runner = make_runner(tmp_path, 1, invocation_log=invocation_log)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert result.returncode == 0, result.stderr
    assert invocation_log.read_text().splitlines() == mac_groups_from_source()


def assert_runner_tool_error(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2
    assert "expected-fail runner tool error" in result.stderr


def test_a_missing_runner_is_a_tool_error(tmp_path: Path) -> None:
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(tmp_path / "missing-runner")}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert_runner_tool_error(result)


def test_an_unexecutable_runner_is_a_tool_error(tmp_path: Path) -> None:
    runner = tmp_path / "unexecutable-runner.sh"
    runner.write_text("#!/bin/sh\nexit 1\n")
    runner.chmod(0o644)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert_runner_tool_error(result)


def test_a_runner_that_fails_to_launch_is_a_tool_error(tmp_path: Path) -> None:
    runner = tmp_path / "broken-runner.sh"
    runner.write_text("#!/definitely/not/an/interpreter\n")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert_runner_tool_error(result)


def test_a_surviving_exclusion_turns_the_gate_red(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, 0)
    env = os.environ | {"KG_EXPECTED_FAIL_RUNNER": str(runner)}
    result = run("./ops/ci_expected_fail_exclusions.sh", env=env)
    assert result.returncode == 1
    assert "release" in result.stderr
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

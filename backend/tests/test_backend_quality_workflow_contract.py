"""Contract tests for the repository's backend quality workflow."""

from __future__ import annotations

import configparser
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/backend-quality.yml"
PYTEST_INI = ROOT / "backend/pytest.ini"
REGISTRY = ROOT / "docs/registry.yml"
STRATEGY = ROOT / "docs/reference/testing/backend_strategy.md"
TESTS_STEP = "Run backend tests and collect coverage"
# Every event that can start this workflow: its own push/schedule triggers plus
# the events of pr-gate, which reaches it through workflow_call.
TRIGGER_EVENTS = ("push", "schedule", "pull_request", "workflow_dispatch")
# pytest options that narrow which collected tests run. A lane that passes one
# of these is a different suite, not the same suite on a different trigger.
SELECTION_OPTIONS = (
    "-k",
    "-m",
    "--deselect",
    "--ignore",
    "--ignore-glob",
    "--lf",
    "--last-failed",
    "--ff",
    "--failed-first",
    "--sw",
    "--stepwise",
    "--nf",
    "--new-first",
)
_FAKE_UV = """\
import json
import os
import sys

with open(os.environ["KG_FAKE_UV_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
"""


def _event_block(workflow: str, event: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(event)}:\n(.*?)(?=^  (?:push|pull_request|schedule|permissions|jobs):|\Z)",
        workflow,
    )
    assert match, f"workflow must declare {event}"
    return match.group(1)


def _registry_entry(registry: str, entry_id: str) -> str:
    match = re.search(
        rf"(?ms)^  - id: {re.escape(entry_id)}\n(.*?)(?=^  - id: |\Z)",
        registry,
    )
    assert match, f"registry must declare {entry_id}"
    return match.group(1)


def _step_block(workflow: str, step_name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(step_name)}\n(.*?)(?=^      - name: |\Z)",
        workflow,
    )
    assert match, f"workflow must declare step {step_name}"
    return match.group(1)


def _step_run_script(workflow: str, step_name: str) -> str:
    match = re.search(
        r"(?ms)^        run: \|\n(.*?)(?=^        \S|\Z)",
        _step_block(workflow, step_name),
    )
    assert match, f"step {step_name} must use a literal run block"
    return textwrap.dedent(match.group(1))


def _is_selection_option(arg: str) -> bool:
    name = arg.split("=", 1)[0]
    if name in SELECTION_OPTIONS:
        return True
    # Attached short form: `-knot slow`, `-mslow`.
    return len(arg) > 2 and arg[:2] in {"-k", "-m"} and not arg.startswith("--")


def _dry_run_uv_calls(tmp_path: Path, step_name: str, event: str) -> list[list[str]]:
    """Execute a workflow step with `uv` replaced by a recorder.

    The step runs exactly as GitHub's `shell: bash` template runs it, so the
    recorded argv is what the runner would execute for ``event`` — including
    any branching on ``GITHUB_EVENT_NAME`` — without running the suite.
    """
    run_dir = tmp_path / event
    bin_dir = run_dir / "bin"
    bin_dir.mkdir(parents=True)
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(f"#!{sys.executable}\n{_FAKE_UV}", encoding="utf-8")
    fake_uv.chmod(0o755)
    script = run_dir / "step.sh"
    script.write_text(_step_run_script(WORKFLOW.read_text(encoding="utf-8"), step_name), encoding="utf-8")
    log = run_dir / "uv-calls.jsonl"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(run_dir),
        "GITHUB_EVENT_NAME": event,
        "COVERAGE_FILE": str(run_dir / "coverage" / ".coverage"),
        "KG_FAKE_UV_LOG": str(log),
    }
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=run_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _ci_pytest_argv(tmp_path: Path) -> dict[str, list[str]]:
    argv_by_event: dict[str, list[str]] = {}
    for event in TRIGGER_EVENTS:
        calls = _dry_run_uv_calls(tmp_path, TESTS_STEP, event)
        assert len(calls) == 1, f"{event}: the tests step must invoke uv exactly once, got {calls}"
        argv_by_event[event] = calls[0]
    return argv_by_event


def test_backend_quality_workflow_is_scoped_to_backend_changes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert re.search(r"(?m)^  workflow_call:\s*$", workflow)
    assert not re.search(r"(?m)^  pull_request:", workflow)

    push_paths = _event_block(workflow, "push")
    assert "paths:" in push_paths
    assert "backend/**" in push_paths
    assert ".github/workflows/backend-quality.yml" in push_paths


def test_backend_quality_workflow_uses_locked_module_form_toolchain() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pyproject = (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")

    assert "backend-quality:" in workflow
    assert "working-directory: backend" in workflow
    assert "uv sync --locked" in workflow
    assert "uv run python -m pytest -q" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run python -m coverage report --fail-under=85" in workflow
    assert "--cov=src/kg" in workflow
    assert '"pytest-cov' in pyproject
    assert '"ruff' in pyproject


def test_backend_ruff_is_pinned_in_project_lock_and_not_external_tool_cache() -> None:
    pyproject = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ruff==0.16.3" in pyproject["dependency-groups"]["dev"]
    ruff_package = next(package for package in lock["package"] if package["name"] == "ruff")
    assert ruff_package["version"] == "0.16.3"
    root_package = next(
        package for package in lock["package"] if package["name"] == "kg" and package["source"].get("editable") == "."
    )
    locked_ruff = next(
        requirement for requirement in root_package["metadata"]["requires-dev"]["dev"] if requirement["name"] == "ruff"
    )
    assert locked_ruff["specifier"] == "==0.16.3"
    assert "uv sync --locked" in workflow
    ruff_step = _step_block(workflow, "Run Ruff")
    run_lines = [line.strip() for line in ruff_step.splitlines() if line.strip().startswith("run:")]
    assert run_lines == ["run: uv run ruff check src tests"]


def test_backend_quality_artifact_carries_head_and_lock_identity() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for marker in (
        "git rev-parse HEAD",
        "git rev-parse HEAD:backend/uv.lock",
        "sha256sum backend/uv.lock",
        "HEAD_SHA",
        "LOCK_SHA256",
        "actions/upload-artifact",
        "backend-quality-${{ github.sha }}",
    ):
        assert marker in workflow


def test_backend_quality_artifact_is_fail_closed_and_coverage_is_runner_temp() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    upload = _step_block(workflow, "Upload backend quality evidence")

    assert "COVERAGE_FILE: ${{ runner.temp }}/backend-quality/.coverage" in workflow
    assert "test -s coverage.xml" in workflow
    assert "backend/coverage.xml" in upload
    assert "backend/ci-artifacts/" in upload
    assert "if-no-files-found: error" in upload
    assert ".coverage" not in upload


def test_backend_quality_runs_the_same_unselected_suite_on_every_trigger(tmp_path: Path) -> None:
    """Issue #2116: the nightly lane must not be a silently narrower suite.

    `-k "not slow"` matched test-ID substrings, not markers, and no test was
    marked slow, so the nightly fork only deselected the test guarding it.
    Evaluate the real step per event instead of matching its text.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "- cron:" in _event_block(workflow, "schedule")
    assert "PYTEST_ADDOPTS" not in workflow

    argv_by_event = _ci_pytest_argv(tmp_path)
    reference = argv_by_event["push"]
    assert reference[:4] == ["run", "python", "-m", "pytest"]
    for event, argv in argv_by_event.items():
        assert argv == reference, f"{event} runs a different backend suite than push: {argv} != {reference}"

    pytest_args = reference[4:]
    positional = [arg for arg in pytest_args if not arg.startswith("-")]
    assert not positional, f"CI must collect the configured testpaths, not {positional}"
    selection = [arg for arg in pytest_args if _is_selection_option(arg)]
    assert not selection, f"CI deselects tests: {selection}"

    ini = configparser.ConfigParser(interpolation=None)
    ini.read(PYTEST_INI, encoding="utf-8")
    addopts = shlex.split(ini.get("pytest", "addopts", fallback=""))
    ini_selection = [arg for arg in addopts if _is_selection_option(arg)]
    assert not ini_selection, f"pytest.ini addopts deselects tests: {ini_selection}"


def test_backend_quality_provenance_is_explicit() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    provenance = _step_block(workflow, "Capture backend quality provenance")

    for marker in (
        "python --version",
        "sys.executable",
        "PYTHON_VERSION",
        "PYTHON_EXECUTABLE",
    ):
        assert marker in provenance
    assert r'echo "- python --version: \`$python_version\`"' in provenance
    assert r'echo "- sys.executable: \`$python_executable\`"' in provenance
    assert '} >> "$GITHUB_STEP_SUMMARY"' in provenance


def test_backend_strategy_registry_covers_workflow_and_lock() -> None:
    registry = _registry_entry(
        REGISTRY.read_text(encoding="utf-8"),
        "reference.testing_backend_strategy",
    )

    assert ".github/workflows/backend-quality.yml" in registry
    assert "backend/uv.lock" in registry


def test_backend_strategy_documents_complete_quality_artifact() -> None:
    strategy = STRATEGY.read_text(encoding="utf-8")

    for marker in (
        "coverage.xml",
        "backend-quality-provenance.txt",
        "backend-quality-verdict.txt",
    ):
        assert marker in strategy


def test_backend_quality_does_not_turn_failures_into_success() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for marker in (
        "test-failure",
        "coverage-failure",
        "infrastructure-inconclusive",
        "steps.tests.outcome",
        "steps.coverage.outcome",
        "ruff-failure",
        "steps.ruff.outcome",
        "exit 1",
    ):
        assert marker in workflow

    verdict = workflow.split("name: Classify backend quality result", 1)[1]
    assert "continue-on-error: true" not in verdict.split("- name:", 1)[0]

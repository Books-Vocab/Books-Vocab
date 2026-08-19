"""Contract tests for the repository's backend quality workflow."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/backend-quality.yml"
REGISTRY = ROOT / "docs/registry.yml"
STRATEGY = ROOT / "docs/reference/testing/backend_strategy.md"


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
        package
        for package in lock["package"]
        if package["name"] == "kg" and package["source"].get("editable") == "."
    )
    locked_ruff = next(
        requirement
        for requirement in root_package["metadata"]["requires-dev"]["dev"]
        if requirement["name"] == "ruff"
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


def test_backend_quality_provenance_and_nightly_non_slow_lane_are_explicit() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    schedule = _event_block(workflow, "schedule")
    provenance = _step_block(workflow, "Capture backend quality provenance")

    assert "- cron:" in schedule
    assert 'GITHUB_EVENT_NAME" == "schedule"' in workflow
    assert 'uv run python -m pytest -q -k "not slow"' in workflow
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

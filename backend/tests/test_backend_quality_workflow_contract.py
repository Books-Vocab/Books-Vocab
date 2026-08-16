"""Contract tests for the repository's backend quality workflow."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/backend-quality.yml"


def _event_block(workflow: str, event: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(event)}:\n(.*?)(?=^  (?:push|pull_request|permissions|jobs):|\Z)",
        workflow,
    )
    assert match, f"workflow must declare {event}"
    return match.group(1)


def test_backend_quality_workflow_is_scoped_to_backend_changes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for event in ("push", "pull_request"):
        paths = _event_block(workflow, event)
        assert "paths:" in paths
        assert "backend/**" in paths
        assert ".github/workflows/backend-quality.yml" in paths


def test_backend_quality_workflow_uses_locked_module_form_toolchain() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pyproject = (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")

    assert "backend-quality:" in workflow
    assert "working-directory: backend" in workflow
    assert "uv sync --locked" in workflow
    assert "uv run python -m pytest -q" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run python -m coverage report" in workflow
    assert "--cov=src/kg" in workflow
    assert '"pytest-cov' in pyproject
    assert '"ruff' in pyproject


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


def test_backend_quality_does_not_turn_failures_into_success() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for marker in (
        "test-failure",
        "coverage-failure",
        "infrastructure-inconclusive",
        "steps.tests.outcome",
        "steps.coverage.outcome",
        "exit 1",
    ):
        assert marker in workflow

    verdict = workflow.split("name: Classify backend quality result", 1)[1]
    assert "continue-on-error: true" not in verdict.split("- name:", 1)[0]

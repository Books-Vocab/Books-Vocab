"""Executable contract for the repository's LLM-eval GitHub workflow.

The workflow is intentionally tested as data rather than by asking GitHub to
schedule a run.  This keeps trigger and command regressions local, while the
real workflow remains the only execution path in CI.
"""

from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent

import pytest
import yaml


_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = _ROOT / ".github" / "workflows" / "llm-eval.yml"
_WORKFLOW_PATH = ".github/workflows/llm-eval.yml"
_EVAL_PATH = "lab/llm_eval/**"
_FULL_SHA = re.compile(r"@[0-9a-f]{40}$")


def _load(text: str) -> dict:
    document = yaml.safe_load(text)
    assert isinstance(document, dict), "workflow must parse as a mapping"
    return document


def _workflow_errors(document: dict) -> list[str]:
    """Return named contract violations instead of hiding which guard fired."""
    errors: list[str] = []
    # PyYAML's YAML 1.1 resolver parses the unquoted ``on`` key as True.
    triggers = document.get("on", document.get(True))
    if not isinstance(triggers, dict):
        return ["on must define push and pull_request triggers"]

    for event in ("push", "pull_request"):
        config = triggers.get(event)
        paths = config.get("paths") if isinstance(config, dict) else None
        if not isinstance(paths, list):
            errors.append(f"{event} trigger must define paths")
            continue
        if _EVAL_PATH not in paths:
            errors.append(f"{event} trigger misses {_EVAL_PATH}")
        if _WORKFLOW_PATH not in paths:
            errors.append(f"{event} trigger misses {_WORKFLOW_PATH}")

    jobs = document.get("jobs")
    job = jobs.get("llm-eval") if isinstance(jobs, dict) else None
    if not isinstance(job, dict):
        return errors + ["jobs.llm-eval is required"]
    if job.get("runs-on") != "ubuntu-latest":
        errors.append("llm-eval job must run on ubuntu-latest")
    defaults = job.get("defaults")
    run_defaults = defaults.get("run") if isinstance(defaults, dict) else None
    if not isinstance(run_defaults, dict) or run_defaults.get("working-directory") != "lab/llm_eval":
        errors.append("llm-eval job must default run working-directory to lab/llm_eval")

    steps = job.get("steps")
    if not isinstance(steps, list):
        return errors + ["llm-eval job must define steps"]
    uses = [step.get("uses") for step in steps if isinstance(step, dict) and step.get("uses")]
    for action in uses:
        if not isinstance(action, str) or not _FULL_SHA.search(action):
            errors.append(f"external action is not pinned to a full SHA: {action!r}")
    if not any(isinstance(action, str) and action.startswith("actions/checkout@") for action in uses):
        errors.append("workflow must checkout the repository")
    if not any(isinstance(action, str) and action.startswith("astral-sh/setup-uv@") for action in uses):
        errors.append("workflow must install uv with setup-uv")

    run_commands = [
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run", ""), str)
    ]
    joined = "\n".join(run_commands)
    if not any("uv sync" in command and "--frozen" in command and "--extra dev" in command
               for command in run_commands):
        errors.append("workflow must install the frozen dev environment")
    if not any("pytest" in command and "tests/test_ci_contract.py" in command
               for command in run_commands):
        errors.append("workflow must run the CI contract test")
    if "lab/llm_eval" in joined and any("cd lab/llm_eval" in command for command in run_commands):
        errors.append("workflow must use the fixed working-directory, not a second cd")
    return errors


def test_llm_eval_workflow_contract_is_green():
    assert _WORKFLOW.is_file(), "the dedicated workflow must exist"
    assert _workflow_errors(_load(_WORKFLOW.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize(
    ("mutate", "expected_fragment"),
    [
        (
            lambda text: text.replace("      - 'lab/llm_eval/**'\n", "", 1),
            "trigger misses lab/llm_eval/**",
        ),
        (
            lambda text: text.replace("uv sync --frozen --extra dev", "uv sync --extra dev", 1),
            "frozen dev environment",
        ),
        (
            lambda text: text.replace(
                "uv run --frozen --extra dev pytest -q tests/test_ci_contract.py",
                "uv run --frozen --extra dev python -c 'pass'",
                1,
            ),
            "CI contract test",
        ),
    ],
)
def test_workflow_contract_detects_removed_guards(mutate, expected_fragment):
    text = _WORKFLOW.read_text(encoding="utf-8")
    errors = _workflow_errors(_load(mutate(text)))
    assert any(expected_fragment in error for error in errors), errors


def test_complete_minimal_workflow_is_accepted():
    sha_checkout = "1" * 40
    sha_uv = "2" * 40
    minimal = dedent(
        f"""
        name: llm-eval
        on:
          push:
            paths: &eval_paths
              - 'lab/llm_eval/**'
              - '.github/workflows/llm-eval.yml'
          pull_request:
            paths: *eval_paths
        jobs:
          llm-eval:
            runs-on: ubuntu-latest
            defaults:
              run:
                working-directory: lab/llm_eval
            steps:
              - uses: actions/checkout@{sha_checkout}
              - uses: astral-sh/setup-uv@{sha_uv}
              - run: uv sync --frozen --extra dev
              - run: uv run --frozen --extra dev pytest -q tests/test_ci_contract.py
        """
    )
    assert _workflow_errors(_load(minimal)) == []

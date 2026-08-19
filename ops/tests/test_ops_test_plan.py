from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "ops_test_plan.py"
SCHEMA = "kg.ops.test-plan.v1"


def run_plan(*paths: str, stdin: str | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *paths],
        cwd=ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    return result, payload


def test_python_and_shell_paths_get_exact_commands_without_execution() -> None:
    result, payload = run_plan(
        "ops/tests/test_alpha.py",
        "ops/tests/test_beta.sh",
    )

    assert result.returncode == 0, result.stderr
    assert payload == {
        "schema": SCHEMA,
        "status": "planned",
        "executed": False,
        "changedPaths": [
            "ops/tests/test_alpha.py",
            "ops/tests/test_beta.sh",
        ],
        "ignoredPaths": [],
        "fallback": False,
        "commands": [
            {
                "kind": "pytest",
                "paths": ["ops/tests/test_alpha.py"],
                "command": (
                    "uv run --no-project --python 3.13 --with pytest pytest -q "
                    "ops/tests/test_alpha.py"
                ),
                "reason": "exact pytest file",
            },
            {
                "kind": "shell",
                "paths": ["ops/tests/test_beta.sh"],
                "command": "./ops/tests/test_beta.sh",
                "reason": "direct shell test file",
            },
        ],
    }


def test_argv_and_stdin_are_sorted_and_duplicate_free() -> None:
    stdin_result, stdin_payload = run_plan(
        stdin="ops/tests/test_zeta.py\nops/tests/test_alpha.py\nops/tests/test_zeta.py\n"
    )
    argv_result, argv_payload = run_plan(
        "ops/tests/test_zeta.py",
        "ops/tests/test_alpha.py",
        "ops/tests/test_zeta.py",
    )

    assert stdin_result.returncode == argv_result.returncode == 0
    assert stdin_result.stdout == argv_result.stdout
    assert stdin_payload["changedPaths"] == [
        "ops/tests/test_alpha.py",
        "ops/tests/test_zeta.py",
    ]
    assert [item["paths"] for item in stdin_payload["commands"]] == [
        ["ops/tests/test_alpha.py"],
        ["ops/tests/test_zeta.py"],
    ]


def test_ui_world_manifest_asset_gets_validation_route() -> None:
    result, payload = run_plan("ops/fixtures/ui_worlds/marketing_demo.json")

    assert result.returncode == 0, result.stderr
    assert payload["fallback"] is False
    assert payload["ignoredPaths"] == []
    assert payload["commands"] == [
        {
            "kind": "ui-fixture-validation",
            "paths": ["ops/fixtures/ui_worlds/marketing_demo.json"],
            "command": (
                "uv run --no-project --python 3.13 python "
                "ops/ui_world_manifest.py validate "
                "ops/fixtures/ui_worlds/marketing_demo.json"
            ),
            "reason": "UI World fixture validation route",
        }
    ]


def test_ui_world_manifest_runtime_gets_validation_route() -> None:
    result, payload = run_plan("ops/ui_world_manifest.py")

    assert result.returncode == 0, result.stderr
    assert payload["fallback"] is False
    assert any(
        command["kind"] == "ui-fixture-validation"
        and "ops/ui_world_manifest.py validate" in command["command"]
        for command in payload["commands"]
    )


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ops-suite.yml",
        "ops/test_ops.sh",
        "ops/ci_scope_router.sh",
    ],
)
def test_central_or_workflow_paths_use_complete_ops_fallback(path: str) -> None:
    result, payload = run_plan(path)

    assert result.returncode == 0, result.stderr
    assert payload["fallback"] is True
    assert len(payload["commands"]) == 1
    command = payload["commands"][0]
    assert command["kind"] == "ops-fallback"
    assert command["paths"] == [path]
    assert command["command"] == "./ops/test_ops.sh"
    assert "complete ops fallback" in command["reason"]


def test_unknown_ops_runtime_uses_fallback_with_reason() -> None:
    result, payload = run_plan("ops/new_runtime.py")

    assert result.returncode == 0, result.stderr
    assert payload["fallback"] is True
    assert payload["commands"][0]["kind"] == "ops-fallback"
    assert payload["commands"][0]["command"] == "./ops/test_ops.sh"
    assert "unknown ops runtime" in payload["commands"][0]["reason"]


def test_non_ops_paths_do_not_generate_commands() -> None:
    result, payload = run_plan(
        "backend/src/kg/app.py",
        "docs/reference/testing/smoke_checklist.md",
        "ios/BooksAndVocab/App.swift",
    )

    assert result.returncode == 0, result.stderr
    assert payload["fallback"] is False
    assert payload["commands"] == []
    assert payload["ignoredPaths"] == [
        "backend/src/kg/app.py",
        "docs/reference/testing/smoke_checklist.md",
        "ios/BooksAndVocab/App.swift",
    ]


@pytest.mark.parametrize("invocation", [{"paths": (), "stdin": ""}, {"paths": ("../outside.py",)}])
def test_invalid_input_returns_machine_readable_error(invocation: dict) -> None:
    result, payload = run_plan(*invocation["paths"], stdin=invocation.get("stdin", ""))

    assert result.returncode == 2
    assert payload["schema"] == SCHEMA
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "input-error"
    assert payload["error"]["message"]

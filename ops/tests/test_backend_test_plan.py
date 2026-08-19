from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = OPS_ROOT / "backend_test_plan.py"
SPEC = importlib.util.spec_from_file_location("backend_test_plan", SCRIPT)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)

FULL_COMMAND = ["uv", "run", "--locked", "python", "-m", "pytest", "-q"]


def _run_cli(argv: list[str], stdin_text: str = "") -> tuple[int, str, dict[str, object]]:
    output = io.StringIO()
    returncode = planner.main(argv, stdin=io.StringIO(stdin_text), stdout=output)
    rendered = output.getvalue()
    return returncode, rendered, json.loads(rendered)


def test_single_backend_test_file_uses_exact_pytest_file_selector() -> None:
    plan = planner.plan_changed_paths(["backend/tests/test_cards.py"])

    assert plan["schema"] == "kg.backend.test-plan.v1"
    assert plan["status"] == "planned"
    assert plan["plan_kind"] == "targeted"
    assert plan["changed_paths"] == ["backend/tests/test_cards.py"]
    assert plan["selectors"] == ["tests/test_cards.py"]
    assert plan["command"] == [*FULL_COMMAND, "tests/test_cards.py"]
    assert plan["cwd"] == "backend"
    assert plan["reason"] == "backend-test-files-only"


def test_multiple_test_files_are_sorted_and_deduplicated() -> None:
    plan = planner.plan_changed_paths(
        [
            "backend/tests/test_zeta.py",
            "./backend/tests/test_alpha.py",
            "backend/tests/test_zeta.py",
        ]
    )

    assert plan["changed_paths"] == [
        "backend/tests/test_alpha.py",
        "backend/tests/test_zeta.py",
    ]
    assert plan["selectors"] == [
        "tests/test_alpha.py",
        "tests/test_zeta.py",
    ]
    assert plan["command"] == [*FULL_COMMAND, "tests/test_alpha.py", "tests/test_zeta.py"]


def test_backend_source_change_falls_back_without_source_to_test_map() -> None:
    plan = planner.plan_changed_paths(["backend/src/kg/cards.py"])

    assert plan["plan_kind"] == "full"
    assert plan["command"] == FULL_COMMAND
    assert plan["selectors"] == []
    assert plan["reason"] == "backend-source-changed-no-source-to-test-map"


@pytest.mark.parametrize(
    "changed_path",
    ["backend/pyproject.toml", "backend/pytest.ini", "backend/uv.lock"],
)
def test_backend_runtime_config_change_uses_full_acceptance_command(changed_path: str) -> None:
    plan = planner.plan_changed_paths([changed_path])

    assert plan["plan_kind"] == "full"
    assert plan["command"] == FULL_COMMAND
    assert plan["reason"] == "backend-runtime-or-test-config-changed"


def test_backend_workflow_change_uses_full_acceptance_command() -> None:
    plan = planner.plan_changed_paths([".github/workflows/backend-quality.yml"])

    assert plan["plan_kind"] == "full"
    assert plan["command"] == FULL_COMMAND
    assert plan["reason"] == "backend-runtime-or-test-config-changed"


@pytest.mark.parametrize("changed_path", ["ios/BooksAndVocab/App.swift", "pyproject.toml"])
def test_non_backend_change_does_not_produce_backend_command(changed_path: str) -> None:
    plan = planner.plan_changed_paths([changed_path])

    assert plan["plan_kind"] == "none"
    assert plan["command"] is None
    assert plan["selectors"] == []
    assert plan["reason"] == "no-backend-paths"


def test_unknown_backend_path_fails_closed_to_full_fallback() -> None:
    plan = planner.plan_changed_paths(["backend/scripts/new_runtime_entry.py"])

    assert plan["plan_kind"] == "full"
    assert plan["command"] == FULL_COMMAND
    assert plan["reason"] == "unknown-backend-path-fail-closed"


def test_nested_backend_test_path_is_unknown_and_fails_closed() -> None:
    plan = planner.plan_changed_paths(["backend/tests/routers/test_library.py"])

    assert plan["plan_kind"] == "full"
    assert plan["command"] == FULL_COMMAND
    assert plan["reason"] == "unknown-backend-path-fail-closed"


def test_cli_accepts_argv_and_emits_deterministic_json() -> None:
    first_rc, first_text, first = _run_cli(
        [
            "backend/tests/test_zeta.py",
            "backend/tests/test_alpha.py",
            "backend/tests/test_alpha.py",
        ]
    )
    second_rc, second_text, second = _run_cli(
        ["backend/tests/test_alpha.py", "backend/tests/test_zeta.py"]
    )

    assert first_rc == second_rc == 0
    assert first_text == second_text
    assert first == second


def test_cli_accepts_newline_delimited_stdin() -> None:
    returncode, _, payload = _run_cli(
        ["--paths-stdin"],
        "backend/tests/test_b.py\nbackend/tests/test_a.py\n",
    )

    assert returncode == 0
    assert payload["selectors"] == ["tests/test_a.py", "tests/test_b.py"]
    assert payload["command"] == [*FULL_COMMAND, "tests/test_a.py", "tests/test_b.py"]


def test_cli_reports_invalid_input_as_machine_readable_error() -> None:
    returncode, _, payload = _run_cli(
        ["--paths-stdin"],
        "../backend/tests/test_cards.py\n",
    )

    assert returncode == 2
    assert payload == {
        "command": None,
        "cwd": "backend",
        "error": "path traversal is not allowed: ../backend/tests/test_cards.py",
        "plan_kind": "error",
        "reason": "invalid-input",
        "schema": "kg.backend.test-plan.v1",
        "status": "error",
    }


def test_plan_rejects_empty_changed_path() -> None:
    with pytest.raises(planner.InputFormatError, match="changed path must not be empty"):
        planner.plan_changed_paths([""])

"""Focused tests for backlog acceptance-contract helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location(
    "backlog_contract_under_test", OPS / "backlog_contract.py"
)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONTRACT
SPEC.loader.exec_module(CONTRACT)


def test_contract_helpers_extract_repository_paths_without_shell_parsing():
    assert CONTRACT.site_paths("ops/backlog.py:10; docs/runbook/backlog/X.json") == [
        "ops/backlog.py", "docs/runbook/backlog/X.json"
    ]
    assert CONTRACT.command_paths("uv run pytest ops/tests/test_backlog.py") == [
        "ops/tests/test_backlog.py"
    ]


def test_selector_helpers_are_pure_and_reject_compound_commands():
    assert CONTRACT.pytest_selector_probe("uv run pytest -k test_store") == [
        "uv", "run", "pytest", "--collect-only", "-k", "test_store"
    ]
    assert CONTRACT.pytest_selector_probe("pytest -k test_store && rm -rf /") is None
    assert CONTRACT.pytest_collected_count("2/9 tests collected") == 2
    assert CONTRACT.pytest_collected_count("no tests collected") == 0


def test_preflight_reports_unhashable_contract_values_instead_of_raising(tmp_path):
    common = {
        "status": "triaged",
        "groomed_at": "2026-08-16",
        "contract_evidence": "observed red",
        "contract_checked_at": "2026-08-16",
        "contract_checked_by": "test",
        "fix_site": "ops/backlog.py:1",
        "acceptance_cmd": "true",
    }
    for field, value in (("contract_status", []), ("contract_baseline", {})):
        payload = {**common, field: value}
        problems = CONTRACT.preflight(
            payload,
            repo=tmp_path,
            default_root=tmp_path,
            required_since="2026-08-10",
            contract_fields=("contract_status", "contract_baseline"),
            contract_statuses=("ready", "blocked"),
            contract_baselines=("red", "no-op", "unknown"),
        )
        assert problems and all(isinstance(problem, dict) for problem in problems)


def _groomed_payload(*, scope_files, fix_site, acceptance_cmd):
    return {
        "id": "IMP-20260818-guard00",
        "status": "triaged",
        "groomed_at": "2026-08-18",
        "contract_status": "ready",
        "contract_baseline": "red",
        "contract_evidence": "baseline=RED; add-only admission contract",
        "contract_checked_at": "2026-08-18",
        "contract_checked_by": "test",
        "scope": {"schema": "kg.backlog.scope.v1", "files": scope_files},
        "fix_site": fix_site,
        "acceptance_cmd": acceptance_cmd,
    }


def test_preflight_allows_missing_paths_declared_as_add(tmp_path):
    payload = _groomed_payload(
        scope_files=[
            {"path": "ops/new_fix.py", "operation": "add"},
            {"path": "ops/tests/test_new_fix.py", "operation": "add"},
        ],
        fix_site="ops/new_fix.py:1",
        acceptance_cmd="uv run pytest ops/tests/test_new_fix.py",
    )

    assert CONTRACT.preflight(
        payload,
        repo=tmp_path,
        default_root=tmp_path,
        required_since="2026-08-10",
        contract_fields=("contract_status", "contract_baseline"),
        contract_statuses=("ready", "blocked"),
        contract_baselines=("red", "no-op", "unknown"),
    ) == []


def test_preflight_keeps_undeclared_or_modify_missing_paths_blocked(tmp_path):
    payload = _groomed_payload(
        scope_files=[
            {"path": "ops/existing_fix.py", "operation": "modify"},
            {"path": "ops/tests/test_declared.py", "operation": "add"},
            {"path": "ops/tests/test_modify.py", "operation": "modify"},
        ],
        fix_site="ops/missing_fix.py:1",
        acceptance_cmd=(
            "uv run pytest ops/tests/test_declared.py "
            "ops/tests/test_modify.py ops/tests/test_undeclared.py"
        ),
    )

    problems = CONTRACT.preflight(
        payload,
        repo=tmp_path,
        default_root=tmp_path,
        required_since="2026-08-10",
        contract_fields=("contract_status", "contract_baseline"),
        contract_statuses=("ready", "blocked"),
        contract_baselines=("red", "no-op", "unknown"),
    )

    assert {problem["kind"] for problem in problems} == {
        "fix-site-missing",
        "acceptance-dependency-missing",
    }
    assert {problem["path"] for problem in problems} == {
        "ops/missing_fix.py",
        "ops/tests/test_modify.py",
        "ops/tests/test_undeclared.py",
    }


def test_preflight_keeps_non_literal_add_paths_blocked(tmp_path):
    payload = _groomed_payload(
        scope_files=[
            {"path": "ops/new_fix*.py", "operation": "add"},
            {"path": "ops/tests/test_new.py", "operation": "add"},
        ],
        fix_site="ops/new_fix*.py:1",
        acceptance_cmd="uv run pytest ops/tests/test_new.py",
    )

    problems = CONTRACT.preflight(
        payload,
        repo=tmp_path,
        default_root=tmp_path,
        required_since="2026-08-10",
        contract_fields=("contract_status", "contract_baseline"),
        contract_statuses=("ready", "blocked"),
        contract_baselines=("red", "no-op", "unknown"),
    )

    assert problems == [{"kind": "fix-site-missing", "path": "ops/new_fix*.py"}]


def test_preflight_does_not_exempt_add_paths_when_scope_is_invalid(tmp_path):
    payload = _groomed_payload(
        scope_files=[
            {"path": "ops/new_fix.py", "operation": "add"},
            {"path": "ops/tests/test_new.py", "operation": "add"},
        ],
        fix_site="ops/new_fix.py:1",
        acceptance_cmd="uv run pytest ops/tests/test_new.py",
    )
    payload["scope"]["schema"] = "kg.backlog.scope.invalid"

    problems = CONTRACT.preflight(
        payload,
        repo=tmp_path,
        default_root=tmp_path,
        required_since="2026-08-10",
        contract_fields=("contract_status", "contract_baseline"),
        contract_statuses=("ready", "blocked"),
        contract_baselines=("red", "no-op", "unknown"),
    )

    assert {problem["kind"] for problem in problems} == {
        "fix-site-missing",
        "acceptance-dependency-missing",
    }


def test_preflight_does_not_exempt_traversal_paths_from_invalid_scope(tmp_path):
    payload = _groomed_payload(
        scope_files=[
            {"path": "../outside.py", "operation": "add"},
            {"path": "ops/tests/test_new.py", "operation": "add"},
        ],
        fix_site="../outside.py:1",
        acceptance_cmd="uv run pytest ops/tests/test_new.py",
    )

    problems = CONTRACT.preflight(
        payload,
        repo=tmp_path,
        default_root=tmp_path,
        required_since="2026-08-10",
        contract_fields=("contract_status", "contract_baseline"),
        contract_statuses=("ready", "blocked"),
        contract_baselines=("red", "no-op", "unknown"),
    )

    assert {problem["kind"] for problem in problems} == {
        "fix-site-missing",
        "acceptance-dependency-missing",
    }

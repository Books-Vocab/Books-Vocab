from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_cost_fingerprint as fingerprint


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True,
        capture_output=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "audit-test")
    (tmp_path / "ops" / "fixtures" / "ui_worlds").mkdir(parents=True)
    (tmp_path / "ios" / "BooksAndVocabUITests").mkdir(parents=True)
    (tmp_path / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").write_text(
        '{"schema":"fixture"}\n', encoding="utf-8",
    )
    (tmp_path / "ios" / "BooksAndVocabUITests" / "FixtureDatasetUITests.swift").write_text(
        "final class FixtureDatasetUITests {\n"
        "    func testReviewCalendarRequiredEvidenceUsesStableSelectors() {}\n"
        "}\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def _ui_ticket(command: str) -> dict:
    return {
        "id": "APP-UI-001",
        "fix_site": "ios/BooksAndVocabUITests/FixtureDatasetUITests.swift",
        "scope": {
            "files": [{
                "path": "ios/BooksAndVocabUITests/FixtureDatasetUITests.swift",
                "operation": "modify",
            }],
        },
        "acceptance_cmd": command,
        "gate_tier": "S1",
    }


def test_audit_finds_full_ui_group_and_missing_precise_selector(git_repo: Path) -> None:
    report = fingerprint.audit_acceptance(
        _ui_ticket("./ops/ios_ops.sh test --ui --dataset marketing_demo --list"),
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )
    codes = {finding["code"] for finding in report["findings"]}

    assert "unnecessary-full-test-group" in codes
    assert "ui-ticket-missing-precise-selector" in codes
    assert "missing-test-scope-selector" in codes
    assert report["ticket_mutated"] is False


def test_precise_ui_selector_has_no_scope_finding(git_repo: Path) -> None:
    report = fingerprint.audit_acceptance(
        _ui_ticket(
            "./ops/ios_ops.sh test --ui --dataset marketing_demo "
            "-g FixtureDatasetUITests --list"
        ),
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )
    codes = {finding["code"] for finding in report["findings"]}

    assert "ui-ticket-missing-precise-selector" not in codes
    assert "missing-test-scope-selector" not in codes


def test_precise_pytest_file_is_an_equivalent_ui_selector(git_repo: Path) -> None:
    report = fingerprint.audit_acceptance(
        _ui_ticket("pytest -q tests/test_feature.py"),
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )
    codes = {finding["code"] for finding in report["findings"]}

    assert "ui-ticket-missing-precise-selector" not in codes


def test_specific_ios_method_is_an_equivalent_precise_selector(git_repo: Path) -> None:
    report = fingerprint.audit_acceptance(
        _ui_ticket(
            "./ops/ios_ops.sh test --ui --dataset marketing_demo "
            "testReviewCalendarRequiredEvidenceUsesStableSelectors --list"
        ),
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )
    codes = {finding["code"] for finding in report["findings"]}

    assert "ui-ticket-missing-precise-selector" not in codes
    assert "missing-test-scope-selector" not in codes


def test_audit_blocks_reuse_of_old_head_fixture_and_test_definition(git_repo: Path) -> None:
    ticket = _ui_ticket(
        "./ops/ios_ops.sh test --ui --dataset marketing_demo "
        "-g FixtureDatasetUITests --list"
    )
    current = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["ios/BooksAndVocabUITests/FixtureDatasetUITests.swift"],
        acceptance_command=ticket["acceptance_cmd"],
        test_definitions=["ios/BooksAndVocabUITests/FixtureDatasetUITests.swift"],
        fixtures=["ops/fixtures/ui_worlds/marketing_demo.json"],
        scope=ticket["scope"],
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )
    previous = copy.deepcopy(current)
    previous["head_sha"] = "0" * 40
    previous["fixture_digest"] = "1" * 64
    previous["test_definition_digest"] = "2" * 64
    ticket["gate_fingerprint"] = previous
    ticket["verdict"] = "pass"
    before = json.dumps(ticket, sort_keys=True)

    report = fingerprint.audit_acceptance(
        ticket,
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )
    codes = {finding["code"] for finding in report["findings"]}

    assert {"stale-head", "stale-fixture", "stale-test-definition"} <= codes
    assert report["verdict_reuse"]["allowed"] is False
    assert json.dumps(ticket, sort_keys=True) == before


def test_audit_refuses_prior_verdict_without_identity_fingerprint(git_repo: Path) -> None:
    ticket = _ui_ticket("pytest -q tests/test_feature.py")
    ticket.update({"verdict": "pass", "verified_evidence": "old gate evidence"})

    report = fingerprint.audit_acceptance(
        ticket,
        repo=git_repo,
        toolchain={"xcode": "unavailable"},
    )

    assert any(
        finding["code"] == "verdict-fingerprint-missing"
        for finding in report["findings"]
    )
    assert report["verdict_reuse"]["allowed"] is False


def test_audit_refuses_incomplete_prior_fingerprint(git_repo: Path) -> None:
    ticket = _ui_ticket("pytest -q tests/test_feature.py")
    current = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["ios/BooksAndVocabUITests/FixtureDatasetUITests.swift"],
        acceptance_command=ticket["acceptance_cmd"],
        test_definitions=["ios/BooksAndVocabUITests/FixtureDatasetUITests.swift"],
        fixtures=["ops/fixtures/ui_worlds/marketing_demo.json"],
        scope=ticket["scope"],
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )
    current.pop("exact_head")
    ticket["gate_fingerprint"] = current

    report = fingerprint.audit_acceptance(
        ticket,
        repo=git_repo,
        toolchain={"xcode": "Xcode 26.4"},
    )

    assert any(
        finding["code"] == "fingerprint-fields-missing"
        for finding in report["findings"]
    )
    assert report["verdict_reuse"]["allowed"] is False

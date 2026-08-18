from __future__ import annotations

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
    _git(tmp_path, "config", "user.name", "fingerprint-test")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert True\n", encoding="utf-8",
    )
    (tmp_path / "fixtures" / "case.json").write_text(
        json.dumps({"case": "one"}) + "\n", encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def test_fingerprint_contains_all_cost_identity_inputs(git_repo: Path) -> None:
    head = _git(git_repo, "rev-parse", "HEAD")
    result = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py -k feature",
        test_definitions=["tests/test_feature.py"],
        fixtures=["fixtures/case.json"],
        scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4", "python": "3.13.7"},
    )

    assert result["schema"] == fingerprint.FINGERPRINT_SCHEMA
    assert result["head_sha"] == head
    assert result["gate_tier"] == "S1"
    assert result["scope"] == {
        "schema": "kg.backlog.scope.v1",
        "files": [{"path": "src/feature.py", "operation": "modify"}],
    }
    for key in (
        "changed_file_digest", "acceptance_command_digest",
        "test_definition_digest", "fixture_digest", "fingerprint_digest",
    ):
        assert len(result[key]) == 64
    assert result["toolchain"] == {"xcode": "Xcode 26.4", "python": "3.13.7"}


def test_file_and_definition_digests_change_without_reusing_head(git_repo: Path) -> None:
    before = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py -k feature",
        test_definitions=["tests/test_feature.py"],
        fixtures=["fixtures/case.json"],
        scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )
    (git_repo / "src" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    (git_repo / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert 2 == 2\n", encoding="utf-8",
    )
    (git_repo / "fixtures" / "case.json").write_text(
        json.dumps({"case": "two"}) + "\n", encoding="utf-8",
    )
    after = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py -k feature",
        test_definitions=["tests/test_feature.py"],
        fixtures=["fixtures/case.json"],
        scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )

    assert after["head_sha"] == before["head_sha"]
    assert after["changed_file_digest"] != before["changed_file_digest"]
    assert after["test_definition_digest"] != before["test_definition_digest"]
    assert after["fixture_digest"] != before["fixture_digest"]
    assert after["fingerprint_digest"] != before["fingerprint_digest"]


def test_command_test_path_is_included_in_definition_digest(git_repo: Path) -> None:
    before = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py",
        scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )
    (git_repo / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert 3 == 3\n", encoding="utf-8",
    )
    after = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py",
        scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
        gate_tier="S1",
        toolchain={"xcode": "Xcode 26.4"},
    )

    assert before["test_definition"]["files"][0]["path"] == "tests/test_feature.py"
    assert after["test_definition_digest"] != before["test_definition_digest"]


def test_scope_is_not_guessed_when_ticket_has_legacy_prose(git_repo: Path) -> None:
    result = fingerprint.build_fingerprint(
        git_repo,
        changed_files=["src/feature.py"],
        acceptance_command="pytest -q tests/test_feature.py",
        scope="modify the feature",
        gate_tier="S1",
        toolchain={"xcode": "unavailable"},
    )

    assert result["scope"]["status"] == "unknown"
    assert result["scope"]["value"] == "modify the feature"


def test_fingerprint_requires_toolchain_version(git_repo: Path) -> None:
    with pytest.raises(fingerprint.FingerprintError, match="toolchain"):
        fingerprint.build_fingerprint(
            git_repo,
            changed_files=["src/feature.py"],
            acceptance_command="pytest -q tests/test_feature.py",
            scope={"files": [{"path": "src/feature.py", "operation": "modify"}]},
            gate_tier="S1",
            toolchain={"python": "3.13.7"},
        )

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_orchestrate as coordinator


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, relative_path: str, contents: str, message: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    _git(repo, "add", relative_path)
    _git(repo, "commit", "-qm", message)


def _synthetic_rebase_refs(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "shared.txt", "base\n", "base")
    _git(repo, "branch", "base")
    _commit(repo, "ops/incoming_main.py", "incoming\n", "incoming main")
    _git(repo, "branch", "incoming-main")
    _git(repo, "checkout", "-q", "-b", "solver", "base")
    _commit(repo, "ios/issue_1033.py", "branch\n", "solver branch")
    return repo


def test_intent_type_is_only_branch_naming() -> None:
    assert coordinator._intent_type("fix crash in reader", None) == "debug"
    assert coordinator._intent_type("investigate sync drift", None) == "research"
    assert coordinator._intent_type("add reader filter", None) == "feat"
    assert coordinator._intent_type("anything", "debug") == "debug"


def test_gate_plan_routes_product_surfaces_to_existing_entry_points() -> None:
    plan = coordinator._plan_checks([
        "backend/src/kg/app.py", "ios/BooksAndVocab/App.swift",
        "ops/example.sh", "docs/reference/tech_index.md",
    ])
    names = {item["name"] for item in plan}
    assert "backend-tests" in names
    assert "ios-tests" in names
    assert "ops-tests" in names
    assert "docs-lint" in names
    assert "shell-syntax:ops/example.sh" in names


def test_gate_plan_skips_deleted_shell_file_in_target_worktree(tmp_path: Path) -> None:
    plan = coordinator._plan_checks(
        [".claude/skills/app-debug/find-polluter.sh"], worktree=tmp_path
    )
    names = {item["name"] for item in plan}
    assert "shell-syntax:.claude/skills/app-debug/find-polluter.sh" not in names


def test_gate_plan_never_mutates_remote_or_integrates_branches() -> None:
    plan = coordinator._plan_checks(["ops/worktree_orchestrate.py"])
    commands = [" ".join(item["cmd"]) for item in plan]
    rendered = " ".join(commands)
    assert "git merge" not in rendered
    assert "git push" not in rendered


def test_rebase_preflight_compares_declared_scope_only_to_incoming_main(tmp_path: Path) -> None:
    repo = _synthetic_rebase_refs(tmp_path)
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ios/issue_1033.py", "operation": "modify"}],
    }

    result = coordinator._rebase_preflight(
        repo, base="base", incoming_main="incoming-main", scope=scope
    )

    assert result["verdict"] == "pass"
    assert result["incoming_main_files"] == ["ops/incoming_main.py"]
    assert result["branch_files"] == ["ios/issue_1033.py"]
    assert result["collisions"] == []


def test_rebase_preflight_blocks_declared_scope_collision(tmp_path: Path) -> None:
    repo = _synthetic_rebase_refs(tmp_path)
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ops/incoming_main.py", "operation": "modify"}],
    }

    result = coordinator._rebase_preflight(
        repo, base="base", incoming_main="incoming-main", scope=scope
    )

    assert result["verdict"] == "block"
    assert result["collisions"] == ["ops/incoming_main.py"]


def test_rebase_preflight_fails_closed_for_missing_refs(tmp_path: Path) -> None:
    repo = _synthetic_rebase_refs(tmp_path)
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ios/issue_1033.py", "operation": "modify"}],
    }

    missing_base = coordinator._rebase_preflight(
        repo, base="missing-base", incoming_main="incoming-main", scope=scope
    )
    missing_incoming = coordinator._rebase_preflight(
        repo, base="base", incoming_main="missing-incoming", scope=scope
    )

    assert missing_base["verdict"] == "block"
    assert missing_base["reason"] == "base ref cannot be resolved"
    assert missing_incoming["verdict"] == "block"
    assert missing_incoming["reason"] == "incoming-main ref cannot be resolved"


def test_rebase_preflight_fails_closed_for_unstructured_scope(tmp_path: Path) -> None:
    repo = _synthetic_rebase_refs(tmp_path)

    result = coordinator._rebase_preflight(
        repo, base="base", incoming_main="incoming-main", scope="ops/incoming_main.py"
    )

    assert result["verdict"] == "block"
    assert result["reason"] == "declared Scope is unstructured or invalid"


def test_preflight_uses_active_declared_scope_for_rebase_collision_check(
    tmp_path: Path, capsys: object
) -> None:
    repo = _synthetic_rebase_refs(tmp_path)
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ios/issue_1033.py", "operation": "modify"}],
    }
    state_path = tmp_path / "worktree_registry.json"
    state_path.write_text(
        json.dumps({
            "schema": "kg.worktree.registry.v2",
            "records": [{
                "branch": "solver",
                "path": str(repo),
                "status": "active",
                "scope": scope,
            }],
        }),
        encoding="utf-8",
    )

    rc = coordinator.main([
        "preflight", "--state", str(state_path), "--worktree", str(repo),
        "--base", "base", "--incoming-main", "incoming-main", "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["verdict"] == "pass"
    assert payload["scope_files"] == ["ios/issue_1033.py"]
    assert payload["incoming_main_files"] == ["ops/incoming_main.py"]
    assert payload["branch_files"] == ["ios/issue_1033.py"]

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

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


def test_open_uses_exact_base_for_failed_provisioning_compensation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_sha = "a" * 40
    compensation: list[str] = []
    git_calls: list[list[str]] = []
    monkeypatch.setattr(coordinator, "_require_unfrozen", lambda command: None)
    monkeypatch.setattr(coordinator, "_resolve_commit", lambda path, ref: base_sha)
    monkeypatch.setattr(
        coordinator,
        "_registry_register",
        lambda **kwargs: (
            coordinator.registry.EXIT_OK,
            {
                "branch": "feat/provision-failure",
                "path": str(tmp_path / "worktree"),
                "claim_generation": 2,
                "base_sha": base_sha,
            },
        ),
    )
    def fail_worktree_add(
        argv: list[str], cwd: Path = coordinator.ROOT
    ) -> tuple[int, str]:
        git_calls.append(argv)
        return 1, "injected add failure"

    monkeypatch.setattr(coordinator, "_git", fail_worktree_add)

    def fail_compensation(argv: list[str]) -> int:
        compensation.extend(argv)
        return coordinator.registry.EXIT_CLAIMED

    monkeypatch.setattr(coordinator.registry, "main", fail_compensation)
    args = Namespace(
        slug="provision-failure",
        intent="test provisioning",
        type="feat",
        path=str(tmp_path / "worktree"),
        external_id=["DIRECT-TEST"],
        base="origin/main",
        codex_thread_id="thread-test",
        delegated=True,
        state=str(tmp_path / "custom-registry.json"),
        scope=json.dumps(_scope_for("ops/a.py")),
        scope_file=None,
        json=True,
    )

    assert coordinator.cmd_open(args) == coordinator.EXIT_BLOCK

    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == (
        "git worktree add failed and registry compensation failed"
    )
    assert git_calls[0][-1] == base_sha
    assert compensation[compensation.index("--expected-head-sha") + 1] == base_sha
    assert compensation[compensation.index("--state") + 1] == str(
        (tmp_path / "custom-registry.json").resolve()
    )


def _scope_for(path: str) -> dict[str, object]:
    return {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": path, "operation": "modify"}],
    }


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


def test_adopt_prefers_active_record_over_terminal_duplicate(tmp_path: Path, capsys: object) -> None:
    repo = _synthetic_rebase_refs(tmp_path)
    scope = {
        "schema": "kg.worktree.scope.v1",
        "files": [{"path": "ios/issue_1033.py", "operation": "modify"}],
    }
    state_path = tmp_path / "worktree_registry.json"
    terminal = {
        "branch": "solver",
        "path": str(repo),
        "status": "abandoned",
        "base": "old-base",
        "scope": scope,
    }
    active = {
        "branch": "solver",
        "path": str(repo),
        "status": "active",
        "base": "base",
        "scope": scope,
        "claim_generation": 0,
    }
    state_path.write_text(
        json.dumps({
            "schema": "kg.worktree.registry.v2",
            "records": [terminal, active],
        }),
        encoding="utf-8",
    )

    rc = coordinator.main([
        "adopt", "--state", str(state_path), "--worktree", str(repo),
        "--intent", "reanchor worker", "--base", "base",
        "--external-id", "ISSUE-1141", "--scope", json.dumps(scope),
        "--codex-thread-id", "worker-thread", "--delegated", "--json",
    ])

    json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    matches = [record for record in state["records"] if record["branch"] == "solver"]
    assert rc == coordinator.EXIT_OK
    assert len(matches) == 2
    assert sum(record["status"] == "active" for record in matches) == 1
    assert next(record for record in matches if record["status"] == "active")["claim_generation"] == 1


def _handoff_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "handoff-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "README.md", "base\n", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "worker")
    _commit(repo, "ops/handoff_change.py", "change\n", "worker change")
    tip_sha = _git(repo, "rev-parse", "HEAD")
    handed_back_at = "2026-08-21T00:00:00Z"
    record = {
        "branch": "worker",
        "path": str(repo),
        "status": coordinator.registry.STATUS_ACTIVE,
        "external_ids": ["USER-20260821-im-handback-package"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/handoff_change.py", "operation": "modify"}],
        },
        "base": base_sha,
        "base_sha": base_sha,
        "claim_generation": 0,
        "handed_back_at": handed_back_at,
        "handed_back_sha": tip_sha,
    }
    record["handback_claim_generation"] = 0
    record["handback_seal"] = coordinator.registry._seal_with_digest(
        coordinator.registry._seal_body(
            record,
            base_sha=base_sha,
            tip_sha=tip_sha,
            outcomes=[{"id": "USER-20260821-im-handback-package", "status": "passed"}],
            handed_back_at=handed_back_at,
        )
    )
    state_path = tmp_path / "worktree_registry.json"
    coordinator.registry.save_state(state_path, {"schema": coordinator.registry.SCHEMA, "records": [record]})
    gate_path = coordinator._gate_record_path(str(state_path), repo)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps({
        "schema": coordinator.GATE_SCHEMA,
        "worktree": str(repo),
        "base": base_sha,
        "files": ["ops/handoff_change.py"],
        "verdict": "pass",
        "head": tip_sha,
        "results": [{"name": "git-diff-check", "status": "pass", "rc": 0}],
    }), encoding="utf-8")
    return repo, state_path, base_sha, tip_sha


def test_handoff_package_emits_exact_im_payload(tmp_path: Path, capsys: object) -> None:
    repo, state_path, base_sha, tip_sha = _handoff_fixture(tmp_path)

    rc = coordinator.main([
        "handoff", "--state", str(state_path), "--worktree", str(repo),
        "--incoming-main", base_sha, "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_OK
    assert payload["schema"] == "kg.worktree.handoff.v1"
    assert payload["status"] == "ready-for-im"
    assert payload["base_sha"] == base_sha
    assert payload["tip_sha"] == tip_sha
    assert payload["observed_main_sha"] == base_sha
    assert payload["scope"] == ["ops/handoff_change.py"]
    assert payload["handback_seal"]["tip_sha"] == tip_sha
    assert payload["validation"]["gate"]["verdict"] == "pass"


def test_handoff_package_blocks_when_main_advanced(tmp_path: Path, capsys: object) -> None:
    repo, state_path, base_sha, _ = _handoff_fixture(tmp_path)
    _git(repo, "checkout", "-q", "-b", "incoming-main", base_sha)
    _commit(repo, "main_only.py", "advanced\n", "advance main")
    incoming_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "worker")

    rc = coordinator.main([
        "handoff", "--state", str(state_path), "--worktree", str(repo),
        "--incoming-main", incoming_sha, "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert payload["status"] == "blocked"
    assert payload["observed_main_sha"] == incoming_sha
    assert "does not equal hand-back base" in payload["reason"]


def test_handoff_package_blocks_when_gate_base_is_stale(tmp_path: Path, capsys: object) -> None:
    repo, state_path, base_sha, _ = _handoff_fixture(tmp_path)
    gate_path = coordinator._gate_record_path(str(state_path), repo)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["base"] = "stale-base"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    rc = coordinator.main([
        "handoff", "--state", str(state_path), "--worktree", str(repo),
        "--incoming-main", base_sha, "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert payload["status"] == "blocked"
    assert payload["reason"] == "local gate base does not equal hand-back base"

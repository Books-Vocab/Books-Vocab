from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_orchestrate as coordinator  # noqa: E402
from delivery_control.domain.models import CheckStatus, HandbackReceipt, Scope  # noqa: E402
from delivery_control.domain.observations import (  # noqa: E402
    CheckSnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)
from worktree_reanchor_core import (  # noqa: E402
    git_ops,
    lifecycle_proof,
    registry_ops,
    resume_git_ops,
)
from worktree_reanchor_core.errors import ReanchorRefused  # noqa: E402
from delivery_control.services.pr_contract import render_pull_request_body  # noqa: E402


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


def _fixture_receipt_body(
    *, number: int, branch: str, base: str, head: str
) -> str:
    receipt = HandbackReceipt(
        lane_id=f"DIRECT-PR-{number}",
        owner_thread_id="owner-thread-1",
        claim_generation=0,
        branch=branch,
        worktree_path=f"/tmp/pr-{number}",
        base_sha=base,
        parent_sha=base,
        head_sha=head,
        origin_main_sha=base,
        content_digest="e" * 64,
        scope=Scope.from_paths(modify=(f"ops/pr_{number}.py",)),
    )
    return render_pull_request_body(receipt)


class _FixtureRecoveryGitHub:
    def __init__(self, repo: Path, *, operation: str) -> None:
        self.repo = repo
        self.operation = operation

    def _pull_request(self, branch: str = "feat/exact-pr") -> PullRequestSnapshot:
        head = _git(self.repo, "rev-parse", f"refs/remotes/origin/{branch}")
        base = _git(self.repo, "merge-base", head, "refs/remotes/origin/main")
        return PullRequestSnapshot(
            number=42,
            url="https://example.test/pull/42",
            branch=branch,
            base_sha=base,
            head_sha=head,
            state="OPEN",
            draft=False,
            mergeable=True,
            node_id="PR_42",
            body=_fixture_receipt_body(
                number=42,
                branch=branch,
                base=base,
                head=head,
            ),
        )

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory((self._pull_request(branch),))

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory((self._pull_request(),))

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        assert number == 42
        status = (
            CheckStatus.FAILURE
            if self.operation == "resume-published"
            else CheckStatus.SUCCESS
        )
        return CheckSnapshot(
            status=status,
            head_sha=self._pull_request().head_sha,
            observed_at=datetime(2026, 8, 22, tzinfo=UTC),
            names=("required",),
        )

    def merge_queue_entry_snapshot(self, pull_request_id: str) -> None:
        assert pull_request_id == "PR_42"


@pytest.fixture(autouse=True)
def _recovery_github_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lifecycle_proof,
        "build_github",
        lambda repo, *, operation: _FixtureRecoveryGitHub(
            repo, operation=operation
        ),
    )


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



def test_open_compensates_against_existing_branch_head_after_add_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_sha = "a" * 40
    branch_sha = "b" * 40
    compensation: list[str] = []
    monkeypatch.setattr(coordinator, "_require_unfrozen", lambda command: None)
    resolved = iter((base_sha, branch_sha))
    monkeypatch.setattr(
        coordinator, "_resolve_commit", lambda path, ref: next(resolved)
    )
    monkeypatch.setattr(
        coordinator,
        "_registry_register",
        lambda **kwargs: (
            coordinator.registry.EXIT_OK,
            {
                "branch": "feat/existing-branch",
                "path": str(tmp_path / "worktree"),
                "claim_generation": 4,
                "base_sha": base_sha,
            },
        ),
    )
    monkeypatch.setattr(
        coordinator,
        "_git",
        lambda argv, cwd=coordinator.ROOT: (1, "branch already exists"),
    )
    monkeypatch.setattr(
        coordinator.registry,
        "main",
        lambda argv: compensation.extend(argv) or coordinator.registry.EXIT_CLAIMED,
    )
    args = Namespace(
        slug="existing-branch",
        intent="test existing branch compensation",
        type="feat",
        path=str(tmp_path / "worktree"),
        external_id=["DIRECT-TEST-EXISTING"],
        base="origin/main",
        codex_thread_id="thread-test",
        delegated=False,
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
    assert (
        compensation[compensation.index("--expected-head-sha") + 1] == branch_sha
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


def test_handoff_package_preserves_historical_base_when_main_advanced(
    tmp_path: Path, capsys: object
) -> None:
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
    assert rc == coordinator.EXIT_OK
    assert payload["status"] == "ready-for-im"
    assert payload["observed_main_sha"] == incoming_sha
    assert payload["base_sha"] == base_sha


def test_handoff_package_blocks_when_base_is_not_in_incoming_main_history(
    tmp_path: Path, capsys: object
) -> None:
    repo, state_path, _, _ = _handoff_fixture(tmp_path)
    _git(repo, "checkout", "-q", "--orphan", "unrelated-main")
    _git(repo, "rm", "-q", "-rf", ".")
    _commit(repo, "unrelated.txt", "unrelated\n", "unrelated main")
    incoming_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "worker")

    rc = coordinator.main([
        "handoff", "--state", str(state_path), "--worktree", str(repo),
        "--incoming-main", incoming_sha, "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert payload["status"] == "blocked"
    assert "not an ancestor" in payload["reason"]


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


def _reanchor_fixture(
    tmp_path: Path,
    *,
    conflict: bool = False,
    external_ids: list[str] | None = None,
) -> tuple[Path, Path, Path, dict[str, object]]:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test User")
    _commit(seed, "shared.txt", "base\n", "base")
    base_sha = _git(seed, "rev-parse", "HEAD")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-q", "origin", "main")
    _git(seed, "checkout", "-q", "-b", "feat/exact-pr", base_sha)
    if conflict:
        _commit(seed, "shared.txt", "branch\n", "branch change")
        scope = _scope_for("shared.txt")
    else:
        _commit(seed, "ops/reanchor_change.py", "branch\n", "branch change")
        scope = {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/reanchor_change.py", "operation": "add"}],
        }
    remote_head = _git(seed, "rev-parse", "HEAD")
    _git(seed, "push", "-q", "origin", "feat/exact-pr")
    _git(seed, "checkout", "-q", "main")
    if conflict:
        _commit(seed, "shared.txt", "main\n", "advance main")
    else:
        _commit(seed, "main_only.txt", "main\n", "advance main")
    live_main = _git(seed, "rev-parse", "HEAD")
    _git(seed, "push", "-q", "origin", "main")

    repo = tmp_path / "control"
    _git(tmp_path, "clone", "-q", "--branch", "main", str(remote), str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    record: dict[str, object] = {
        "branch": "feat/exact-pr",
        "path": str(tmp_path / "released-worktree"),
        "intent": "same-owner merge-front reanchor",
        "base": base_sha,
        "base_sha": base_sha,
        "status": "published",
        "external_ids": (
            ["DIRECT-REANCHOR-1"] if external_ids is None else external_ids
        ),
        "scope": scope,
        "codex_thread_id": "owner-thread-1",
        "delegated": True,
        "claim_generation": 4,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "handed_back_sha": remote_head,
        "handback_claim_generation": 4,
    }
    record["handback_seal"] = coordinator.registry._seal_with_digest(
        coordinator.registry._seal_body(
            record,
            base_sha=base_sha,
            tip_sha=remote_head,
            outcomes=[{"name": "focused", "status": "success"}],
            handed_back_at="2026-08-21T00:00:00Z",
            origin_main_sha=base_sha,
        )
    )
    state_path = tmp_path / "worktree_registry.json"
    coordinator.registry.save_state(
        state_path,
        {"schema": coordinator.registry.SCHEMA, "records": [record]},
    )
    target = tmp_path / "reanchored"
    expected = {
        "base_sha": base_sha,
        "remote_head": remote_head,
        "live_main": live_main,
        "scope": scope,
    }
    return repo, state_path, target, expected


def _reanchor_argv(
    repo: Path,
    state_path: Path,
    target: Path,
    expected: dict[str, object],
    *,
    owner: str = "owner-thread-1",
    lane: str = "DIRECT-REANCHOR-1",
) -> list[str]:
    return [
        "reanchor",
        "--repo", str(repo),
        "--state", str(state_path),
        "--merge-front-pr", "42",
        "--lane", lane,
        "--branch", "feat/exact-pr",
        "--owner-thread-id", owner,
        "--claim-generation", "4",
        "--expected-remote-head", str(expected["remote_head"]),
        "--live-main", str(expected["live_main"]),
        "--path", str(target),
        "--json",
    ]


def test_reanchor_recreates_exact_remote_branch_for_same_owner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    original = coordinator.registry.load_state(state_path)["records"][0]

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    records = state["records"]
    old = records[0]
    active = [item for item in state["records"] if item["status"] == "active"]
    assert rc == coordinator.EXIT_OK
    assert payload["status"] == "ready-for-owner-tests"
    assert payload["merge_front_pr"] == 42
    assert _git(target, "branch", "--show-current") == "feat/exact-pr"
    assert _git(target, "merge-base", "--is-ancestor", str(expected["live_main"]), "HEAD") == ""
    assert _git(repo, "ls-remote", "origin", "refs/heads/feat/exact-pr").split()[0] == expected["remote_head"]
    assert [item["status"] for item in records] == ["abandoned", "active"]
    assert [item["claim_generation"] for item in records] == [4, 5]
    assert old["resolved_at"] is not None
    assert old["handed_back_sha"] == expected["remote_head"]
    assert old["handed_back_at"] == original["handed_back_at"]
    assert old["handback_claim_generation"] == original["handback_claim_generation"]
    assert old["handback_seal"] == original["handback_seal"]
    assert len(active) == 1
    assert active[0]["codex_thread_id"] == "owner-thread-1"
    assert active[0]["claim_generation"] == 5
    assert active[0]["base_sha"] == expected["live_main"]
    assert active[0]["scope"] == expected["scope"]
    assert active[0]["handed_back_sha"] is None


def test_reanchor_accepts_direct_assignment_with_branch_lane_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(
        tmp_path,
        external_ids=[],
    )

    rc = coordinator.main(
        _reanchor_argv(
            repo,
            state_path,
            target,
            expected,
            lane="feat/exact-pr",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_OK
    assert payload["status"] == "ready-for-owner-tests"
    assert [item["status"] for item in state["records"]] == [
        "abandoned",
        "active",
    ]
    assert state["records"][1]["external_ids"] == []


def test_reanchor_machine_proof_rejects_non_front_before_local_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    class NonFrontGitHub(_FixtureRecoveryGitHub):
        def list_open_pull_requests(self) -> PullRequestInventory:
            candidate = self._pull_request()
            earlier = PullRequestSnapshot(
                number=41,
                url="https://example.test/pull/41",
                branch="feat/earlier",
                base_sha=candidate.base_sha,
                head_sha=candidate.head_sha,
                state="OPEN",
                draft=False,
                mergeable=True,
                node_id="PR_41",
                body=_fixture_receipt_body(
                    number=41,
                    branch="feat/earlier",
                    base=candidate.base_sha,
                    head=candidate.head_sha,
                ),
            )
            return PullRequestInventory((candidate, earlier))

        def required_check_snapshot(self, number: int) -> CheckSnapshot:
            return CheckSnapshot(
                status=CheckStatus.SUCCESS,
                head_sha=self._pull_request().head_sha,
                observed_at=datetime(2026, 8, 22, tzinfo=UTC),
                names=("required",),
            )

        def merge_queue_entry_snapshot(self, pull_request_id: str) -> None:
            assert pull_request_id in {"PR_41", "PR_42"}

    monkeypatch.setattr(
        lifecycle_proof,
        "build_github",
        lambda repo, *, operation: NonFrontGitHub(repo, operation=operation),
    )

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "deterministic merge-front" in payload["reason"]
    assert [item["status"] for item in state["records"]] == ["published"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


def test_reanchor_registry_save_failure_leaves_original_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    def fail_save(*args: object, **kwargs: object) -> None:
        raise OSError("injected registry save failure")

    monkeypatch.setattr(registry_ops.registry, "save_state", fail_save)

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "registry save failure" in payload["reason"]
    assert [item["status"] for item in state["records"]] == ["published"]
    assert state["records"][0].get("resolved_at") is None
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


def test_reanchor_stale_remote_cas_compensates_local_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    real_verify = git_ops.verify_remote_cas
    calls = 0

    def fail_final_cas(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ReanchorRefused("remote branch changed during reanchor")
        real_verify(*args, **kwargs)

    monkeypatch.setattr(git_ops, "verify_remote_cas", fail_final_cas)

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "remote branch changed" in payload["reason"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""
    assert all(item["status"] != "active" for item in state["records"])


def test_reanchor_rejects_wrong_owner_before_git_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    rc = coordinator.main(
        _reanchor_argv(repo, state_path, target, expected, owner="other-owner")
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert "owner" in payload["reason"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


def test_reanchor_rejects_scope_collision_without_creating_worktree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    state = coordinator.registry.load_state(state_path)
    state["records"].append({
        "branch": "feat/other",
        "path": str(tmp_path / "other"),
        "intent": "other owner",
        "base": str(expected["live_main"]),
        "base_sha": str(expected["live_main"]),
        "status": "active",
        "external_ids": ["DIRECT-OTHER"],
        "scope": expected["scope"],
        "codex_thread_id": "other-owner",
        "claim_generation": 0,
    })
    coordinator.registry.save_state(state_path, state)

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert "Scope" in payload["reason"] or "owned" in payload["reason"]
    assert not target.exists()


def test_reanchor_conflict_aborts_and_removes_only_created_local_assets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path, conflict=True)

    rc = coordinator.main(_reanchor_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "conflict" in payload["reason"]
    assert payload["compensation"]["complete"] is True
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""
    assert _git(repo, "ls-remote", "origin", "refs/heads/feat/exact-pr").split()[0] == expected["remote_head"]
    assert all(item["status"] != "active" for item in state["records"])


def _resume_argv(
    repo: Path,
    state_path: Path,
    target: Path,
    expected: dict[str, object],
    *,
    owner: str = "owner-thread-1",
    generation: int = 4,
    remote_head: str | None = None,
    previous_handback: str | None = None,
) -> list[str]:
    argv = [
        "resume-published",
        "--repo", str(repo),
        "--state", str(state_path),
        "--lane", "DIRECT-REANCHOR-1",
        "--branch", "feat/exact-pr",
        "--owner-thread-id", owner,
        "--claim-generation", str(generation),
        "--expected-remote-head", remote_head or str(expected["remote_head"]),
        "--path", str(target),
        "--json",
    ]
    if previous_handback is not None:
        argv.extend(["--previous-handback", previous_handback])
    return argv


def test_resume_published_recreates_exact_head_and_preserves_recorded_base(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    original = coordinator.registry.load_state(state_path)["records"][0]

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    old, active = state["records"]
    assert rc == coordinator.EXIT_OK
    assert payload["schema"] == "kg.worktree.resume-published.v1"
    assert payload["status"] == "ready-for-owner-fix"
    assert payload["next_action"]
    assert payload["not_performed"] == ["tests", "hand-back", "push", "force-push"]
    assert _git(target, "branch", "--show-current") == original["branch"]
    assert _git(target, "rev-parse", "HEAD") == expected["remote_head"]
    assert old["status"] == "abandoned"
    assert old["resolved_at"] is not None
    assert old["handback_seal"] == original["handback_seal"]
    assert active["status"] == "active"
    assert active["claim_generation"] == 5
    assert active["base"] == original["base"]
    assert active["base_sha"] == original["base_sha"]
    assert active["scope"] == original["scope"]
    assert active["external_ids"] == original["external_ids"]
    assert active["codex_thread_id"] == original["codex_thread_id"]
    assert active["branch"] == original["branch"]
    assert active["handed_back_sha"] is None


def test_resume_published_accepts_legacy_record_base_without_base_sha(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    state = coordinator.registry.load_state(state_path)
    state["records"][0].pop("base_sha")
    coordinator.registry.save_state(state_path, state)

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_OK
    assert payload["status"] == "ready-for-owner-fix"
    assert state["records"][1]["base_sha"] == expected["base_sha"]


def test_resume_published_refreshes_an_owner_advanced_published_head(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    _git(repo, "checkout", "-q", "-b", "owner-fix", str(expected["remote_head"]))
    _commit(repo, "ops/reanchor_change.py", "owner fix\n", "owner fix")
    advanced_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/feat/exact-pr")

    rc = coordinator.main(
        _resume_argv(
            repo,
            state_path,
            target,
            expected,
            remote_head=advanced_head,
            previous_handback=str(expected["remote_head"]),
        )
    )

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_OK
    assert payload["status"] == "ready-for-owner-fix"
    assert _git(target, "rev-parse", "HEAD") == advanced_head
    assert state["records"][0]["status"] == "abandoned"
    assert state["records"][1]["status"] == "active"
    assert state["records"][1]["claim_generation"] == 5
    assert state["records"][1]["handed_back_sha"] is None


def test_resume_published_compensates_when_required_failure_clears_midflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    class ClearingFailureGitHub(_FixtureRecoveryGitHub):
        required_reads = 0

        def required_check_snapshot(self, number: int) -> CheckSnapshot:
            self.required_reads += 1
            return CheckSnapshot(
                status=(
                    CheckStatus.FAILURE
                    if self.required_reads == 1
                    else CheckStatus.SUCCESS
                ),
                head_sha=self._pull_request().head_sha,
                observed_at=datetime(2026, 8, 22, tzinfo=UTC),
                names=("required",),
            )

    monkeypatch.setattr(
        lifecycle_proof,
        "build_github",
        lambda repo, *, operation: ClearingFailureGitHub(
            repo, operation=operation
        ),
    )

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "required code failure" in payload["reason"]
    assert payload["compensation"]["complete"] is True
    assert [item["status"] for item in state["records"]] == ["published"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"owner": "other-owner"}, "owner"),
        ({"generation": 3}, "selector"),
        ({"remote_head": "0" * 40}, "hand-back"),
    ],
)
def test_resume_published_rejects_owner_generation_and_head_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
    reason_fragment: str,
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    rc = coordinator.main(
        _resume_argv(repo, state_path, target, expected, **overrides)
    )

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert reason_fragment in payload["reason"]
    assert [item["status"] for item in state["records"]] == ["published"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


@pytest.mark.parametrize("existing_asset", ["target", "branch"])
def test_resume_published_rejects_existing_target_or_local_branch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    existing_asset: str,
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    if existing_asset == "target":
        target.mkdir()
    else:
        _git(repo, "branch", "feat/exact-pr", str(expected["remote_head"]))

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert any(
        word in payload["reason"] for word in ("new", "exist", "duplicate")
    )
    assert [item["status"] for item in state["records"]] == ["published"]


def test_resume_published_rejects_remote_branch_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    remote = Path(_git(repo, "remote", "get-url", "origin"))
    _git(tmp_path, "--git-dir", str(remote), "update-ref", "refs/heads/feat/exact-pr", str(expected["live_main"]))

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert "remote branch changed" in payload["reason"]
    assert not target.exists()


def test_resume_published_save_failure_compensates_only_new_local_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)

    def fail_save(*args: object, **kwargs: object) -> None:
        raise OSError("injected resume registry save failure")

    monkeypatch.setattr(registry_ops.registry, "save_state", fail_save)

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    remote_readback = _git(repo, "ls-remote", "origin", "refs/heads/feat/exact-pr")
    assert rc == coordinator.EXIT_BLOCK
    assert "registry save failure" in payload["reason"]
    assert payload["compensation"]["complete"] is True
    assert [item["status"] for item in state["records"]] == ["published"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""
    assert remote_readback.split()[0] == expected["remote_head"]


def test_resume_published_git_failure_compensates_only_new_local_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    real_git = resume_git_ops.git_ops._git

    def fail_switch(args: list[str], cwd: Path) -> tuple[int, str]:
        if args[:2] == ["switch", "-c"]:
            return 1, "injected local branch provisioning failure"
        return real_git(args, cwd)

    monkeypatch.setattr(resume_git_ops.git_ops, "_git", fail_switch)

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "branch recreation failed" in payload["reason"]
    assert payload["compensation"]["complete"] is True
    assert [item["status"] for item in state["records"]] == ["published"]
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""
    assert _git(repo, "ls-remote", "origin", "refs/heads/feat/exact-pr").split()[0] == expected["remote_head"]


def test_resume_published_registry_fingerprint_cas_compensates_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    real_provision = resume_git_ops.provision_exact

    def provision_then_drift(*args: object, **kwargs: object) -> str:
        head = real_provision(*args, **kwargs)
        state = coordinator.registry.load_state(state_path)
        state["records"][0]["intent"] = "concurrent owner update"
        coordinator.registry.save_state(state_path, state)
        return head

    monkeypatch.setattr(resume_git_ops, "provision_exact", provision_then_drift)

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    state = coordinator.registry.load_state(state_path)
    assert rc == coordinator.EXIT_BLOCK
    assert "registry claim changed" in payload["reason"]
    assert payload["compensation"]["complete"] is True
    assert [item["status"] for item in state["records"]] == ["published"]
    assert state["records"][0]["intent"] == "concurrent owner update"
    assert not target.exists()
    assert _git(repo, "branch", "--list", "feat/exact-pr") == ""


def test_resume_published_is_the_only_atomic_escape_from_published_ownership(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    state = coordinator.registry.load_state(state_path)
    original = state["records"][0]
    register_rc, refusal = coordinator.registry._register_record(
        state,
        branch="feat/competing",
        path=str(tmp_path / "competing"),
        intent="competing registration",
        base=str(original["base"]),
        external_ids=list(original["external_ids"]),
        scope=original["scope"],
        codex_thread_id="owner-thread-1",
        delegated=True,
    )
    assert register_rc != coordinator.registry.EXIT_OK
    assert "owned" in refusal["reason"]

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    capsys.readouterr()
    records = coordinator.registry.load_state(state_path)["records"]
    assert rc == coordinator.EXIT_OK
    assert [(item["status"], item["claim_generation"]) for item in records] == [
        ("abandoned", 4),
        ("active", 5),
    ]


def test_resume_published_rejects_dirty_unreleased_recorded_worktree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    released = tmp_path / "released-worktree"
    _git(repo, "worktree", "add", "-q", "-b", "stale-local", str(released), str(expected["base_sha"]))
    (released / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    rc = coordinator.main(_resume_argv(repo, state_path, target, expected))

    payload = json.loads(capsys.readouterr().out)
    assert rc == coordinator.EXIT_BLOCK
    assert "released" in payload["reason"] or "dirty" in payload["reason"]
    assert not target.exists()


def test_resume_published_rejects_duplicate_and_unknown_registry_truth(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, state_path, target, expected = _reanchor_fixture(tmp_path)
    state = coordinator.registry.load_state(state_path)
    duplicate = dict(state["records"][0])
    state["records"].append(duplicate)
    coordinator.registry.save_state(state_path, state)

    duplicate_rc = coordinator.main(_resume_argv(repo, state_path, target, expected))
    duplicate_payload = json.loads(capsys.readouterr().out)

    state = coordinator.registry.load_state(state_path)
    state["records"].pop()
    state["records"].append({"status": "unknown", "branch": "feat/unknown"})
    coordinator.registry.save_state(state_path, state)
    unknown_rc = coordinator.main(_resume_argv(repo, state_path, target, expected))
    unknown_payload = json.loads(capsys.readouterr().out)

    assert duplicate_rc == coordinator.EXIT_BLOCK
    assert "exactly one" in duplicate_payload["reason"]
    assert unknown_rc == coordinator.EXIT_BLOCK
    assert "malformed" in unknown_payload["reason"] or "unknown" in unknown_payload["reason"]
    assert not target.exists()

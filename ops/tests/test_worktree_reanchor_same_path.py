from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import worktree_registry as registry
from worktree_reanchor_core import git_ops, transaction
from worktree_reanchor_core.errors import ReanchorRefused

LANE = "DIRECT-DELIVERY-REANCHOR-SAME-PATH-RESUME-20260901"
BRANCH = "debug/production-dogfood-same-path-source"
OWNER = "owner-thread-same-path"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return result.stdout.strip()


def _write(cwd: Path, relative: str, content: str) -> None:
    path = cwd / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _same_path_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str, str, str]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    target = tmp_path / "owner-worktree"
    state_path = tmp_path / "worktree_registry.json"

    _git(tmp_path, "init", "--bare", "-q", str(remote))
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "switch", "-c", "main")
    _git(repo, "remote", "add", "origin", str(remote))

    _write(repo, "README.md", "base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "switch", "-c", BRANCH)
    _write(repo, "ops/reanchor_change.py", "source\n")
    _git(repo, "add", "ops/reanchor_change.py")
    _git(repo, "commit", "-m", "source")
    remote_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
    _git(repo, "switch", "main")
    _git(repo, "branch", "-D", BRANCH)

    _write(repo, "main_change.txt", "live main\n")
    _git(repo, "add", "main_change.txt")
    _git(repo, "commit", "-m", "advance main")
    live_main = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", "main")

    # This is the state after supported resume-published materialization: the
    # original owner already has the exact recorded branch/path checked out.
    _git(repo, "worktree", "add", "--detach", str(target), remote_head)
    _git(target, "switch", "-c", BRANCH)
    record = {
        "branch": BRANCH,
        "path": str(target),
        "intent": "same-path resume reanchor transport",
        "base": base,
        "base_sha": base,
        "status": "active",
        "external_ids": [LANE],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [
                {"path": "ops/reanchor_change.py", "operation": "add"},
            ],
        },
        "codex_thread_id": OWNER,
        "delegated": True,
        "claim_generation": 1,
        "handed_back_at": None,
        "handed_back_sha": None,
        "handback_claim_generation": None,
    }
    registry.save_state(
        state_path,
        {"schema": registry.SCHEMA, "records": [record]},
    )
    return repo, state_path, target, base, remote_head, live_main


def test_reanchor_reuses_exact_path_authorized_by_resumed_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, state_path, target, _base, remote_head, live_main = _same_path_fixture(
        tmp_path
    )
    lifecycle = SimpleNamespace(
        merge_front_policy="owner-local-required-failure-recovery"
    )
    monkeypatch.setattr(
        transaction.lifecycle_proof, "build_github", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        transaction.lifecycle_proof,
        "verify_reanchor_lifecycle",
        lambda *_args, **_kwargs: lifecycle,
    )

    payload = transaction.perform_reanchor(
        repo=repo,
        state_path=state_path,
        merge_front_pr=42,
        lane_id=LANE,
        branch=BRANCH,
        owner_thread_id=OWNER,
        claim_generation=1,
        expected_remote_head=remote_head,
        live_main=live_main,
        target=target,
        allow_required_failure_recovery=True,
    )

    assert payload["status"] == "ready-for-owner-tests"
    assert payload["worktree"] == str(target)
    assert _git(target, "branch", "--show-current") == BRANCH
    assert _git(target, "status", "--porcelain=v1") == ""
    assert _git(target, "merge-base", "--is-ancestor", live_main, "HEAD") == ""


def test_late_lifecycle_failure_restores_existing_owner_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, state_path, target, _base, remote_head, live_main = _same_path_fixture(
        tmp_path
    )
    before = registry.load_state(state_path)
    lifecycle = SimpleNamespace(
        merge_front_policy="owner-local-required-failure-recovery"
    )
    calls = 0

    def verify_lifecycle(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ReanchorRefused("injected final lifecycle drift")
        return lifecycle

    monkeypatch.setattr(
        transaction.lifecycle_proof, "build_github", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        transaction.lifecycle_proof,
        "verify_reanchor_lifecycle",
        verify_lifecycle,
    )

    with pytest.raises(
        ReanchorRefused, match="injected final lifecycle drift"
    ) as error:
        transaction.perform_reanchor(
            repo=repo,
            state_path=state_path,
            merge_front_pr=42,
            lane_id=LANE,
            branch=BRANCH,
            owner_thread_id=OWNER,
            claim_generation=1,
            expected_remote_head=remote_head,
            live_main=live_main,
            target=target,
            allow_required_failure_recovery=True,
        )

    assert error.value.details["compensation"]["complete"] is True
    assert error.value.details["compensation"]["preserved_existing"] is True
    assert registry.load_state(state_path) == before
    assert _git(target, "branch", "--show-current") == BRANCH
    assert _git(target, "rev-parse", "HEAD") == remote_head
    assert _git(target, "status", "--porcelain=v1") == ""


def test_generic_new_target_validation_remains_strict(
    tmp_path: Path,
) -> None:
    repo, _state_path, target, _base, _remote_head, _live_main = _same_path_fixture(
        tmp_path
    )
    unregistered = tmp_path / "unregistered"
    unregistered.mkdir()
    new_target = tmp_path / "new-target"

    with pytest.raises(ReanchorRefused, match="repository root"):
        git_ops.validate_new_target(repo, target=repo, branch=BRANCH)
    with pytest.raises(ReanchorRefused, match="repository root"):
        git_ops.validate_new_target(repo, target=unregistered, branch=BRANCH)
    with pytest.raises(ReanchorRefused, match="duplicate adoption"):
        git_ops.validate_new_target(repo, target=new_target, branch=BRANCH)
    with pytest.raises(ReanchorRefused, match="repository root"):
        git_ops.validate_new_target(repo, target=target, branch=BRANCH)

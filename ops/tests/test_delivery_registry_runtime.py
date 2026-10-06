from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import worktree_registry
from delivery_control.adapters.module_runner import ModuleCommandRunner
from delivery_control.adapters.registry import RegistryCliAdapter


def test_registry_cas_finishes_after_source_executable_removal(tmp_path: Path) -> None:
    branch = "feat/self-hosted-release"
    worktree = tmp_path / "feature-worktree"
    state_path = tmp_path / ".cache" / "worktree_registry.json"
    state_path.parent.mkdir()
    handed_back_at = "2026-08-21T00:00:00Z"
    head = "b" * 40
    seal_body = {
        "schema": "kg.worktree.handback.v1",
        "branch": branch,
        "path": str(worktree),
        "external_ids": ["DIRECT-SELF-HOSTED"],
        "owner_thread_id": "thread-self-hosted",
        "base_sha": "a" * 40,
        "tip_sha": head,
        "outcomes": [{"status": "passed"}],
        "handed_back_at": handed_back_at,
    }
    record = {
        "branch": branch,
        "path": str(worktree),
        "intent": "prove self-hosted release",
        "base": "a" * 40,
        "status": "cleanup_pending",
        "external_ids": ["DIRECT-SELF-HOSTED"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-self-hosted",
        "claim_generation": 3,
        "handback_claim_generation": 3,
        "handed_back_at": handed_back_at,
        "handed_back_sha": head,
        "handback_seal": worktree_registry._seal_with_digest(seal_body),
    }
    state_path.write_text(
        json.dumps({"schema": "kg.worktree.registry.v2", "records": [record]}),
        encoding="utf-8",
    )
    executable = tmp_path / "worktree_registry.py"
    executable.touch()
    adapter = RegistryCliAdapter(
        script_path=executable,
        state_path=state_path,
        runner=ModuleCommandRunner(
            executable=executable,
            main=worktree_registry.main,
        ),
    )
    executable.unlink()

    adapter.resolve(
        "DIRECT-SELF-HOSTED",
        "published",
        expected_claim_generation=3,
        expected_branch=branch,
        expected_path=str(worktree),
        expected_head_sha=head,
    )

    resolved = json.loads(state_path.read_text(encoding="utf-8"))["records"][0]
    assert resolved["status"] == "published"


def test_registry_cas_anchors_after_source_worktree_cwd_is_removed(
    tmp_path: Path,
) -> None:
    branch = "feat/deleted-cwd-release"
    source_worktree = tmp_path / "source-worktree"
    target_repo = tmp_path / "canonical-main"
    state_path = tmp_path / ".cache" / "worktree_registry.json"
    source_worktree.mkdir()
    target_repo.mkdir()
    subprocess.run(
        ("git", "init", "-b", "main", str(target_repo)),
        check=True,
        capture_output=True,
        text=True,
    )
    (target_repo / "README").write_text("test\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(target_repo), "add", "README"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(target_repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "commit",
            "-m",
            "init",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    state_path.parent.mkdir()
    head = "b" * 40
    seal_body = {
        "schema": "kg.worktree.handback.v1",
        "branch": branch,
        "path": str(source_worktree),
        "external_ids": ["DIRECT-DELETED-CWD"],
        "owner_thread_id": "thread-deleted-cwd",
        "base_sha": "a" * 40,
        "tip_sha": head,
        "outcomes": [{"status": "passed"}],
        "handed_back_at": "2026-08-21T00:00:00Z",
    }
    record = {
        "branch": branch,
        "path": str(source_worktree),
        "intent": "prove stable registry cwd",
        "base": "a" * 40,
        "status": "cleanup_pending",
        "external_ids": ["DIRECT-DELETED-CWD"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-deleted-cwd",
        "claim_generation": 3,
        "handback_claim_generation": 3,
        "handed_back_at": "2026-08-21T00:00:00Z",
        "handed_back_sha": head,
        "handback_seal": worktree_registry._seal_with_digest(seal_body),
    }
    state_path.write_text(
        json.dumps({"schema": "kg.worktree.registry.v2", "records": [record]}),
        encoding="utf-8",
    )
    executable = tmp_path / "worktree_registry.py"
    executable.touch()
    adapter = RegistryCliAdapter(
        script_path=executable,
        state_path=state_path,
        runner=ModuleCommandRunner(
            executable=executable,
            main=worktree_registry.main,
            source_root=target_repo,
            target_repo=target_repo,
        ),
    )

    original_cwd = os.open(".", os.O_RDONLY)
    try:
        os.chdir(source_worktree)
        source_worktree.rmdir()
        adapter.resolve(
            "DIRECT-DELETED-CWD",
            "published",
            expected_claim_generation=3,
            expected_branch=branch,
            expected_path=str(source_worktree),
            expected_head_sha=head,
        )
        assert Path.cwd() == target_repo.resolve()
    finally:
        os.fchdir(original_cwd)
        os.close(original_cwd)

    resolved = json.loads(state_path.read_text(encoding="utf-8"))["records"][0]
    assert resolved["status"] == "published"

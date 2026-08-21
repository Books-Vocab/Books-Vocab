from __future__ import annotations

import json
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

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.cli import DeliveryApplication, RuntimeStatusMap, main
from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.models import CheckStatus, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    FileChange,
    FileOperation,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.services.publish import render_pull_request_body

BASE = "a" * 40
HEAD = "b" * 40
DIGEST = "c" * 64
BRANCH = "feat/cli"
WORKTREE = Path("/tmp/cli-worktree").resolve()


def _record() -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id="DIRECT-CLI",
        branch=BRANCH,
        path=WORKTREE,
        status="active",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha=BASE,
        claim_generation=2,
        owner_thread_id="thread-cli",
        handed_back_sha=HEAD,
        handback_claim_generation=2,
        handback_valid=True,
        handback_digest=DIGEST,
        handback_origin_main_sha=BASE,
    )


def _snapshot() -> WorktreeSnapshot:
    return WorktreeSnapshot(
        path=WORKTREE,
        branch=BRANCH,
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        clean=True,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )


class FakeRegistry:
    def __init__(self) -> None:
        self.record = _record()
        self.fail_resolve_once = False

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return self.record if lane_id == self.record.lane_id else None

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.record,))

    def resolve(
        self,
        lane_id: str,
        disposition: str,
        *,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
    ) -> None:
        if self.fail_resolve_once:
            self.fail_resolve_once = False
            raise CompareAndSwapConflict("injected registry CAS failure")
        assert lane_id == self.record.lane_id
        assert expected_claim_generation == self.record.claim_generation
        assert expected_branch == self.record.branch
        assert Path(expected_path) == self.record.path
        assert expected_head_sha == self.record.handed_back_sha
        self.record = replace(self.record, status=disposition)

    def persist_handback(self, receipt: object, *, expected_claim_generation: int) -> None:
        raise AssertionError("CLI must consume, not create, handbacks")


class FakeGit:
    def __init__(self) -> None:
        self.snapshot = _snapshot()
        self.remote: str | None = None
        self.local: str | None = HEAD
        self.worktrees = (PhysicalWorktree(WORKTREE, HEAD, BRANCH),)
        self.fail_remove_once = False

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        assert path == WORKTREE and base_sha == BASE
        return self.snapshot

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.worktrees

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        assert worktree == WORKTREE and branch == BRANCH
        assert expected_local_sha == HEAD and expected_remote_sha == self.remote
        self.remote = HEAD
        return HEAD

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
        assert path == WORKTREE and expected_head_sha == HEAD
        if self.fail_remove_once:
            self.fail_remove_once = False
            raise CompareAndSwapConflict("injected worktree removal failure")
        self.worktrees = ()

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert branch == BRANCH and expected_head_sha == HEAD
        self.local = None

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self.remote = None

    def local_main_sha(self) -> str:
        return BASE

    def origin_main_sha(self) -> str:
        return BASE

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        return expected_origin_sha


class FakeGitHub:
    def __init__(self) -> None:
        self.pull_request: PullRequestSnapshot | None = None

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory(
            () if self.pull_request is None else (self.pull_request,)
        )

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        return self.pull_request

    def create_pull_request(
        self, *, branch: str, title: str, body: str
    ) -> PullRequestSnapshot:
        self.pull_request = PullRequestSnapshot(
            number=41,
            url="https://example.test/pull/41",
            branch=branch,
            base_sha=BASE,
            head_sha=HEAD,
            state="OPEN",
            draft=False,
            mergeable=True,
            title=title,
            body=body,
        )
        return self.pull_request

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        raise AssertionError("new publication must not update")

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert self.pull_request is not None and number == 41
        return self.pull_request

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/a.py",)

    def branch_is_protected(self, branch: str) -> bool:
        return False

    def merge_queue_enabled(self, branch: str) -> bool:
        return True

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return CheckSnapshot(
            status=CheckStatus.SUCCESS,
            head_sha=HEAD,
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
            names=("required",),
        )

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        return self.get_pull_request(number)

    def enqueue(
        self, *, number: int, expected_base_sha: str, expected_head_sha: str
    ) -> None:
        return None

    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]:
        return ()


def test_publish_command_makes_github_durable_then_releases_local_assets() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
    )

    result = app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert result["publication"].pull_request.number == 41
    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert git.local is None
    assert git.remote == HEAD


def test_publish_retry_recovers_after_pr_creation_then_registry_cas_failure() -> None:
    registry = FakeRegistry()
    registry.fail_resolve_once = True
    git = FakeGit()
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
    )

    with pytest.raises(CompareAndSwapConflict, match="injected registry"):
        app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert github.pull_request is not None
    assert git.remote == HEAD
    assert registry.record.status == "active"

    app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert git.local is None


def test_release_retry_recovers_after_registry_publish_then_cleanup_failure() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    git.fail_remove_once = True
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
    )

    with pytest.raises(CompareAndSwapConflict, match="removal"):
        app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert registry.record.status == "published"
    assert git.worktrees

    app.release_published(41)

    assert git.worktrees == ()
    assert git.local is None


def test_cli_queue_preserves_explicit_hold_as_typed_input(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def enqueue(self, *, pull_request_number: int, holds: frozenset[object]) -> object:
            self.calls.append((pull_request_number, holds))
            return {"queued": False}

    application = FakeApplication()

    assert main(
        ["queue", "--pr", "41", "--hold", "security"],
        application_factory=lambda **_: application,
    ) == 0

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert application.calls[0][0] == 41
    assert {item.value for item in application.calls[0][1]} == {"security"}


def test_runtime_status_file_fails_closed_for_unlisted_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"thread-1": "running"}), encoding="utf-8")

    runtime = RuntimeStatusMap.from_file(path)

    assert runtime.owner_status("thread-1") == "running"
    assert runtime.owner_status("thread-unknown") == "unknown"


def test_cli_validate_pr_body_uses_machine_receipt_not_workflow_regex(
    tmp_path: Path, capsys: object
) -> None:
    record = _record()
    receipt = DeliveryApplication(
        repo=Path("/repo"),
        git=FakeGit(),
        github=FakeGitHub(),
        registry=FakeRegistry(),
        runtime=RuntimeStatusMap(),
    ).receipt(record.lane_id)
    body_path = tmp_path / "body.md"
    body_path.write_text(render_pull_request_body(receipt), encoding="utf-8")

    assert main(
        [
            "validate-pr-body",
            "--head-sha",
            receipt.head_sha,
            "--body-file",
            str(body_path),
        ],
        application_factory=lambda **_: object(),
    ) == 0

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["result"]["head_sha"] == receipt.head_sha

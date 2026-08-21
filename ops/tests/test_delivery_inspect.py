from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.git_cli import GitCliAdapter
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.domain.models import (
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    Scope,
    WorktreeSnapshot,
)
from delivery_control.domain.states import CheckStatus, LaneState
from delivery_control.ports.process import CommandResult
from delivery_control.services.inspect import InspectService


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_git_adapter_uses_porcelain_and_computes_exact_base_diff(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-qc", "feat/example")
    (repo / "ops").mkdir()
    (repo / "ops" / "change.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "ops/change.py")
    _git(repo, "commit", "-qm", "change")

    adapter = GitCliAdapter(repo=repo)
    physical = adapter.list_worktrees()
    snapshot = adapter.inspect_worktree(repo, base_sha)

    assert physical == (
        PhysicalWorktree(
            path=repo.resolve(),
            head_sha=_git(repo, "rev-parse", "HEAD"),
            branch="feat/example",
            prunable=False,
        ),
    )
    assert snapshot.clean
    assert snapshot.base_sha == base_sha
    assert snapshot.changed_paths == ("ops/change.py",)


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)


def test_registry_adapter_surfaces_malformed_records_without_hiding_valid_ones(
    tmp_path: Path,
) -> None:
    valid = {
        "branch": "feat/one",
        "path": str(tmp_path / "one"),
        "status": "active",
        "external_ids": ["#1"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-1",
    }
    malformed = {"branch": "feat/bad", "path": "relative", "status": "active"}
    runner = StaticRunner(
        [
            CommandResult(
                argv=("registry", "list"),
                exit_code=0,
                stdout=json.dumps({"records": [valid, malformed]}),
                stderr="",
            )
        ]
    )
    adapter = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    )

    inventory = adapter.list_records()

    assert [record.lane_id for record in inventory.records] == ["#1"]
    assert inventory.records[0].owner_thread_id == "thread-1"
    assert inventory.problems[0].identity == "feat/bad"
    assert (
        "Scope" in inventory.problems[0].reason
        or "path" in inventory.problems[0].reason
    )


def test_github_adapter_keeps_required_checks_separate_from_advisory_rollup() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                argv=("gh", "pr", "list"),
                exit_code=0,
                stdout=json.dumps(
                    [
                        {
                            "number": 12,
                            "url": "https://example.test/pull/12",
                            "headRefName": "feat/one",
                            "baseRefOid": "a" * 40,
                            "headRefOid": "b" * 40,
                            "state": "OPEN",
                            "isDraft": False,
                            "mergeable": "MERGEABLE",
                        }
                    ]
                ),
                stderr="",
            ),
            CommandResult(
                argv=("gh", "pr", "checks"),
                exit_code=1,
                stdout=json.dumps([{"state": "FAILURE", "name": "required"}]),
                stderr="",
            ),
        ]
    )
    adapter = GitHubCliAdapter(runner=runner)

    pull_requests = adapter.list_open_pull_requests()
    required = adapter.required_check_status(12)

    assert pull_requests[0].number == 12
    assert required is CheckStatus.FAILURE
    assert runner.calls[0][:4] == ("gh", "pr", "list", "--state")
    assert "--required" in runner.calls[1]


class FakeRegistry:
    def __init__(self, records: tuple[RegistrySnapshot, ...]) -> None:
        self.inventory = RegistryInventory(records=records)

    def list_records(self) -> RegistryInventory:
        return self.inventory

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return next(
            (item for item in self.inventory.records if item.lane_id == lane_id), None
        )


class FakeGit:
    def __init__(
        self,
        physical: tuple[PhysicalWorktree, ...],
        snapshots: dict[Path, WorktreeSnapshot],
    ) -> None:
        self.physical = physical
        self.snapshots = snapshots

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self.snapshots[path]

    def remote_branch_sha(self, branch: str) -> str | None:
        return None

    def local_main_sha(self) -> str:
        return "a" * 40

    def origin_main_sha(self) -> str:
        return "a" * 40


class FakeGitHub:
    def __init__(self, pull_requests: tuple[PullRequestSnapshot, ...]) -> None:
        self.pull_requests = pull_requests

    def list_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        return self.pull_requests

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        return next(
            (item for item in self.pull_requests if item.branch == branch), None
        )

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        return next(item for item in self.pull_requests if item.number == number)

    def required_check_status(self, number: int) -> CheckStatus:
        return CheckStatus.SUCCESS


def test_inspect_service_correlates_registry_physical_and_github_facts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    scope = Scope.from_paths(modify=("ops/a.py",))
    record = RegistrySnapshot(
        lane_id="#1",
        branch="feat/one",
        path=path,
        status="active",
        scope=scope,
        base_sha="a" * 40,
        owner_thread_id="thread-1",
        handed_back_sha="b" * 40,
        handback_valid=True,
    )
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    snapshot = WorktreeSnapshot(
        path=path,
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
        parent_sha="a" * 40,
        clean=True,
        changed_paths=("ops/a.py",),
    )
    pull_request = PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
    )
    service = InspectService(
        registry=FakeRegistry((record,)),
        git=FakeGit((physical,), {path: snapshot}),
        github=FakeGitHub((pull_request,)),
    )

    inventory = service.inspect()

    assert len(inventory.lanes) == 1
    assert inventory.lanes[0].decision.state is LaneState.READY_TO_QUEUE
    assert inventory.lanes[0].pull_requests == (pull_request,)


def test_inspect_service_marks_scope_overlap_and_unregistered_physical_worktrees(
    tmp_path: Path,
) -> None:
    scope = Scope.from_paths(modify=("ops/shared.py",))
    records = tuple(
        RegistrySnapshot(
            lane_id=f"#{index}",
            branch=f"feat/{index}",
            path=tmp_path / str(index),
            status="active",
            scope=scope,
            base_sha="a" * 40,
            owner_thread_id=f"thread-{index}",
        )
        for index in (1, 2)
    )
    orphan_path = tmp_path / "orphan"
    orphan = PhysicalWorktree(path=orphan_path, head_sha="c" * 40, branch="feat/orphan")
    orphan_snapshot = WorktreeSnapshot(
        path=orphan_path,
        branch="feat/orphan",
        base_sha="a" * 40,
        head_sha="c" * 40,
        parent_sha="a" * 40,
        clean=True,
        changed_paths=("ops/orphan.py",),
    )
    service = InspectService(
        registry=FakeRegistry(records),
        git=FakeGit((orphan,), {orphan_path: orphan_snapshot}),
        github=FakeGitHub(()),
    )

    inventory = service.inspect()
    states = {lane.key: lane.decision.state for lane in inventory.lanes}

    assert states["#1"] is LaneState.BLOCKED_COLLISION
    assert states["#2"] is LaneState.BLOCKED_COLLISION
    assert states[str(orphan_path)] is LaneState.BLOCKED_OWNER

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.git_cli import GitCliAdapter
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.adapters.errors import AdapterCommandError
from delivery_control.domain.models import CheckStatus, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    FileChange,
    FileOperation,
    InventoryProblem,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import LaneState
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


def test_git_adapter_computes_operation_aware_exact_base_diff(tmp_path: Path) -> None:
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
    (repo / "base.txt").write_text("changed\n", encoding="utf-8")
    (repo / "ops").mkdir()
    (repo / "ops" / "change.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "change")

    snapshot = GitCliAdapter(repo=repo).inspect_worktree(repo, base_sha)

    assert snapshot.clean
    assert snapshot.changes == (
        FileChange(FileOperation.MODIFY, "base.txt"),
        FileChange(FileOperation.ADD, "ops/change.py"),
    )


def test_git_new_remote_branch_push_uses_absent_ref_lease(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 0, "feat/one\n", ""),
            CommandResult(("git",), 0, f"{head}\n", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, f"{head}\trefs/heads/feat/one\n", ""),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    adapter.push_branch(
        worktree=tmp_path,
        branch="feat/one",
        expected_local_sha=head,
        expected_remote_sha=None,
    )

    push = next(call for call in runner.calls if "push" in call)
    assert "--force-with-lease=refs/heads/feat/one:" in push


def test_git_local_branch_delete_uses_atomic_expected_old_sha(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 0, f"{head}\n", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 128, "", "unknown revision"),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    adapter.delete_local_branch("feat/one", expected_head_sha=head)

    assert any(
        call[-4:] == ("update-ref", "-d", "refs/heads/feat/one", head)
        for call in runner.calls
    )


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
        "claim_generation": 4,
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
    inventory = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).list_records()

    assert [record.lane_id for record in inventory.records] == ["#1"]
    assert inventory.records[0].claim_generation == 4
    assert inventory.problems[0].identity == "feat/bad"


def test_registry_get_ignores_terminal_history_for_same_lane(tmp_path: Path) -> None:
    active = {
        "branch": "feat/current",
        "path": str(tmp_path / "current"),
        "status": "active",
        "external_ids": ["#1"],
        "base": "a" * 40,
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"operation": "modify", "path": "ops/a.py"}],
        },
        "codex_thread_id": "thread-current",
        "claim_generation": 2,
    }
    terminal = {
        **active,
        "branch": "feat/historical",
        "path": str(tmp_path / "historical"),
        "status": "merged",
        "codex_thread_id": "thread-historical",
        "claim_generation": 1,
    }
    runner = StaticRunner(
        [CommandResult(("registry",), 0, json.dumps({"records": [terminal, active]}), "")]
    )

    record = RegistryCliAdapter(
        script_path=Path("/repo/ops/worktree_registry.py"), runner=runner
    ).get("#1")

    assert record is not None
    assert record.branch == "feat/current"


def _pr_payload() -> dict[str, object]:
    return {
        "number": 12,
        "url": "https://example.test/pull/12",
        "headRefName": "feat/one",
        "baseRefOid": "a" * 40,
        "headRefOid": "b" * 40,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "title": "fix: one",
        "body": "## Scope\n- ops/a.py\n\n## Validation\n- required",
    }


def test_github_adapter_surfaces_malformed_entries() -> None:
    runner = StaticRunner(
        [
            CommandResult(
                argv=("gh", "pr", "list"),
                exit_code=0,
                stdout=json.dumps([_pr_payload(), 7]),
                stderr="",
            )
        ]
    )
    inventory = GitHubCliAdapter(runner=runner).list_open_pull_requests()
    assert [item.number for item in inventory.records] == [12]
    assert inventory.problems == (
        InventoryProblem("github", "entry[1]", "PR entry is not an object"),
    )


def test_github_required_check_snapshot_is_bound_to_exact_head() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(
                ("gh",),
                0,
                json.dumps([{"state": "SUCCESS", "name": "required"}]),
                "",
            ),
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
        ]
    )
    snapshot = GitHubCliAdapter(runner=runner).required_check_snapshot(12)
    assert snapshot.status is CheckStatus.SUCCESS
    assert snapshot.head_sha == "b" * 40
    assert snapshot.names == ("required",)


def test_github_required_checks_preserve_empty_nonzero_command_failure() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 1, "", "network failure"),
        ]
    )

    with pytest.raises(AdapterCommandError):
        GitHubCliAdapter(runner=runner).required_check_snapshot(12)


def test_github_enqueue_atomically_matches_expected_head() -> None:
    runner = StaticRunner(
        [
            CommandResult(("gh",), 0, json.dumps(_pr_payload()), ""),
            CommandResult(("gh",), 0, "", ""),
        ]
    )
    adapter = GitHubCliAdapter(runner=runner)

    adapter.enqueue(
        number=12,
        expected_base_sha="a" * 40,
        expected_head_sha="b" * 40,
    )

    assert runner.calls[-1][-2:] == ("--match-head-commit", "b" * 40)


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
    def __init__(
        self,
        pull_requests: tuple[PullRequestSnapshot, ...],
        *,
        problems: tuple[InventoryProblem, ...] = (),
    ) -> None:
        self.pull_requests = pull_requests
        self.problems = problems

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory(self.pull_requests, self.problems)

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        return next(
            (item for item in self.pull_requests if item.branch == branch), None
        )

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        return next(item for item in self.pull_requests if item.number == number)

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        pull_request = self.get_pull_request(number)
        return CheckSnapshot(
            CheckStatus.SUCCESS,
            pull_request.head_sha,
            datetime(2026, 8, 21, tzinfo=UTC),
            ("required",),
        )

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/a.py",)

    def branch_is_protected(self, branch: str) -> bool:
        return False


class FakeRuntime:
    def owner_status(self, thread_id: str) -> str:
        return "running"

    def dispatch(self, thread_id: str, instruction: str) -> None:
        return None


def _record(path: Path, *, status: str = "active") -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id="#1",
        branch="feat/one",
        path=path,
        status=status,
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=3,
        owner_thread_id="thread-1",
        handed_back_sha="b" * 40,
        handback_claim_generation=3,
        handback_valid=True,
    )


def _snapshot(
    path: Path, *, clean: bool = True, head: str = "b" * 40
) -> WorktreeSnapshot:
    return WorktreeSnapshot(
        path=path,
        branch="feat/one",
        base_sha="a" * 40,
        head_sha=head,
        parent_sha="a" * 40,
        clean=clean,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )


def _pull_request(*, head: str = "b" * 40) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha=head,
        state="OPEN",
        draft=False,
        mergeable=True,
        title="fix: one",
        body="## Scope\n- ops/a.py\n\n## Validation\n- required",
    )


def test_inspect_service_requires_exact_registry_physical_pr_and_check_tuple(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path),)),
        git=FakeGit((physical,), {path: _snapshot(path)}),
        github=FakeGitHub((_pull_request(),)),
        runtime=FakeRuntime(),
    )
    inventory = service.inspect()
    active = next(item for item in inventory.lanes if item.key == "#1")
    assert active.decision.state is LaneState.READY_TO_QUEUE
    assert not active.problems


def test_inspect_service_never_marks_dirty_or_head_drift_ready(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="c" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path),)),
        git=FakeGit((physical,), {path: _snapshot(path, clean=False, head="c" * 40)}),
        github=FakeGitHub((_pull_request(),)),
        runtime=FakeRuntime(),
    )
    active = next(item for item in service.inspect().lanes if item.key == "#1")
    assert active.decision.state is LaneState.BLOCKED_DIRTY
    assert any("HEAD differs" in problem.reason for problem in active.problems)


def test_terminal_registry_history_does_not_claim_physical_worktree(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path, status="abandoned"),)),
        git=FakeGit((physical,), {path: _snapshot(path)}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )
    inventory = service.inspect()
    assert any(item.key == str(path.resolve()) for item in inventory.lanes)
    orphan = next(item for item in inventory.lanes if item.key == str(path.resolve()))
    assert orphan.decision.state is LaneState.BLOCKED_OWNER


def test_inspect_surfaces_github_inventory_problems(tmp_path: Path) -> None:
    problem = InventoryProblem("github", "entry[0]", "malformed")
    service = InspectService(
        registry=FakeRegistry(()),
        git=FakeGit((), {}),
        github=FakeGitHub((), problems=(problem,)),
        runtime=FakeRuntime(),
    )
    assert problem in service.inspect().source_problems

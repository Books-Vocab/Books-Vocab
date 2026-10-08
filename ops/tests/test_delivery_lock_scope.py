"""Operation-lease scope for queue, cleanup-merged and release-published (#2236).

The delivery ``OperationLock`` serializes registry read-modify-write and local
worktree/ref mutation.  GitHub API calls, ``ls-remote`` and ``push`` must run
outside it, otherwise one slow network section makes every concurrent
delivery mutation fail with ``delivery mutation already in progress``.
"""

from __future__ import annotations

import fcntl
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control import cli
from delivery_control.adapters import operation_lock
from delivery_control.adapters.operation_lock import OperationLock
from delivery_control.adapters.runtime import RuntimeStatusMap
from delivery_control.application_services import DeliveryApplication
from delivery_control.domain.errors import CompareAndSwapConflict
from test_delivery_cli import (
    EVENT_START,
    HEAD,
    FakeGit,
    FakeGitHub,
    FakeRegistry,
    MemoryTelemetry,
    _historical_pull_request,
)

NETWORK_CALLS = frozenset(
    {
        "github.get_pull_request",
        "github.changed_paths",
        "git.remote_branch_sha",
        "git.delete_remote_branch",
        "git.origin_main_sha",
    }
)
LEASED_CALLS = frozenset(
    {"registry.resolve", "git.remove_worktree", "git.delete_local_branch"}
)

Calls = list[tuple[str, bool]]


def _lease_held(repo: Path) -> bool:
    return OperationLock(repo, command="probe").path in operation_lock._HELD_LOCKS


def _observe(
    target: object,
    prefix: str,
    names: tuple[str, ...],
    calls: Calls,
    held: Callable[[], bool],
) -> None:
    """Record, per call, whether the delivery lease was held at that moment."""

    for name in names:
        original = getattr(target, name)

        def observed(
            *args: object,
            _name: str = f"{prefix}.{name}",
            _original: Callable[..., object] = original,
            **kwargs: object,
        ) -> object:
            calls.append((_name, held()))
            return _original(*args, **kwargs)

        setattr(target, name, observed)


def _application(
    repo: Path,
) -> tuple[DeliveryApplication, FakeRegistry, FakeGit, FakeGitHub]:
    registry, git, github = FakeRegistry(), FakeGit(), FakeGitHub()
    application = DeliveryApplication(
        repo=repo,
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )
    return application, registry, git, github


def _observe_cleanup_ports(
    repo: Path, registry: FakeRegistry, git: FakeGit, github: FakeGitHub
) -> Calls:
    calls: Calls = []

    def held() -> bool:
        return _lease_held(repo)

    _observe(github, "github", ("get_pull_request", "changed_paths"), calls, held)
    _observe(
        git,
        "git",
        (
            "remote_branch_sha",
            "delete_remote_branch",
            "origin_main_sha",
            "remove_worktree",
            "delete_local_branch",
        ),
        calls,
        held,
    )
    _observe(registry, "registry", ("resolve",), calls, held)
    return calls


def _publish_with_interrupted_release(
    application: DeliveryApplication, registry: FakeRegistry, git: FakeGit
) -> None:
    """Leave a durable PR whose worktree, local and remote branch all remain."""

    git.fail_remove_once = True
    with pytest.raises(CompareAndSwapConflict, match="removal"):
        application.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert registry.record.status == "cleanup_pending"
    assert git.worktrees and git.local == HEAD and git.remote == HEAD


def _assert_network_outside_and_mutation_inside_lease(calls: Calls) -> None:
    network = [(name, held) for name, held in calls if name in NETWORK_CALLS]
    leased = [(name, held) for name, held in calls if name in LEASED_CALLS]
    assert network, calls
    assert [name for name, held in network if held] == []
    assert {name for name, _ in leased} == LEASED_CALLS
    assert [name for name, held in leased if not held] == []


def test_scoped_lease_commands_are_exactly_the_narrowed_mutations() -> None:
    assert cli.SCOPED_LEASE_COMMANDS == {
        "queue",
        "cleanup-merged",
        "release-published",
    }
    assert cli.SCOPED_LEASE_COMMANDS <= cli.MUTATING_COMMANDS


def test_queue_admits_while_another_process_holds_the_operation_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    application, _, _, github = _application(tmp_path)
    application.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    calls: Calls = []
    _observe(github, "github", ("enqueue",), calls, lambda: _lease_held(tmp_path))

    lock_path = OperationLock(tmp_path, command="x").path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as foreign:
        fcntl.flock(foreign.fileno(), fcntl.LOCK_EX)
        exit_code = cli.main(
            ["--repo", str(tmp_path), "queue", "--pr", "41"],
            application_factory=lambda **_: application,
        )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert json.loads(captured.out)["ok"] is True
    assert calls == [("github.enqueue", False)]


def test_cleanup_merged_network_io_runs_outside_the_operation_lease(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    application, registry, git, github = _application(tmp_path)
    _publish_with_interrupted_release(application, registry, git)
    assert github.pull_request is not None
    github.pull_request = replace(
        github.pull_request,
        state="MERGED",
        merged_at=EVENT_START.replace(minute=2),
    )
    calls = _observe_cleanup_ports(tmp_path, registry, git, github)

    exit_code = cli.main(
        ["--repo", str(tmp_path), "cleanup-merged", "--pr", "41"],
        application_factory=lambda **_: application,
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert registry.record.status == "merged"
    assert git.worktrees == () and git.local is None and git.remote is None
    _assert_network_outside_and_mutation_inside_lease(calls)


def test_release_published_network_io_runs_outside_the_operation_lease(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    application, registry, git, github = _application(tmp_path)
    _publish_with_interrupted_release(application, registry, git)
    calls = _observe_cleanup_ports(tmp_path, registry, git, github)

    exit_code = cli.main(
        ["--repo", str(tmp_path), "release-published", "--pr", "41"],
        application_factory=lambda **_: application,
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert registry.record.status == "published"
    assert git.worktrees == () and git.local is None and git.remote == HEAD
    _assert_network_outside_and_mutation_inside_lease(calls)


def test_legacy_cleanup_merged_stays_inside_one_lease(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migration-only exception: receipt-less PRs keep the whole-run lease."""

    application, _, _, github = _application(tmp_path)
    github.pull_request = _historical_pull_request(number=41)
    observed: list[tuple[int, bool]] = []

    class LegacyCleanup:
        def cleanup_merged_pr(self, pull_request_number: int) -> object:
            observed.append((pull_request_number, _lease_held(tmp_path)))
            return {"legacy": True}

    monkeypatch.setattr(
        DeliveryApplication, "_legacy_cleanup", lambda self: LegacyCleanup()
    )

    exit_code = cli.main(
        ["--repo", str(tmp_path), "cleanup-merged", "--pr", "41"],
        application_factory=lambda **_: application,
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.err
    assert observed == [(41, True)]

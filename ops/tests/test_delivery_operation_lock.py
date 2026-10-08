from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.operation_lock import _HELD_LOCKS, OperationLock
from delivery_control.cli import main


def test_operation_lock_allows_nested_context_without_releasing_outer_lease(
    tmp_path: Path,
) -> None:
    with OperationLock(tmp_path, command="sync-main"):
        with OperationLock(tmp_path, command="cleanup-merged"):
            pass
        with OperationLock(tmp_path, command="registry:resolve"):
            pass


def test_operation_lock_rejects_an_external_process(tmp_path: Path) -> None:
    script = """
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[2])
from delivery_control.adapters.operation_lock import OperationLock
with OperationLock(Path(sys.argv[1]), command='child'):
    pass
"""

    with (
        OperationLock(tmp_path, command="sync-main"),
        pytest.raises(subprocess.CalledProcessError),
    ):
        subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), str(OPS)],
            check=True,
            env={**os.environ, "PYTHONPATH": str(OPS)},
            capture_output=True,
            text=True,
        )


def test_operation_lock_releases_after_context_exit(tmp_path: Path) -> None:
    with OperationLock(tmp_path, command="sync-main"):
        pass

    with OperationLock(tmp_path, command="cleanup-merged"):
        pass


def test_cli_reuses_the_outer_lease_for_nested_registry_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = OperationLock(tmp_path, command="probe").path

    class FakeApplication:
        repo = tmp_path

        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        def record_published_base(self, pull_request_number: int) -> object:
            # record-published-base keeps the whole-command lease: the CLI
            # re-entered the outer lease instead of contending on the flock.
            depth = _HELD_LOCKS[lock_path][1]
            with OperationLock(tmp_path, command="registry:record-published-base"):
                self.calls.append((pull_request_number, depth))
            return {"recorded": True}

    application = FakeApplication()
    with OperationLock(tmp_path, command="sync-main"):
        assert (
            main(
                ["record-published-base", "--pr", "41"],
                application_factory=lambda **_: application,
            )
            == 0
        )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert application.calls == [(41, 2)]


def test_suite_lock_is_isolated_from_the_real_delivery_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real delivery holding the shared lock must not redden this suite."""
    import fcntl

    from worktree_registry_core.environment import common_anchor

    # The lock registry/orchestrate actually contend on lives at the canonical
    # anchor (common dir parent), not at a linked worktree's own .cache.
    anchor = common_anchor(OPS.parent)
    with monkeypatch.context() as real:
        real.delenv("KG_DELIVERY_LOCK_DIR", raising=False)
        real_lock = OperationLock(anchor, command="probe").path
    real_lock.parent.mkdir(parents=True, exist_ok=True)
    with real_lock.open("a+") as held:
        try:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # A real delivery already holds it: exactly the contended scenario.
            pass
        assert OperationLock(anchor, command="suite").path != real_lock
        with OperationLock(anchor, command="suite-under-real-delivery"):
            pass


def test_lock_dir_env_override_is_keyed_per_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KG_DELIVERY_LOCK_DIR", str(tmp_path / "locks"))
    repo_a, repo_b = tmp_path / "a", tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    with OperationLock(repo_a, command="a"):
        assert OperationLock(repo_a, command="a").path.parent == tmp_path / "locks"
        with OperationLock(repo_b, command="b"):
            pass
    assert (
        OperationLock(repo_a, command="a").path
        != OperationLock(repo_b, command="b").path
    )

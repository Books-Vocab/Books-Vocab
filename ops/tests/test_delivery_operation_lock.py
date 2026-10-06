from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.operation_lock import OperationLock
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
    class FakeApplication:
        repo = tmp_path

        def __init__(self) -> None:
            self.calls: list[int] = []

        def enqueue(
            self, *, pull_request_number: int, holds: frozenset[object]
        ) -> object:
            del holds
            self.calls.append(pull_request_number)
            return {"queued": True}

    application = FakeApplication()
    with OperationLock(tmp_path, command="sync-main"):
        assert (
            main(
                ["queue", "--pr", "41"],
                application_factory=lambda **_: application,
            )
            == 0
        )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert application.calls == [41]

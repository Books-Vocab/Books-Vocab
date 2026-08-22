from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.operation_lock import OperationLock
from delivery_control.cli import main
from delivery_control.domain.errors import DeliverySourceError


def test_operation_lock_rejects_a_second_process_descriptor(tmp_path: Path) -> None:
    def acquire_second_lock() -> None:
        with OperationLock(tmp_path, command="cleanup-merged"):
            pass

    with OperationLock(tmp_path, command="sync-main"), pytest.raises(
        DeliverySourceError, match="already in progress"
    ):
        acquire_second_lock()


def test_operation_lock_releases_after_context_exit(tmp_path: Path) -> None:
    with OperationLock(tmp_path, command="sync-main"):
        pass

    with OperationLock(tmp_path, command="cleanup-merged"):
        pass


def test_cli_returns_typed_lock_block_without_running_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeApplication:
        repo = tmp_path

        def __init__(self) -> None:
            self.calls: list[int] = []

        def enqueue(self, *, pull_request_number: int, holds: frozenset[object]) -> object:
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
            == 1
        )

    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert "already in progress" in payload["error"]
    assert application.calls == []

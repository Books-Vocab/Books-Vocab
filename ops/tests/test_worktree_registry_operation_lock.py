from __future__ import annotations

import json
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_registry as registry


class _RecordingLock:
    calls: list[str] = []

    def __init__(self, _anchor: Path, *, command: str) -> None:
        self.calls.append(command)

    def __enter__(self) -> "_RecordingLock":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None


def test_direct_registry_mutation_acquires_shared_operation_lock(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": []})
    _RecordingLock.calls = []
    monkeypatch.setattr(registry, "OperationLock", _RecordingLock)

    assert (
        registry.main(["compact", "--state", str(state_path), "--commit", "--json"])
        == registry.EXIT_OK
    )

    assert _RecordingLock.calls == ["registry:compact"]


def test_registry_read_only_command_does_not_acquire_operation_lock(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": []})

    class _UnexpectedLock:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("read-only registry command acquired mutation lock")

    monkeypatch.setattr(registry, "OperationLock", _UnexpectedLock)

    assert registry.main(["list", "--state", str(state_path), "--json"]) == registry.EXIT_OK

    assert json.loads(capsys.readouterr().out)["records"] == []


def test_read_only_compaction_does_not_acquire_operation_lock(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": []})

    class _UnexpectedLock:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("read-only compaction acquired mutation lock")

    monkeypatch.setattr(registry, "OperationLock", _UnexpectedLock)

    assert registry.main(["compact", "--state", str(state_path), "--json"]) == registry.EXIT_OK


def test_nested_orchestrator_registry_call_can_skip_outer_lock(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "registry.json"
    registry.save_state(state_path, {"schema": registry.SCHEMA, "records": []})
    _RecordingLock.calls = []
    monkeypatch.setattr(registry, "OperationLock", _RecordingLock)

    assert (
        registry.main(
            ["compact", "--state", str(state_path), "--commit", "--json"],
            acquire_lock=False,
        )
        == registry.EXIT_OK
    )

    assert _RecordingLock.calls == []

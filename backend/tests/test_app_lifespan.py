from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kg.app_lifespan import AppLifespanDependencies, build_app_lifespan_from_dependencies
from kg.settings import KGSettings


class _SpyLogger:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def info(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        self._events.append(("log", rendered))


def _settings(tmp_path) -> KGSettings:
    return KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret-key-for-ci-at-least-32-bytes",
        admin_token="adm-secret",
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )


def _dependencies(tmp_path, events: list[object]) -> AppLifespanDependencies:
    async def _reset_async_clients() -> None:
        events.append("reset_async_clients")

    def _assert_single_worker(lock_path) -> None:
        events.append(("assert_single_worker", lock_path))

    def _reap_orphaned_runs() -> int:
        events.append("reap_orphaned_runs")
        return 2

    def _release_worker_lock() -> None:
        events.append("release_worker_lock")

    def _reset_clients() -> None:
        events.append("reset_clients")

    return AppLifespanDependencies(
        settings=_settings(tmp_path),
        logger=_SpyLogger(events),
        assert_single_worker_fn=_assert_single_worker,
        reap_orphaned_runs_fn=_reap_orphaned_runs,
        release_worker_lock_fn=_release_worker_lock,
        reset_clients_fn=_reset_clients,
        reset_async_clients_fn=_reset_async_clients,
    )


def test_build_app_lifespan_from_dependencies_runs_expected_flow(tmp_path):
    events: list[object] = []
    lifespan = build_app_lifespan_from_dependencies(
        dependencies=_dependencies(tmp_path, events)
    )
    app = FastAPI(lifespan=lifespan)

    with TestClient(app):
        pass

    assert events == [
        ("log", "KG API starting up"),
        ("assert_single_worker", tmp_path / ".worker.lock"),
        "reap_orphaned_runs",
        ("log", "Reaped 2 orphaned pipeline run(s) → interrupted"),
        ("log", "KG API shutting down"),
        "release_worker_lock",
        "reset_clients",
        "reset_async_clients",
    ]


def test_app_lifespan_dependencies_are_replaceable_named_contract(tmp_path):
    deps = _dependencies(tmp_path, [])
    replacement_logger = _SpyLogger([])

    replaced = replace(deps, logger=replacement_logger)

    assert replaced.logger is replacement_logger
    assert replaced.settings == deps.settings

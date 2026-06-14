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

    def warning(self, message: str, *args: object) -> None:
        rendered = message % args if args else message
        self._events.append(("warning", rendered))


def _settings(tmp_path) -> KGSettings:
    return KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret-key-for-ci-at-least-32-bytes",
        admin_token="adm-secret",
        admin_password="adm-pw-secret",
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


def _run_lifespan_with_settings(tmp_path, settings: KGSettings) -> list[object]:
    events: list[object] = []
    deps = replace(_dependencies(tmp_path, events), settings=settings)
    lifespan = build_app_lifespan_from_dependencies(dependencies=deps)
    app = FastAPI(lifespan=lifespan)
    with TestClient(app):
        pass
    return events


def _warnings(events: list[object]) -> list[str]:
    return [
        e[1]
        for e in events
        if isinstance(e, tuple) and len(e) == 2 and e[0] == "warning"
    ]


def test_empty_admin_token_logs_startup_warning(tmp_path):
    """Blank admin_token at startup → a prominent WARNING (no hard-fail)."""
    settings = replace(_settings(tmp_path), admin_token="", admin_password="adm-pw")
    events = _run_lifespan_with_settings(tmp_path, settings)
    warnings = _warnings(events)
    assert any("admin_token" in w.lower() or "admin token" in w.lower() for w in warnings), warnings


def test_empty_admin_password_logs_startup_warning(tmp_path):
    """Blank admin_password at startup → a prominent WARNING (no hard-fail)."""
    settings = replace(_settings(tmp_path), admin_token="adm-tok", admin_password="")
    events = _run_lifespan_with_settings(tmp_path, settings)
    warnings = _warnings(events)
    assert any("admin_password" in w.lower() or "admin password" in w.lower() for w in warnings), warnings


def test_configured_admin_secrets_emit_no_warning(tmp_path):
    """Both admin secrets set → no admin-secret startup warning."""
    settings = replace(_settings(tmp_path), admin_token="adm-tok", admin_password="adm-pw")
    events = _run_lifespan_with_settings(tmp_path, settings)
    warnings = _warnings(events)
    assert not any("admin" in w.lower() for w in warnings), warnings


def test_empty_admin_secrets_do_not_hard_fail(tmp_path):
    """Blank admin secrets must NOT raise at startup (dev/test flow preserved)."""
    settings = replace(_settings(tmp_path), admin_token="", admin_password="")
    events = _run_lifespan_with_settings(tmp_path, settings)
    # Startup + shutdown both completed (no exception escaped TestClient).
    assert ("log", "KG API starting up") in events
    assert ("log", "KG API shutting down") in events


def test_app_lifespan_dependencies_are_replaceable_named_contract(tmp_path):
    deps = _dependencies(tmp_path, [])
    replacement_logger = _SpyLogger([])

    replaced = replace(deps, logger=replacement_logger)

    assert replaced.logger is replacement_logger
    assert replaced.settings == deps.settings

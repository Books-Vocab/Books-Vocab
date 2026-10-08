from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kg.admin_wiring import (
    AdminHandlerDependencies,
    AdminHandlers,
    create_admin_handlers_from_dependencies,
)


def _settings():
    return SimpleNamespace(
        admin_token="adm-token",
        admin_password="",
        data_dir=Path("/tmp/kg-data"),
    )


def _load_users():
    return {}


def _save_users(_users):
    return None


def _mem_logs(*_args, **_kwargs):
    return []


def _card_store(*_args, **_kwargs):
    return None


def _build_entitlements(_user_record):
    return {"ok": True}


def _current_admin_grant(_user_record):
    return {}


def _dependencies() -> AdminHandlerDependencies:
    return AdminHandlerDependencies(
        runtime_settings_fn=_settings,
        runtime_users_lock_file_fn=lambda: Path("/tmp/users.lock"),
        load_users_fn=_load_users,
        save_users_fn=_save_users,
        mem_log_getter=_mem_logs,
        card_store_factory=_card_store,
        build_entitlements_response_fn=_build_entitlements,
        current_admin_grant_record_fn=_current_admin_grant,
    )


def test_create_admin_handlers_from_dependencies_returns_named_bundle():
    handlers = create_admin_handlers_from_dependencies(dependencies=_dependencies())

    assert isinstance(handlers, AdminHandlers)
    assert callable(handlers.admin_ui)
    assert callable(handlers.admin_stats)
    assert callable(handlers.admin_test_catalog)


def test_admin_handler_dependencies_are_replaceable_named_contract():
    deps = _dependencies()
    replacement = replace(deps, runtime_users_lock_file_fn=lambda: Path("/tmp/other.lock"))

    assert replacement.runtime_users_lock_file_fn() == Path("/tmp/other.lock")
    assert deps.runtime_users_lock_file_fn() == Path("/tmp/users.lock")


@pytest.mark.anyio
async def test_admin_log_retention_runs_via_threadpool():
    handlers = create_admin_handlers_from_dependencies(dependencies=_dependencies())
    report = {
        "pipeline_log": {"deleted": 1},
        "judge_log": {"deleted": 2},
        "translate_log": {"deleted": 3},
        "translate_cache_hits": {"deleted": 4},
        "token_usage": {"deleted": 5},
    }
    calls = []

    async def fake_threadpool(fn, *args, **kwargs):
        calls.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    with (
        patch("kg.log_retention.run_all", return_value=report) as run_all,
        patch("kg.admin_wiring.run_in_threadpool", new=fake_threadpool),
    ):
        response = await handlers.admin_log_retention_run()

    assert calls == [(run_all, (), {})]
    assert response["pipeline_deleted"] == 1
    assert response["translate_cache_hits_deleted"] == 4

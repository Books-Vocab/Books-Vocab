from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kg.admin_wiring import (
    AdminHandlerDependencies,
    AdminHandlers,
    create_admin_handlers,
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


def test_create_admin_handlers_preserves_legacy_wrapper_contract():
    deps = _dependencies()

    named = create_admin_handlers_from_dependencies(dependencies=deps)
    legacy = create_admin_handlers(
        runtime_settings_fn=deps.runtime_settings_fn,
        runtime_users_lock_file_fn=deps.runtime_users_lock_file_fn,
        load_users_fn=deps.load_users_fn,
        save_users_fn=deps.save_users_fn,
        mem_log_getter=deps.mem_log_getter,
        card_store_factory=deps.card_store_factory,
        build_entitlements_response_fn=deps.build_entitlements_response_fn,
        current_admin_grant_record_fn=deps.current_admin_grant_record_fn,
    )

    assert isinstance(legacy, AdminHandlers)
    named_ui = named.admin_ui()
    legacy_ui = legacy.admin_ui()
    assert type(named_ui) is type(legacy_ui)
    assert named_ui.body == legacy_ui.body

    named_tests_ui = named.admin_tests_ui()
    legacy_tests_ui = legacy.admin_tests_ui()
    assert type(named_tests_ui) is type(legacy_tests_ui)
    assert named_tests_ui.body == legacy_tests_ui.body


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

    with patch("kg.log_retention.run_all", return_value=report) as run_all, \
         patch("kg.admin_wiring.run_in_threadpool", new=fake_threadpool):
        response = await handlers.admin_log_retention_run()

    assert calls == [(run_all, (), {})]
    assert response["pipeline_deleted"] == 1
    assert response["translate_cache_hits_deleted"] == 4

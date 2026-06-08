from __future__ import annotations

from fastapi import FastAPI

from kg.app_runtime_state import RuntimeUserState, install_runtime_user_state
from kg.settings import KGSettings


def test_install_runtime_user_state_returns_named_bundle_and_wires_app_state(tmp_path):
    app = FastAPI()
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-secret",
    )
    app.state.kg_settings = settings

    bindings = install_runtime_user_state(
        app,
        settings,
        default_subscription_payload_fn=lambda: {"source": "test"},
    )

    assert isinstance(bindings, RuntimeUserState)
    assert app.state.user_store is bindings.user_store
    assert app.state.load_users is bindings.load_users
    assert app.state.save_users is bindings.save_users
    assert app.state.normalize_users_payload is bindings.normalize_users_payload


def test_runtime_user_state_load_and_save_share_the_same_store(tmp_path):
    app = FastAPI()
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-secret",
    )
    app.state.kg_settings = settings

    bindings = install_runtime_user_state(
        app,
        settings,
        default_subscription_payload_fn=lambda: {"source": "test"},
    )

    expected = {"user-123": {"config": {"theme": "dark"}}}
    bindings.save_users(expected)

    assert bindings.load_users() == expected
    assert app.state.load_users() == expected

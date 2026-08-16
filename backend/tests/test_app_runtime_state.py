from __future__ import annotations

import json
from dataclasses import replace

from fastapi import FastAPI

from kg.app_runtime_state import (
    RuntimeUserState,
    RuntimeUserStateDependencies,
    install_runtime_user_state,
    install_runtime_user_state_from_dependencies,
)
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


def test_install_runtime_user_state_from_dependencies_matches_compat_wrapper(tmp_path):
    app = FastAPI()
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-secret",
    )
    app.state.kg_settings = settings

    named = install_runtime_user_state_from_dependencies(
        dependencies=RuntimeUserStateDependencies(
            app=app,
            settings=settings,
            default_subscription_payload_fn=lambda: {"source": "test"},
        )
    )

    other_app = FastAPI()
    other_app.state.kg_settings = settings
    compat = install_runtime_user_state(
        other_app,
        settings,
        default_subscription_payload_fn=lambda: {"source": "test"},
    )

    assert isinstance(named, RuntimeUserState)
    assert isinstance(compat, RuntimeUserState)
    assert named.load_users() == compat.load_users()
    assert named.normalize_users_payload({}) == compat.normalize_users_payload({})


def test_runtime_user_state_dependencies_are_replaceable_named_contract(tmp_path):
    app = FastAPI()
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-secret",
    )
    deps = RuntimeUserStateDependencies(
        app=app,
        settings=settings,
        default_subscription_payload_fn=lambda: {"source": "test"},
    )

    replacement = replace(
        deps,
        default_subscription_payload_fn=lambda: {"source": "other"},
    )

    assert deps.default_subscription_payload_fn()["source"] == "test"
    assert replacement.default_subscription_payload_fn()["source"] == "other"


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


def test_runtime_user_state_persists_normalized_legacy_config(tmp_path):
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-secret",
    )
    settings.users_file.write_text(
        json.dumps(
            {
                "user-123": {
                    "config": {
                        "review_mode": {
                            "mode": "relaxed",
                            "include_dictionary_cards": True,
                        }
                    }
                }
            }
        )
    )
    app = FastAPI()
    app.state.kg_settings = settings

    install_runtime_user_state(
        app,
        settings,
        default_subscription_payload_fn=lambda: {"source": "test"},
    )

    persisted = json.loads(settings.users_file.read_text())
    assert persisted["user-123"]["config"]["review_mode"] == {"mode": "relaxed"}

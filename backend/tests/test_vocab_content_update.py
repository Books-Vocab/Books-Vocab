"""Integration tests for PATCH /api/vocab/{word} content-update.

Distinct from PATCH /api/vocab/{word}/archive (archive state toggle) and
DELETE /api/vocab/{word} (soft delete). This route mutates editorial content:
meaning / note (with `explanation` accepted as a write-through alias for note).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    (data_dir / "users.json").write_text(json.dumps({user_id: {"config": {}}}))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    _swap_settings(KGSettings(data_dir=data_dir, jwt_secret=TEST_JWT_SECRET))
    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        yield SimpleNamespace(
            client=TestClient(app, raise_server_exceptions=False),
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _seed_word(api, word="apple", translation="蘋果"):
    # Seed directly via CardStore so we don't trigger the real embedding call
    # the HTTP add path makes (no API key under test). Mirrors test_vocab_service.
    from kg.cards import CardStore

    store = CardStore(api.data_dir / "users" / api.user_id / "cards.db")
    store.add(content=word, meaning=translation, notebook_id="default")
    return word


def test_update_meaning(isolated_api):
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(
        f"/api/vocab/{word}", json={"meaning": "a round fruit"}, headers=isolated_api.headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == word
    assert body["meaning"] == "a round fruit"


def test_update_note(isolated_api):
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(
        f"/api/vocab/{word}", json={"note": "from Latin malum"}, headers=isolated_api.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "from Latin malum"


def test_explanation_aliases_note(isolated_api):
    """`explanation` is accepted as a write-through alias for the `note` column."""
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(
        f"/api/vocab/{word}", json={"explanation": "teacher commentary"}, headers=isolated_api.headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "teacher commentary"


def test_explicit_note_wins_over_explanation(isolated_api):
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(
        f"/api/vocab/{word}",
        json={"note": "real note", "explanation": "ignored"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "real note"


def test_update_multiple_fields(isolated_api):
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(
        f"/api/vocab/{word}",
        json={"meaning": "fruit", "note": "n."},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meaning"] == "fruit"
    assert body["note"] == "n."


def test_empty_body_returns_400(isolated_api):
    word = _seed_word(isolated_api)
    r = isolated_api.client.patch(f"/api/vocab/{word}", json={}, headers=isolated_api.headers)
    assert r.status_code == 400, r.text


def test_update_nonexistent_word_returns_404(isolated_api):
    r = isolated_api.client.patch(
        "/api/vocab/ghostword", json={"meaning": "x"}, headers=isolated_api.headers
    )
    assert r.status_code == 404, r.text


def test_update_requires_auth(isolated_api):
    r = isolated_api.client.patch("/api/vocab/apple", json={"meaning": "x"})
    assert r.status_code == 401, r.text


def test_update_persists_in_lookup(isolated_api):
    word = _seed_word(isolated_api)
    isolated_api.client.patch(
        f"/api/vocab/{word}", json={"meaning": "persisted"}, headers=isolated_api.headers
    )
    r = isolated_api.client.get(f"/api/vocab/{word}", headers=isolated_api.headers)
    assert r.status_code == 200, r.text
    assert r.json()["meaning"] == "persisted"

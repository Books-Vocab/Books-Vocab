from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from datetime import UTC, datetime, timedelta
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

# Always prefer this workspace's source tree during tests.
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Force deterministic test env (do not inherit prod secrets/config).
os.environ["KG_DATA_DIR"] = "/tmp/kg_test_default"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci-at-least-32-bytes"
os.environ["GEMINI_API_KEY"] = "fake-key"


TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _swap_settings(new_settings):
    """Replace app.state.kg_settings and rebuild load/save closures."""
    from kg.user_store import CachedUserStore, normalize_users_payload
    from kg.billing import default_subscription_payload
    from kg.api import app

    app.state.kg_settings = new_settings

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(new_settings.users_file, _normalize)
    app.state.user_store = user_store
    app.state.load_users = lambda: user_store.load()
    app.state.save_users = lambda users: user_store.save(users)
    app.state.normalize_users_payload = _normalize


class _DummyEmbeddingStore:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def has(self, card_id: str) -> bool:
        return card_id in self._ids

    def add(self, card_id: str, text: str) -> None:
        self._ids.add(card_id)

    def find_similar(self, card_id: str, k: int = 3):
        return []


@pytest.fixture()
def isolated_api(tmp_path):
    import kg.api as api_mod
    import kg.deps as deps_mod
    from kg.api import app
    from kg.settings import KGSettings

    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    users_file.write_text(
        json.dumps(
            {
                user_id: {"config": {}},
                "other_user": {
                    "config": {"integrations": {"mochi": {"api_key": "mk_live"}}},
                    "provider": "google",
                    "email": "other@example.com",
                },
            }
        )
    )

    users_data = json.loads(users_file.read_text())
    users_data[user_id]["subscription"] = {
        "is_active": True,
        "status": "active",
        "plan_name": "Books & Vocab Pro",
        "trial_days": 7,
        "will_renew": True,
    }
    users_file.write_text(json.dumps(users_data))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save

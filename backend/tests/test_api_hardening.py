"""
Tests for API hardening: input validation, request size limit, _USER_LOCKS LRU cap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def client_env(tmp_path):
    (tmp_path / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:6]
    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps(
            {
                user_id: {
                    "config": {},
                    "subscription": {
                        "is_active": True,
                        "status": "active",
                        "plan_name": "Books & Vocab Pro",
                        "trial_days": 7,
                        "will_renew": True,
                    },
                }
            }
        )
    )

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield client, user_id, headers, tmp_path
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


# ============================================================================
# Task 1 — _USER_LOCKS LRU cap
# ============================================================================


class TestUserLocksLRU:

    def test_locks_capped_at_max(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            for i in range(api_mod._MAX_USER_LOCKS + 50):
                await api_mod.get_user_lock(f"user_{i}")
            return len(api_mod._USER_LOCKS)

        size = asyncio.run(run())
        assert size <= api_mod._MAX_USER_LOCKS, (
            f"_USER_LOCKS grew to {size}, expected <= {api_mod._MAX_USER_LOCKS}"
        )

    def test_recent_user_kept_after_eviction(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            # Fill to max
            for i in range(api_mod._MAX_USER_LOCKS):
                await api_mod.get_user_lock(f"old_user_{i}")
            # Access a recent user — should be kept
            await api_mod.get_user_lock("recent_user")
            # Add one more to trigger eviction
            await api_mod.get_user_lock("new_user_trigger")
            return "recent_user" in api_mod._USER_LOCKS

        kept = asyncio.run(run())
        assert kept, "recently accessed user should not be evicted"

    def test_same_user_returns_same_lock_after_reaccess(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            deps_mod._USER_LOCKS_MUTEX = None
            l1 = await api_mod.get_user_lock("stable_user")
            # Access many other users to push eviction pressure
            for i in range(api_mod._MAX_USER_LOCKS - 1):
                await api_mod.get_user_lock(f"filler_{i}")
            # Re-access stable_user before eviction pressure hits it
            l2 = await api_mod.get_user_lock("stable_user")
            return l1 is l2

        assert asyncio.run(run()), "same lock object must be returned for reaccessed user"


# ============================================================================
# Task 2 — Input length validation (422)
# ============================================================================


class TestInputValidation:
    def test_validation_error_log_redacts_secret_body_fields(self, client_env, caplog):
        client, _user_id, _headers, _ = client_env

        caplog.set_level(logging.WARNING, logger="kg.api")
        r = client.post(
            "/auth/verify",
            json={"provider": "invalid-provider", "token": "secret-provider-token"},
        )

        assert r.status_code == 422, r.text
        assert "secret-provider-token" not in caplog.text
        assert "secret-provider-token" not in r.text
        assert "[REDACTED]" in caplog.text

    def test_validation_error_log_redacts_secret_error_input(self, client_env, caplog):
        client, _user_id, _headers, _ = client_env
        oversized_token = "secret-provider-token-" + ("x" * 10000)

        caplog.set_level(logging.WARNING, logger="kg.api")
        r = client.post(
            "/auth/verify",
            json={"provider": "apple", "token": oversized_token},
        )

        assert r.status_code == 422, r.text
        assert "secret-provider-token" not in caplog.text
        assert "secret-provider-token" not in r.text
        assert "[REDACTED]" in caplog.text
        assert r.json()["detail"][0]["input"] == "[REDACTED]"

    def test_validation_error_log_redacts_camel_case_secret_body_fields(self, client_env, caplog):
        client, _user_id, headers, _ = client_env

        caplog.set_level(logging.WARNING, logger="kg.api")
        r = client.post(
            "/api/vocab",
            json=[{"word": "x" * 201, "translation": "test", "accessToken": "secret-access-token"}],
            headers=headers,
        )

        assert r.status_code == 422, r.text
        assert "secret-access-token" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_validation_error_redacts_camel_case_secret_error_input(self):
        redacted = api_mod._redact_validation_payload(
            [{"loc": ["body", "accessToken"], "input": "secret-access-token"}]
        )

        assert redacted == [{"loc": ["body", "accessToken"], "input": "[REDACTED]"}]

    def test_validation_redaction_covers_common_secret_key_styles(self):
        redacted = api_mod._redact_validation_payload(
            {
                "api_key": "secret-api-key",
                "apiKey": "secret-api-key-camel",
                "client-secret": "secret-client",
                "secret": "secret-generic",
                "safe": "visible",
            }
        )

        assert redacted == {
            "api_key": "[REDACTED]",
            "apiKey": "[REDACTED]",
            "client-secret": "[REDACTED]",
            "secret": "[REDACTED]",
            "safe": "visible",
        }

    def test_validation_body_regex_redacts_non_json_secret_keys(self):
        redacted = api_mod._redact_validation_body(
            "apiKey=secret-api-key&client-secret=secret-client&safe=visible"
        )

        assert redacted == "[non-json body omitted: secret-like field present]"
        assert "secret-api-key" not in redacted
        assert "secret-client" not in redacted

    def test_validation_body_truncates_non_json_without_secret_keys(self):
        redacted = api_mod._redact_validation_body("safe=" + ("x" * 1000))

        assert redacted is not None
        assert len(redacted) == 500
        assert redacted.startswith("safe=")

    def test_translate_word_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/translate/quick",
            json={"word": "x" * 501, "context": "some context"},
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_translate_context_too_long_truncated(self, client_env):
        """Overlong context is silently truncated by the before-validator, not rejected."""
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/translate/quick",
            json={"word": "hello", "context": "x" * 5001},
            headers=headers,
        )
        # Before-validator truncates to 1000 chars, so Pydantic accepts it.
        # The request proceeds (may fail for other reasons like missing API key,
        # but it should NOT be 422).
        assert r.status_code != 422, r.text

    def test_translate_word_at_limit_accepted(self, client_env):
        """Exactly 500 chars should pass Pydantic validation (not 422)."""
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/translate/quick",
            json={"word": "x" * 500, "context": "some context"},
            headers=headers,
        )
        # Any status other than 422 means Pydantic accepted the input
        assert r.status_code != 422, f"Exactly 500 chars should be accepted, got {r.status_code}"

    def test_vocab_word_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "x" * 201, "translation": "test", "context": ""}],
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_vocab_translation_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "hello", "translation": "x" * 1001, "context": ""}],
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_vocab_context_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "hello", "translation": "test", "context": "x" * 5001}],
            headers=headers,
        )
        assert r.status_code == 422, r.text


# ============================================================================
# Task 3 — Request body size limit (413)
# ============================================================================


class TestRequestBodySizeLimit:

    def test_large_body_returns_413(self, client_env):
        client, user_id, headers, _ = client_env
        large_body = b"x" * (11 * 1024 * 1024)  # 11MB
        r = client.post(
            "/api/vocab",
            content=large_body,
            headers={**headers, "content-type": "application/json", "content-length": str(len(large_body))},
        )
        assert r.status_code == 413, r.text

    def test_body_at_limit_not_rejected_by_size(self, client_env):
        client, user_id, headers, _ = client_env
        # 9MB body — should NOT get 413 (may still get 422 from JSON parse, but not 413)
        small_body = b"x" * (9 * 1024 * 1024)
        r = client.post(
            "/api/vocab",
            content=small_body,
            headers={**headers, "content-type": "application/json", "content-length": str(len(small_body))},
        )
        assert r.status_code != 413, "9MB body should not be rejected by size limit middleware"


# ============================================================================
# Vocab intake batch cap — POST /api/vocab list max_length
# ============================================================================


class TestVocabIntakeBatchCap:
    """POST /api/vocab must cap the entries list AT THE SCHEMA LAYER.

    A pre-existing handler guard (vocab_intake.add_vocab_entries) already raised
    422 for >500 entries, but only AFTER FastAPI deserialized the entire list
    into VocabEntry models — so a ~10^5-element payload still got fully parsed,
    which is the amplification the audit flags. Putting max_length=500 on the
    route's `entries` field rejects at request-validation time (FastAPI
    RequestValidationError, loc-based "too_long") before the list is built.

    This test pins the *schema-layer* rejection by asserting the FastAPI
    validation-error shape, distinguishing it from the handler's custom
    {"code":"ValidationError"} body.
    """

    @staticmethod
    def _entry(i: int) -> dict:
        return {"word": f"w{i}", "translation": "t"}

    def test_over_cap_rejected_at_schema_layer(self, client_env):
        client, _user_id, headers, _ = client_env
        payload = [self._entry(i) for i in range(501)]
        r = client.post("/api/vocab", json=payload, headers=headers)
        assert r.status_code == 422, r.text
        body = r.json()
        # FastAPI request-validation error: detail is a list of loc/type dicts.
        # The handler's guard instead returns {"code":"ValidationError",...}.
        detail = body.get("detail")
        assert isinstance(detail, list), (
            f"expected FastAPI validation-error list, got {body!r}"
        )
        types = {err.get("type") for err in detail}
        assert "too_long" in types, f"expected too_long error, got {detail!r}"

    def test_route_entries_field_has_max_length_500(self):
        """The route signature carries the cap as schema metadata."""
        import typing

        from kg.routers import vocab as vocab_router

        hints = typing.get_type_hints(
            vocab_router.add_vocab, include_extras=True
        )
        entries_hint = hints["entries"]
        metadata = getattr(entries_hint, "__metadata__", ())
        # The cap can sit directly on a constraint marker (annotated-types
        # MaxLen) or inside a pydantic FieldInfo's nested .metadata list.
        max_lengths: list[int] = []
        for m in metadata:
            direct = getattr(m, "max_length", None)
            if direct is not None:
                max_lengths.append(direct)
            for inner in getattr(m, "metadata", ()):  # FieldInfo.metadata
                inner_len = getattr(inner, "max_length", None)
                if inner_len is not None:
                    max_lengths.append(inner_len)
        assert 500 in max_lengths, (
            f"entries field must carry max_length=500, metadata={metadata!r}"
        )

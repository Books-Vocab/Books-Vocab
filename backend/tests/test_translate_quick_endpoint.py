"""Integration tests for POST /api/translate/quick.

Covers the endpoint's HTTP contract (not the service-layer cache, which is
exercised in test_translate_cache_integration.py):

  1. Happy path — 200 + response shape conforms to QuickTranslateResponse
     ({t, p, r}). Critical because the iOS reader binds against these keys.
  2. Validation — 422 when `word` violates Pydantic constraints
     (min_length=1 / max_length=500).
  3. Auth — 401 when the bearer token is expired or invalid.

These are *endpoint* tests using FastAPI's TestClient + the shared
`isolated_api` fixture. The LLM is stubbed via `_gemini_async_client`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt

import kg.routers.translate as translate_router_mod

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def _stub_quick_llm(content: str = '{"t":"喚起","p":"v.","r":"evoke"}') -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=None,
        )
    )
    return client


def test_translate_quick_basic_request_returns_expected_shape(isolated_api):
    """200 + body matches QuickTranslateResponse: keys {t, p, r}.

    The iOS reader's translation card binds on these exact keys; a regression
    that renames `t`/`p`/`r` silently would break that surface."""
    client = isolated_api.client
    headers = isolated_api.headers

    fake = _stub_quick_llm('{"t":"喚起","p":"v.","r":"evoke"}')
    with patch.object(translate_router_mod, "_gemini_async_client", return_value=fake):
        r = client.post(
            "/api/translate/quick",
            json={"word": "evoke", "context": "The story can evoke deep memories."},
            headers=headers,
        )

    assert r.status_code == 200, r.text
    body = r.json()
    # Required field
    assert body["t"] == "喚起"
    # Optional but present fields
    assert body["p"] == "v."
    assert body["r"] == "evoke"
    # No leakage of unexpected keys (response_model strips them)
    assert set(body.keys()) <= {"t", "p", "r"}


def test_translate_quick_invalid_request_returns_422(isolated_api):
    """Pydantic validation: word must be 1..500 chars.

    Three concrete violations (empty word / >500 chars / missing word) should
    all surface as 422 with a `detail` payload — never 200/500."""
    client = isolated_api.client
    headers = isolated_api.headers

    # Empty word violates min_length=1
    r_empty = client.post(
        "/api/translate/quick",
        json={"word": "", "context": "hi"},
        headers=headers,
    )
    assert r_empty.status_code == 422, r_empty.text
    assert "detail" in r_empty.json()

    # Word > 500 violates max_length=500
    r_long = client.post(
        "/api/translate/quick",
        json={"word": "x" * 501, "context": "hi"},
        headers=headers,
    )
    assert r_long.status_code == 422, r_long.text
    assert "detail" in r_long.json()

    # Missing required `word` field
    r_missing = client.post(
        "/api/translate/quick",
        json={"context": "hi"},
        headers=headers,
    )
    assert r_missing.status_code == 422, r_missing.text
    assert "detail" in r_missing.json()


def test_translate_quick_unauthenticated_returns_401(isolated_api):
    """Expired and invalid bearer tokens must yield 401 + WWW-Authenticate.

    HTTPBearer-without-header returns 403 (FastAPI default), which is a
    different contract; here we lock down the 401 path that the iOS client
    actually reacts to (refresh / re-auth flow)."""
    client = isolated_api.client

    # Expired token
    expired_payload = {
        "sub": isolated_api.user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC) - timedelta(hours=2),
        "exp": datetime.now(tz=UTC) - timedelta(hours=1),
    }
    expired_token = pyjwt.encode(expired_payload, TEST_JWT_SECRET, algorithm="HS256")
    r_expired = client.post(
        "/api/translate/quick",
        json={"word": "evoke", "context": "hi"},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r_expired.status_code == 401, r_expired.text
    assert r_expired.headers.get("www-authenticate", "").lower().startswith("bearer")

    # Invalid token (garbage)
    r_invalid = client.post(
        "/api/translate/quick",
        json={"word": "evoke", "context": "hi"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r_invalid.status_code == 401, r_invalid.text
    assert r_invalid.headers.get("www-authenticate", "").lower().startswith("bearer")

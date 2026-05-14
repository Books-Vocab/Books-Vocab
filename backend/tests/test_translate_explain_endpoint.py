"""Integration tests for POST /api/translate/explain.

Symmetric to test_translate_quick_endpoint.py — locks down the HTTP contract
of the explain endpoint independently of the service-layer cache:

  1. Happy path — 200 + response shape conforms to ExplainResponse ({e}).
     The iOS reader's "explain" surface binds against this exact key.
  2. Validation — 422 when `word` violates Pydantic constraints
     (min_length=1 / max_length=500 / missing).
  3. Auth — 401 when the bearer token is expired or invalid (with
     `WWW-Authenticate: Bearer` header, which is the iOS refresh trigger).

LLM is stubbed via `_gemini_async_client` so no network is touched.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt

import kg.routers.translate as translate_router_mod

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def _stub_explain_llm(content: str = '{"e":"To bring a feeling or memory to mind."}') -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=None,
        )
    )
    return client


def test_explain_basic_request_returns_expected_shape(isolated_api):
    """200 + body matches ExplainResponse: keys {e}.

    The reader's explain card binds on this exact key; a silent rename of
    `e` would break that surface without a backend test failure."""
    client = isolated_api.client
    headers = isolated_api.headers

    fake = _stub_explain_llm('{"e":"To bring a feeling or memory to mind."}')
    with patch.object(translate_router_mod, "_gemini_async_client", return_value=fake):
        r = client.post(
            "/api/translate/explain",
            json={"word": "evoke", "context": "The story can evoke deep memories."},
            headers=headers,
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["e"] == "To bring a feeling or memory to mind."
    # response_model strips any unexpected keys; lock the shape.
    assert set(body.keys()) == {"e"}


def test_explain_invalid_request_returns_422(isolated_api):
    """Pydantic validation: word must be 1..500 chars.

    Empty / >500 chars / missing should all surface as 422 + detail —
    never 200/500. No LLM patch needed: validation fails before dispatch."""
    client = isolated_api.client
    headers = isolated_api.headers

    # Empty word violates min_length=1
    r_empty = client.post(
        "/api/translate/explain",
        json={"word": "", "context": "hi"},
        headers=headers,
    )
    assert r_empty.status_code == 422, r_empty.text
    assert "detail" in r_empty.json()

    # Word > 500 violates max_length=500
    r_long = client.post(
        "/api/translate/explain",
        json={"word": "x" * 501, "context": "hi"},
        headers=headers,
    )
    assert r_long.status_code == 422, r_long.text
    assert "detail" in r_long.json()

    # Missing required `word` field
    r_missing = client.post(
        "/api/translate/explain",
        json={"context": "hi"},
        headers=headers,
    )
    assert r_missing.status_code == 422, r_missing.text
    assert "detail" in r_missing.json()


def test_explain_invalid_token_returns_401(isolated_api):
    """Expired and invalid bearer tokens must yield 401 + WWW-Authenticate.

    HTTPBearer-without-header returns 403 (FastAPI default); here we lock
    down the 401 path that the iOS client reacts to (refresh/re-auth)."""
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
        "/api/translate/explain",
        json={"word": "evoke", "context": "hi"},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r_expired.status_code == 401, r_expired.text
    assert r_expired.headers.get("www-authenticate", "").lower().startswith("bearer")

    # Invalid token (garbage)
    r_invalid = client.post(
        "/api/translate/explain",
        json={"word": "evoke", "context": "hi"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r_invalid.status_code == 401, r_invalid.text
    assert r_invalid.headers.get("www-authenticate", "").lower().startswith("bearer")

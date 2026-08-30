"""Integration tests for POST /api/translate/quick.

Covers the endpoint's HTTP contract (not the service-layer cache, which is
exercised in test_translate_cache_integration.py):

  1. Happy path — 200 + response shape conforms to QuickTranslateResponse
     ({t, p, r}). Critical because the iOS reader binds against these keys.
  2. Validation — 422 when `word` violates Pydantic constraints
     (min_length=1 / max_length=500).
  3. Auth — 401 when the bearer token is expired or invalid.

These are *endpoint* tests using FastAPI's TestClient + the shared
`isolated_api` fixture. The LLM client is stubbed via `create_async_client`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest

from conftest import TEST_JWT_SECRET


@pytest.fixture(scope="module", autouse=True)
def _token_tracker_is_closed_after_module():
    yield
    from kg import token_tracker

    token_tracker.reset()
    assert token_tracker._conn is None, "token_tracker connection leaked past test module"


def _stub_quick_llm(
    content: str = '{"t":"喚起","p":"v.","r":"evoke"}',
    *,
    usage=None,
) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=usage,
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
    with patch("kg.translate_handlers.create_async_client", return_value=fake):
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


def test_translate_quick_success_header_reports_post_use_quota_snapshot(isolated_api):
    """A successful response reports quota remaining after its LLM usage."""
    client = isolated_api.client
    headers = isolated_api.headers
    usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0)

    fake = _stub_quick_llm(usage=usage)
    with patch("kg.translate_handlers.create_async_client", return_value=fake):
        r = client.post(
            "/api/translate/quick",
            json={"word": "evoke-quota-snapshot", "context": "The story can evoke deep memories."},
            headers=headers,
        )

    assert r.status_code == 200, r.text
    # The Pro test user has a $0.30 limit; 1M Gemini input tokens consume
    # $0.10, leaving 2/3 of the quota. The old route emitted the pre-use 1.0.
    assert r.headers["X-Quota-Fraction"] == "0.6667"
    assert r.headers["X-Quota-Reset"] == "86400"


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

    # ValueError-based Pydantic validators include ctx.error in Pydantic v2;
    # the API handler must still serialize this as a normal 422.
    r_bad_lang = client.post(
        "/api/translate/quick",
        json={"word": "evoke", "source_lang": "xx"},
        headers=headers,
    )
    assert r_bad_lang.status_code == 422, r_bad_lang.text
    assert "detail" in r_bad_lang.json()


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

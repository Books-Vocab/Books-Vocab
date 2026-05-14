"""Translate service — cooldown (cache), quota exhaustion, and concurrent dedup.

These tests pin three behaviors that protect the LLM spend budget:

1. Repeat requests within the cache TTL ("cooldown") must short-circuit and
   not call the LLM a second time.
2. When a user's daily quota is exhausted, the translate router must surface
   a clear 429 with a reset hint (so clients can back off intelligently).
3. Concurrent identical requests must dedup the LLM call (a "thundering herd"
   on a fresh cache miss must not multiply LLM spend).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


# ── 1. cooldown / cache short-circuit ─────────────────────────────


def _llm_stub(content: str, user_id: str = "u_test"):
    """LLM stub matching the shape translate_service uses (chat_async + user_id)."""
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )
    return SimpleNamespace(
        chat_async=AsyncMock(return_value=response),
        user_id=user_id,
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.translate_log as tl
    tl._reset()
    yield
    tl._reset()


@pytest.mark.asyncio
async def test_translate_repeat_request_within_cooldown_uses_cache_not_llm():
    """Same user, same input, twice in a row → LLM called exactly once.

    "Cooldown" in this codebase is the translate_log cache (default 1-day TTL).
    The second identical call within TTL must short-circuit without invoking
    the LLM, even though both calls go through the full service path.
    """
    from kg.api_models import TranslateRequest
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"id": "u_test", "config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}
    llm = _llm_stub('{"t":"喚起","p":"v.","r":"evoke"}', user_id="u_test")
    import logging
    logger = logging.getLogger("test")

    r1 = await run_quick_translate(req, user, llm=llm, logger=logger)
    r2 = await run_quick_translate(req, user, llm=llm, logger=logger)

    assert r1.t == "喚起"
    assert r2.t == "喚起"
    # First call hit LLM, second served from cache.
    assert llm.chat_async.await_count == 1


# ── 2. quota exhaustion → 429 with reset hint ─────────────────────


def test_translate_quota_exhausted_returns_clear_error(isolated_api):
    """When a user's quota is exhausted, /api/translate/quick returns 429
    with a machine-readable reset hint, not a generic 500/502."""
    # Force the quota check to report exhausted, regardless of token usage.
    fake_quota = {"exceeded": True, "fraction": 0.0, "reset_seconds": 1234}
    with patch("kg.quota_service.check_and_get_quota", return_value=fake_quota):
        resp = isolated_api.client.post(
            "/api/translate/quick",
            json={"word": "evoke", "context": "The story evokes memories."},
            headers=isolated_api.headers,
        )

    assert resp.status_code == 429, resp.text
    body = resp.json()
    # Surface (a) a stable code clients can branch on, and
    # (b) a reset hint so clients can back off precisely.
    detail = body.get("detail", body)
    assert detail.get("code") == "quota_exhausted"
    assert detail.get("reset_seconds") == 1234


# ── 3. concurrent dedup ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_translate_concurrent_same_input_dedup():
    """Same user, same input, fired concurrently → LLM called exactly once.

    Without dedup, both coroutines miss the cache and both call the LLM —
    doubling spend on every duplicate burst (e.g. retries, double-taps,
    UI race conditions). This pins the behavior we want.
    """
    from kg.api_models import TranslateRequest
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"id": "u_test", "config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}

    call_started = asyncio.Event()
    release = asyncio.Event()

    async def slow_chat(*args, **kwargs):
        # First waiter signals "I started"; then both block until release,
        # guaranteeing both coroutines race on the same cache miss.
        call_started.set()
        await release.wait()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"t":"喚起","p":"v.","r":"evoke"}'))],
            usage=None,
        )

    llm = SimpleNamespace(chat_async=AsyncMock(side_effect=slow_chat), user_id="u_test")
    import logging
    logger = logging.getLogger("test")

    t1 = asyncio.create_task(run_quick_translate(req, user, llm=llm, logger=logger))
    # Ensure t1 enters the LLM call before t2 even starts — t2 must see the
    # in-flight call and dedup, not race past the cache check.
    await call_started.wait()
    t2 = asyncio.create_task(run_quick_translate(req, user, llm=llm, logger=logger))

    # Give t2 a moment to reach the dedup point.
    await asyncio.sleep(0.05)
    release.set()

    r1, r2 = await asyncio.gather(t1, t2)
    assert r1.t == "喚起"
    assert r2.t == "喚起"
    assert llm.chat_async.await_count == 1, (
        f"Expected dedup → 1 LLM call, got {llm.chat_async.await_count}. "
        "Concurrent identical requests must share a single in-flight LLM call."
    )

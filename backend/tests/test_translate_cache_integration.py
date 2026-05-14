"""End-to-end: translate_service cache short-circuit invokes record_cache_hit."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.translate_log as tl
    tl._reset()
    yield
    tl._reset()


def _llm_stub(content: str, user_id: str = "u1"):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )
    return SimpleNamespace(
        chat_async=AsyncMock(return_value=response),
        user_id=user_id,
    )


@pytest.mark.asyncio
async def test_cache_hit_short_circuit_records_counter():
    """On the 2nd identical call, cache short-circuits AND increments hit counter."""
    from kg.api_models import TranslateRequest
    from kg.translate_log import count_cache_hits_since
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}
    llm = _llm_stub('{"t":"喚起","p":"v.","r":"evoke"}')
    import logging
    logger = logging.getLogger("test")

    # 1st call → LLM miss, record translate_log row, no cache_hit
    await run_quick_translate(req, user, llm=llm, logger=logger)
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert count_cache_hits_since(cutoff) == 0

    # 2nd identical call → cache short-circuit, increments hit counter
    await run_quick_translate(req, user, llm=llm, logger=logger)
    assert count_cache_hits_since(cutoff) == 1

    # 3rd call → another hit
    await run_quick_translate(req, user, llm=llm, logger=logger)
    assert count_cache_hits_since(cutoff) == 2


# ---------------------------------------------------------------------------
# TTL + cross-user + model-key — end-to-end via translate_service.
# These complement test_translate_log.py (which exercises the cache layer
# directly) by covering the service-level wiring users actually hit.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_cache_ttl_env_respected(monkeypatch):
    """TRANSLATE_CACHE_TTL_DAYS=1 → after 2-day-aged cache row, service re-calls LLM.

    Verifies the env override propagates through `_run_llm_translate` (not just
    `translate_log.lookup()` in isolation).
    """
    monkeypatch.setenv("TRANSLATE_CACHE_TTL_DAYS", "1")
    from kg.api_models import TranslateRequest
    from kg.translate_log import _get_conn, _lock
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}
    llm = _llm_stub('{"t":"喚起","p":"v.","r":"evoke"}')
    import logging
    logger = logging.getLogger("test")

    # 1st call — LLM miss → record.
    await run_quick_translate(req, user, llm=llm, logger=logger)
    assert llm.chat_async.await_count == 1

    # Age the recorded row to 2 days ago — beyond the 1-day TTL.
    old_ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE translate_log SET created_at=? WHERE word='evoke'", (old_ts,))
        conn.commit()

    # 2nd call — cache row is now stale → service must re-call LLM.
    await run_quick_translate(req, user, llm=llm, logger=logger)
    assert llm.chat_async.await_count == 2, (
        "Stale cache row (older than TRANSLATE_CACHE_TTL_DAYS) must not short-circuit LLM"
    )


@pytest.mark.asyncio
async def test_translate_cache_cross_user_hit_does_not_leak_user_specific_data():
    """User A misses → caches. User B hits cache; hit row is attributed to user B.

    The translate cache is intentionally cross-user (same word/context/lang/op →
    same translation). But the *audit trail* must attribute the hit to whoever
    triggered the lookup, not the original cacher. Otherwise admin metrics
    falsely bill user A for user B's traffic.
    """
    from kg.api_models import TranslateRequest
    from kg.translate_log import _get_conn, _lock
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}
    import logging
    logger = logging.getLogger("test")

    # User A: cache miss → LLM call → translate_log row owned by user_a.
    llm_a = _llm_stub('{"t":"喚起","p":"v.","r":"evoke"}', user_id="user_a")
    result_a = await run_quick_translate(req, user, llm=llm_a, logger=logger)
    assert llm_a.chat_async.await_count == 1

    # User B: cache hit — must NOT call LLM, must return the same payload.
    llm_b = _llm_stub('{"t":"SHOULD_NOT_BE_CALLED"}', user_id="user_b")
    result_b = await run_quick_translate(req, user, llm=llm_b, logger=logger)
    assert llm_b.chat_async.await_count == 0, "Cross-user cache must hit on identical key"
    assert result_a.t == result_b.t == "喚起"

    # Audit: translate_log (misses) stays owned by user A.
    # translate_cache_hits (hits) is attributed to user B — billing/observability fairness.
    with _lock:
        conn = _get_conn()
        miss_users = [r[0] for r in conn.execute(
            "SELECT user_id FROM translate_log WHERE word='evoke'"
        ).fetchall()]
        hit_users = [r[0] for r in conn.execute(
            "SELECT user_id FROM translate_cache_hits WHERE word='evoke'"
        ).fetchall()]
    assert miss_users == ["user_a"], "LLM-miss row must remain owned by the user who paid for the call"
    assert hit_users == ["user_b"], "Cache-hit row must be attributed to the requesting user, not the cacher"


@pytest.mark.asyncio
async def test_translate_cache_invalidation_on_model_change():
    """Cache key must include `model`: changing model invalidates the prior entry.

    Translation outputs are model-dependent (prompt-format, instruction-following,
    style). A cache entry written by `gemini-2.5-flash-lite` must not be served
    to a request explicitly asking for a different model — otherwise switching
    model has no effect until TTL expires.
    """
    from kg.api_models import TranslateRequest
    from kg.translate_service import run_quick_translate

    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    user = {"config": {"translation": {"source_lang": "en", "target_lang": "zh-Hant"}}}
    import logging
    logger = logging.getLogger("test")

    llm_v1 = _llm_stub('{"t":"v1","p":"v.","r":"evoke"}')
    await run_quick_translate(req, user, llm=llm_v1, logger=logger, model="gemini-2.5-flash-lite")
    assert llm_v1.chat_async.await_count == 1

    # Same input, different model — must re-call LLM (no cache hit).
    llm_v2 = _llm_stub('{"t":"v2","p":"v.","r":"evoke"}')
    result_v2 = await run_quick_translate(req, user, llm=llm_v2, logger=logger, model="gemini-2.5-pro")
    assert llm_v2.chat_async.await_count == 1, (
        "Cache key must include model — switching model must not serve stale output"
    )
    assert result_v2.t == "v2"

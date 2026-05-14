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

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import HTTPException

from .cards import CardStore
from .daily_stats import DailyReviewStatsStore
from .embeddings import EmbeddingStore
from .graph import GraphStore

_STORE_CACHE: OrderedDict[str, object] = OrderedDict()
_STORE_CACHE_LOCK = threading.Lock()
_STORE_CACHE_MAX = 100


def _get_cached(key: str, factory):
    with _STORE_CACHE_LOCK:
        if key in _STORE_CACHE:
            _STORE_CACHE.move_to_end(key)
            return _STORE_CACHE[key]
        instance = factory()
        _STORE_CACHE[key] = instance
        while len(_STORE_CACHE) > _STORE_CACHE_MAX:
            _STORE_CACHE.popitem(last=False)
        return instance


def clear_store_cache() -> None:
    with _STORE_CACHE_LOCK:
        _STORE_CACHE.clear()


def create_card_store(user_dir: Path) -> CardStore:
    key = f"card:{user_dir}"
    return _get_cached(key, lambda: CardStore(user_dir / "cards.db"))


def create_daily_stats_store(user_dir: Path) -> DailyReviewStatsStore:
    key = f"stats:{user_dir}"
    return _get_cached(key, lambda: DailyReviewStatsStore(user_dir / "daily_review_stats.db"))


def create_graph_store(user_dir: Path) -> GraphStore:
    key = f"graph:{user_dir}"
    return _get_cached(key, lambda: GraphStore(user_dir / "graph.json", user_dir / "candidates.json"))


_gemini_client = None


def create_gemini_client():
    global _gemini_client
    from openai import OpenAI

    if _gemini_client is not None:
        return _gemini_client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    _gemini_client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    return _gemini_client


def reset_gemini_client() -> None:
    global _gemini_client
    _gemini_client = None


_async_gemini_client = None


def create_async_gemini_client():
    global _async_gemini_client
    from openai import AsyncOpenAI

    if _async_gemini_client is not None:
        return _async_gemini_client
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    _async_gemini_client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    return _async_gemini_client


def reset_async_gemini_client() -> None:
    global _async_gemini_client
    _async_gemini_client = None


def create_embedding_store(
    user_dir: Path,
    *,
    gemini_client_factory,
    user_id: str | None = None,
) -> EmbeddingStore:
    return EmbeddingStore(
        user_dir / "embeddings.npy",
        user_dir / "card_ids.json",
        gemini_client_factory(),
        user_id=user_id,
    )

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import HTTPException

from .cards import CardStore
from .daily_stats import DailyReviewStatsStore
from .embeddings import EmbeddingStore
from .graph import GraphStore
from .notebook import NotebookStore

logger = logging.getLogger(__name__)

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


def _migrate_graph_files(user_dir: Path, notebook_id: str) -> tuple[Path, Path]:
    """Resolve graph file paths with lazy migration from legacy names."""
    links_path = user_dir / f"graph_{notebook_id}.json"
    candidates_path = user_dir / f"candidates_{notebook_id}.json"

    if notebook_id == "default":
        legacy_links = user_dir / "graph.json"
        legacy_candidates = user_dir / "candidates.json"
        if not links_path.exists() and legacy_links.exists():
            logger.info("Migrating %s -> %s", legacy_links, links_path)
            legacy_links.rename(links_path)
            bak = legacy_links.with_suffix(".json.bak")
            if bak.exists():
                bak.rename(links_path.with_suffix(".json.bak"))
        if not candidates_path.exists() and legacy_candidates.exists():
            logger.info("Migrating %s -> %s", legacy_candidates, candidates_path)
            legacy_candidates.rename(candidates_path)

    return links_path, candidates_path


def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path = _migrate_graph_files(user_dir, notebook_id)
    return _get_cached(key, lambda: GraphStore(links_path, candidates_path))


def _migrate_embedding_files(user_dir: Path, notebook_id: str) -> tuple[Path, Path]:
    """Resolve embedding file paths with lazy migration from legacy names."""
    emb_path = user_dir / f"embeddings_{notebook_id}.npy"
    ids_path = user_dir / f"card_ids_{notebook_id}.json"

    if notebook_id == "default":
        legacy_emb = user_dir / "embeddings.npy"
        legacy_ids = user_dir / "card_ids.json"
        if not emb_path.exists() and legacy_emb.exists():
            logger.info("Migrating %s -> %s", legacy_emb, emb_path)
            legacy_emb.rename(emb_path)
        if not ids_path.exists() and legacy_ids.exists():
            logger.info("Migrating %s -> %s", legacy_ids, ids_path)
            legacy_ids.rename(ids_path)

    return emb_path, ids_path


def create_notebook_store(user_dir: Path) -> NotebookStore:
    key = f"notebook:{user_dir}"
    return _get_cached(key, lambda: NotebookStore(user_dir / "notebooks.db"))


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
    notebook_id: str = "default",
) -> EmbeddingStore:
    emb_path, ids_path = _migrate_embedding_files(user_dir, notebook_id)
    return EmbeddingStore(
        emb_path,
        ids_path,
        gemini_client_factory(),
        user_id=user_id,
    )

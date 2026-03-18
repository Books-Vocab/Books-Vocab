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


def _close_store(store: object) -> None:
    """Best-effort close for evicted stores."""
    close_fn = getattr(store, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            logger.debug("Failed to close evicted store %s", type(store).__name__, exc_info=True)


def _get_cached(key: str, factory):
    with _STORE_CACHE_LOCK:
        if key in _STORE_CACHE:
            _STORE_CACHE.move_to_end(key)
            return _STORE_CACHE[key]
        instance = factory()
        _STORE_CACHE[key] = instance
        while len(_STORE_CACHE) > _STORE_CACHE_MAX:
            _, evicted = _STORE_CACHE.popitem(last=False)
            _close_store(evicted)
        return instance


def clear_store_cache() -> None:
    with _STORE_CACHE_LOCK:
        for store in _STORE_CACHE.values():
            _close_store(store)
        _STORE_CACHE.clear()


def create_card_store(user_dir: Path) -> CardStore:
    key = f"card:{user_dir}"
    return _get_cached(key, lambda: CardStore(user_dir / "cards.db"))


def create_daily_stats_store(user_dir: Path) -> DailyReviewStatsStore:
    key = f"stats:{user_dir}"
    return _get_cached(key, lambda: DailyReviewStatsStore(user_dir / "daily_review_stats.db"))


def _migrate_legacy_file(legacy: Path, target: Path) -> None:
    """Rename a legacy file to its notebook-scoped path. Race-safe."""
    if not target.exists() and legacy.exists():
        try:
            logger.info("Migrating %s -> %s", legacy, target)
            legacy.rename(target)
            bak = legacy.with_suffix(legacy.suffix + ".bak")
            if bak.exists():
                bak.rename(target.with_suffix(target.suffix + ".bak"))
        except FileNotFoundError:
            pass  # already migrated by concurrent request


def _resolve_notebook_paths(
    user_dir: Path,
    notebook_id: str,
    file_specs: list[tuple[str, str]],
) -> list[Path]:
    """Resolve per-notebook file paths with lazy migration from legacy names.

    file_specs: list of (template, legacy_name) — template uses {nb} placeholder.
    """
    paths = [user_dir / tmpl.format(nb=notebook_id) for tmpl, _ in file_specs]
    if notebook_id == "default":
        for (_, legacy_name), target in zip(file_specs, paths):
            _migrate_legacy_file(user_dir / legacy_name, target)
    return paths


def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("graph_{nb}.json", "graph.json"),
        ("candidates_{nb}.json", "candidates.json"),
    ])
    return _get_cached(key, lambda: GraphStore(links_path, candidates_path))


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
    emb_path, ids_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("embeddings_{nb}.npy", "embeddings.npy"),
        ("card_ids_{nb}.json", "card_ids.json"),
    ])
    return EmbeddingStore(
        emb_path,
        ids_path,
        gemini_client_factory(),
        user_id=user_id,
    )

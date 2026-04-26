from __future__ import annotations

import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

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
    """Cache-or-build with double-checked locking.

    Builds (factory()) run *outside* `_STORE_CACHE_LOCK` so slow store init
    (SQLite engine open + PRAGMAs + .npy load) doesn't serialise unrelated
    cache lookups. If two callers race on the same missing key, both build
    their own instance; the second arrival discards its build and returns
    the already-cached one — duplicate close is harmless.
    """
    # Fast path: existing entry.
    with _STORE_CACHE_LOCK:
        if key in _STORE_CACHE:
            _STORE_CACHE.move_to_end(key)
            return _STORE_CACHE[key]

    # Build outside the lock.
    instance = factory()

    # Insert + evict under the lock; drop our build if another thread won.
    with _STORE_CACHE_LOCK:
        existing = _STORE_CACHE.get(key)
        if existing is not None:
            _STORE_CACHE.move_to_end(key)
            evicted_self = instance
            instance = existing
        else:
            _STORE_CACHE[key] = instance
            evicted_self = None
        evicted: list[object] = []
        while len(_STORE_CACHE) > _STORE_CACHE_MAX:
            _, victim = _STORE_CACHE.popitem(last=False)
            evicted.append(victim)

    if evicted_self is not None:
        _close_store(evicted_self)
    for victim in evicted:
        _close_store(victim)
    return instance


def evict_notebook_cache(user_dir: Path, notebook_id: str) -> None:
    """Remove cached graph and embedding stores for a deleted notebook."""
    with _STORE_CACHE_LOCK:
        for prefix in ("graph", "embedding"):
            key = f"{prefix}:{user_dir}:{notebook_id}"
            store = _STORE_CACHE.pop(key, None)
            if store is not None:
                _close_store(store)


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
    if not re.match(r'^[a-zA-Z0-9_-]+$', notebook_id):
        raise ValueError(f"Invalid notebook_id: {notebook_id!r}")
    paths = [user_dir / tmpl.format(nb=notebook_id) for tmpl, _ in file_specs]
    if notebook_id == "default":
        for (_, legacy_name), target in zip(file_specs, paths):
            _migrate_legacy_file(user_dir / legacy_name, target)
    return paths


def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path, blocked_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("graph_{nb}.json", "graph.json"),
        ("candidates_{nb}.json", "candidates.json"),
        ("blocked_{nb}.json", "blocked.json"),
    ])
    pj_path = user_dir / f"pending_judge_{notebook_id}.json"
    return _get_cached(key, lambda: GraphStore(links_path, candidates_path, blocked_path, pending_judge_path=pj_path))


def create_notebook_store(user_dir: Path) -> NotebookStore:
    key = f"notebook:{user_dir}"
    return _get_cached(key, lambda: NotebookStore(user_dir / "notebooks.db"))


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _require_gemini_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured on server")
    return api_key


_gemini_client = None


def create_gemini_client():
    global _gemini_client
    from openai import OpenAI

    if _gemini_client is not None:
        return _gemini_client
    _gemini_client = OpenAI(
        api_key=_require_gemini_api_key(),
        base_url=_GEMINI_BASE_URL,
    )
    return _gemini_client


def reset_gemini_client() -> None:
    global _gemini_client
    client = _gemini_client
    _gemini_client = None
    if client is not None:
        try:
            client.close()
        except Exception:
            logger.debug("Failed to close gemini client", exc_info=True)


_async_gemini_client = None


def create_async_gemini_client():
    global _async_gemini_client
    from openai import AsyncOpenAI

    if _async_gemini_client is not None:
        return _async_gemini_client
    _async_gemini_client = AsyncOpenAI(
        api_key=_require_gemini_api_key(),
        base_url=_GEMINI_BASE_URL,
    )
    return _async_gemini_client


async def reset_async_gemini_client() -> None:
    global _async_gemini_client
    client = _async_gemini_client
    _async_gemini_client = None
    if client is not None:
        try:
            await client.close()
        except Exception:
            logger.debug("Failed to close async gemini client", exc_info=True)


def create_embedding_store(
    user_dir: Path,
    *,
    llm,
    notebook_id: str = "default",
    model: str | None = None,
    dim: int | None = None,
) -> EmbeddingStore:
    if model is None or dim is None:
        from .settings import load_settings
        s = load_settings()
        model = model or s.embedding_model
        dim = dim or s.embedding_dim
    key = f"embedding:{user_dir}:{notebook_id}:{model}:{dim}"
    emb_path, ids_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("embeddings_{nb}.npy", "embeddings.npy"),
        ("card_ids_{nb}.json", "card_ids.json"),
    ])
    return _get_cached(key, lambda: EmbeddingStore(emb_path, ids_path, llm, model=model, dim=dim))

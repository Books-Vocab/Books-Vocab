from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from .cards import CardStore
from .embeddings import EmbeddingStore
from .graph import GraphStore
from .graph_event_log import GraphEventStore, GraphSnapshotStore
from .library import LibraryStore
from .llm.providers import REGISTRY, LLMProvider
from .notebook import NotebookStore
from .ops_shared import NOTEBOOK_FILE_SPECS
from .review_events import ReviewEventStore

logger = logging.getLogger(__name__)

_STORE_CACHE: OrderedDict[str, object] = OrderedDict()
_STORE_CACHE_LOCK = threading.Lock()
_STORE_INIT_EVENTS: dict[str, threading.Event] = {}
_STORE_CACHE_GENERATION = 0
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
    """Cache-or-build with per-key in-flight coordination.

    Builds (factory()) run *outside* `_STORE_CACHE_LOCK` so slow store init
    (SQLite engine open + PRAGMAs + .npy load) doesn't serialise unrelated
    cache lookups. One caller owns a missing key's in-flight build; same-key
    waiters block on its event, then re-check the cache. If the just-built
    instance was evicted before a waiter wakes, the waiter registers itself as
    the next sole builder under the global lock, so same-key builds still never
    overlap.
    """
    while True:
        with _STORE_CACHE_LOCK:
            if key in _STORE_CACHE:
                _STORE_CACHE.move_to_end(key)
                return _STORE_CACHE[key]
            event = _STORE_INIT_EVENTS.get(key)
            if event is None:
                event = threading.Event()
                _STORE_INIT_EVENTS[key] = event
                generation = _STORE_CACHE_GENERATION
                break
        event.wait()

    try:
        instance = factory()
    except BaseException:
        with _STORE_CACHE_LOCK:
            if _STORE_INIT_EVENTS.get(key) is event:
                _STORE_INIT_EVENTS.pop(key, None)
                event.set()
        raise

    # Insert + evict under the global lock.
    with _STORE_CACHE_LOCK:
        evicted: list[object] = []
        if _STORE_CACHE_GENERATION == generation:
            _STORE_CACHE[key] = instance
        while len(_STORE_CACHE) > _STORE_CACHE_MAX:
            _, victim = _STORE_CACHE.popitem(last=False)
            evicted.append(victim)
        if _STORE_INIT_EVENTS.get(key) is event:
            _STORE_INIT_EVENTS.pop(key, None)
            event.set()

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
    global _STORE_CACHE_GENERATION
    with _STORE_CACHE_LOCK:
        _STORE_CACHE_GENERATION += 1
        for store in _STORE_CACHE.values():
            _close_store(store)
        _STORE_CACHE.clear()


def create_card_store(user_dir: Path) -> CardStore:
    key = f"card:{user_dir}"
    return _get_cached(key, lambda: CardStore(user_dir / "cards.db"))


def create_review_event_store(user_dir: Path) -> ReviewEventStore:
    key = f"review_events:{user_dir}"
    return _get_cached(key, lambda: ReviewEventStore(user_dir / "review_events.db"))


def create_graph_event_store(user_dir: Path) -> GraphEventStore:
    """Per-user 圖譜變動帳本(單檔,notebook_id 為欄位,跨 notebook 共享)。"""
    key = f"graph_events:{user_dir}"
    return _get_cached(key, lambda: GraphEventStore(user_dir / "graph_events.db"))


def create_graph_snapshot_store(user_dir: Path) -> GraphSnapshotStore:
    """Per-user 圖譜週期 snapshot store（與 graph event ledger 共用同一 SQLite 檔）。"""
    key = f"graph_snapshots:{user_dir}"
    return _get_cached(key, lambda: GraphSnapshotStore(user_dir / "graph_events.db"))


def _migrate_legacy_file(legacy: Path, target: Path) -> None:
    """Rename a legacy file to its notebook-scoped path. Race-safe."""
    if not target.exists() and legacy.exists():
        # already migrated by concurrent request
        with contextlib.suppress(FileNotFoundError):
            logger.info("Migrating %s -> %s", legacy, target)
            legacy.rename(target)
            bak = legacy.with_suffix(legacy.suffix + ".bak")
            if bak.exists():
                bak.rename(target.with_suffix(target.suffix + ".bak"))


def _resolve_notebook_paths(
    user_dir: Path,
    notebook_id: str,
    file_specs: list[tuple[str, str | None]],
) -> list[Path]:
    """Resolve per-notebook file paths with lazy migration from legacy names.

    file_specs: list of (template, legacy_name) — template uses {nb} placeholder.
    Specs come from ops_shared.NOTEBOOK_FILE_SPECS; only specs with a non-None
    legacy_name are passed here, so the migration loop never sees None.
    """
    if not re.match(r'^[a-zA-Z0-9_-]+$', notebook_id):
        raise ValueError(f"Invalid notebook_id: {notebook_id!r}")
    paths = [user_dir / tmpl.format(nb=notebook_id) for tmpl, _ in file_specs]
    if notebook_id == "default":
        for (_, legacy_name), target in zip(file_specs, paths, strict=True):
            _migrate_legacy_file(user_dir / legacy_name, target)
    return paths


def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path, blocked_path = _resolve_notebook_paths(user_dir, notebook_id, [
        NOTEBOOK_FILE_SPECS["graph"],
        NOTEBOOK_FILE_SPECS["candidates"],
        NOTEBOOK_FILE_SPECS["blocked"],
    ])
    pj_path = user_dir / f"pending_judge_{notebook_id}.json"
    # 注入 per-user 變動帳本,讓 Store 層每筆 mutation emit 真實事件(Phase 6)。
    # 用 provider 而非直接注入:GraphStore 可能被長期持有(pipeline 跨秒 hold),而
    # event_store 在共享 LRU 快取中可能先被逐出並 close;每次 emit 透過 provider 重解析,
    # 命中快取(逐出則重建)後再寫,杜絕對死引用靜默丟事件。
    return _get_cached(
        key,
        lambda: GraphStore(
            links_path, candidates_path, blocked_path, pending_judge_path=pj_path,
            event_store_provider=lambda: create_graph_event_store(user_dir),
            snapshot_store_provider=lambda: create_graph_snapshot_store(user_dir),
            event_notebook_id=notebook_id,
        ),
    )


def create_notebook_store(user_dir: Path) -> NotebookStore:
    key = f"notebook:{user_dir}"
    return _get_cached(key, lambda: NotebookStore(user_dir / "notebooks.db"))


def create_library_store(user_dir: Path) -> LibraryStore:
    key = f"library:{user_dir}"
    return _get_cached(key, lambda: LibraryStore(user_dir / "library.db"))


# Per-provider OpenAI-compatible client cache. Keyed by provider name so a
# multi-provider deploy (translate→DeepSeek, embed→Gemini) holds one client
# per provider rather than per call.
_clients: dict[str, object] = {}
_async_clients: dict[str, object] = {}
_clients_lock = threading.Lock()


def _require_api_key(provider: LLMProvider) -> str:
    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"{provider.api_key_env} not configured on server "
            f"(required for LLM provider {provider.name!r})"
        )
    return api_key


def create_client(provider: LLMProvider):
    """Sync OpenAI-compatible client for a provider, cached per provider name."""
    from openai import OpenAI

    with _clients_lock:
        client = _clients.get(provider.name)
        if client is None:
            client = OpenAI(api_key=_require_api_key(provider), base_url=provider.base_url)
            _clients[provider.name] = client
        return client


def create_async_client(provider: LLMProvider):
    """Async OpenAI-compatible client for a provider, cached per provider name."""
    from openai import AsyncOpenAI

    with _clients_lock:
        client = _async_clients.get(provider.name)
        if client is None:
            client = AsyncOpenAI(api_key=_require_api_key(provider), base_url=provider.base_url)
            _async_clients[provider.name] = client
        return client


def create_gemini_client():
    """Backward-compatible alias — sync client for the gemini provider."""
    return create_client(REGISTRY["gemini"])


def reset_clients() -> None:
    """Drop + close all cached sync clients (e.g. after API key rotation)."""
    with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.debug("Failed to close sync LLM client", exc_info=True)


async def reset_async_clients() -> None:
    """Drop + close all cached async clients."""
    with _clients_lock:
        clients = list(_async_clients.values())
        _async_clients.clear()
    for client in clients:
        try:
            await client.close()
        except Exception:
            logger.debug("Failed to close async LLM client", exc_info=True)


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
        NOTEBOOK_FILE_SPECS["embeddings"],
        NOTEBOOK_FILE_SPECS["card_ids"],
    ])
    return _get_cached(key, lambda: EmbeddingStore(emb_path, ids_path, llm, model=model, dim=dim))

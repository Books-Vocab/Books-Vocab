from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..notebook import validate_notebook_access


@dataclass(frozen=True)
class ResolvedStores:
    cards: Any
    graph: Any
    embeddings: Any | None = None


def _resolve_embedding_store(
    user: dict[str, Any],
    notebook_id: str,
    *,
    embedding_store_factory: Callable[..., Any] | None,
    client_factory: Callable[..., Any] | None,
) -> Any | None:
    """Build an embedding store for mutation paths, or None if disabled."""
    if embedding_store_factory is None or client_factory is None:
        return None

    from ..deps_quota import _is_pro
    from ..llm.providers import provider_for
    from ..tracked_llm import TrackedLLM

    provider = provider_for("embed")
    llm = TrackedLLM(
        client_factory(provider),
        user.get("id", "unknown"),
        provider=provider,
        enforce_quota=True,
        is_pro=_is_pro(user),
    )
    return embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id)


def _resolve_stores(
    user: dict[str, Any],
    notebook_id: str | None,
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    embedding_store_factory: Callable[..., Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> ResolvedStores:
    """Validate notebook access and construct card/graph/embedding stores."""
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id or "default") if graph_store_factory is not None else None
    embeddings = _resolve_embedding_store(
        user,
        notebook_id or "default",
        embedding_store_factory=embedding_store_factory,
        client_factory=client_factory,
    )
    return ResolvedStores(cards=cards, graph=graph, embeddings=embeddings)

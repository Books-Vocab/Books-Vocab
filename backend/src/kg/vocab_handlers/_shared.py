from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..notebook import validate_notebook_access


@dataclass(frozen=True)
class ResolvedStores:
    cards: Any
    graph: Any
    embeddings: Any | None = None


class CardStoreFactory(Protocol):
    def __call__(self, user_dir: Path) -> Any: ...


class NotebookStoreFactory(Protocol):
    def __call__(self, user_dir: Path) -> Any: ...


class GraphStoreFactory(Protocol):
    def __call__(self, user_dir: Path, notebook_id: str = "default") -> Any: ...


class EmbeddingStoreFactory(Protocol):
    def __call__(self, user_dir: Path, llm: Any, notebook_id: str = "default") -> Any: ...


class ClientFactory(Protocol):
    def __call__(self, provider: Any) -> Any: ...


class _CardNotebookGraph:
    """Route graph reads to the notebook owning each card."""

    def __init__(self, cards: Any, user_dir: Path, graph_store_factory: GraphStoreFactory) -> None:
        self._cards = cards
        self._user_dir = user_dir
        self._graph_store_factory = graph_store_factory
        self._graphs: dict[str, Any] = {}

    def get_links_for(self, card_id: str) -> object:
        card = self._cards.get(card_id)
        if card is None:
            return ()

        notebook_id = getattr(card, "notebook_id", "default") or "default"
        graph = self._graphs.get(notebook_id)
        if graph is None:
            graph = self._graph_store_factory(self._user_dir, notebook_id=notebook_id)
            self._graphs[notebook_id] = graph
        return graph.get_links_for(card_id)


def _resolve_embedding_store(
    user: dict[str, Any],
    notebook_id: str,
    *,
    embedding_store_factory: EmbeddingStoreFactory | None,
    client_factory: ClientFactory | None,
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
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory | None = None,
    notebook_store_factory: NotebookStoreFactory | None = None,
    embedding_store_factory: EmbeddingStoreFactory | None = None,
    client_factory: ClientFactory | None = None,
) -> ResolvedStores:
    """Validate notebook access and construct card/graph/embedding stores."""
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    if graph_store_factory is None:
        graph = None
    elif notebook_id is None:
        graph = _CardNotebookGraph(cards, user["dir"], graph_store_factory)
    else:
        graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    embeddings = _resolve_embedding_store(
        user,
        notebook_id or "default",
        embedding_store_factory=embedding_store_factory,
        client_factory=client_factory,
    )
    return ResolvedStores(cards=cards, graph=graph, embeddings=embeddings)

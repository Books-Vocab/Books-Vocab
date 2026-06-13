from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..api_models import (
    ArchiveWordRequest,
    BatchArchiveRequest,
    BatchDeleteRequest,
    CardResponse,
    VocabContentUpdateRequest,
)
from ..vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    list_vocab_cards,
    lookup_vocab_word,
    update_vocab_word_content,
)
from ._shared import _resolve_stores


def list_vocab_response(
    since: str | None,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str | None = None,
) -> list[Any]:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return list_vocab_cards(
        since=since,
        cards_store=stores.cards,
        graph=stores.graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def lookup_word_response(
    word: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> CardResponse:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return lookup_vocab_word(
        word,
        cards_store=stores.cards,
        graph=stores.graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def archive_word_response(
    word: str,
    req: ArchiveWordRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str | None = None,
) -> dict[str, str]:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return archive_vocab_word(
        word,
        archived=req.archived,
        cards_store=stores.cards,
        graph=stores.graph,
        notebook_id=notebook_id,
    )


def update_word_content_response(
    word: str,
    req: VocabContentUpdateRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> CardResponse:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return update_vocab_word_content(
        word,
        meaning=req.meaning,
        note=req.note,
        explanation=req.explanation,
        cards_store=stores.cards,
        graph=stores.graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def delete_word_response(
    word: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    embedding_store_factory: Callable[..., Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, str]:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
        embedding_store_factory=embedding_store_factory,
        client_factory=client_factory,
    )
    return delete_vocab_word(
        word,
        cards_store=stores.cards,
        graph=stores.graph,
        embeddings=stores.embeddings,
        notebook_id=notebook_id,
    )


def batch_delete_response(
    req: BatchDeleteRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    embedding_store_factory: Callable[..., Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, Any]:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
        embedding_store_factory=embedding_store_factory,
        client_factory=client_factory,
    )
    return batch_delete_vocab_words(
        req.words,
        cards_store=stores.cards,
        graph=stores.graph,
        embeddings=stores.embeddings,
        notebook_id=notebook_id,
    )


def batch_archive_response(
    req: BatchArchiveRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, Any]:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return batch_archive_vocab_words(
        req.words,
        archived=req.archived,
        cards_store=stores.cards,
        graph=stores.graph,
        notebook_id=notebook_id,
    )

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import GraphLinkResponse, VocabAddResponse


def build_vocab_router(
    *,
    list_vocab: Callable[..., Any],
    lookup_word: Callable[..., Any],
    delete_word: Callable[..., Any],
    get_graph_links: Callable[..., Any],
    add_vocab: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.get("/api/vocab")(list_vocab)
    router.get("/api/vocab/{word}")(lookup_word)
    router.delete("/api/vocab/{word}")(delete_word)
    router.get("/api/graph/links", response_model=list[GraphLinkResponse])(get_graph_links)
    router.post("/api/vocab", response_model=VocabAddResponse)(add_vocab)
    return router

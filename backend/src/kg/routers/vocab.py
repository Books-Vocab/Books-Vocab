from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import CardResponse, DeleteWordResponse, GraphLinkResponse, ReviewStatePushResponse, VocabAddResponse


def build_vocab_router(
    *,
    list_vocab: Callable[..., Any],
    lookup_word: Callable[..., Any],
    archive_word: Callable[..., Any],
    delete_word: Callable[..., Any],
    get_graph_links: Callable[..., Any],
    add_vocab: Callable[..., Any],
    push_review: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.get("/api/vocab", response_model=list[CardResponse])(list_vocab)
    router.get("/api/vocab/{word}", response_model=CardResponse)(lookup_word)
    router.patch("/api/vocab/{word}/archive")(archive_word)
    router.delete("/api/vocab/{word}", response_model=DeleteWordResponse)(delete_word)
    router.get("/api/graph/links", response_model=list[GraphLinkResponse])(get_graph_links)
    router.post("/api/vocab", response_model=VocabAddResponse)(add_vocab)
    router.patch("/api/vocab/review", response_model=ReviewStatePushResponse)(push_review)
    return router

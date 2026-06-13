"""Vocabulary API request handlers.

Split into responsibility-focused submodules; this package re-exports every
public name so callers (``routers/vocab.py``) need no changes.
"""
from __future__ import annotations

from ._shared import _resolve_stores
from .crud import (
    archive_word_response,
    batch_archive_response,
    batch_delete_response,
    delete_word_response,
    list_vocab_response,
    lookup_word_response,
    update_word_content_response,
)
from .graph import (
    create_manual_link_response,
    delete_graph_link_response,
    get_graph_links_response,
    hide_graph_link_response,
    unhide_graph_link_response,
)
from .intake import add_vocab_response
from .review import (
    pull_review_events_response,
    push_review_events_response,
    push_review_response,
)

__all__ = [
    "_resolve_stores",
    "add_vocab_response",
    "archive_word_response",
    "batch_archive_response",
    "batch_delete_response",
    "create_manual_link_response",
    "delete_graph_link_response",
    "delete_word_response",
    "get_graph_links_response",
    "hide_graph_link_response",
    "list_vocab_response",
    "lookup_word_response",
    "pull_review_events_response",
    "push_review_events_response",
    "push_review_response",
    "unhide_graph_link_response",
    "update_word_content_response",
]

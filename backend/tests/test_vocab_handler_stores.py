from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import kg.vocab_handlers._shared as shared


def test_resolve_stores_returns_named_bundle(monkeypatch):
    seen_notebooks: list[str] = []
    cards = object()
    graph = object()

    monkeypatch.setattr(
        shared,
        "validate_notebook_access",
        lambda _store, notebook_id: seen_notebooks.append(notebook_id),
    )

    resolved = shared._resolve_stores(
        {"dir": Path("/tmp/u_vocab")},
        "nb1",
        card_store_factory=lambda _path: cards,
        graph_store_factory=lambda _path, **_kwargs: graph,
        notebook_store_factory=lambda _path: object(),
    )

    assert resolved.cards is cards
    assert resolved.graph is graph
    assert resolved.embeddings is None
    assert seen_notebooks == ["nb1"]


def test_resolve_stores_optionally_builds_embedding_store(monkeypatch):
    cards = object()
    graph = object()
    embedding_store = object()
    fake_provider = SimpleNamespace(name="gemini", chat_model="m", api_key_env="GEMINI_API_KEY")
    embedding_factory = MagicMock(return_value=embedding_store)

    monkeypatch.setattr(shared, "validate_notebook_access", lambda *_a, **_k: None)
    monkeypatch.setattr("kg.llm.providers.provider_for", lambda _call_type: fake_provider)
    monkeypatch.setattr("kg.deps_quota._is_pro", lambda user: bool(user.get("isPro")))
    monkeypatch.setattr("kg.tracked_llm.TrackedLLM", lambda *args, **kwargs: SimpleNamespace(args=args, kwargs=kwargs))

    resolved = shared._resolve_stores(
        {"id": "u1", "dir": Path("/tmp/u_vocab"), "isPro": False},
        "default",
        card_store_factory=lambda _path: cards,
        graph_store_factory=lambda _path, **_kwargs: graph,
        notebook_store_factory=lambda _path: object(),
        embedding_store_factory=embedding_factory,
        client_factory=lambda provider: f"client:{provider.name}",
    )

    assert resolved.cards is cards
    assert resolved.graph is graph
    assert resolved.embeddings is embedding_store
    embedding_factory.assert_called_once()
    assert embedding_factory.call_args.kwargs["notebook_id"] == "default"

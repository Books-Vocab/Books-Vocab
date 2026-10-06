from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg.vocab_add_link_operation import (
    STEP_IDS,
    IdempotencyConflict,
    create_operation,
    get_operation,
    run_add_link_operation,
)


@pytest.fixture(autouse=True)
def isolated_operation_db(tmp_path, monkeypatch):
    import kg.vocab_add_link_operation as operations

    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    operations.reset()
    yield
    operations.reset()


def payload(word: str = "luminous", translation: str | None = None) -> dict:
    return {
        "from_id": "source-card",
        "target_word": word,
        "translation": translation,
        "context": "a luminous room",
        "source": None,
        "source_lang": "en",
        "target_lang": "zh-Hant",
    }


class Cards:
    def __init__(self, source, target=None):
        self.items = {source.id: source}
        if target is not None:
            self.items[target.id] = target
        self.added = []
        self.updated = []

    def get(self, card_id):
        return self.items.get(card_id)

    def find_by_content(self, content, notebook_id=None):
        return next(
            (
                card
                for card in self.items.values()
                if card.content.casefold() == content.casefold()
                and (notebook_id is None or card.notebook_id == notebook_id)
            ),
            None,
        )

    def add(self, **kwargs):
        card = SimpleNamespace(
            id=f"target-{len(self.added) + 1}",
            content=kwargs["content"],
            meaning=kwargs["meaning"],
            pos=kwargs.get("pos"),
            note=None,
            collocations=[],
            examples=kwargs.get("examples", []),
            notebook_id=kwargs.get("notebook_id", "default"),
            is_archived=False,
            is_deleted=False,
        )
        self.items[card.id] = card
        self.added.append(card)
        return card

    def batch_update(self, updates):
        self.updated.extend(updates)
        return len(updates)


class Graph:
    def __init__(self):
        self.links = []

    def find_link_between(self, from_id, to_id):
        return next(
            (link for link in self.links if {link.from_id, link.to_id} == {from_id, to_id}),
            None,
        )


class AsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def user():
    return {"id": "user-1", "dir": Path("/tmp/user-1"), "record": {}, "config": {}}


def run(operation_id, cards, graph, **kwargs):
    asyncio.run(
        run_add_link_operation(
            operation_id,
            user(),
            card_store_factory=lambda _: cards,
            graph_store_factory=lambda *_args, **_kwargs: graph,
            get_user_lock_fn=lambda _uid: AsyncLock(),
            **kwargs,
        )
    )


def test_idempotency_and_request_conflict():
    first, created = create_operation(
        user_id="user-1", notebook_id="default", idempotency_key="tap-1", payload=payload()
    )
    assert created is True
    assert first["status"] == "queued"
    assert [step["id"] for step in first["steps"]] == list(STEP_IDS)

    replay, replay_created = create_operation(
        user_id="user-1", notebook_id="default", idempotency_key="tap-1", payload=payload()
    )
    assert replay_created is False
    assert replay["operation_id"] == first["operation_id"]

    with pytest.raises(IdempotencyConflict):
        create_operation(
            user_id="user-1",
            notebook_id="default",
            idempotency_key="tap-1",
            payload=payload("different"),
        )


def test_missing_target_translates_enriches_and_links_once():
    source = SimpleNamespace(
        id="source-card",
        content="source",
        meaning="來源",
        notebook_id="default",
        is_deleted=False,
        is_archived=False,
    )
    cards = Cards(source)
    graph = Graph()
    calls = []

    async def translate(**_kwargs):
        calls.append("translate")
        return SimpleNamespace(t="發光的", p="adj.", r="luminous")

    async def enrich(**_kwargs):
        calls.append("enrich")

    def link(**kwargs):
        calls.append("link")
        result = SimpleNamespace(id="link-1", from_id=kwargs["from_id"], to_id=kwargs["to_id"], status="active")
        graph.links.append(result)
        return result

    operation, _ = create_operation(user_id="user-1", notebook_id="default", idempotency_key="tap-2", payload=payload())
    run(operation["operation_id"], cards, graph, translate_fn=translate, enrich_fn=enrich, link_fn=link)

    result = get_operation("user-1", operation["operation_id"])
    assert result["status"] == "succeeded"
    assert calls == ["translate", "enrich", "link"]
    assert result["target_card_id"] == "target-1"
    assert result["link_id"] == "link-1"
    assert cards.added[0].examples == []

    # A retry/re-entry is a no-op after the durable terminal state.
    run(operation["operation_id"], cards, graph, translate_fn=translate, enrich_fn=enrich, link_fn=link)
    assert len(cards.added) == 1
    assert calls == ["translate", "enrich", "link"]


def test_existing_target_skips_translation_and_enrichment():
    source = SimpleNamespace(
        id="source-card",
        content="source",
        meaning="來源",
        notebook_id="default",
        is_deleted=False,
        is_archived=False,
    )
    target = SimpleNamespace(
        id="target-card",
        content="luminous",
        meaning="明亮的",
        notebook_id="default",
        is_deleted=False,
        is_archived=False,
    )
    cards = Cards(source, target)
    graph = Graph()
    calls = []

    async def translate(**_kwargs):
        calls.append("translate")
        return SimpleNamespace(t="明亮的")

    async def enrich(**_kwargs):
        calls.append("enrich")

    def link(**kwargs):
        calls.append("link")
        return SimpleNamespace(id="link-existing", from_id=kwargs["from_id"], to_id=kwargs["to_id"], status="active")

    operation, _ = create_operation(user_id="user-1", notebook_id="default", idempotency_key="tap-3", payload=payload())
    run(operation["operation_id"], cards, graph, translate_fn=translate, enrich_fn=enrich, link_fn=link)

    result = get_operation("user-1", operation["operation_id"])
    assert result["status"] == "succeeded"
    assert calls == ["link"]
    assert result["target_card_id"] == "target-card"


def test_enrichment_failure_is_pollable_warning_but_does_not_block_link():
    source = SimpleNamespace(
        id="source-card",
        content="source",
        meaning="來源",
        notebook_id="default",
        is_deleted=False,
        is_archived=False,
    )
    cards = Cards(source)
    graph = Graph()

    async def translate(**_kwargs):
        return SimpleNamespace(t="發光的", p="adj.", r="luminous")

    async def enrich(**_kwargs):
        raise TimeoutError("upstream")

    def link(**kwargs):
        result = SimpleNamespace(id="link-2", from_id=kwargs["from_id"], to_id=kwargs["to_id"], status="active")
        graph.links.append(result)
        return result

    operation, _ = create_operation(user_id="user-1", notebook_id="default", idempotency_key="tap-4", payload=payload())
    run(operation["operation_id"], cards, graph, translate_fn=translate, enrich_fn=enrich, link_fn=link)

    result = get_operation("user-1", operation["operation_id"])
    assert result["status"] == "succeeded_with_warnings"
    assert "enrichment_failed" in result["warnings"]
    assert result["link_id"] == "link-2"


def test_cancellation_interrupts_running_operation_and_current_step():
    source = SimpleNamespace(
        id="source-card",
        content="source",
        meaning="來源",
        notebook_id="default",
        is_deleted=False,
        is_archived=False,
    )
    cards = Cards(source)
    graph = Graph()
    translate_started = asyncio.Event()
    allow_translate = asyncio.Event()

    async def translate(**_kwargs):
        translate_started.set()
        await allow_translate.wait()
        return SimpleNamespace(t="發光的", p="adj.", r="luminous")

    operation, _ = create_operation(
        user_id="user-1", notebook_id="default", idempotency_key="tap-cancel", payload=payload()
    )

    async def exercise_cancellation():
        task = asyncio.create_task(
            run_add_link_operation(
                operation["operation_id"],
                user(),
                card_store_factory=lambda _: cards,
                graph_store_factory=lambda *_args, **_kwargs: graph,
                get_user_lock_fn=lambda _uid: AsyncLock(),
                translate_fn=translate,
            )
        )
        await translate_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise_cancellation())

    result = get_operation("user-1", operation["operation_id"])
    assert result["status"] == "interrupted"
    assert result["ended_at"] is not None
    assert result["error_code"] == "cancelled"
    translate_step = next(step for step in result["steps"] if step["id"] == "translate")
    assert translate_step["status"] == "interrupted"
    assert translate_step["detail_code"] == "cancelled"
    assert get_operation("user-1", operation["operation_id"])["status"] != "running"

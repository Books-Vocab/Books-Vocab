from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from kg.cards import CardStore
from kg.cards.dictionary_models import DictionaryEntry
from kg.exceptions import ConflictError
from kg.graph import GraphStore, LinkKind
from kg.lexical import (
    LexicalAttribution,
    LexicalEntry,
    LexicalExample,
    LexicalSense,
)


def _service(cards: CardStore, graph: GraphStore):
    from kg.dictionary_cards import DictionaryCardService

    return DictionaryCardService(cards=cards, graph=graph, lexical=None, judge=None)


def _entry(word: str = "invoke") -> LexicalEntry:
    return LexicalEntry(
        provider="free_dictionary",
        dictionary_id="wiktionary-en",
        schema_version="v1",
        entry_key=f"en.{word}",
        word=word,
        language="en",
        senses=[
            LexicalSense(
                key="sense-1",
                part_of_speech="verb",
                definition="To call upon for help.",
                translations=["援引"],
                examples=[
                    LexicalExample(key="example-1", text="They invoked an old rule."),
                    LexicalExample(key="example-2", text="She invoked the agreement."),
                ],
            ),
            LexicalSense(
                key="sense-2",
                part_of_speech="verb",
                definition="To cause something to happen.",
                examples=[LexicalExample(key="example-3", text="The command invoked a task.")],
            ),
        ],
        attribution=LexicalAttribution(
            provider="free_dictionary",
            source_url=f"https://en.wiktionary.org/wiki/{word}",
            license_name="CC BY-SA 4.0",
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution_text="Dictionary data from Wiktionary via FreeDictionaryAPI.com",
        ),
        fetched_at=datetime.now(UTC),
    )


def _save_sidecar(
    cards: CardStore,
    card_id: str,
    entry: LexicalEntry,
    *,
    status: str = "active",
    sense_key: str = "sense-1",
    example_key: str = "example-1",
) -> None:
    with Session(cards.engine) as session:
        session.add(
            DictionaryEntry(
                card_id=card_id,
                provider=entry.provider,
                dictionary_id=entry.dictionary_id,
                provider_entry_key=entry.entry_key,
                provider_schema_version=entry.schema_version,
                selected_sense_key=sense_key,
                selected_example_key=example_key,
                payload_json=entry.model_dump_json(),
                source_url=entry.attribution.source_url,
                license_name=entry.attribution.license_name,
                license_url=entry.attribution.license_url,
                attribution_text=entry.attribution.attribution_text,
                fetched_at=entry.fetched_at,
                materialization_status=status,
            )
        )
        session.commit()


def test_saved_dictionary_detail_selection_and_reader_visibility_are_independent(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    card = cards.add(
        "invoke",
        "援引",
        notebook_id="default",
        card_role="dictionary",
        review_eligible=False,
    )
    _save_sidecar(cards, card.id, _entry())

    detail = service.get_saved_card(card.id)
    assert detail.card.id == card.id
    assert detail.card.card_role == "dictionary"
    assert detail.selected_sense_key == "sense-1"
    assert detail.selected_example_key == "example-1"
    assert detail.entry.attribution.source_url.endswith("/invoke")

    changed = service.update_selection(
        card.id,
        sense_key="sense-1",
        example_key="example-2",
    )
    assert changed.selected_example_key == "example-2"
    assert cards.get(card.id).review_eligible is False

    hidden = service.set_reader_visibility(card.id, reader_hidden=True)
    assert hidden.reader_hidden is True
    assert cards.get(card.id).card_role == "dictionary"

    cards.update(card.id, card_role="learning", review_eligible=True)
    visible = service.set_reader_visibility(card.id, reader_hidden=False)
    assert visible.card_role == "learning"
    assert visible.reader_hidden is False
    with pytest.raises(ConflictError):
        service.update_selection(
            card.id,
            sense_key="sense-2",
            example_key="example-3",
        )


def test_dictionary_projection_cursor_lifecycle_links_and_staged_exclusion(tmp_path, monkeypatch):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    source = cards.add("source", "來源", notebook_id="default")
    first = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    staged = cards.add(
        "pending", "待處理", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    second = cards.add(
        "trigger", "觸發", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    _save_sidecar(cards, first.id, _entry())
    _save_sidecar(cards, staged.id, _entry("pending"), status="staged")
    _save_sidecar(cards, second.id, _entry("trigger"))
    graph.add_link(source.id, first.id, LinkKind.SHARES_USAGE, 1.0, "related")
    graph.add_link(first.id, staged.id, LinkKind.SHARES_USAGE, 1.0, "must stay staged")

    calls = {"all_links": 0, "active_sidecars": 0}
    original_all_links = graph.all_links
    original_active_sidecars = cards.get_active_dictionary_card_ids

    def counted_all_links():
        calls["all_links"] += 1
        return original_all_links()

    def counted_active_sidecars(card_ids):
        calls["active_sidecars"] += 1
        return original_active_sidecars(card_ids)

    monkeypatch.setattr(graph, "all_links", counted_all_links)
    monkeypatch.setattr(cards, "get_active_dictionary_card_ids", counted_active_sidecars)
    full_page = service.list_projection(notebook_id="default", limit=100)
    assert {item.card.id for item in full_page.items} == {first.id, second.id}
    assert calls == {"all_links": 1, "active_sidecars": 1}

    page1 = service.list_projection(
        notebook_id="default", limit=1
    )
    page2 = service.list_projection(
        notebook_id="default",
        limit=10,
        cursor=page1.next_cursor,
    )
    combined = page1.items + page2.items
    assert {item.card.id for item in combined} == {first.id, second.id}
    assert page2.next_cursor is None
    projected_first = next(item for item in combined if item.card.id == first.id)
    assert len(projected_first.links) == 1
    assert projected_first.links[0].fromId == source.id

    cards.update(first.id, is_archived=True, reader_hidden=True)
    archived = service.list_projection(
        notebook_id="default", limit=100, since=datetime(1970, 1, 1, tzinfo=UTC)
    )
    archived_first = next(item for item in archived.items if item.card.id == first.id)
    assert archived_first.card.is_archived is True
    assert archived_first.reader_hidden is True

    cards.update(first.id, card_role="learning", review_eligible=True, promotion_state="idle")
    promoted = service.list_projection(
        notebook_id="default", limit=100, since=datetime(1970, 1, 1, tzinfo=UTC)
    )
    assert next(item for item in promoted.items if item.card.id == first.id).card.card_role == "learning"

    cards.delete(second.id)
    deleted = service.list_projection(
        notebook_id="default", limit=100, since=datetime(1970, 1, 1, tzinfo=UTC)
    )
    assert next(item for item in deleted.items if item.card.id == second.id).card.is_deleted is True


def test_unfiltered_dictionary_projection_resolves_each_notebook_graph(tmp_path):
    from kg.dictionary_cards import DictionaryCardService

    cards = CardStore(tmp_path / "cards.db")
    default_graph = GraphStore(tmp_path / "graph-default.json", tmp_path / "candidates-default.json")
    other_graph = GraphStore(tmp_path / "graph-other.json", tmp_path / "candidates-other.json")
    graphs = {"default": default_graph, "other": other_graph}
    service = DictionaryCardService(
        cards=cards,
        graph=default_graph,
        graph_resolver=lambda notebook_id: graphs[notebook_id],
        lexical=None,
        judge=None,
    )

    expected = {}
    for notebook_id, graph, word in (
        ("default", default_graph, "invoke"),
        ("other", other_graph, "trigger"),
    ):
        source = cards.add(f"source-{notebook_id}", "來源", notebook_id=notebook_id)
        target = cards.add(
            word,
            "援引",
            notebook_id=notebook_id,
            card_role="dictionary",
            review_eligible=False,
        )
        _save_sidecar(cards, target.id, _entry(word))
        graph.add_link(
            source.id,
            target.id,
            LinkKind.SHARES_USAGE,
            1.0,
            f"link-{notebook_id}",
        )
        expected[target.id] = f"link-{notebook_id}"

    projection = service.list_projection(notebook_id=None, limit=100)
    assert {item.card.id for item in projection.items} == set(expected)
    for item in projection.items:
        assert [link.reason for link in item.links] == [expected[item.card.id]]

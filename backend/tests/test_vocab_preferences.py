from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kg.api_models.cards import CardResponse
from kg.api_models.vocab import CardPreferencesUpdateRequest
from kg.cards import CardStore
from kg.exceptions import NotFoundError
from kg.vocab_crud import update_vocab_word_preferences


class _Cards:
    def __init__(self, card):
        self.card = card
        self.updates: list[dict[str, object]] = []

    def find_by_content(self, word, notebook_id=None):
        if word.casefold() == self.card.content.casefold() and notebook_id == self.card.notebook_id:
            return self.card
        return None

    def update(self, card_id, **updates):
        assert card_id == self.card.id
        self.updates.append(updates)
        for key, value in updates.items():
            setattr(self.card, key, value)


class _Graph:
    @staticmethod
    def get_links_for(card_id):
        return []


def _response_builder(card, graph, cards_by_id):
    return CardResponse(
        id=card.id,
        content=card.content,
        meaning=card.meaning,
        pos=None,
        difficulty=None,
        difficultyTier=None,
        note=None,
        examples=[],
        mode=getattr(card, "mode", "recognition"),
        isDeleted=card.is_deleted,
        isArchived=card.is_archived,
        isReaderHidden=card.is_reader_hidden,
        isReviewExcluded=card.is_review_excluded,
    )


def test_preferences_request_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        CardPreferencesUpdateRequest()

    assert CardPreferencesUpdateRequest(reader_hidden=True).reader_hidden is True
    assert CardPreferencesUpdateRequest(review_excluded=False).review_excluded is False


def test_preferences_request_accepts_mode_alone_and_rejects_unknown_modes():
    # #2042: the review direction is a per-card preference; it may be the only
    # field in the request, and only the two card modes the model knows exist.
    assert CardPreferencesUpdateRequest(mode="production").mode == "production"
    assert CardPreferencesUpdateRequest(mode="recognition").mode == "recognition"
    # An explicit null mode is "leave unchanged", so on its own it is still an
    # empty request.
    with pytest.raises(ValidationError):
        CardPreferencesUpdateRequest(mode=None)
    for invalid in ("cloze", "Production", "", 1):
        with pytest.raises(ValidationError):
            CardPreferencesUpdateRequest(mode=invalid)


def test_update_vocab_word_preferences_sets_mode_without_touching_other_preferences():
    card = SimpleNamespace(
        id="card-1",
        content="focus",
        meaning="專注",
        notebook_id="notebook-1",
        mode="recognition",
        is_deleted=False,
        is_archived=False,
        is_reader_hidden=True,
        is_review_excluded=False,
    )
    cards = _Cards(card)

    response = update_vocab_word_preferences(
        "focus",
        reader_hidden=None,
        review_excluded=None,
        mode="production",
        cards_store=cards,
        graph=_Graph(),
        card_response_builder=_response_builder,
        notebook_id="notebook-1",
    )

    assert cards.updates == [{"mode": "production"}]
    assert response.mode == "production"
    assert response.isReaderHidden is True
    assert response.isReviewExcluded is False


def test_mode_preference_persists_and_bumps_sync_cursor_without_touching_srs(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    try:
        card = store.add("focus", "專注")
        assert card.mode == "recognition"
        store.update(card.id, review_count=4, review_streak=3, review_interval_hours=48)
        before = store.get(card.id)
        assert before is not None

        response = update_vocab_word_preferences(
            "focus",
            reader_hidden=None,
            review_excluded=None,
            mode="production",
            cards_store=store,
            graph=_Graph(),
            card_response_builder=_response_builder,
            notebook_id=card.notebook_id,
        )

        refreshed = store.get(card.id)
        assert refreshed is not None
        assert response.mode == "production"
        assert refreshed.mode == "production"
        # Incremental `/api/vocab?since=` sync keys off updated_at.
        assert refreshed.updated_at > before.updated_at
        assert refreshed.review_count == before.review_count == 4
        assert refreshed.review_streak == before.review_streak == 3
        assert refreshed.review_interval_hours == before.review_interval_hours == 48
        assert refreshed.is_reader_hidden is before.is_reader_hidden is False
        assert refreshed.is_review_excluded is before.is_review_excluded is False
    finally:
        store.close()


def test_update_vocab_word_preferences_changes_only_requested_fields():
    card = SimpleNamespace(
        id="card-1",
        content="focus",
        meaning="專注",
        notebook_id="notebook-1",
        is_deleted=False,
        is_archived=False,
        is_reader_hidden=False,
        is_review_excluded=False,
    )
    cards = _Cards(card)

    response = update_vocab_word_preferences(
        "focus",
        reader_hidden=True,
        review_excluded=None,
        cards_store=cards,
        graph=_Graph(),
        card_response_builder=_response_builder,
        notebook_id="notebook-1",
    )

    assert cards.updates == [{"is_reader_hidden": True}]
    assert card.is_reader_hidden is True
    assert card.is_review_excluded is False
    assert response.isReaderHidden is True
    assert response.isReviewExcluded is False

    with pytest.raises(NotFoundError):
        update_vocab_word_preferences(
            "focus",
            reader_hidden=False,
            review_excluded=None,
            cards_store=cards,
            graph=_Graph(),
            card_response_builder=_response_builder,
            notebook_id="other-notebook",
        )


def test_preference_columns_default_and_round_trip(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    try:
        card = store.add("focus", "專注")
        assert card.is_reader_hidden is False
        assert card.is_review_excluded is False

        review_at = card.updated_at
        store.update(
            card.id,
            review_count=4,
            review_streak=3,
            lapse_count=1,
            review_interval_hours=48,
            next_review_at=review_at,
        )
        before_preferences = store.get(card.id)
        assert before_preferences is not None

        store.update(card.id, is_reader_hidden=True, is_review_excluded=True)
        refreshed = store.get(card.id)
        assert refreshed is not None
        assert refreshed.is_reader_hidden is True
        assert refreshed.is_review_excluded is True
        assert refreshed.review_count == before_preferences.review_count == 4
        assert refreshed.review_streak == before_preferences.review_streak == 3
        assert refreshed.lapse_count == before_preferences.lapse_count == 1
        assert refreshed.review_interval_hours == before_preferences.review_interval_hours == 48
        assert refreshed.next_review_at == before_preferences.next_review_at == review_at
    finally:
        store.close()

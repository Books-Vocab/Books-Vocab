"""Structural de-leak contract for the /api/decks DTOs (§2.1 / §7).

Two load-bearing assertions the plan calls out explicitly:
* ``DeckCard`` carries ZERO of the 7 SRS attributes at the type layer;
* no ``/api/decks`` route reuses ``CardResponse`` (which would drag SRS in).
"""
from __future__ import annotations

import inspect

import kg.routers.shared_decks as decks_router
from kg.api_models.decks import DeckCard

_SRS_CAMEL = {
    "reviewIntervalHours", "nextReviewAt", "lastReviewedAt",
    "reviewCount", "lapseCount", "reviewStreak", "lastReviewFeedback",
}


def test_deckcard_has_zero_srs_attributes():
    fields = set(DeckCard.model_fields)
    assert _SRS_CAMEL.isdisjoint(fields), f"SRS leaked into DeckCard: {_SRS_CAMEL & fields}"
    # Defensive: no field even smells like review scheduling.
    assert not any(
        tok in f.lower() for f in fields for tok in ("review", "lapse", "streak")
    ), f"review-shaped field on DeckCard: {fields}"


def test_decks_router_does_not_reuse_card_response():
    assert "CardResponse" not in inspect.getsource(decks_router)

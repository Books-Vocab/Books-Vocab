"""Tests for Pydantic model validation gaps."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models import (
    AuthVerifyRequest,
    ManualLinkRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    ReviewStateEntry,
    VocabEntry,
)

# --- VocabEntry / Notebook name: non-empty contract ---


class TestNonEmptyStringContract:
    def test_empty_translation_rejected(self):
        # Mirrors the word field's min_length=1 — a card must carry a meaning.
        with pytest.raises(ValidationError):
            VocabEntry(word="hello", translation="")

    def test_non_empty_translation_accepted(self):
        e = VocabEntry(word="hello", translation="你好")
        assert e.translation == "你好"

    def test_empty_notebook_create_name_rejected(self):
        with pytest.raises(ValidationError):
            NotebookCreateRequest(name="")

    def test_empty_notebook_update_name_rejected(self):
        with pytest.raises(ValidationError):
            NotebookUpdateRequest(name="")

    def test_notebook_update_name_none_still_allowed(self):
        # None means "don't change" — only provided strings must be non-empty.
        r = NotebookUpdateRequest(name=None)
        assert r.name is None

# --- ManualLinkRequest: empty string IDs ---


class TestManualLinkRequestValidation:
    def test_empty_from_id_rejected(self):
        with pytest.raises(ValidationError):
            ManualLinkRequest(from_id="", to_id="abc")

    def test_empty_to_id_rejected(self):
        with pytest.raises(ValidationError):
            ManualLinkRequest(from_id="abc", to_id="")

    def test_valid_ids_accepted(self):
        m = ManualLinkRequest(from_id="a", to_id="b")
        assert m.from_id == "a"


# --- AuthVerifyRequest: provider literal ---


class TestAuthVerifyRequestValidation:
    def test_unknown_provider_rejected(self):
        with pytest.raises(ValidationError):
            AuthVerifyRequest(provider="facebook", token="tok")

    @pytest.mark.parametrize("provider", ["apple", "google"])
    def test_known_provider_accepted(self, provider):
        r = AuthVerifyRequest(provider=provider, token="tok")
        assert r.provider == provider


# --- NotebookCreateRequest / NotebookUpdateRequest: color ---


class TestNotebookColorValidation:
    @pytest.mark.parametrize("model", [NotebookCreateRequest, NotebookUpdateRequest])
    @pytest.mark.parametrize(
        "color, should_raise",
        [
            ("red", True),
            ("not-a-color", True),
            ("#5B8C5A", False),
            ("#AABBCC", False),
        ],
    )
    def test_hex_color_validation(self, model, color, should_raise):
        if should_raise:
            with pytest.raises(ValidationError):
                model(name="nb", color=color)
        else:
            r = model(name="nb", color=color)
            assert r.color == color

    def test_create_none_color_accepted(self):
        r = NotebookCreateRequest(name="nb", color=None)
        assert r.color is None


# --- ReviewStateEntry: non-negative numerics ---


class TestReviewStateEntryValidation:
    def _valid_entry(self, **overrides):
        defaults = dict(
            word="hello",
            review_interval_hours=12.0,
            next_review_at="2026-01-01T00:00:00Z",
            last_reviewed_at="2026-01-01T00:00:00Z",
            review_count=0,
            lapse_count=0,
            review_streak=0,
            last_review_feedback=0,
        )
        defaults.update(overrides)
        return ReviewStateEntry(**defaults)

    @pytest.mark.parametrize(
        "field, value",
        [
            ("review_interval_hours", -1.0),
            ("review_count", -1),
            ("lapse_count", -1),
            ("review_streak", -1),
        ],
    )
    def test_negative_field_rejected(self, field, value):
        with pytest.raises(ValidationError):
            self._valid_entry(**{field: value})

    def test_valid_entry_accepted(self):
        e = self._valid_entry()
        assert e.review_count == 0


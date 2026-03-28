"""Tests for Pydantic model validation gaps."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models import (
    AuthVerifyRequest,
    DailyReviewStatEntry,
    ManualLinkRequest,
    NotebookCreateRequest,
    NotebookUpdateRequest,
    ReviewStateEntry,
)


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

    def test_apple_accepted(self):
        r = AuthVerifyRequest(provider="apple", token="tok")
        assert r.provider == "apple"

    def test_google_accepted(self):
        r = AuthVerifyRequest(provider="google", token="tok")
        assert r.provider == "google"


# --- NotebookCreateRequest / NotebookUpdateRequest: color ---


class TestNotebookColorValidation:
    def test_create_invalid_color_rejected(self):
        with pytest.raises(ValidationError):
            NotebookCreateRequest(name="nb", color="red")

    def test_create_valid_hex_color(self):
        r = NotebookCreateRequest(name="nb", color="#5B8C5A")
        assert r.color == "#5B8C5A"

    def test_create_none_color_accepted(self):
        r = NotebookCreateRequest(name="nb", color=None)
        assert r.color is None

    def test_update_invalid_color_rejected(self):
        with pytest.raises(ValidationError):
            NotebookUpdateRequest(color="not-a-color")

    def test_update_valid_hex_color(self):
        r = NotebookUpdateRequest(color="#AABBCC")
        assert r.color == "#AABBCC"


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

    def test_negative_interval_rejected(self):
        with pytest.raises(ValidationError):
            self._valid_entry(review_interval_hours=-1.0)

    def test_negative_review_count_rejected(self):
        with pytest.raises(ValidationError):
            self._valid_entry(review_count=-1)

    def test_negative_lapse_count_rejected(self):
        with pytest.raises(ValidationError):
            self._valid_entry(lapse_count=-1)

    def test_negative_review_streak_rejected(self):
        with pytest.raises(ValidationError):
            self._valid_entry(review_streak=-1)

    def test_valid_entry_accepted(self):
        e = self._valid_entry()
        assert e.review_count == 0


# --- DailyReviewStatEntry: day_key pattern + non-negative counts ---


class TestDailyReviewStatEntryValidation:
    def test_invalid_day_key_rejected(self):
        with pytest.raises(ValidationError):
            DailyReviewStatEntry(day_key="March 10", total=5, remembered=4, forgot=1)

    def test_valid_day_key_accepted(self):
        e = DailyReviewStatEntry(day_key="2026-03-10", total=5, remembered=4, forgot=1)
        assert e.day_key == "2026-03-10"

    def test_negative_total_rejected(self):
        with pytest.raises(ValidationError):
            DailyReviewStatEntry(day_key="2026-03-10", total=-1, remembered=0, forgot=0)

    def test_negative_remembered_rejected(self):
        with pytest.raises(ValidationError):
            DailyReviewStatEntry(day_key="2026-03-10", total=5, remembered=-1, forgot=0)

    def test_negative_forgot_rejected(self):
        with pytest.raises(ValidationError):
            DailyReviewStatEntry(day_key="2026-03-10", total=5, remembered=0, forgot=-1)

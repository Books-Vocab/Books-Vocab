"""Tests for NotebookCreateRequest / NotebookUpdateRequest validators.

Color regex coverage lives in test_model_validation.py; this file covers
the cover_pattern whitelist + name max_length contract.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models.notebook import (
    VALID_COVER_PATTERNS,
    NotebookCreateRequest,
    NotebookUpdateRequest,
)

# --- cover_pattern whitelist ---

@pytest.mark.parametrize("pattern", sorted(VALID_COVER_PATTERNS))
def test_create_accepts_valid_patterns(pattern):
    r = NotebookCreateRequest(name="nb", cover_pattern=pattern)
    assert r.cover_pattern == pattern


def test_create_accepts_empty_string_to_clear():
    r = NotebookCreateRequest(name="nb", cover_pattern="")
    assert r.cover_pattern == ""


def test_create_accepts_none():
    r = NotebookCreateRequest(name="nb", cover_pattern=None)
    assert r.cover_pattern is None


def test_create_rejects_invalid_pattern():
    with pytest.raises(ValidationError) as exc:
        NotebookCreateRequest(name="nb", cover_pattern="stripes")
    assert "cover_pattern" in str(exc.value)


def test_update_accepts_valid_pattern():
    r = NotebookUpdateRequest(cover_pattern="dots")
    assert r.cover_pattern == "dots"


def test_update_accepts_empty_string_to_clear():
    r = NotebookUpdateRequest(cover_pattern="")
    assert r.cover_pattern == ""


def test_update_rejects_invalid_pattern():
    with pytest.raises(ValidationError):
        NotebookUpdateRequest(cover_pattern="diamonds")


# --- name max_length=100 ---

def test_create_name_at_max_length_accepted():
    r = NotebookCreateRequest(name="x" * 100)
    assert len(r.name) == 100


def test_create_name_over_max_length_rejected():
    with pytest.raises(ValidationError):
        NotebookCreateRequest(name="x" * 101)


def test_update_name_over_max_length_rejected():
    with pytest.raises(ValidationError):
        NotebookUpdateRequest(name="x" * 101)


# --- cover_pattern max_length=30 guards before whitelist ---

def test_create_cover_pattern_over_max_length_rejected():
    with pytest.raises(ValidationError):
        NotebookCreateRequest(name="nb", cover_pattern="x" * 31)

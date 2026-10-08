"""Capture-normalize contract: backend half of the iOS↔backend pact.

The trailing sentence-punctuation set stripped at vocab capture time MUST stay
in lock-step between:

  * iOS  `ReaderTranslationHandler.normalizeWord`
    (ios/BooksAndVocab/Views/Reader/ReaderTranslationHandler+Persistence.swift)
  * backend `_clean_content` (kg.vocab_shared)

Contract SoT: docs/reference/card_format.md §"Word capture normalization".

The fixtures below are the SAME strings asserted in the iOS test
(`normalizeWord_stripsTrailingSentencePunctuation`). Backend additionally
lowercases the first char of a simple capitalized token (dedup concern) — that
delta is asserted separately so the shared trailing-punctuation contract stays
the focus of this test.
"""

from __future__ import annotations

import pytest

from kg.vocab_shared import _clean_content

# Shared trailing-punctuation set: `.,;:!?` — identical on both runtimes.
TRAILING_PUNCTUATION_FIXTURES = [
    ("code.", "code"),
    ("end?!", "end"),
    ("really,", "really"),
    ("wait;", "wait"),
    ("note:", "note"),
    ("  spaced.  ", "spaced"),
    # Word-internal punctuation preserved (lowercase already, no case delta).
    ("don't", "don't"),
    ("well-known,", "well-known"),
]


def test_clean_content_strips_shared_trailing_punctuation_set():
    for raw, expected in TRAILING_PUNCTUATION_FIXTURES:
        assert _clean_content(raw) == expected, f"{raw!r} → {_clean_content(raw)!r}, expected {expected!r}"


def test_clean_content_additionally_lowercases_first_char():
    # Backend-only delta vs iOS: leading uppercase of a simple capitalized
    # single token (rest already lowercase) is folded.
    # iOS keeps "Code" (display-natural); backend stores "code" (dedup).
    assert _clean_content("Code.") == "code"
    # Acronyms, mixed-case words and multi-word phrases are NOT folded.
    assert _clean_content("NASA.") == "NASA"
    assert _clean_content("New York.") == "New York"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PhD", "PhD"),
        ("YouTube", "YouTube"),
        ("McCarthy", "McCarthy"),
        ("JavaScript", "JavaScript"),
        ("LinkedIn", "LinkedIn"),
        ("PhD.", "PhD"),
    ],
)
def test_clean_content_preserves_mixed_case_tokens(raw, expected):
    # Uppercase after the first char means the casing is meaningful: keep it.
    assert _clean_content(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("However", "however"),
        ("Code.", "code"),
        ("NASA.", "NASA"),
        ("New York.", "New York"),
        ("I", "I"),
    ],
)
def test_clean_content_folds_only_simple_capitalized_tokens(raw, expected):
    assert _clean_content(raw) == expected

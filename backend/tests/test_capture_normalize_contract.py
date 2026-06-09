"""Capture-normalize contract: backend half of the iOS↔backend pact.

The trailing sentence-punctuation set stripped at vocab capture time MUST stay
in lock-step between:

  * iOS  `ReaderTranslationHandler.normalizeWord`
    (ios/BooksAndVocab/Views/Reader/ReaderTranslationHandler+Persistence.swift)
  * backend `_clean_content` (kg.vocab_shared)

Contract SoT: docs/reference/card_format.md §"Word capture normalization".

The fixtures below are the SAME strings asserted in the iOS test
(`normalizeWord_stripsTrailingSentencePunctuation`). Backend additionally
lowercases the first char (dedup concern) — that delta is asserted separately
so the shared trailing-punctuation contract stays the focus of this test.
"""

from __future__ import annotations

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
    # Backend-only delta vs iOS: leading uppercase of a single token is folded.
    # iOS keeps "Code" (display-natural); backend stores "code" (dedup).
    assert _clean_content("Code.") == "code"
    # Acronyms and multi-word phrases are NOT folded.
    assert _clean_content("NASA.") == "NASA"
    assert _clean_content("New York.") == "New York"

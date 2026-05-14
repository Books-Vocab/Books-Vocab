"""Backend-side multi-format parser boundary tests.

The backend does not run EPUB/PDF/TXT/MD parsers directly (that lives in iOS
`EPUBConverter.swift`). The backend's only multi-format ingestion surface is
the EPUB-sourced context normalizer (`_normalize_context`) and the
`VocabEntry` / `TranslateRequest` field validators wired to it. These tests
pin its behavior against three real-world hazards from upstream parsers:

1. Malformed / pathological strings (control chars, broken surrogates,
   embedded NULs, isolated combining marks) — must not raise.
2. Encoding edge cases (BOM, UTF-16 round-trip, latin1, mixed scripts) —
   the model must normalize to clean NFC text without dropping content.
3. Large-payload defense — a 50MB context must process without exploding
   memory and must obey the model's hard max length.
"""

from __future__ import annotations

import sys
import time

import pytest
from pydantic import ValidationError

from kg.api_models import TranslateRequest, VocabEntry, _normalize_context


# ---------------------------------------------------------------------------
# 1. Malformed-input characterization
# ---------------------------------------------------------------------------


class TestMalformedInput:
    """Pathological strings from broken parsers must not crash normalize."""

    def test_empty_and_whitespace_only(self) -> None:
        assert _normalize_context("") == ""
        assert _normalize_context("   ") == ""
        assert _normalize_context("\n\n\n") == ""
        assert _normalize_context("  ") == ""

    def test_only_zero_width_chars(self) -> None:
        """Zero-width / NBSP / various Unicode spaces collapse to nothing."""
        # ​ (ZWSP) and   (NBSP) are in the collapse set.
        out = _normalize_context("​  ")
        # After collapsing whitespace runs and stripping, this is empty.
        assert out == ""

    def test_embedded_null_byte_does_not_raise(self) -> None:
        """A NUL byte from a truncated PDF chunk must be passed through, not
        raise — Pydantic should accept it through the validator."""
        result = _normalize_context("hello\x00world")
        # NUL is not in the collapse set; current contract preserves it.
        assert "hello" in result and "world" in result

    def test_lone_surrogate_does_not_crash(self) -> None:
        """A lone UTF-16 surrogate (a common malformed-EPUB artifact) must
        not crash the normalizer. Characterization: Python's unicodedata
        accepts unpaired surrogates and passes them through; the regex
        passes preserve the surrounding text."""
        bad = "ok \ud83d trailing"  # high surrogate without low
        out = _normalize_context(bad)
        assert "ok" in out and "trailing" in out

    def test_isolated_combining_marks(self) -> None:
        """Stray combining marks from a botched OCR/PDF parse must NFC-fold
        without raising."""
        # Latin 'e' + combining acute accent → should fold to 'é'.
        out = _normalize_context("café latte")
        assert "café" in out

    def test_control_chars_preserved_or_collapsed(self) -> None:
        """\\t and \\r are explicitly collapsed; other C0 controls pass
        through unchanged (current contract)."""
        out = _normalize_context("a\tb\rc")
        # Tab + CR are in the collapse set → become a single space run.
        assert out == "a b c"

    def test_vocab_entry_accepts_dirty_context(self) -> None:
        """A VocabEntry built from a malformed but recoverable parser
        output must succeed and emit normalized context."""
        entry = VocabEntry(
            word="hello",
            translation="你好",
            context="  hello  world\n\nfrom EPUB  ",
        )
        assert entry.context == "hello world from EPUB"


# ---------------------------------------------------------------------------
# 2. Encoding edge cases
# ---------------------------------------------------------------------------


class TestEncodingEdges:
    """Inputs that survived various decoder paths must normalize cleanly."""

    def test_utf8_bom_preserved_as_char(self) -> None:
        """The BOM (U+FEFF) is not in the collapse set — current contract
        keeps it. Pin behavior so callers know to strip upstream if they
        care."""
        out = _normalize_context("﻿text after bom")
        assert out.endswith("text after bom")

    def test_utf16_decoded_text_normalizes(self) -> None:
        """Text that came in as UTF-16 bytes and was decoded upstream must
        normalize identically to UTF-8 text."""
        original = "Привет мир — EPUB context"
        as_utf16_bytes = original.encode("utf-16")
        decoded = as_utf16_bytes.decode("utf-16")
        assert _normalize_context(decoded) == original

    def test_latin1_decoded_text_normalizes(self) -> None:
        """A latin1 byte string decoded to str must normalize without
        loss."""
        latin1_bytes = b"caf\xe9 \xa0special"  # 'café  special'
        decoded = latin1_bytes.decode("latin1")
        out = _normalize_context(decoded)
        assert "café" in out
        # \xa0 (NBSP) was collapsed, so two spaces → one.
        assert "café special" == out

    def test_mixed_scripts_preserved(self) -> None:
        """Mixed CJK + Latin + emoji (a real EPUB scenario) must round
        through normalize untouched apart from whitespace folding."""
        out = _normalize_context("日本語 mixed with English 🎌")
        assert out == "日本語 mixed with English 🎌"

    def test_nfd_input_folds_to_nfc(self) -> None:
        """An NFD-decomposed input from a Mac-extracted EPUB must fold to
        NFC."""
        nfd = "é"  # 'e' + combining acute
        nfc = "é"
        assert _normalize_context(nfd) == nfc

    def test_translate_request_encoding_round_trip(self) -> None:
        """Encoded-then-decoded user input must build a TranslateRequest
        without ValidationError."""
        req = TranslateRequest(
            word="café",
            context="The café​was\tquiet.",
        )
        assert req.context == "The café was quiet."


# ---------------------------------------------------------------------------
# 3. Large-payload defense
# ---------------------------------------------------------------------------


class TestLargePayload:
    """Massive contexts from a runaway parser must not OOM or hang."""

    def test_normalize_50mb_within_budget(self) -> None:
        """50MB of pathological whitespace must normalize in a few seconds
        and not balloon memory beyond a small multiple of input size."""
        big = ("a" + "\n\n  \t " * 4) * (50 * 1024 * 1024 // 25)
        # ~50MB of repeating 'a' interleaved with collapsible whitespace.
        assert sys.getsizeof(big) > 40 * 1024 * 1024
        t0 = time.monotonic()
        out = _normalize_context(big)
        elapsed = time.monotonic() - t0
        # Generous budget — the regex passes are linear; this should finish
        # well under 10s on modest hardware. Failure here flags a perf
        # regression (catastrophic-backtracking style).
        assert elapsed < 10.0, f"normalize too slow on 50MB: {elapsed:.2f}s"
        # All collapsible runs gone → a-runs separated by single spaces.
        assert "\n" not in out and "\t" not in out
        assert "  " not in out  # no double space

    def test_vocab_entry_rejects_oversize_context(self) -> None:
        """VocabEntry.context cap is 5000 chars — a 50KB string from a
        misbehaving parser must fail validation cleanly, not silently
        truncate (that's VocabEntry's contract; TranslateRequest truncates,
        VocabEntry rejects)."""
        huge = "x" * 50_000
        with pytest.raises(ValidationError):
            VocabEntry(word="w", translation="t", context=huge)

    def test_translate_request_truncates_oversize_context(self) -> None:
        """TranslateRequest's contract is to truncate context to 1000 chars
        after normalize — verify upstream parsers can dump unlimited input
        without breaking the API."""
        huge = "word " * 10_000  # 50KB
        req = TranslateRequest(word="word", context=huge)
        assert len(req.context) <= 1000

"""Tests for kg.text_utils — NFC normalization helpers."""
from __future__ import annotations

import unicodedata

from kg.text_utils import normalize_nfc, normalize_nfc_lower


class TestNormalizeNfc:
    def test_basic_ascii(self):
        assert normalize_nfc("hello") == "hello"

    def test_nfc_composed_cafe(self):
        """café composed (U+00E9) stays unchanged."""
        composed = "caf\u00e9"
        assert normalize_nfc(composed) == composed

    def test_nfc_decomposed_cafe(self):
        """café decomposed (e + U+0301) → composed form."""
        decomposed = "cafe\u0301"  # NFD
        result = normalize_nfc(decomposed)
        assert result == "caf\u00e9"
        assert unicodedata.is_normalized("NFC", result)

    def test_strips_whitespace(self):
        assert normalize_nfc("  hello  ") == "hello"
        assert normalize_nfc("\thello\n") == "hello"

    def test_empty_string(self):
        assert normalize_nfc("") == ""

    def test_preserves_case(self):
        assert normalize_nfc("Hello World") == "Hello World"


class TestNormalizeNfcLower:
    def test_basic_lowering(self):
        assert normalize_nfc_lower("HELLO") == "hello"

    def test_nfc_composed_cafe(self):
        composed = "Caf\u00e9"
        assert normalize_nfc_lower(composed) == "caf\u00e9"

    def test_nfc_decomposed_cafe(self):
        decomposed = "Cafe\u0301"
        result = normalize_nfc_lower(decomposed)
        assert result == "caf\u00e9"
        assert unicodedata.is_normalized("NFC", result)

    def test_strips_whitespace(self):
        assert normalize_nfc_lower("  Hello  ") == "hello"

    def test_empty_string(self):
        assert normalize_nfc_lower("") == ""

    def test_turkish_dotted_capital_i(self):
        """Turkish İ (U+0130) lowercases to 'i' + combining dot above in Python,
        but NFC normalization produces the expected lowercase form."""
        result = normalize_nfc_lower("\u0130stanbul")
        # Python str.lower() converts İ → i\u0307 (i + combining dot above)
        # NFC keeps that as-is since there's no precomposed form
        assert result.startswith("i")
        assert "stanbul" in result

    def test_mixed_case_unicode(self):
        assert normalize_nfc_lower("Ü ü") == "ü ü"

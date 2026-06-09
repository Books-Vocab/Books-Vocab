"""Tests for cost pricing resolution — longest-substring match, order-independent.

Root cause guarded here: the unknown-model fallback used to scan
VERTEX_PRICING in dict *insertion order* and take the first key that is a
substring of the model name. That made resolution silently depend on dict
ordering — an unknown 'gemini-2.5-flash-tts-experimental' could resolve to the
shorter 'gemini-2.5-flash' if that key happened to be listed first. The fix
resolves to the longest (most specific) matching key regardless of order.

cost.py is stdlib-only, so no extra --with deps are needed.

Run:
    cd lab/podcast && uv run --with pytest python -m pytest monitor/test_cost.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cost  # noqa: E402


def _row(short_in: float, short_out: float) -> dict:
    return {
        "input_short": short_in, "input_long": short_in,
        "output_short": short_out, "output_long": short_out,
        "long_threshold": 200_000,
    }


# ── Order-independence contract (the actual root-cause guard) ──
# Adversarial table where the SHORT prefix is inserted BEFORE the long key.
# Old insertion-order scan would match the short prefix first → wrong rates.
# Longest-match must ignore order and pick the more specific key.
def test_longest_match_ignores_insertion_order():
    table = {
        "gemini-x-flash": _row(0.30, 2.50),        # short prefix, inserted first
        "gemini-x-flash-tts": _row(9.99, 99.99),   # specific key, inserted later
        "gemini-2.5-pro": _row(1.25, 10.0),        # fallback anchor (required key)
    }
    assert cost._resolve_pricing("gemini-x-flash-tts-experimental", table) is table["gemini-x-flash-tts"]


def test_exact_key_wins_over_substring():
    table = {
        "gemini-x-flash-tts": _row(9.99, 99.99),
        "gemini-x-flash-tts-experimental": _row(1.0, 2.0),  # exact target
        "gemini-2.5-pro": _row(1.25, 10.0),
    }
    assert cost._resolve_pricing("gemini-x-flash-tts-experimental", table) is table["gemini-x-flash-tts-experimental"]


def test_fully_unknown_falls_back_to_pro():
    table = {"gemini-2.5-pro": _row(1.25, 10.0)}
    assert cost._resolve_pricing("totally-unknown-model", table) is table["gemini-2.5-pro"]


# ── Regression against the live VERTEX_PRICING table ──
_TOK = 100_000  # below every 200K long_threshold → short-tier rates


def _short_cost(key: str) -> float:
    r = cost.VERTEX_PRICING[key]
    return (_TOK * r["input_short"] + _TOK * r["output_short"]) / 1_000_000


def test_known_model_exact_rates_unchanged():
    assert cost._vertex_cost("gemini-2.5-flash-tts", _TOK, _TOK) == _short_cost("gemini-2.5-flash-tts")


def test_flash_tts_suffix_variant_resolves_to_flash_tts():
    assert cost._vertex_cost("gemini-2.5-flash-tts-experimental", _TOK, _TOK) == _short_cost("gemini-2.5-flash-tts")


def test_pro_tts_suffix_variant_resolves_to_pro_tts():
    assert cost._vertex_cost("gemini-2.5-pro-tts-preview", _TOK, _TOK) == _short_cost("gemini-2.5-pro-tts")


def test_long_context_tier_applies_after_resolution():
    r = cost.VERTEX_PRICING["gemini-2.5-flash-tts"]
    over = r["long_threshold"] + 1
    expected = (over * r["input_long"]) / 1_000_000
    assert cost._vertex_cost("gemini-2.5-flash-tts-experimental", over, 0) == expected

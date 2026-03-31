"""Word difficulty scoring via Zipf frequency."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from wordfreq import zipf_frequency


@dataclass(frozen=True)
class DifficultyTier:
    tag: str
    css_class: str
    color: str
    label: str


# Standardized absolute thresholds (previously calibrated on 2026-02-24)
# These provide a stable difficulty scale regardless of the user's vocabulary size.
TIERS = [
    (3.44, DifficultyTier("core", "diff-core", "#4caf50", "core")),
    (3.01, DifficultyTier("intermediate", "diff-intermediate", "#cfad25", "intermediate")),
    (2.55, DifficultyTier("advanced", "diff-advanced", "#e88a1a", "advanced")),
    (0.0,  DifficultyTier("rare", "diff-rare", "#e05252", "rare")),
]


@lru_cache(maxsize=4096)
def get_zipf(word: str, lang: str = "en") -> float:
    """Get Zipf frequency for a word. Higher = more common."""
    tokens = word.strip().split()
    if len(tokens) > 1:
        return min(zipf_frequency(t, lang) for t in tokens)
    return zipf_frequency(word, lang)


def get_tier(word: str) -> DifficultyTier:
    """Map a word to its difficulty tier using absolute Zipf thresholds."""
    z = get_zipf(word)
    for threshold, tier in TIERS:
        if z >= threshold:
            return tier
    return TIERS[-1][1]

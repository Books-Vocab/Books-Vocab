"""Canonical Gemini 3.1 Flash TTS audio-tag palette — single source of truth.

The podcast pipeline steers vocal delivery with inline `[...]` audio tags. Gemini
3.1 Flash TTS gives the strongest prosody for tags drawn from its official
`example_audio_tags` set (noun forms like `[sadness]`, `[amusement]`), NOT the
2.5-era adjective forms (`[sad]`, `[amused]`) the pipeline originally shipped.

This module is the ONE place the palette is defined. Two prompt files
(`prompts/scriptwriter.md`, `prompts/script_review.md`) mirror it inside
`<!-- TTS_PALETTE:START -->` / `<!-- TTS_PALETTE:END -->` markers, and
`test_palette_consistency.py` asserts all three agree — so the palette can never
silently drift or fossilize again.

Source: Gemini 3.1 official `example_audio_tags` array
(GoogleCloudPlatform/generative-ai · audio/speech/getting-started/gemini_3_1_flash_tts.ipynb).
"""

from __future__ import annotations

import re

# Curated emotion tags (noun forms — strongest 3.1 prosody). Picked for the
# range a two-host book discussion actually needs.
CANONICAL_EMOTION: frozenset[str] = frozenset(
    {
        "curiosity", "interest", "excitement", "enthusiasm", "amusement",
        "humor", "joy", "happiness", "awe", "admiration", "surprise", "shock",
        "skepticism", "doubt", "confusion", "uncertainty", "determination",
        "confidence", "sympathy", "caring", "melancholy", "nostalgia",
        "sadness", "grief", "relief", "satisfaction", "frustration",
        "disappointment", "tension", "anticipation", "hope", "sarcasm",
        "passion", "yearning",
    }
)

# Energy tags — new in 3.1, drive paragraph-level dynamics.
CANONICAL_ENERGY: frozenset[str] = frozenset({"high energy", "low energy"})

# Pacing + non-verbal vocalizations (official forms).
CANONICAL_PACING_NONVERBAL: frozenset[str] = frozenset(
    {"slow", "fast", "whispers", "laughs", "giggles", "sighs", "gasp"}
)

# Pause tags — Gemini 3.1 Mode 4 ("Pacing and pauses"), all High reliability.
# These insert measured silence and REPLACE SSML <break time="Ns"/> (Gemini 3.1
# does not parse SSML). [short pause]≈250ms, [medium pause]≈500ms, [long pause]≈1s+.
CANONICAL_PAUSE: frozenset[str] = frozenset(
    {"short pause", "medium pause", "long pause"}
)

# The full palette the scriptwriter may use and the reviewer must enforce.
CANONICAL: frozenset[str] = (
    CANONICAL_EMOTION
    | CANONICAL_ENERGY
    | CANONICAL_PACING_NONVERBAL
    | CANONICAL_PAUSE
)

# 2.5-era adjective form → 3.1 noun form. Used by the reviewer's auto-fix and as
# reference when reading old scripts (which are NOT rewritten). Tags with no
# direct noun equivalent (deadpan/thoughtful/somber/warm/tender) move to the
# host's Voice direction (Director's Notes), not an inline tag.
LEGACY_TO_CANONICAL: dict[str, str] = {
    "excited": "excitement",
    "skeptical": "skepticism",
    "amused": "amusement",
    "uncertain": "uncertainty",
    "sad": "sadness",
    "surprised": "surprise",
    "happy": "happiness",
    "sarcastic": "sarcasm",
    "empathetic": "sympathy",
    "whispering": "whispers",
    "sighing": "sighs",
    "laughing": "laughs",
    "chuckling": "giggles",
    "speaking slowly": "slow",
    "speaking quickly": "fast",
}

# 3.1 canonical (noun/energy/pause) form → the 2.5-era form the model actually
# voices, derived by inverting LEGACY_TO_CANONICAL. Used when synthesizing on a
# non-3.1 family so 3.1-authored tags are never read aloud as literal words.
CANONICAL_TO_LEGACY: dict[str, str] = {v: k for k, v in LEGACY_TO_CANONICAL.items()}

# Bracket-tag matcher (single level — content placeholders never nest tags).
_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def sanitize_tags_for_family(text: str, family: str) -> tuple[str, dict[str, int]]:
    """Make 3.1-authored audio tags safe for a non-3.1 synthesis family.

    Gemini does NOT silently drop an unsupported inline tag — it speaks it as
    literal text. Scripts are authored against the 3.1 palette (noun emotions,
    energy/pause tags), so on a 2.5-family synth we must rewrite or remove any
    3.1-only tag *before* the text reaches the API.

    Policy (family != "3.1"):
      • palette tag with a known 2.5-era form  → rewrite ([excitement]→[excited],
        [whispers]→[whispering], [slow]→[speaking slowly], …)
      • palette tag with no 2.5 form (energy, pause, abstract emotion nouns like
        [awe]/[determination], [gasp])          → strip
      • non-palette bracket (e.g. [NEW HABIT])  → leave untouched (it is spoken
        CONTENT — a habit-stacking placeholder, not an audio direction)

    On family == "3.1" the text is returned verbatim (full palette is valid).

    Returns the cleaned text and a {change_key: count} map for logging.
    """
    if family == "3.1":
        return text, {}

    changes: dict[str, int] = {}

    def _bump(key: str) -> None:
        changes[key] = changes.get(key, 0) + 1

    def _repl(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        if key in CANONICAL_TO_LEGACY:           # rewrite to the 2.5-era form
            new = CANONICAL_TO_LEGACY[key]
            _bump(f"{key}->{new}")
            return f"[{new}]"
        if key in CANONICAL:                     # 3.1-only palette tag, no 2.5 form
            _bump(f"{key}(strip)")
            return ""                            # strip so it is never voiced
        return m.group(0)                        # unknown bracket = content, keep

    out = _TAG_RE.sub(_repl, text)
    if changes:
        # Tidy whitespace left by stripped tags: collapse runs of spaces/tabs
        # (never newlines) and drop spaces before punctuation.
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r" +([,.!?;:])", r"\1", out)
        out = re.sub(r"(?m)^[ \t]+", "", out)   # leading space from a line-start strip
        out = re.sub(r"(?m)[ \t]+$", "", out)
    return out, changes

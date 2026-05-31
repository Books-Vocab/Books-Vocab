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

# The full palette the scriptwriter may use and the reviewer must enforce.
CANONICAL: frozenset[str] = (
    CANONICAL_EMOTION | CANONICAL_ENERGY | CANONICAL_PACING_NONVERBAL
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

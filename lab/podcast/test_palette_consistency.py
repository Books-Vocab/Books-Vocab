"""Palette drift guard.

The Gemini 3.1 audio-tag palette is defined once in `tts_tags.CANONICAL` and
mirrored in two prompt files. This test asserts all three agree, so the palette
can never silently fossilize the way the 2.5-era set did (see git c9c196e0 era:
model bumped to 3.1, palette left on 2.5 adjective forms).

Each prompt file must contain exactly one block:

    <!-- TTS_PALETTE:START -->
    ...tags as `[tag name]` ...
    <!-- TTS_PALETTE:END -->

Any palette edit must touch tts_tags.py AND both prompt blocks or this fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tts_tags

PROMPTS = Path(__file__).parent / "prompts"
PROMPT_FILES = [PROMPTS / "scriptwriter.md", PROMPTS / "script_review.md"]

_BLOCK_RE = re.compile(
    r"<!--\s*TTS_PALETTE:START\s*-->(.*?)<!--\s*TTS_PALETTE:END\s*-->",
    re.DOTALL,
)
# Tag names: lowercase words, optional single spaces (e.g. "high energy").
_TAG_RE = re.compile(r"\[([a-z][a-z ]*[a-z])\]")


def _extract_palette(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    blocks = _BLOCK_RE.findall(text)
    assert blocks, f"{path.name}: missing <!-- TTS_PALETTE:START/END --> block"
    assert len(blocks) == 1, f"{path.name}: expected exactly 1 palette block, got {len(blocks)}"
    return set(_TAG_RE.findall(blocks[0]))


@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: p.name)
def test_prompt_palette_matches_canonical(path: Path) -> None:
    extracted = _extract_palette(path)
    canonical = set(tts_tags.CANONICAL)
    missing = canonical - extracted
    extra = extracted - canonical
    assert not missing and not extra, (
        f"{path.name} palette out of sync with tts_tags.CANONICAL\n"
        f"  missing from prompt: {sorted(missing)}\n"
        f"  extra in prompt: {sorted(extra)}"
    )


def test_both_prompts_identical() -> None:
    sets = [_extract_palette(p) for p in PROMPT_FILES]
    assert sets[0] == sets[1], (
        "scriptwriter.md and script_review.md palettes differ:\n"
        f"  only in scriptwriter: {sorted(sets[0] - sets[1])}\n"
        f"  only in script_review: {sorted(sets[1] - sets[0])}"
    )


def test_legacy_map_targets_are_canonical() -> None:
    bad = {v for v in tts_tags.LEGACY_TO_CANONICAL.values() if v not in tts_tags.CANONICAL}
    assert not bad, f"LEGACY_TO_CANONICAL maps to non-canonical tags: {sorted(bad)}"

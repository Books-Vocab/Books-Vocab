"""Palette injection contract.

Pre-refactor the Gemini palette was hand-mirrored in three files and this test
asserted they agreed. That mirror is GONE: the palette now lives only in
`tts_tags.TAG_CONCEPTS` and is injected into the authoring/review prompts at
runtime via `{tts_palette}` (see pipeline.inject_tts_palette + render_palette_md).

So drift is structurally impossible. What this test now guards instead:

  1. the authoring prompts carry the `{tts_palette}` placeholder (injection has a
     target) and NO leftover hand-written palette block,
  2. render_palette_md(family) round-trips to palette(family) (the injected text
     actually lists exactly the registry's tags),
  3. the back-compat LEGACY_TO_CANONICAL still targets canonical tags.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tts_tags

PROMPTS = Path(__file__).parent / "prompts"
# Prompts whose palette block is injected (need the full {tts_palette}).
PALETTE_PROMPTS = [PROMPTS / "scriptwriter.md", PROMPTS / "script_review.md"]
# Every prompt pipeline runs through inject_tts_palette (run_scriptwriter,
# run_script_reviewer, run_claude(inject_tts=True) for tts_prep). A prompt here
# with no {tts_*} target, or a typo'd placeholder, would silently ship a stale
# 3.1-hardcoded prompt — inject does a no-op .replace(), it does not raise.
INJECT_PROMPTS = PALETTE_PROMPTS + [PROMPTS / "tts_prep.md"]
KNOWN_PLACEHOLDERS = {"tts_engine", "tts_family", "tts_palette"}
_PLACEHOLDER_RE = re.compile(r"\{(tts_[a-z_]+)\}")

# Tag names: lowercase words, optional single spaces (e.g. "high energy").
_TAG_RE = re.compile(r"\[([a-z][a-z ]*[a-z])\]")


@pytest.mark.parametrize("path", INJECT_PROMPTS, ids=lambda p: p.name)
def test_inject_prompt_uses_only_known_placeholders(path: Path) -> None:
    found = set(_PLACEHOLDER_RE.findall(path.read_text(encoding="utf-8")))
    assert found, f"{path.name}: inject_tts prompt has no {{tts_*}} placeholder (stale/hardcoded?)"
    unknown = found - KNOWN_PLACEHOLDERS
    assert not unknown, (
        f"{path.name}: unknown placeholder(s) {sorted(unknown)} — inject_tts_palette "
        f"only fills {sorted(KNOWN_PLACEHOLDERS)}; a typo here ships silently (no-op replace)"
    )


@pytest.mark.parametrize("path", PALETTE_PROMPTS, ids=lambda p: p.name)
def test_prompt_has_palette_placeholder(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "{tts_palette}" in text, f"{path.name}: missing {{tts_palette}} injection point"


@pytest.mark.parametrize("path", PALETTE_PROMPTS, ids=lambda p: p.name)
def test_prompt_has_no_handwritten_palette_block(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "TTS_PALETTE:START" not in text, (
        f"{path.name}: stale hand-mirrored palette block — the palette is injected "
        f"from tts_tags now, delete the static block and use {{tts_palette}}"
    )


@pytest.mark.parametrize("family", sorted(tts_tags.KNOWN_FAMILIES))
def test_render_palette_md_round_trips(family: str) -> None:
    md = tts_tags.render_palette_md(family)
    rendered = set(_TAG_RE.findall(md))
    expected = tts_tags.palette(family)
    assert rendered == expected, (
        f"render_palette_md({family!r}) tag set != palette({family!r})\n"
        f"  missing from render: {sorted(expected - rendered)}\n"
        f"  extra in render: {sorted(rendered - expected)}"
    )


def test_render_palette_md_rejects_unknown_family() -> None:
    with pytest.raises((ValueError, KeyError, RuntimeError)):
        tts_tags.render_palette_md("9.9")


def test_legacy_map_targets_are_canonical() -> None:
    bad = {v for v in tts_tags.LEGACY_TO_CANONICAL.values() if v not in tts_tags.CANONICAL}
    assert not bad, f"LEGACY_TO_CANONICAL maps to non-canonical tags: {sorted(bad)}"

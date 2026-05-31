#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai",
#     "python-dotenv",
#     "pydub",
#     "audioop-lts",
#     "pytest",
# ]
# ///
"""Unit tests for synthesize._parse_overview_hosts — Voice direction injection.

Guards the Director's Notes feature: the per-host **Voice direction** line in
overview.md must reach the TTS system prompt as performance framing, must be
backward-compatible (old overview.md files lack the field), and must never emit a
`Speaker1:` / `Speaker2:`-prefixed line (Gemini would vocalize the persona blurb
and pad audio to the model's max output — see _parse_overview_hosts comment).
"""

from __future__ import annotations

import re
from pathlib import Path

import synthesize

_VOICE_MAPPING = (
    "### Voice Mapping\n"
    "- **Maya (Puck)**: Speaker1\n"
    "- **Kai (Charon)**: Speaker2\n"
)


def _write_overview(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "overview.md"
    p.write_text(_VOICE_MAPPING + "\n" + body, encoding="utf-8")
    return p


def test_voice_direction_injected(tmp_path: Path) -> None:
    body = (
        "### Maya\n"
        "- **Personality**: relentlessly curious\n"
        "- **Speaking style**: quick, analogical\n"
        "- **Voice direction**: bright mid-Atlantic, high energy, dry wit\n"
        "### Kai\n"
        "- **Personality**: grounded skeptic\n"
        "- **Speaking style**: measured, concrete\n"
        "- **Voice direction**: low warm register, unhurried, deadpan\n"
    )
    speaker_map, system_prompt = synthesize._parse_overview_hosts(_write_overview(tmp_path, body))

    assert speaker_map == {"Maya": "Speaker1", "Kai": "Speaker2"}
    assert "Performance: bright mid-Atlantic, high energy, dry wit" in system_prompt
    assert "Performance: low warm register, unhurried, deadpan" in system_prompt


def test_backward_compatible_without_voice_direction(tmp_path: Path) -> None:
    body = (
        "### Maya\n"
        "- **Personality**: relentlessly curious\n"
        "- **Speaking style**: quick, analogical\n"
        "### Kai\n"
        "- **Personality**: grounded skeptic\n"
        "- **Speaking style**: measured, concrete\n"
    )
    speaker_map, system_prompt = synthesize._parse_overview_hosts(_write_overview(tmp_path, body))

    assert speaker_map == {"Maya": "Speaker1", "Kai": "Speaker2"}
    # Hosts still present; no dangling "Performance:" when the field is absent.
    assert "Maya (voiced by Speaker1)" in system_prompt
    assert "Performance:" not in system_prompt


def test_no_speaker_prefixed_dialogue_line(tmp_path: Path) -> None:
    body = (
        "### Maya\n"
        "- **Personality**: curious\n"
        "- **Speaking style**: quick\n"
        "- **Voice direction**: bright, high energy\n"
        "### Kai\n"
        "- **Personality**: skeptic\n"
        "- **Speaking style**: measured\n"
        "- **Voice direction**: low, unhurried\n"
    )
    _, system_prompt = synthesize._parse_overview_hosts(_write_overview(tmp_path, body))

    # No line may start with "Speaker1:" / "Speaker2:" — that triggers Gemini's
    # 655s padding bug. "(voiced by Speaker1)" mid-line is fine.
    offenders = [ln for ln in system_prompt.splitlines() if re.match(r"^\s*Speaker[12]\s*:", ln)]
    assert not offenders, f"found Speaker-prefixed lines: {offenders}"

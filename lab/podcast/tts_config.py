# /// script
# requires-python = ">=3.12"
# ///
"""Shared TTS-model config — dependency-free so both the heavy pipeline.py and
the lean monitor/server.py (fastapi-only deps) can import it without dragging in
ebooklib/bs4. Single source of truth for the selectable TTS models + family
extraction used by the start endpoints' allowlist and the synthesize gate."""

from __future__ import annotations

import re

# Selectable TTS models (also the server-side allowlist). synthesize.py does no
# format validation, so this is the only gate. An empty/absent choice falls
# through to synthesize.py's TTS_MODEL env default.
ALLOWED_TTS_MODELS = (
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-tts",
    "gemini-2.5-flash-tts",
)


def tts_family(model_id: str) -> str:
    """Extract the model family (e.g. '3.1', '2.5') from a TTS model id.

    The scriptwriter palette is family-specific, so the family — not the full
    id — determines script compatibility. Falls back to the raw id when no
    dotted version token is present.
    """
    m = re.search(r"(\d+\.\d+)", model_id)
    return m.group(1) if m else model_id

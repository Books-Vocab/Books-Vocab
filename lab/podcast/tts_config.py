# /// script
# requires-python = ">=3.12"
# ///
"""Shared TTS-model config — dependency-free so both the heavy pipeline.py and
the lean monitor/server.py (fastapi-only deps) can import it without dragging in
ebooklib/bs4. Single source of truth for the selectable TTS models + family
extraction used by the start endpoints' allowlist and the synthesize gate."""

from __future__ import annotations

import re
from pathlib import Path

# Generation-family suffixes stamped onto synthesized audio filenames
# (ep_1_pro.mp3 / ep_1_flash.m4a). Load-bearing for podcast_upload.sh and the
# monitor episode regexes — keep this tuple as the single source of the convention.
_AUDIO_FAMILY_SUFFIXES = ("_pro", "_flash")


def audio_stem(audio: Path) -> str:
    """Audio filename stem with the generation-family suffix stripped.

    ``ep_1_pro`` / ``ep_1_flash`` → ``ep_1``. Single source for the ``_pro``/
    ``_flash`` convention so subtitle.py and audio_qa.py never drift.
    """
    stem = audio.stem
    for suffix in _AUDIO_FAMILY_SUFFIXES:
        stem = stem.removesuffix(suffix)
    return stem


def find_sibling_script(audio: Path) -> Path | None:
    """Resolve an audio file back to its sibling script ``.md``, or None.

    Probes ``{stem}_script.md`` then ``{stem}.md`` next to the audio, where
    *stem* has the generation-family suffix stripped (see :func:`audio_stem`).
    """
    stem = audio_stem(audio)
    candidates = (
        audio.parent / f"{stem}_script.md",
        audio.parent / f"{stem}.md",
    )
    return next((c for c in candidates if c.exists()), None)

# Selectable TTS models (also the server-side allowlist). synthesize.py does no
# format validation, so this is the only gate. An empty/absent choice falls
# through to synthesize.py's TTS_MODEL env default.
ALLOWED_TTS_MODELS = (
    "gemini-2.5-flash-tts",          # default (synthesize.py env default + .env)
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-tts",
)

# The default synthesis model — single source for synthesize.py's env fallback
# and pipeline.py's family resolution when a workspace has no .tts_model sidecar.
# First entry of the allowlist by construction (the canonical default sits first).
DEFAULT_TTS_MODEL = ALLOWED_TTS_MODELS[0]


def sanitize_slug(title: str, max_len: int = 30) -> str:
    """Produce a workspace slug that matches backend ``_SERIES_ID_RE``.

    Backend (``backend/src/kg/routers/podcast.py``) and ``ops/podcast_upload.sh``
    both enforce ``^[a-z0-9_]+$`` on ``series_id``. The upload script derives
    ``series_id`` from ``basename(workspace)``, so the slug MUST satisfy that
    regex — otherwise upload succeeds but every API call 404s.

    Algorithm: lowercase → collapse non-alphanumeric runs into single ``_`` →
    strip leading/trailing ``_`` → truncate to ``max_len`` → re-rstrip ``_``
    in case truncation landed mid-segment. Empty result falls back to
    ``"untitled"`` (still regex-valid).
    """
    s = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "untitled"


def tts_family(model_id: str) -> str:
    """Extract the model family (e.g. '3.1', '2.5') from a TTS model id.

    The scriptwriter palette is family-specific, so the family — not the full
    id — determines script compatibility. Falls back to the raw id when no
    dotted version token is present.
    """
    m = re.search(r"(\d+\.\d+)", model_id)
    return m.group(1) if m else model_id


# ─── Script parsing regexes (shared by synthesize, subtitle, audio_qa) ───

# Matches **AnyName:** at start of line — multi-word/hyphenated host names.
DIALOGUE_RE = re.compile(r"\*\*([^:*]+):\*\*\s*(.*)")
# Structural lines to skip: headings, blockquotes, rules, HTML comments.
SKIP_LINE_RE = re.compile(r"^(#{1,6}\s|>\s|---\s*$|<!--.*-->\s*$)")
# Inline markdown emphasis stripped from spoken text.
INLINE_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
INLINE_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
# Audio direction tags [excitement] / [laughs] — stripped before alignment/QA.
DIRECTION_RE = re.compile(r"\[.*?\]")
# Legacy SSML markup in old workspaces (Gemini 3.1 has no SSML).
SSML_RE = re.compile(r"<[^>]+>")

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai",
#     "python-dotenv",
#     "pydub",
#     "audioop-lts",
# ]
# ///
"""TTS Synthesizer — podcast script (.md) → audio via Vertex AI Gemini TTS.

Usage:
    # Single script
    uv run synthesize.py workspaces/flow_950f1a7d/scripts/ep_1_script.md

    # All scripts in a directory
    uv run synthesize.py workspaces/flow_950f1a7d/scripts/

    # Dry run (parse + chunk, no API calls)
    uv run synthesize.py workspaces/flow_950f1a7d/scripts/ --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tts_config import (
    DIALOGUE_RE as _DIALOGUE_RE,
    SKIP_LINE_RE as _SKIP_LINE_RE,
    strip_inline_emphasis as _strip_inline_emphasis,
    tts_family as _tts_family,
    DEFAULT_TTS_MODEL as _DEFAULT_TTS_MODEL,
)
from tts_tags import sanitize_tags_for_family as _sanitize_tags_for_family

# ─── Events.jsonl emission (cost / usage tracking) ───
# Writes one NDJSON line per TTS batch + episode boundary so the dashboard's
# /api/workspace/<n>/cost endpoint can compute Vertex spend. Shape mirrors
# pipeline.py's wrap: {ts, stage_label, event}. Module-level lock makes
# ThreadPoolExecutor writes safe.
_EVENTS_LOCK = threading.Lock()
_EVENTS_WORKSPACE: Path | None = None  # set by main() before parallel start


def _set_events_workspace(workspace: Path) -> None:
    global _EVENTS_WORKSPACE
    _EVENTS_WORKSPACE = workspace


def _emit_event(stage_label: str, event_payload: dict) -> None:
    """Append one wrapped event to <workspace>/events.jsonl. No-op if no ws."""
    if _EVENTS_WORKSPACE is None:
        return
    wrapped = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "stage_label": stage_label,
        "event": event_payload,
    }
    line = json.dumps(wrapped, ensure_ascii=False) + "\n"
    with _EVENTS_LOCK:
        with (_EVENTS_WORKSPACE / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()


from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# Force line-buffered stdout for real-time progress visibility
sys.stdout.reconfigure(line_buffering=True)

# Resolve credential path relative to script dir
_cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if _cred_path and not Path(_cred_path).is_absolute():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ROOT / _cred_path)

from google import genai
from google.genai import types as genai_types
from pydub import AudioSegment

# ─── Config ───

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1").strip()
# Default matches .env: Gemini 2.5 Flash TTS (default since 2026-06-02 — quality
# verified sufficient, ~8x cheaper than 3.1-flash-preview). 3.1-flash-preview and
# 2.5-pro-tts stay selectable via --tts-model / TTS_MODEL env. Bracket [] audio-tag
# handling differs by family — see tts_config.tts_family() and scriptwriter prompt.
TTS_MODEL = os.getenv("TTS_MODEL", _DEFAULT_TTS_MODEL).strip()
# Synthesis family ("3.1" / "2.5"). Scripts are authored for the 3.1 palette, so
# on a non-3.1 family _sanitize_dialogue rewrites/strips 3.1-only tags before they
# reach the API (an unsupported tag is otherwise SPOKEN ALOUD, not dropped).
TTS_FAMILY = _tts_family(TTS_MODEL)
# Per-episode accumulator of tag rewrites/strips, reset in parse_script, reported
# in synthesize_script. {change_key: count}.
_TAG_SANITIZE_LOG: dict[str, int] = {}
TTS_MAX_CONCURRENT = int(os.getenv("TTS_MAX_CONCURRENT", "10"))
TTS_RETRY_ATTEMPTS = int(os.getenv("TTS_RETRY_ATTEMPTS", "4"))
VOICE_SPEAKER1 = ""  # set from overview.md Voice Mapping
VOICE_SPEAKER2 = ""
MAX_WORDS_PER_BATCH = int(os.getenv("TTS_MAX_WORDS_PER_BATCH", "800"))
SILENCE_MS = int(os.getenv("TTS_SILENCE_MS", "50"))
OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "m4a").strip().lower()
MP3_BITRATE = os.getenv("TTS_MP3_BITRATE", "192k").strip()
# AAC at 128k is roughly transparent for spoken voice and ~30% smaller than
# 192k MP3. `+faststart` reorders MP4 boxes so the `moov` atom precedes `mdat`,
# letting AVPlayer start playback during the first Range request instead of
# waiting for the whole file (which is the entire point of moving to S3).
AAC_BITRATE = os.getenv("TTS_AAC_BITRATE", "128k").strip()
# Per-episode wall-clock deadline for one synthesize_batches() call (one shared
# deadline for all in-flight batches, not a per-batch timer). A single stuck
# Gemini call should not block the whole episode. On expiry unfinished batches
# are marked stuck and re-queued on next run; cached siblings on disk survive.
TTS_BATCH_TIMEOUT = int(os.getenv("TTS_BATCH_TIMEOUT", "600"))  # 10 min / episode

# Mastering: EBU R128 loudness normalization. Disable with TTS_MASTER=0.
MASTER_ENABLED = os.getenv("TTS_MASTER", "1").strip() != "0"
MASTER_LUFS = float(os.getenv("TTS_MASTER_LUFS", "-16"))  # Apple Podcasts target
MASTER_TP = float(os.getenv("TTS_MASTER_TP", "-1.5"))  # true peak ceiling
MASTER_LRA = float(os.getenv("TTS_MASTER_LRA", "11"))  # loudness range

# ─── Dynamic Host Config ───


def _read_voice_mapping(
    text: str, overview_path: Path
) -> tuple[dict[str, str], str, str]:
    """Parse Voice Mapping section from overview.md text.

    Returns (speaker_map, voice_speaker1, voice_speaker2).
    Pure text parsing — no file I/O, no global state mutations.
    """
    speaker_map: dict[str, str] = {}
    voice1 = ""
    voice2 = ""
    voice_map_re = re.compile(r"\*\*([^*()]+?)\s*\(([^)]+)\)\*\*:\s*(Speaker[12])")
    for m in voice_map_re.finditer(text):
        name, voice, alias = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        speaker_map[name] = alias
        if alias == "Speaker1":
            voice1 = voice
        else:
            voice2 = voice

    if len(speaker_map) != 2 or not voice1 or not voice2:
        raise RuntimeError(
            f"Voice Mapping in {overview_path} incomplete — "
            f"expected 2 entries of form '**Host (Voice)**: SpeakerN'. "
            f"Got speakers={speaker_map}, voices=({voice1!r}, {voice2!r}). "
            f"Run tts-prep stage to fix."
        )

    # Architect writes the placeholder `(TBD)`; tts-prep is responsible for
    # replacing it with a real Gemini voice. If we see TBD here, tts-prep
    # didn't run — fail loud rather than ship to TTS with a bogus voice name.
    if voice1.upper() == "TBD" or voice2.upper() == "TBD":
        raise RuntimeError(
            f"Voice Mapping still contains TBD placeholder in {overview_path}. "
            f"Run the tts-prep pipeline stage to assign real voices before synthesizing."
        )

    return speaker_map, voice1, voice2


def _build_system_prompt(text: str, speaker_map: dict[str, str]) -> str:
    """Construct TTS system prompt from host profile sections in overview.md text.

    Pure text transformation — no file I/O, no global state.

    IMPORTANT: do NOT use "Speaker1: ..." / "Speaker2: ..." format here —
    Gemini multi-speaker parses those lines as dialogue and will vocalize
    the persona description in that speaker's voice at the start of every
    batch, padding audio out to the model's max output (~655s). Use a plain
    narrative frame instead.
    """
    prompt_parts = [
        "Read aloud as a two-host podcast conversation. Warm, intellectual, and engaging "
        "— like two smart friends discussing a book over coffee. Natural pacing with "
        "pauses between speaker turns.",
        "",
        "Voice direction (do NOT speak these character notes — they are style guidance only):",
    ]

    # Extract each host's profile section — emit as style notes, NOT dialogue.
    for name, alias in speaker_map.items():
        section_re = re.compile(
            rf"###\s+(?:Host [AB]:\s*)?{re.escape(name)}\s*\n(.*?)(?=\n###|\n##|\Z)",
            re.DOTALL,
        )
        section_match = section_re.search(text)
        if section_match:
            lines = section_match.group(1).strip().splitlines()
            personality = ""
            style = ""
            voice_dir = ""
            for line in lines:
                if "**Personality**" in line:
                    personality = line.split(":", 1)[-1].strip()
                elif "**Speaking style**" in line:
                    style = line.split(":", 1)[-1].strip()
                elif "**Voice direction**" in line:
                    voice_dir = line.split(":", 1)[-1].strip()
            if personality or style or voice_dir:
                desc = f"{personality} {style}".strip()
                entry = f"- {name} (voiced by {alias}): {desc}"
                # Voice direction = explicit TTS performance notes (accent, energy,
                # timbre, signature delivery). Gemini 3.1 leans on this framing for
                # expressive, distinct voices. Optional — older overview.md files
                # without the field fall back to personality+style only.
                if voice_dir:
                    entry += f" Performance: {voice_dir}"
                prompt_parts.append(entry)

    prompt_parts.append(
        "\nThey interrupt each other naturally, react with genuine surprise or amusement, "
        "and think together rather than taking turns lecturing."
    )
    prompt_parts.append(
        "The dialogue to perform follows below. Speak ONLY the dialogue; do not read the voice direction."
    )

    return "\n".join(prompt_parts)


def _parse_overview_hosts(overview_path: Path) -> tuple[dict[str, str], str]:
    """Extract speaker map + TTS system prompt from overview.md.

    Requires Voice Mapping section with format:
        **HostName (VoiceName)**: Speaker1
        **HostName (VoiceName)**: Speaker2
    The tts-prep stage agent writes this; no defaults or fallbacks.

    Composes _read_voice_mapping (pure parse) and _build_system_prompt (pure
    transform); this function owns file I/O and global voice state updates.
    """
    global VOICE_SPEAKER1, VOICE_SPEAKER2

    if not overview_path.exists():
        raise RuntimeError(
            f"{overview_path} missing — run pipeline tts-prep stage first"
        )

    text = overview_path.read_text(encoding="utf-8")

    speaker_map, voice1, voice2 = _read_voice_mapping(text, overview_path)
    VOICE_SPEAKER1 = voice1
    VOICE_SPEAKER2 = voice2

    system_prompt = _build_system_prompt(text, speaker_map)

    print(f"  Hosts: {', '.join(f'{n} → {a}' for n, a in speaker_map.items())}")
    return speaker_map, system_prompt


# ─── Parse ───


def _sanitize_dialogue(text: str) -> str:
    """Strip inline markdown emphasis + make audio tags safe for TTS_FAMILY."""
    text = _strip_inline_emphasis(text)
    text, changes = _sanitize_tags_for_family(text, TTS_FAMILY)
    for k, n in changes.items():
        _TAG_SANITIZE_LOG[k] = _TAG_SANITIZE_LOG.get(k, 0) + n
    return text


def parse_script(path: Path, speaker_map: dict[str, str]) -> list[dict[str, str]]:
    """Parse a markdown script → list of {speaker, text} turns.

    Hardened rules:
    - Skip structural lines (title/subtitle/---/##/<!--...-->) instead of
      concat'ing them onto the previous turn (Gemini would otherwise vocalize
      "dash dash dash" or "END OF SCRIPT").
    - Strip inline **bold** / *italic* emphasis from dialogue so asterisks
      never reach the TTS prompt.
    - Host name lookup is case-insensitive and raises on unknown names,
      because silent drop + continuation-to-previous was a silent corruption
      path (the wrong speaker would eat the rest of the line).
    """
    text = path.read_text(encoding="utf-8")
    turns: list[dict[str, str]] = []
    lower_map = {k.lower(): v for k, v in speaker_map.items()}
    _TAG_SANITIZE_LOG.clear()  # per-script tally for synthesize_script to report

    for ln_idx, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue

        m = _DIALOGUE_RE.match(stripped)
        if m:
            name = m.group(1).strip()
            dialogue = _sanitize_dialogue(m.group(2).strip())
            alias = lower_map.get(name.lower())
            if not alias:
                raise RuntimeError(
                    f"{path.name}:{ln_idx}: unknown speaker **{name}:**. "
                    f"Known hosts: {list(speaker_map.keys())}. Fix the script "
                    f"or overview.md Voice Mapping."
                )
            if dialogue:
                turns.append({"speaker": alias, "text": dialogue})
            continue

        # Non-dialogue, non-skip, non-blank line = continuation of previous
        # speaker's text. Safe only because we already skipped structural
        # markdown above.
        if turns:
            turns[-1]["text"] += " " + _sanitize_dialogue(stripped)

    return turns


# ─── Chunk ───


def _word_count(text: str) -> int:
    return len(text.split())


# Vertex gemini-2.5-pro-tts fails to emit STOP token when a batch ends on a
# very short utterance (e.g. "Please.", "Stay honest.") and pads audio with
# silence up to the model's 655s cap. Never end a batch on a turn shorter
# than this threshold — carry the short turn forward to the next batch.
MIN_BATCH_END_WORDS = 5


def chunk_turns(
    turns: list[dict[str, str]], max_words: int
) -> list[list[dict[str, str]]]:
    """Split turns into batches that fit within the word budget.

    Constraint: a batch never ends on a turn shorter than MIN_BATCH_END_WORDS.
    Short closing turns trigger Vertex gemini-2.5-pro-tts to pad to its 655s
    max-output ceiling (known bug, finishReason=OTHER, Google marked
    WONTFIX on GitHub issue #922). We defensively roll short final turns
    into the next batch so every boundary lands on a substantive sentence.
    """
    if max_words <= 0:
        raise ValueError("max_words must be > 0")

    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_words = 0

    for turn in turns:
        turn_words = _word_count(turn["text"])

        if turn_words > max_words:
            raise ValueError(
                f"Single turn exceeds word limit ({turn_words} > {max_words}): "
                f"{turn['text'][:80]}..."
            )

        if current and current_words + turn_words > max_words:
            # About to close out `current`. If its last turn is too short
            # for safe EOS, don't close — keep accumulating (soft budget).
            if _word_count(current[-1]["text"]) < MIN_BATCH_END_WORDS:
                current.append(turn)
                current_words += turn_words
                continue
            batches.append(current)
            current = []
            current_words = 0

        current.append(turn)
        current_words += turn_words

    # Final batch: if it ends on a short turn AND has a prior batch, merge
    # backward so the tail doesn't dangle on "Please." or similar.
    if current:
        if _word_count(current[-1]["text"]) < MIN_BATCH_END_WORDS and batches:
            # Pull the short tail into the previous batch so both sides safe
            tail = current.pop()
            batches[-1].append(tail)
        if current:
            batches.append(current)

    return batches


def format_prompt(system_instructions: str, turns: list[dict[str, str]]) -> str:
    dialogue = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    return f"{system_instructions}\n\n{dialogue}".strip()


# ─── Cache identity ───
#
# Audio is a pure function of (prompt sent to the API, both voices, model) per
# batch, plus render settings per episode. Every cache decision keys on exactly
# those inputs — never on a batch index or on "the output file exists" — so an
# edited turn, a re-cast voice or a model switch can't be voiced with stale
# audio. Bump the schema when batch post-processing (e.g. silence trim)
# changes, which invalidates every cached batch and episode once.
_SYNTH_CACHE_SCHEMA = 1


def _sha256_json(payload: dict) -> str:
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _voices() -> dict[str, str]:
    return {"Speaker1": VOICE_SPEAKER1, "Speaker2": VOICE_SPEAKER2}


def _batch_cache_key(prompt: str) -> str:
    """Content key for one batch: the full prompt (system prompt + dialogue),
    both voices and the TTS model."""
    return _sha256_json(
        {
            "schema": _SYNTH_CACHE_SCHEMA,
            "model": TTS_MODEL,
            "voices": _voices(),
            "prompt": prompt,
        }
    )


def _batch_cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"batch_{key}.wav"


def _episode_fingerprint(batch_keys: list[str]) -> str:
    """Identity of a finished episode file: its ordered batch keys (which also
    capture chunking) plus the settings combine_and_export renders with."""
    return _sha256_json(
        {
            "schema": _SYNTH_CACHE_SCHEMA,
            "batches": batch_keys,
            "render": {
                "silence_ms": SILENCE_MS,
                "output_format": OUTPUT_FORMAT,
                "mp3_bitrate": MP3_BITRATE,
                "aac_bitrate": AAC_BITRATE,
                "master": [MASTER_ENABLED, MASTER_LUFS, MASTER_TP, MASTER_LRA],
            },
        }
    )


# ─── Synthesize ───


def build_client() -> genai.Client:
    if not GCP_PROJECT_ID:
        print("ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)
    return genai.Client(
        vertexai=True,
        project=GCP_PROJECT_ID,
        location=GCP_LOCATION,
    )


def build_speech_config() -> genai_types.SpeechConfig:
    return genai_types.SpeechConfig(
        multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker1",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=VOICE_SPEAKER1
                        )
                    ),
                ),
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker2",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=VOICE_SPEAKER2
                        )
                    ),
                ),
            ]
        ),
    )


def audio_bytes_to_segment(audio_bytes: bytes, mime_type: str) -> AudioSegment:
    if "wav" in mime_type:
        return AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
    return AudioSegment(data=audio_bytes, sample_width=2, frame_rate=24000, channels=1)


# Trim trailing silence defense: Vertex gemini-2.5-pro-tts frequently pads
# batches out to its 655s cap with silence after the last spoken word
# (finishReason=OTHER bug, Google marked WONTFIX). This post-processes the
# raw segment to cut anything quieter than -45 dBFS at the tail, keeping a
# short natural breath.
_TRAIL_SILENCE_THRESH_DBFS = -45
_TRAIL_KEEP_MS = 400


def _trim_trailing_silence(segment: AudioSegment) -> AudioSegment:
    """Cut trailing near-silence, preserving a short natural tail."""
    from pydub.silence import detect_leading_silence

    reversed_ = segment.reverse()
    trail_ms = detect_leading_silence(
        reversed_, silence_threshold=_TRAIL_SILENCE_THRESH_DBFS, chunk_size=50
    )
    if trail_ms <= _TRAIL_KEEP_MS:
        return segment
    cut_to = len(segment) - (trail_ms - _TRAIL_KEEP_MS)
    return segment[:cut_to]


def _generate_with_retry(client, prompt, speech_config, index):
    """Call generate_content with exponential backoff for transient errors.

    Vertex Gemini-TTS preview models have tight RPM. SDK has internal retry but
    not enough under burst; this adds outer-level retry to handle 429/503/504.
    """
    import random

    attempts = max(1, TTS_RETRY_ATTEMPTS)
    last_exc = None
    for attempt in range(attempts):
        try:
            return client.models.generate_content(
                model=TTS_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=speech_config,
                ),
            )
        except Exception as e:
            last_exc = e
            name = type(e).__name__
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            transient = code in {408, 429, 500, 502, 503, 504} or name in {
                "ResourceExhausted",
                "ServiceUnavailable",
                "DeadlineExceeded",
                "InternalServerError",
                "APIError",
                "ClientError",
                "ServerError",
            }
            if not transient or attempt == attempts - 1:
                raise
            # 429 = per-minute quota exhausted; must wait ≥60s for quota reset.
            # Other transients use standard exponential backoff.
            if code == 429:
                backoff = 60 + 15 * attempt + random.random() * 5
            else:
                backoff = (2**attempt) + random.random()
            print(
                f"  batch {index}: {name} code={code} — retry {attempt + 1}/{attempts} after {backoff:.1f}s"
            )
            time.sleep(backoff)
    raise last_exc  # pragma: no cover — loop always returns or raises


def _synthesize_one(
    client: genai.Client,
    speech_config: genai_types.SpeechConfig,
    prompt: str,
    index: int,
    total: int,
    batch_words: int,
    turns_count: int,
    cache_path: Path | None = None,
    episode_label: str = "Synthesize",
) -> tuple[int, AudioSegment]:
    """Synthesize a single batch. Caches to disk on success. Returns (index, segment).

    On success, emits a `tts_usage` event to <workspace>/events.jsonl for
    dashboard cost aggregation. Uses response.usage_metadata when available
    (real Vertex token counts) and falls back to char/4 + audio_seconds*25.
    """
    t0 = time.time()

    response = _generate_with_retry(client, prompt, speech_config, index)

    audio_data = None
    mime_type = "audio/pcm"
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if part.inline_data:
                audio_data = part.inline_data.data
                mime_type = part.inline_data.mime_type or "audio/pcm"
                break
        if audio_data:
            break

    if not audio_data:
        raise RuntimeError(f"Batch {index}: no audio data returned")

    elapsed = time.time() - t0
    segment = audio_bytes_to_segment(audio_data, mime_type)
    raw_duration_s = len(segment) / 1000

    # Trim trailing silence before caching — handles Vertex TTS padding bug.
    segment = _trim_trailing_silence(segment)
    trimmed_duration_s = len(segment) / 1000
    trimmed_ms = int(raw_duration_s * 1000 - trimmed_duration_s * 1000)

    # Persist to disk immediately — survives subsequent stuck batches / crashes.
    # Same-dir temp + os.replace: a truncated wav at cache_path would be
    # reused as this batch's audio on every later run.
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = cache_path.with_name(f"{cache_path.name}.{index}.part")
        try:
            segment.export(str(part_path), format="wav")
            os.replace(part_path, cache_path)
        finally:
            part_path.unlink(missing_ok=True)

    # ─── Emit usage event for cost dashboard ───
    # Prefer Vertex's real token counts; fallback to estimates if absent.
    um = getattr(response, "usage_metadata", None)
    input_tokens = getattr(um, "prompt_token_count", None) if um else None
    output_tokens = getattr(um, "candidates_token_count", None) if um else None
    total_tokens = getattr(um, "total_token_count", None) if um else None
    input_chars = len(prompt)
    if input_tokens is None:
        # 4 chars/token is a rough English/Gemini avg; clearly marked as estimate
        input_tokens = max(1, input_chars // 4)
    if output_tokens is None:
        # Google official: 25 audio tokens per second
        output_tokens = int(round(trimmed_duration_s * 25))
    _emit_event(
        episode_label,
        {
            "type": "tts_usage",
            "model": TTS_MODEL,
            "batch_index": index,
            "batch_total": total,
            "turns": turns_count,
            "words": batch_words,
            "input_chars": input_chars,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "audio_seconds": round(trimmed_duration_s, 2),
            "elapsed_s": round(elapsed, 2),
            "trimmed_ms": trimmed_ms,
            "usage_source": "vertex_api" if um else "estimated",
        },
    )

    trim_note = (
        f" (trimmed {trimmed_ms / 1000:.1f}s silence)" if trimmed_ms > 1000 else ""
    )
    print(
        f"  batch {index}/{total}: {turns_count} turns, {batch_words} words → {trimmed_duration_s:.1f}s audio in {elapsed:.1f}s{trim_note}"
    )
    return index, segment


def synthesize_batches(
    client: genai.Client,
    speech_config: genai_types.SpeechConfig,
    system_instructions: str,
    batches: list[list[dict[str, str]]],
    cache_dir: Path | None = None,
    episode_label: str = "Synthesize",
) -> list[AudioSegment]:
    """Synthesize batches with content-keyed disk caching + wall-clock timeout.

    - Each successful batch writes `<cache_dir>/batch_<key>.wav` immediately,
      where key = `_batch_cache_key` (prompt + both voices + model).
    - On re-run, a batch is loaded from disk only when a file with its exact
      key exists; an edited turn, voice or model misses and hits the API.
    - After every batch succeeded, cache files no current batch references
      (old keys, legacy index-named `batch_NN.wav`, `.part` leftovers) are
      pruned so the dir holds exactly this episode's audio.
    - The whole call shares one `TTS_BATCH_TIMEOUT` wall-clock deadline
      (episode-wide, not per batch) — batches unfinished at the deadline are
      marked stuck and the call raises RuntimeError; batches that already
      finished stay cached, and the next run only retries the missing ones.
    """
    total = len(batches)
    results: dict[int, AudioSegment] = {}
    prompts = [format_prompt(system_instructions, batch) for batch in batches]
    keys = [_batch_cache_key(prompt) for prompt in prompts]

    # Phase 1 — load cached batches
    pending: list[int] = []
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for i, key in enumerate(keys, 1):
            cf = _batch_cache_path(cache_dir, key)
            if cf.is_file() and cf.stat().st_size > 0:
                results[i] = AudioSegment.from_file(str(cf))
                print(
                    f"  batch {i}/{total}: loaded from cache ({len(results[i]) / 1000:.1f}s audio)"
                )
            else:
                pending.append(i)
    else:
        pending = list(range(1, total + 1))

    if not pending:
        print(f"  All {total} batches cached — skipping API calls")
        return _collect_batches(results, total, cache_dir, keys)

    workers = max(1, min(len(pending), TTS_MAX_CONCURRENT))
    print(
        f"  Synthesizing {len(pending)}/{total} batches ({workers} concurrent, {TTS_BATCH_TIMEOUT}s episode deadline)..."
    )

    # Phase 2 — synthesize pending batches, isolate stuck ones via a wall-clock
    # cap. Pool is managed manually (not via `with`) so that on timeout we can
    # shut down WITHOUT waiting — a `with` block's __exit__ joins every worker,
    # which would re-block on the very batch we just declared stuck.
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {}
    for i in pending:
        batch = batches[i - 1]
        batch_words = sum(_word_count(t["text"]) for t in batch)
        cache_path = _batch_cache_path(cache_dir, keys[i - 1]) if cache_dir else None
        fut = pool.submit(
            _synthesize_one,
            client,
            speech_config,
            prompts[i - 1],
            i,
            total,
            batch_words,
            len(batch),
            cache_path,
            episode_label,
        )
        futures[fut] = i

    stuck: list[int] = []
    deadline = time.time() + TTS_BATCH_TIMEOUT
    try:
        # as_completed's own timeout enforces the wall-clock cap: fut.result()
        # alone never times out here because as_completed only yields ALREADY
        # finished futures, so a hung batch would otherwise block forever.
        for fut in as_completed(futures, timeout=max(1, deadline - time.time())):
            i = futures[fut]
            try:
                _, segment = fut.result()
                results[i] = segment
            except Exception as e:
                name = type(e).__name__
                print(f"  batch {i}/{total}: FAILED — {name}: {e!s}"[:200])
                stuck.append(i)
    except FuturesTimeoutError:
        # Wall-clock cap hit: as_completed stopped yielding. Every future still
        # unfinished is stuck — mark it. Their cached siblings survive on disk;
        # the next run only retries the missing batches.
        for fut, i in futures.items():
            if not fut.done():
                print(
                    f"  batch {i}/{total}: FAILED — TimeoutError: exceeded {TTS_BATCH_TIMEOUT}s wall-clock"
                )
                stuck.append(i)
    finally:
        # wait=False when something is stuck: don't freeze the episode on a hung
        # Gemini call (its daemon thread is abandoned). cancel_futures drops any
        # batch that hadn't started yet.
        pool.shutdown(wait=not stuck, cancel_futures=True)

    if stuck:
        raise RuntimeError(
            f"{len(stuck)}/{total} batches failed: {sorted(stuck)}. "
            f"Successful batches are cached — re-run synthesize.py to resume."
        )

    return _collect_batches(results, total, cache_dir, keys)


def _collect_batches(
    results: dict[int, AudioSegment],
    total: int,
    cache_dir: Path | None,
    keys: list[str],
) -> list[AudioSegment]:
    """Ordered segments for a fully-successful run; prunes unreferenced cache."""
    if cache_dir:
        keep = {_batch_cache_path(cache_dir, key).name for key in keys}
        stale = [
            f for f in cache_dir.glob("batch_*") if f.is_file() and f.name not in keep
        ]
        for f in stale:
            f.unlink(missing_ok=True)
        if stale:
            print(f"  pruned {len(stale)} stale batch cache file(s)")
    return [results[i] for i in range(1, total + 1)]


def _parse_loudnorm_json(stderr: str) -> dict | None:
    """Extract the flat loudnorm measurement JSON from ffmpeg stderr.

    The loudnorm block is flat (no nested braces); anchoring on the
    ``input_i`` key means a stray ``{...}`` appearing earlier in stderr
    can't hijack the match. Returns None if no usable block is found.
    """
    m = re.search(r"\{[^{}]*\binput_i\b[^{}]*\}", stderr)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def _master_with_loudnorm(src_wav: Path, dst: Path) -> bool:
    """Two-pass EBU R128 loudness normalization via ffmpeg.

    Targets MASTER_LUFS / MASTER_TP / MASTER_LRA. First pass measures, second
    pass applies linear normalization with measured params (most accurate mode).
    Returns True on success; on any failure caller should fall back.
    """
    if not shutil.which("ffmpeg"):
        print("  [master] ffmpeg not found — skipping loudnorm")
        return False

    af_measure = (
        f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA={MASTER_LRA}:print_format=json"
    )
    try:
        # Pass 1 — measure
        measure = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(src_wav),
                "-af",
                af_measure,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        # ffmpeg writes the loudnorm JSON block to stderr.
        params = _parse_loudnorm_json(measure.stderr)
        if params is None:
            print(
                f"  [master] pass1 produced no usable JSON — stderr tail: {measure.stderr[-200:]!r}"
            )
            return False

        af_apply = (
            f"loudnorm=I={MASTER_LUFS}:TP={MASTER_TP}:LRA={MASTER_LRA}"
            f":measured_I={params['input_i']}"
            f":measured_TP={params['input_tp']}"
            f":measured_LRA={params['input_lra']}"
            f":measured_thresh={params['input_thresh']}"
            f":offset={params['target_offset']}"
            f":linear=true:print_format=summary"
        )

        if OUTPUT_FORMAT == "mp3":
            apply_cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-nostats",
                "-i",
                str(src_wav),
                "-af",
                af_apply,
                "-ar",
                "48000",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                MP3_BITRATE,
                str(dst),
            ]
        elif OUTPUT_FORMAT == "m4a":
            apply_cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-nostats",
                "-i",
                str(src_wav),
                "-af",
                af_apply,
                "-ar",
                "48000",
                "-codec:a",
                "aac",
                "-b:a",
                AAC_BITRATE,
                "-movflags",
                "+faststart",
                str(dst),
            ]
        else:
            apply_cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-nostats",
                "-i",
                str(src_wav),
                "-af",
                af_apply,
                "-ar",
                "48000",
                str(dst),
            ]

        result = subprocess.run(apply_cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(
                f"  [master] pass2 failed (exit {result.returncode}): {result.stderr[-200:]!r}"
            )
            return False
        return True
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError) as e:
        print(f"  [master] error: {e}")
        return False


def combine_and_export(segments: list[AudioSegment], output_path: Path) -> None:
    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=SILENCE_MS)

    for seg in segments:
        combined += seg.set_channels(2) + silence

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_s = len(combined) / 1000

    # Write to a same-dir temp, then os.replace() atomically into place.
    # A truncated/0-byte file at output_path makes main()'s resume (out.exists())
    # treat the episode as complete and ship the broken audio to publish. The
    # atomic rename guarantees output_path either is absent or is the full file.
    # The temp name is per writer (a fixed `<out>.part` let a concurrent run of the
    # same episode move it away mid-export) and ends in the real extension: ffmpeg
    # picks its muxer from it, so `.mp3.part` made loudnorm pass 2 exit 234 and
    # every episode silently ship unmastered. Hidden (`.ep_…`) so the `ep_*` /
    # `*_pro.mp3` audio globs never pick up a leftover.
    part_path = output_path.with_name(
        f".{output_path.stem}.{os.getpid()}.{os.urandom(6).hex()}.part"
        f"{output_path.suffix}"
    )
    try:
        mastered = False
        if MASTER_ENABLED:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp_wav = Path(tf.name)
            try:
                combined.export(str(tmp_wav), format="wav")
                mastered = _master_with_loudnorm(tmp_wav, part_path)
                if mastered:
                    print(
                        f"  [master] loudnorm I={MASTER_LUFS} TP={MASTER_TP} LRA={MASTER_LRA} applied"
                    )
            finally:
                tmp_wav.unlink(missing_ok=True)

        if not mastered:
            if OUTPUT_FORMAT == "mp3":
                combined.export(str(part_path), format="mp3", bitrate=MP3_BITRATE)
            elif OUTPUT_FORMAT == "m4a":
                # pydub passes format="mp4" to ffmpeg for the container; the codec is
                # selected via parameters. +faststart matches the mastering path.
                combined.export(
                    str(part_path),
                    format="mp4",
                    parameters=[
                        "-codec:a",
                        "aac",
                        "-b:a",
                        AAC_BITRATE,
                        "-movflags",
                        "+faststart",
                    ],
                )
            else:
                combined.export(str(part_path), format="wav")

        os.replace(part_path, output_path)
    finally:
        # Best-effort cleanup of the temp on any failure (export raised, master
        # failed, etc.). output_path stays absent so resume re-runs the episode.
        Path(part_path).unlink(missing_ok=True)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  → {output_path.name} ({duration_s:.0f}s, {size_mb:.1f}MB)")


# ─── Orchestrator ───


def _model_tag(model: str) -> str:
    """Short audio-filename tag for a TTS model id.

    `pro`/`flash` collapse all generations (gemini-2.5-pro, gemini-3.1-pro →
    "pro") for backward compat with podcast_upload.sh / monitor regexes. The
    full model id is written to the `.meta.json` sidecar separately.
    Otherwise fall back to the second dash-segment, else the raw model id.
    """
    if "pro" in model:
        return "pro"
    if "flash" in model:
        return "flash"
    return model.split("-")[1] if "-" in model else model


@dataclass(frozen=True)
class EpisodePlan:
    """Everything decided about one episode before any API call."""

    script_path: Path
    output_path: Path
    turns: list[dict[str, str]]
    batches: list[list[dict[str, str]]]
    script_sha256: str
    fingerprint: str
    tag_sanitize: dict[str, int]


def plan_episode(
    script_path: Path, speaker_map: dict[str, str], system_prompt: str
) -> EpisodePlan:
    """Parse + chunk a script and derive its synthesis fingerprint (no I/O
    beyond reading the script)."""
    turns = parse_script(script_path, speaker_map)
    if not turns:
        raise RuntimeError(
            f"No dialogue turns found in {script_path.name}. "
            f"Expected speaker names: {list(speaker_map.keys())}. "
            f"Check that script uses **Name:** format matching overview.md host names."
        )
    batches = chunk_turns(turns, MAX_WORDS_PER_BATCH)
    keys = [_batch_cache_key(format_prompt(system_prompt, batch)) for batch in batches]
    return EpisodePlan(
        script_path=script_path,
        output_path=_output_path_for(script_path),
        turns=turns,
        batches=batches,
        script_sha256=hashlib.sha256(script_path.read_bytes()).hexdigest(),
        fingerprint=_episode_fingerprint(keys),
        tag_sanitize=dict(_TAG_SANITIZE_LOG),
    )


def _stale_reason(plan: EpisodePlan) -> str | None:
    """None when the audio on disk was rendered from exactly this plan's
    inputs (sidecar fingerprint matches); otherwise why it must regenerate.

    Unverifiable audio (no sidecar, unreadable sidecar, pre-fingerprint
    sidecar) regenerates — a SKIP must be proven, never assumed.
    """
    if not plan.output_path.exists():
        return "no audio yet"
    meta_path = plan.output_path.with_suffix(".meta.json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"{meta_path.name} missing — cannot verify audio"
    except (OSError, ValueError):
        return f"{meta_path.name} unreadable — cannot verify audio"
    if not isinstance(meta, dict) or not meta.get("synthesis_fingerprint"):
        return f"{meta_path.name} has no synthesis fingerprint (pre-#2096 audio)"
    if meta["synthesis_fingerprint"] == plan.fingerprint:
        return None
    current = {
        "script_sha256": plan.script_sha256,
        "tts_model": TTS_MODEL,
        "voices": _voices(),
    }
    changed = [k for k, v in current.items() if meta.get(k) != v]
    return "inputs changed: " + ", ".join(
        changed or ["host profiles / batching / render settings"]
    )


def process_file(
    plan: EpisodePlan,
    client: genai.Client,
    speech_config: genai_types.SpeechConfig,
    system_prompt: str,
) -> Path:
    script_path = plan.script_path
    print(f"\n{'─' * 50}")
    print(f"Processing: {script_path.name}")

    total_words = sum(_word_count(t["text"]) for t in plan.turns)
    print(f"  {len(plan.turns)} turns, {total_words} words")
    if plan.tag_sanitize:
        n = sum(plan.tag_sanitize.values())
        detail = ", ".join(f"{k}×{v}" for k, v in sorted(plan.tag_sanitize.items()))
        print(
            f"  tag-sanitize (family {TTS_FAMILY}): {n} cross-family tag(s) made safe — {detail}"
        )
    print(f"  {len(plan.batches)} batches (max {MAX_WORDS_PER_BATCH} words/batch)")

    # Per-episode batch cache: scripts/.cache/ep_N/batch_<key>.wav
    stem = script_path.stem.replace("_script", "")
    cache_dir = script_path.parent / ".cache" / stem
    # Tag this episode's TTS events so the dashboard can attribute cost per-EP.
    # Stem looks like "ep_1" / "ep_12" → label "Synthesize EP1" / "Synthesize EP12".
    ep_match = re.match(r"ep_?(\d+)", stem)
    episode_label = (
        f"Synthesize EP{int(ep_match.group(1))}" if ep_match else f"Synthesize {stem}"
    )
    segments = synthesize_batches(
        client,
        speech_config,
        system_prompt,
        plan.batches,
        cache_dir=cache_dir,
        episode_label=episode_label,
    )

    # Tag output with model name: ep_1_flash.mp3 / ep_1_pro.mp3
    output_path = plan.output_path
    combine_and_export(segments, output_path)

    # The subtitle is forced-aligned to the audio just replaced; subtitle.py
    # skips any existing .srt, so a stale one would ship misaligned forever.
    srt_path = output_path.with_suffix(".srt")
    if srt_path.exists():
        srt_path.unlink()
        print(
            f"  removed stale {srt_path.name} (aligned to the replaced audio) — rerun subtitle"
        )

    # Sidecar metadata: filename keeps the legacy `_pro` / `_flash` short tag
    # for backward compat with podcast_upload.sh / monitor regexes, but the
    # short tag drops the generation (gemini-2.5-pro vs 3.1-pro both collapse
    # to "pro"). Write the full TTS model id beside the audio so the monitor
    # UI can display the real name. Same dir, same stem, `.meta.json` suffix.
    # `synthesis_fingerprint` is what main() compares to decide SKIP; the
    # other fields only explain a mismatch.
    meta_path = output_path.with_suffix(".meta.json")
    meta = {
        "tts_model": TTS_MODEL,
        "voices": _voices(),
        "script_sha256": plan.script_sha256,
        "synthesis_fingerprint": plan.fingerprint,
    }
    try:
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as e:
        print(
            f"  warn: could not write sidecar {meta_path.name}: {e} — next run re-renders"
        )

    return output_path


def _output_path_for(script_path: Path) -> Path:
    """Compute the expected output audio path for a script."""
    model_tag = _model_tag(TTS_MODEL)
    ext = OUTPUT_FORMAT if OUTPUT_FORMAT in ("mp3", "m4a") else "wav"
    return script_path.with_name(
        script_path.stem.replace("_script", "") + f"_{model_tag}.{ext}"
    )


def resolve_scripts(target: Path) -> list[Path]:
    """Find script .md files from target path."""
    if target.is_file():
        return [target]
    if target.is_dir():
        scripts = sorted(target.glob("ep_*_script.md"))
        if not scripts:
            scripts = sorted(target.glob("ep_*.md"))
        if not scripts:
            print(f"No script .md files found in {target}")
            sys.exit(1)
        return scripts
    print(f"ERROR: {target} not found")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Podcast script (.md) → audio via Vertex AI Gemini TTS"
    )
    parser.add_argument("target", help="Path to script .md file or directory")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and chunk only, no API calls"
    )
    args = parser.parse_args()

    target_path = Path(args.target)
    scripts = resolve_scripts(target_path)

    # Detect workspace and load host config from overview.md. Needed before the
    # skip decision: voices + host profiles are synthesis inputs.
    if target_path.is_file():
        workspace_dir = target_path.parent.parent  # scripts/ → workspace/
    else:
        workspace_dir = (
            target_path.parent if target_path.name == "scripts" else target_path
        )

    # Wire workspace for events.jsonl emission (cost dashboard)
    _set_events_workspace(workspace_dir)

    overview_path = workspace_dir / "plan" / "overview.md"
    speaker_map, system_prompt = _parse_overview_hosts(overview_path)

    # Partition into skip/todo. SKIP only when the sidecar fingerprint proves
    # the audio on disk matches the current script, voices, model and render
    # settings; anything else regenerates (unchanged batches come from cache).
    skipped: list[EpisodePlan] = []
    todo: list[tuple[EpisodePlan, str]] = []
    for f in scripts:
        plan = plan_episode(f, speaker_map, system_prompt)
        reason = _stale_reason(plan)
        if reason is None:
            skipped.append(plan)
        else:
            todo.append((plan, reason))

    print(
        f"[Synthesize] {len(scripts)} script(s) found, {len(todo)} to process, {len(skipped)} skipped"
    )
    for plan in skipped:
        size_mb = plan.output_path.stat().st_size / (1024 * 1024)
        print(
            f"  SKIP {plan.script_path.stem}: {plan.output_path.name} up to date ({size_mb:.1f} MB)"
        )
    for plan, reason in todo:
        print(f"  TODO {plan.script_path.stem}: {reason}")

    if not todo:
        print("[Synthesize] Nothing to do")
        return

    if args.dry_run:
        for plan, _ in todo:
            total_words = sum(_word_count(t["text"]) for t in plan.turns)
            batch_sizes = [sum(_word_count(t["text"]) for t in b) for b in plan.batches]
            print(
                f"  {plan.script_path.name}: {len(plan.turns)} turns, {total_words} words, "
                f"{len(plan.batches)} batches {batch_sizes}"
            )
        print("\n[Synthesize] Dry run complete.")
        return

    client = build_client()
    speech_config = build_speech_config()
    print(f"[Synthesize] Model: {TTS_MODEL}, Voices: {VOICE_SPEAKER1}/{VOICE_SPEAKER2}")

    t0 = time.time()
    outputs = []
    for i, (plan, _) in enumerate(todo, 1):
        print(f"\n[Synthesize] ({i}/{len(todo)}) {plan.script_path.stem}")
        out = process_file(plan, client, speech_config, system_prompt)
        outputs.append(out)

    elapsed = time.time() - t0
    total_mb = sum(p.stat().st_size for p in outputs) / (1024 * 1024)
    print(f"\n{'=' * 50}")
    print(
        f"[Synthesize] Done: {len(outputs)} file(s) in {elapsed:.0f}s, {total_mb:.1f} MB total"
    )
    for p in outputs:
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"  {p.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

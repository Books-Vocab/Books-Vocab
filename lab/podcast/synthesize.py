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
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict

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
# Vertex Gemini-TTS GA name (no `-preview`). Override via env if needed.
TTS_MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-tts").strip()
TTS_MAX_CONCURRENT = int(os.getenv("TTS_MAX_CONCURRENT", "3"))
TTS_RETRY_ATTEMPTS = int(os.getenv("TTS_RETRY_ATTEMPTS", "4"))
VOICE_SPEAKER1 = ""  # set from overview.md Voice Mapping
VOICE_SPEAKER2 = ""
MAX_WORDS_PER_BATCH = int(os.getenv("TTS_MAX_WORDS_PER_BATCH", "800"))
SILENCE_MS = int(os.getenv("TTS_SILENCE_MS", "50"))
OUTPUT_FORMAT = os.getenv("TTS_OUTPUT_FORMAT", "mp3").strip().lower()
MP3_BITRATE = os.getenv("TTS_MP3_BITRATE", "192k").strip()
# Per-batch wall-clock timeout. A single stuck Gemini call should not block the
# whole episode. Raised timeout → stuck batch re-queues on next run; cached
# siblings on disk survive.
TTS_BATCH_TIMEOUT = int(os.getenv("TTS_BATCH_TIMEOUT", "600"))  # 10 min / batch

# Mastering: EBU R128 loudness normalization. Disable with TTS_MASTER=0.
MASTER_ENABLED = os.getenv("TTS_MASTER", "1").strip() != "0"
MASTER_LUFS = float(os.getenv("TTS_MASTER_LUFS", "-16"))     # Apple Podcasts target
MASTER_TP = float(os.getenv("TTS_MASTER_TP", "-1.5"))        # true peak ceiling
MASTER_LRA = float(os.getenv("TTS_MASTER_LRA", "11"))        # loudness range

# ─── Dynamic Host Config ───


def _parse_overview_hosts(overview_path: Path) -> tuple[dict[str, str], str]:
    """Extract speaker map + TTS system prompt from overview.md.

    Requires Voice Mapping section with format:
        **HostName (VoiceName)**: Speaker1
        **HostName (VoiceName)**: Speaker2
    The tts-prep stage agent writes this; no defaults or fallbacks.
    """
    global VOICE_SPEAKER1, VOICE_SPEAKER2

    if not overview_path.exists():
        raise RuntimeError(f"{overview_path} missing — run pipeline tts-prep stage first")

    text = overview_path.read_text(encoding="utf-8")

    speaker_map: dict[str, str] = {}
    voice_map_re = re.compile(r"\*\*([^*()]+?)\s*\(([^)]+)\)\*\*:\s*(Speaker[12])")
    for m in voice_map_re.finditer(text):
        name, voice, alias = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        speaker_map[name] = alias
        if alias == "Speaker1":
            VOICE_SPEAKER1 = voice
        else:
            VOICE_SPEAKER2 = voice

    if len(speaker_map) != 2 or not VOICE_SPEAKER1 or not VOICE_SPEAKER2:
        raise RuntimeError(
            f"Voice Mapping in {overview_path} incomplete — "
            f"expected 2 entries of form '**Host (Voice)**: SpeakerN'. "
            f"Got speakers={speaker_map}, voices=({VOICE_SPEAKER1!r}, {VOICE_SPEAKER2!r}). "
            f"Run tts-prep stage to fix."
        )

    # Architect writes the placeholder `(TBD)`; tts-prep is responsible for
    # replacing it with a real Gemini voice. If we see TBD here, tts-prep
    # didn't run — fail loud rather than ship to TTS with a bogus voice name.
    if VOICE_SPEAKER1.upper() == "TBD" or VOICE_SPEAKER2.upper() == "TBD":
        raise RuntimeError(
            f"Voice Mapping still contains TBD placeholder in {overview_path}. "
            f"Run the tts-prep pipeline stage to assign real voices before synthesizing."
        )

    # Build system prompt from host profiles
    prompt_parts = [
        "Read aloud as a two-host podcast conversation. Warm, intellectual, and engaging "
        "— like two smart friends discussing a book over coffee. Natural pacing with "
        "pauses between speaker turns."
    ]

    # Extract each host's profile section
    for name, alias in speaker_map.items():
        # Find the section for this host
        section_re = re.compile(
            rf"###\s+(?:Host [AB]:\s*)?{re.escape(name)}\s*\n(.*?)(?=\n###|\n##|\Z)",
            re.DOTALL,
        )
        section_match = section_re.search(text)
        if section_match:
            lines = section_match.group(1).strip().splitlines()
            # Extract personality and speaking style
            personality = ""
            style = ""
            for line in lines:
                if "**Personality**" in line:
                    personality = line.split(":", 1)[-1].strip()
                elif "**Speaking style**" in line:
                    style = line.split(":", 1)[-1].strip()
            if personality or style:
                desc = f"{personality} {style}".strip()
                prompt_parts.append(f"\n{alias} ({name}): {desc}")

    prompt_parts.append(
        "\nThey interrupt each other naturally, react with genuine surprise or amusement, "
        "and think together rather than taking turns lecturing."
    )

    print(f"  Hosts: {', '.join(f'{n} → {a}' for n, a in speaker_map.items())}")
    return speaker_map, "\n".join(prompt_parts)


# ─── Parse ───

# Matches **AnyName:** at start of line. `[^:*]+` allows multi-word / hyphenated
# host names. Lookup into speaker_map is case-insensitive.
_DIALOGUE_RE = re.compile(r"\*\*([^:*]+):\*\*\s*(.*)")

# Lines that must be SKIPPED (never concat'd onto previous turn):
#   Title `# ...`, subtitle `> ...`, horizontal rule `---`, section `## ...`,
#   HTML comments (sentinel `<!-- END_OF_SCRIPT -->` etc.), stray `###`.
_SKIP_LINE_RE = re.compile(r"^(#{1,6}\s|>\s|---\s*$|<!--.*-->\s*$)")

# Inline markdown emphasis that Gemini may literalize as "asterisk …". We keep
# speaker prefix intact (matched first) then strip remaining *..* / **..**.
_INLINE_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_INLINE_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _sanitize_dialogue(text: str) -> str:
    """Strip inline markdown emphasis from TTS-bound dialogue text."""
    text = _INLINE_BOLD_RE.sub(r"\1", text)
    text = _INLINE_ITALIC_RE.sub(r"\1", text)
    return text


def parse_script(path: Path, speaker_map: dict[str, str]) -> List[Dict[str, str]]:
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
    turns: list[Dict[str, str]] = []
    lower_map = {k.lower(): v for k, v in speaker_map.items()}

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


def chunk_turns(
    turns: List[Dict[str, str]], max_words: int
) -> List[List[Dict[str, str]]]:
    """Split turns into batches that fit within the word budget."""
    if max_words <= 0:
        raise ValueError("max_words must be > 0")

    batches: list[list[Dict[str, str]]] = []
    current: list[Dict[str, str]] = []
    current_words = 0

    for turn in turns:
        turn_words = _word_count(turn["text"])

        if turn_words > max_words:
            raise ValueError(
                f"Single turn exceeds word limit ({turn_words} > {max_words}): "
                f"{turn['text'][:80]}..."
            )

        if current and current_words + turn_words > max_words:
            batches.append(current)
            current = []
            current_words = 0

        current.append(turn)
        current_words += turn_words

    if current:
        batches.append(current)

    return batches


def format_prompt(system_instructions: str, turns: List[Dict[str, str]]) -> str:
    dialogue = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    return f"{system_instructions}\n\n{dialogue}".strip()


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
    return AudioSegment(
        data=audio_bytes, sample_width=2, frame_rate=24000, channels=1
    )


def _generate_with_retry(client, prompt, speech_config, index):
    """Call generate_content with exponential backoff for transient errors.

    Vertex Gemini-TTS preview models have tight RPM. SDK has internal retry but
    not enough under burst; this adds outer-level retry to handle 429/503/504.
    """
    import random
    last_exc = None
    for attempt in range(TTS_RETRY_ATTEMPTS):
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
            # google-genai raises genai.errors.APIError with numeric `.code`
            # (HTTP status). api_core (gRPC path) raises named classes. Cover
            # both so retry fires whether SDK is in Vertex-REST or gRPC mode.
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            transient = (
                code in {408, 429, 500, 502, 503, 504}
                or name in {"ResourceExhausted", "ServiceUnavailable",
                            "DeadlineExceeded", "InternalServerError",
                            "APIError", "ClientError", "ServerError"}
            )
            if not transient or attempt == TTS_RETRY_ATTEMPTS - 1:
                raise
            backoff = (2 ** attempt) + random.random()
            print(f"  batch {index}: {name} code={code} — retry {attempt + 1}/{TTS_RETRY_ATTEMPTS} after {backoff:.1f}s")
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
) -> tuple[int, AudioSegment]:
    """Synthesize a single batch. Caches to disk on success. Returns (index, segment)."""
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
    duration_s = len(segment) / 1000

    # Persist to disk immediately — survives subsequent stuck batches / crashes.
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        segment.export(str(cache_path), format="wav")

    print(f"  batch {index}/{total}: {turns_count} turns, {batch_words} words → {duration_s:.1f}s audio in {elapsed:.1f}s")
    return index, segment


def synthesize_batches(
    client: genai.Client,
    speech_config: genai_types.SpeechConfig,
    system_instructions: str,
    batches: List[List[Dict[str, str]]],
    cache_dir: Path | None = None,
) -> List[AudioSegment]:
    """Synthesize batches with per-batch disk caching + wall-clock timeout.

    - Each successful batch writes `<cache_dir>/batch_N.wav` immediately.
    - On re-run, batches whose cache file exists are loaded from disk (no API call).
    - Each in-flight batch has a `TTS_BATCH_TIMEOUT` wall-clock cap — a stuck
      batch raises TimeoutError, its siblings keep running, and the next run
      only retries the missing one.
    """
    total = len(batches)
    results: dict[int, AudioSegment] = {}

    # Phase 1 — load cached batches
    pending: list[tuple[int, list[Dict[str, str]]]] = []
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for i, batch in enumerate(batches, 1):
            cf = cache_dir / f"batch_{i:02d}.wav"
            if cf.exists() and cf.stat().st_size > 0:
                results[i] = AudioSegment.from_file(str(cf))
                print(f"  batch {i}/{total}: loaded from cache ({len(results[i])/1000:.1f}s audio)")
            else:
                pending.append((i, batch))
    else:
        pending = list(enumerate(batches, 1))

    if not pending:
        print(f"  All {total} batches cached — skipping API calls")
        return [results[i] for i in range(1, total + 1)]

    workers = max(1, min(len(pending), TTS_MAX_CONCURRENT))
    print(f"  Synthesizing {len(pending)}/{total} batches ({workers} concurrent, {TTS_BATCH_TIMEOUT}s per-batch timeout)...")

    # Phase 2 — synthesize pending batches, isolate stuck ones via per-future timeout
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for i, batch in pending:
            prompt = format_prompt(system_instructions, batch)
            batch_words = sum(_word_count(t["text"]) for t in batch)
            cache_path = (cache_dir / f"batch_{i:02d}.wav") if cache_dir else None
            fut = pool.submit(
                _synthesize_one, client, speech_config, prompt,
                i, total, batch_words, len(batch), cache_path,
            )
            futures[fut] = i

        stuck: list[int] = []
        deadline = time.time() + TTS_BATCH_TIMEOUT
        for fut in as_completed(futures):
            i = futures[fut]
            remaining = max(1, deadline - time.time())
            try:
                _, segment = fut.result(timeout=remaining)
                results[i] = segment
            except Exception as e:
                name = type(e).__name__
                print(f"  batch {i}/{total}: FAILED — {name}: {e!s}"[:200])
                stuck.append(i)

    if stuck:
        raise RuntimeError(
            f"{len(stuck)}/{total} batches failed: {sorted(stuck)}. "
            f"Successful batches are cached — re-run synthesize.py to resume."
        )

    return [results[i] for i in range(1, total + 1)]


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
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src_wav),
             "-af", af_measure, "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
        # ffmpeg writes the JSON block to stderr
        m = re.search(r"\{[\s\S]*?\}", measure.stderr)
        if not m:
            print(f"  [master] pass1 produced no JSON — stderr tail: {measure.stderr[-200:]!r}")
            return False
        params = json.loads(m.group(0))

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
            apply_cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src_wav),
                         "-af", af_apply, "-ar", "48000",
                         "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, str(dst)]
        else:
            apply_cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src_wav),
                         "-af", af_apply, "-ar", "48000", str(dst)]

        result = subprocess.run(apply_cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"  [master] pass2 failed (exit {result.returncode}): {result.stderr[-200:]!r}")
            return False
        return True
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError) as e:
        print(f"  [master] error: {e}")
        return False


def combine_and_export(segments: List[AudioSegment], output_path: Path) -> None:
    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=SILENCE_MS)

    for seg in segments:
        combined += seg.set_channels(2) + silence

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_s = len(combined) / 1000

    mastered = False
    if MASTER_ENABLED:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = Path(tf.name)
        try:
            combined.export(str(tmp_wav), format="wav")
            mastered = _master_with_loudnorm(tmp_wav, output_path)
            if mastered:
                print(f"  [master] loudnorm I={MASTER_LUFS} TP={MASTER_TP} LRA={MASTER_LRA} applied")
        finally:
            tmp_wav.unlink(missing_ok=True)

    if not mastered:
        if OUTPUT_FORMAT == "mp3":
            combined.export(str(output_path), format="mp3", bitrate=MP3_BITRATE)
        else:
            combined.export(str(output_path), format="wav")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  → {output_path.name} ({duration_s:.0f}s, {size_mb:.1f}MB)")


# ─── Orchestrator ───


def process_file(
    script_path: Path,
    client: genai.Client,
    speech_config: genai_types.SpeechConfig,
    speaker_map: dict[str, str],
    system_prompt: str,
) -> Path:
    print(f"\n{'─'*50}")
    print(f"Processing: {script_path.name}")

    turns = parse_script(script_path, speaker_map)
    total_words = sum(_word_count(t["text"]) for t in turns)
    print(f"  {len(turns)} turns, {total_words} words")

    if not turns:
        raise RuntimeError(
            f"No dialogue turns found in {script_path.name}. "
            f"Expected speaker names: {list(speaker_map.keys())}. "
            f"Check that script uses **Name:** format matching overview.md host names."
        )

    batches = chunk_turns(turns, MAX_WORDS_PER_BATCH)
    print(f"  {len(batches)} batches (max {MAX_WORDS_PER_BATCH} words/batch)")

    # Per-episode batch cache: scripts/.cache/ep_N/batch_MM.wav
    stem = script_path.stem.replace("_script", "")
    cache_dir = script_path.parent / ".cache" / stem
    segments = synthesize_batches(client, speech_config, system_prompt, batches, cache_dir=cache_dir)

    ext = "mp3" if OUTPUT_FORMAT == "mp3" else "wav"
    # Tag output with model name: ep_1_flash.mp3 / ep_1_pro.mp3
    model_tag = TTS_MODEL.split("-")[1] if "-" in TTS_MODEL else TTS_MODEL  # "2.5" → too long
    if "pro" in TTS_MODEL:
        model_tag = "pro"
    elif "flash" in TTS_MODEL:
        model_tag = "flash"
    output_path = script_path.with_name(
        script_path.stem.replace("_script", "") + f"_{model_tag}.{ext}"
    )
    combine_and_export(segments, output_path)

    return output_path


def _output_path_for(script_path: Path) -> Path:
    """Compute the expected output audio path for a script."""
    if "pro" in TTS_MODEL:
        model_tag = "pro"
    elif "flash" in TTS_MODEL:
        model_tag = "flash"
    else:
        model_tag = TTS_MODEL.split("-")[1] if "-" in TTS_MODEL else TTS_MODEL
    ext = "mp3" if OUTPUT_FORMAT == "mp3" else "wav"
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
    parser.add_argument("--dry-run", action="store_true", help="Parse and chunk only, no API calls")
    args = parser.parse_args()

    scripts = resolve_scripts(Path(args.target))

    # Partition into skip/todo
    skipped: list[Path] = []
    todo: list[Path] = []
    for f in scripts:
        out = _output_path_for(f)
        if out.exists():
            skipped.append(f)
        else:
            todo.append(f)

    print(f"[Synthesize] {len(scripts)} script(s) found, {len(todo)} to process, {len(skipped)} skipped")
    for f in skipped:
        out = _output_path_for(f)
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"  SKIP {f.stem}: {out.name} exists ({size_mb:.1f} MB)")

    if not todo:
        print("[Synthesize] Nothing to do")
        return

    # Detect workspace and load host config from overview.md
    target_path = Path(args.target)
    if target_path.is_file():
        workspace_dir = target_path.parent.parent  # scripts/ → workspace/
    else:
        workspace_dir = target_path.parent if target_path.name == "scripts" else target_path

    overview_path = workspace_dir / "plan" / "overview.md"
    speaker_map, system_prompt = _parse_overview_hosts(overview_path)

    if args.dry_run:
        for f in todo:
            turns = parse_script(f, speaker_map)
            batches = chunk_turns(turns, MAX_WORDS_PER_BATCH)
            total_words = sum(_word_count(t["text"]) for t in turns)
            batch_sizes = [sum(_word_count(t["text"]) for t in b) for b in batches]
            print(f"  {f.name}: {len(turns)} turns, {total_words} words, {len(batches)} batches {batch_sizes}")
        print("\n[Synthesize] Dry run complete.")
        return

    client = build_client()
    speech_config = build_speech_config()
    print(f"[Synthesize] Model: {TTS_MODEL}, Voices: {VOICE_SPEAKER1}/{VOICE_SPEAKER2}")

    t0 = time.time()
    outputs = []
    for i, f in enumerate(todo, 1):
        print(f"\n[Synthesize] ({i}/{len(todo)}) {f.stem}")
        out = process_file(f, client, speech_config, speaker_map, system_prompt)
        outputs.append(out)

    elapsed = time.time() - t0
    total_mb = sum(p.stat().st_size for p in outputs) / (1024 * 1024)
    print(f"\n{'='*50}")
    print(f"[Synthesize] Done: {len(outputs)} file(s) in {elapsed:.0f}s, {total_mb:.1f} MB total")
    for p in outputs:
        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"  {p.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

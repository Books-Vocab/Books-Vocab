#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "stable-ts",
#     "pydub",
#     "audioop-lts",
# ]
# ///
"""Forced alignment — script + audio → word-level SRT subtitles.

Usage:
    # Auto-detect matching audio for script
    uv run subtitle.py workspaces/flow_950f1a7d/scripts/ep_1_script.md

    # Explicit audio path
    uv run subtitle.py workspaces/flow_950f1a7d/scripts/ep_1_script.md --audio ep_1_pro.mp3

    # All scripts in a directory
    uv run subtitle.py workspaces/flow_950f1a7d/scripts/

    # Use a specific Whisper model (default: base)
    uv run subtitle.py ... --model medium
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

# Force line-buffered stdout for real-time progress visibility
sys.stdout.reconfigure(line_buffering=True)

logger = logging.getLogger("podcast.subtitle")

# Audio container suffixes a CLI target may point at. Must stay in sync with the
# patterns find_audio() probes (m4a is the post-Track-B default; mp3 legacy; wav
# unmastered). Anything else is treated as a script target.
AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav"}

from tts_config import (
    DIALOGUE_RE as _DIALOGUE_RE,
    SKIP_LINE_RE as _SKIP_LINE_RE,
    INLINE_BOLD_RE as _INLINE_BOLD_RE,
    INLINE_ITALIC_RE as _INLINE_ITALIC_RE,
    DIRECTION_RE as _DIRECTION_RE,
    SSML_RE as _SSML_RE,
)

# ─── Parse script → plain text ───


def _clean_spoken(text: str) -> str:
    """Strip inline emphasis + direction tags + SSML from dialogue — what the
    listener actually hears, for forced-alignment ground truth."""
    text = _INLINE_BOLD_RE.sub(r"\1", text)
    text = _INLINE_ITALIC_RE.sub(r"\1", text)
    text = _DIRECTION_RE.sub("", text)
    text = _SSML_RE.sub("", text)
    return " ".join(text.split())


def script_to_segments(path: Path) -> list[tuple[str, str]]:
    """Extract (speaker, dialogue) segments from markdown script.

    Mirrors synthesize.py parse_script hardening so forced-alignment sees the
    same word sequence that TTS synthesized.
    """
    text = path.read_text(encoding="utf-8")
    segments: list[tuple[str, str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue

        m = _DIALOGUE_RE.match(stripped)
        if m:
            speaker = m.group(1).strip()
            dialogue = _clean_spoken(m.group(2).strip())
            if dialogue:
                segments.append((speaker, dialogue))
            continue

        # Continuation of previous speaker's text (rare; only after the skips).
        if segments:
            extra = _clean_spoken(stripped)
            if extra:
                speaker, prev = segments[-1]
                segments[-1] = (speaker, f"{prev} {extra}")

    return segments


def build_word_speaker_map(segments: list[tuple[str, str]]) -> list[str]:
    """Build a list mapping each word index (in concatenated text) to its speaker."""
    word_speakers: list[str] = []
    for speaker, text in segments:
        words = text.split()
        word_speakers.extend([speaker] * len(words))
    return word_speakers


def find_audio(script_path: Path) -> Path | None:
    """Find matching audio file for a script."""
    stem = script_path.stem.replace("_script", "")
    parent = script_path.parent
    # Try m4a first (post-Track-B default), then mp3 (legacy), then wav (unmastered).
    for pattern in [
        f"{stem}_pro.m4a", f"{stem}_flash.m4a", f"{stem}.m4a",
        f"{stem}_pro.mp3", f"{stem}_flash.mp3", f"{stem}.mp3",
        f"{stem}.wav",
    ]:
        candidate = parent / pattern
        if candidate.exists():
            return candidate
    return None


def is_audio_target(path: Path) -> bool:
    """True if a CLI target points at an audio file rather than a script."""
    return path.suffix.lower() in AUDIO_SUFFIXES


def resolve_script_for_audio(audio: Path) -> Path | None:
    """Resolve an audio target back to its sibling script .md, or None."""
    stem = audio.stem.removesuffix("_pro").removesuffix("_flash")
    candidates = [
        audio.parent / f"{stem}_script.md",
        audio.parent / f"{stem}.md",
    ]
    return next((c for c in candidates if c.exists()), None)


def _format_ts(seconds: float) -> str:
    """Format seconds → SRT timestamp (HH:MM:SS,mmm)."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_compact_srt(
    srt_path: Path,
    result,
    word_speakers: list[str],
) -> None:
    """Write a compact word-level SRT.

    Each cue = one word. `cue[i].end` is stitched to `cue[i+1].start` so there
    are no gaps between consecutive words (seamless highlight transitions).
    Speaker tags are prepended per cue; sentence boundaries are inferred
    downstream from punctuation (., !, ?) + speaker changes.
    """
    # Flatten word-level timings from whisper result
    words: list[tuple[float, float, str]] = []
    for seg in result.segments:
        for w in seg.words:
            text = (w.word or "").strip()
            if not text:
                continue
            words.append((float(w.start), float(w.end), text))

    if not words:
        srt_path.write_text("", encoding="utf-8")
        return

    # ── Observability guard (no algorithm change) ──
    # `word_speakers` is built from script str.split() (build_word_speaker_map),
    # but `words` here comes from whisper/stable-ts re-tokenization (splits on
    # punctuation/hyphens/contractions), so the counts routinely diverge. The
    # cue→speaker mapping below is positional (`word_speakers[i]`), so any
    # divergence silently misattributes speaker tags from the first mismatch
    # onward and leaves trailing cues untagged. We do NOT fix the mapping here
    # (algorithm choice is out of scope) — we only loud-warn so the operator
    # knows this episode's speaker tags are unreliable and the .srt needs
    # regenerating once a word-aligned mapping lands.
    n_whisper = len(words)
    n_speakers = len(word_speakers)
    if n_whisper != n_speakers:
        diff = n_whisper - n_speakers
        logger.warning(
            "[%s] speaker-map desync: whisper produced %d words but script "
            "speaker-map has %d entries (diff %+d). Per-cue speaker tags are "
            "UNRELIABLE (misattributed from first divergence; %s). Regenerate "
            "this .srt after the word-aligned mapping fix.",
            srt_path.stem,
            n_whisper,
            n_speakers,
            diff,
            f"{diff} trailing cue(s) untagged" if diff > 0
            else f"{-diff} script word(s) dropped",
        )

    # Stitch gaps: cue[i].end = cue[i+1].start (seamless, no blank frames)
    stitched: list[tuple[float, float, str]] = []
    for i, (start, end, text) in enumerate(words):
        if i + 1 < len(words):
            end = words[i + 1][0]
        stitched.append((start, end, text))

    # Emit SRT with per-cue speaker tags
    lines: list[str] = []
    for i, (start, end, text) in enumerate(stitched):
        speaker = word_speakers[i] if i < len(word_speakers) else ""
        tag = f"[{speaker}] " if speaker else ""
        lines.append(str(i + 1))
        lines.append(f"{_format_ts(start)} --> {_format_ts(end)}")
        lines.append(f"{tag}{text}")
        lines.append("")

    srt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def align_and_save(script_path: Path, audio_path: Path, model_name: str) -> Path:
    """Run forced alignment and save SRT."""
    t0 = time.time()

    # Extract segments with speaker info
    segments = script_to_segments(script_path)
    word_speakers = build_word_speaker_map(segments)
    plain_text = " ".join(text for _, text in segments)
    word_count = len(plain_text.split())
    speakers = sorted(set(s for s in word_speakers if s))
    audio_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"  {word_count} words, {len(segments)} segments, speakers: {', '.join(speakers)}")
    print(f"  Audio: {audio_path.name} ({audio_mb:.1f} MB)")

    # Load whisper model (deferred import keeps module-level helpers importable
    # without the heavy stable-ts dependency for unit tests).
    import stable_whisper

    print(f"  Loading whisper model '{model_name}'...")
    model = stable_whisper.load_model(model_name)
    load_elapsed = time.time() - t0
    print(f"  Model loaded in {load_elapsed:.1f}s")

    # Forced alignment
    print(f"  Aligning...")
    align_t0 = time.time()
    result = model.align(str(audio_path), plain_text, language="en")
    align_elapsed = time.time() - align_t0
    print(f"  Alignment done in {align_elapsed:.1f}s")

    # Save compact word-level SRT (one cue per word, contiguous timestamps)
    srt_path = audio_path.with_suffix(".srt")
    write_compact_srt(srt_path, result, word_speakers)
    print(f"  Speaker tags: {', '.join(speakers)}")

    srt_size_kb = srt_path.stat().st_size / 1024
    elapsed = time.time() - t0
    print(f"  → {srt_path.name} ({srt_size_kb:.0f} KB) in {elapsed:.1f}s")
    return srt_path


def main():
    parser = argparse.ArgumentParser(description="Script + audio → word-level SRT")
    parser.add_argument("target", help="Script .md file or directory")
    parser.add_argument("--audio", help="Explicit audio file path")
    parser.add_argument("--model", default="medium", help="Whisper model (tiny/base/small/medium/large)")
    args = parser.parse_args()

    # Route guard warnings to stderr so they stay visible even when the pipeline
    # captures this subprocess's stdout.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    target = Path(args.target)

    if target.is_file():
        # Accept either a script .md or an audio file (.m4a/.mp3/.wav) — resolve to script.
        if is_audio_target(target):
            script = resolve_script_for_audio(target)
            if script is None:
                tried = [f"{target.stem.removesuffix('_pro').removesuffix('_flash')}_script.md",
                         f"{target.stem.removesuffix('_pro').removesuffix('_flash')}.md"]
                print(f"ERROR: no matching script for {target.name} (tried {tried})")
                sys.exit(1)
            scripts = [script]
        else:
            scripts = [target]
    elif target.is_dir():
        scripts = sorted(target.glob("ep_*_script.md"))
        if not scripts:
            scripts = sorted(target.glob("ep_*.md"))
        if not scripts:
            print(f"No script files found in {target}")
            sys.exit(1)
    else:
        print(f"ERROR: {target} not found")
        sys.exit(1)

    # Partition into skip/todo/no-audio
    skipped: list[Path] = []
    no_audio: list[Path] = []
    todo: list[tuple[Path, Path]] = []

    for script in scripts:
        if args.audio:
            audio = Path(args.audio)
            if not audio.is_absolute():
                audio = script.parent / audio
        else:
            audio = find_audio(script)

        if not audio or not audio.exists():
            no_audio.append(script)
            continue

        srt_path = audio.with_suffix(".srt")
        if srt_path.exists():
            skipped.append(script)
        else:
            todo.append((script, audio))

    print(f"[Subtitle] {len(scripts)} script(s) found, {len(todo)} to process, {len(skipped)} skipped, {len(no_audio)} no audio")
    for f in skipped:
        audio = find_audio(f)
        srt = audio.with_suffix(".srt") if audio else None
        size_kb = srt.stat().st_size / 1024 if srt and srt.exists() else 0
        print(f"  SKIP {f.stem}: .srt exists ({size_kb:.0f} KB)")
    for f in no_audio:
        print(f"  NO AUDIO {f.stem}: no matching mp3/wav")

    if not todo:
        print("[Subtitle] Nothing to do")
        return

    t0 = time.time()
    outputs = []
    for i, (script, audio) in enumerate(todo, 1):
        print(f"\n[Subtitle] ({i}/{len(todo)}) {script.stem}")
        srt = align_and_save(script, audio, args.model)
        outputs.append(srt)

    elapsed = time.time() - t0
    total_kb = sum(p.stat().st_size for p in outputs) / 1024
    print(f"\n{'='*50}")
    print(f"[Subtitle] Done: {len(outputs)} subtitle(s) in {elapsed:.0f}s, {total_kb:.0f} KB total")
    for p in outputs:
        size_kb = p.stat().st_size / 1024
        print(f"  {p.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()

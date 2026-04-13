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
import re
import sys
import time
from pathlib import Path

# Force line-buffered stdout for real-time progress visibility
sys.stdout.reconfigure(line_buffering=True)

import stable_whisper

# ─── Host Config ───


def _parse_overview_speakers(overview_path: Path) -> list[str]:
    """Extract host names from overview.md for speaker tagging."""
    if not overview_path.exists():
        return []
    text = overview_path.read_text(encoding="utf-8")
    host_re = re.compile(r"^###\s+(?:Host [AB]:\s*)?(.+?)$", re.MULTILINE)
    hosts = [m.group(1).strip() for m in host_re.finditer(text)]
    return [h for h in hosts if h not in ("Host Dynamics", "Voice Mapping")]


# ─── Parse script → plain text ───

_DIALOGUE_RE = re.compile(r"\*\*(\w+):\*\*\s*(.*)")
# Strip voice direction tags: [excited], [laughing], [speaking slowly], etc.
_DIRECTION_RE = re.compile(r"\[.*?\]")
# Strip SSML-like tags: <break time="0.5s"/>, <emphasis ...>...</emphasis>
_SSML_RE = re.compile(r"<[^>]+>")


def script_to_segments(path: Path) -> list[tuple[str, str]]:
    """Extract (speaker, dialogue) segments from markdown script."""
    text = path.read_text(encoding="utf-8")
    segments: list[tuple[str, str]] = []

    for line in text.strip().splitlines():
        m = _DIALOGUE_RE.match(line.strip())
        if m:
            speaker = m.group(1).strip()
            dialogue = m.group(2).strip()
            dialogue = _DIRECTION_RE.sub("", dialogue)
            dialogue = _SSML_RE.sub("", dialogue)
            dialogue = " ".join(dialogue.split())
            if dialogue:
                segments.append((speaker, dialogue))
        elif line.strip().startswith("*") and line.strip().endswith("*"):
            clean = line.strip().strip("*").strip()
            if clean:
                segments.append(("", clean))

    return segments


def script_to_plain_text(path: Path) -> str:
    """Extract spoken dialogue from markdown script, strip directions."""
    return " ".join(text for _, text in script_to_segments(path))


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
    # Try: ep_1_pro.mp3, ep_1_flash.mp3, ep_1.mp3, ep_1.wav
    for pattern in [f"{stem}_pro.mp3", f"{stem}_flash.mp3", f"{stem}.mp3", f"{stem}.wav"]:
        candidate = parent / pattern
        if candidate.exists():
            return candidate
    return None


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

    # Load whisper model
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

    target = Path(args.target)

    if target.is_file():
        # Accept either a script .md or an audio file (.mp3/.wav) — resolve to script.
        if target.suffix.lower() in {".mp3", ".wav"}:
            stem = target.stem.removesuffix("_pro").removesuffix("_flash")
            candidates = [
                target.parent / f"{stem}_script.md",
                target.parent / f"{stem}.md",
            ]
            script = next((c for c in candidates if c.exists()), None)
            if script is None:
                print(f"ERROR: no matching script for {target.name} (tried {[c.name for c in candidates]})")
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

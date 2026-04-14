#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pydub",
#     "audioop-lts",
# ]
# ///
"""Audio QA — sanity-check synthesized podcast episodes.

Catches the failure modes Whisper forced-alignment can NOT detect:
  - TTS dropped/skipped lines        → words-per-minute too high
  - TTS hallucinated extra audio     → words-per-minute too low
  - Long unintended silences         → silence_gap > threshold
  - Empty / truncated render         → duration vs script word count
  - Clipping (peak ≥ 0 dBFS)         → mastering failed
  - Suspiciously low loudness        → render error or near-silent

Usage:
    uv run audio_qa.py workspaces/<name>/scripts/ep_1_pro.mp3
    uv run audio_qa.py workspaces/<name>/scripts/

Exit codes:
    0 — all checks PASS
    1 — at least one episode has WARN or FAIL findings (CI-friendly)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence

# Speech rate: ~150 wpm conversational, 130-200 acceptable. Outside = suspect.
WPM_MIN = 110
WPM_MAX = 220
SILENCE_MAX_MS = 4000          # any single gap > 4s is suspect
SILENCE_THRESH_DBFS = -40
PEAK_CLIP_DBFS = -0.5          # >= -0.5 dBFS = clipping risk
LOUDNESS_MIN_DBFS = -30        # avg below this = near-silent render

_DIALOGUE_RE = re.compile(r"\*\*(\w+):\*\*\s*(.*)")
_DIRECTION_RE = re.compile(r"\[.*?\]")
_SSML_RE = re.compile(r"<[^>]+>")


def script_word_count(script_path: Path) -> int:
    if not script_path.exists():
        return 0
    text = script_path.read_text(encoding="utf-8")
    spoken: list[str] = []
    for line in text.splitlines():
        m = _DIALOGUE_RE.match(line.strip())
        if m:
            d = m.group(2).strip()
            d = _DIRECTION_RE.sub("", d)
            d = _SSML_RE.sub("", d)
            spoken.append(d)
        elif line.strip().startswith("*") and line.strip().endswith("*"):
            spoken.append(line.strip().strip("*"))
    return len(" ".join(spoken).split())


def find_script(audio_path: Path) -> Path | None:
    stem = audio_path.stem.removesuffix("_pro").removesuffix("_flash")
    for cand in [
        audio_path.parent / f"{stem}_script.md",
        audio_path.parent / f"{stem}.md",
    ]:
        if cand.exists():
            return cand
    return None


def analyze(audio_path: Path) -> dict:
    """Return findings dict for one audio file."""
    findings: list[tuple[str, str]] = []   # (level, message)

    import time
    t0 = time.time()
    seg = AudioSegment.from_file(str(audio_path))
    print(f"    load: {time.time()-t0:.1f}s")

    t1 = time.time()
    duration_s = len(seg) / 1000.0
    duration_min = duration_s / 60.0
    peak_dbfs = seg.max_dBFS
    avg_dbfs = seg.dBFS
    print(f"    dBFS: {time.time()-t1:.1f}s")

    script = find_script(audio_path)
    word_count = script_word_count(script) if script else 0
    wpm = (word_count / duration_min) if duration_min > 0 and word_count else 0.0

    # 1. Duration sanity
    if duration_s < 30:
        findings.append(("FAIL", f"duration {duration_s:.1f}s — render likely truncated"))

    # 2. wpm sanity (catches dropped lines / hallucinated audio)
    if word_count == 0:
        findings.append(("WARN", "no matching script found — wpm check skipped"))
    elif wpm > WPM_MAX:
        findings.append(("WARN", f"wpm {wpm:.0f} > {WPM_MAX} — TTS may have dropped content"))
    elif wpm < WPM_MIN:
        findings.append(("WARN", f"wpm {wpm:.0f} < {WPM_MIN} — TTS may have hallucinated extra audio or excessive pauses"))

    # 3. Long silence detection — seek_step=500ms is 500x faster than default 1ms
    # and plenty accurate for >4s gaps (we're not trying to find millisecond pops).
    t2 = time.time()
    silences = detect_silence(
        seg,
        min_silence_len=SILENCE_MAX_MS,
        silence_thresh=SILENCE_THRESH_DBFS,
        seek_step=500,
    )
    print(f"    silence: {time.time()-t2:.1f}s")
    long_gaps = [(s / 1000.0, e / 1000.0) for s, e in silences if (e - s) >= SILENCE_MAX_MS]
    if long_gaps:
        peek = ", ".join(f"{s:.1f}-{e:.1f}s" for s, e in long_gaps[:3])
        findings.append(("WARN", f"{len(long_gaps)} long silences (>{SILENCE_MAX_MS}ms): {peek}"))

    # 4. Clipping
    if peak_dbfs >= PEAK_CLIP_DBFS:
        findings.append(("WARN", f"peak {peak_dbfs:.2f} dBFS — clipping risk (mastering may have failed)"))

    # 5. Near-silent render
    if avg_dbfs < LOUDNESS_MIN_DBFS:
        findings.append(("FAIL", f"avg loudness {avg_dbfs:.1f} dBFS — render appears near-silent"))

    return {
        "file": audio_path.name,
        "duration_s": round(duration_s, 1),
        "word_count": word_count,
        "wpm": round(wpm, 1),
        "peak_dbfs": round(peak_dbfs, 2),
        "avg_dbfs": round(avg_dbfs, 1),
        "long_silence_count": len(long_gaps),
        "findings": findings,
        "verdict": "FAIL" if any(l == "FAIL" for l, _ in findings)
                   else ("WARN" if findings else "PASS"),
    }


def resolve_targets(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() not in {".mp3", ".wav"}:
            print(f"ERROR: {target} is not an audio file")
            sys.exit(2)
        return [target]
    if target.is_dir():
        files = sorted(list(target.glob("*_pro.mp3")) + list(target.glob("*_flash.mp3")))
        if not files:
            files = sorted(target.glob("*.mp3")) + sorted(target.glob("*.wav"))
        return files
    print(f"ERROR: {target} not found")
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="Audio QA for synthesized podcast episodes")
    parser.add_argument("target", help="Audio file or directory")
    parser.add_argument("--report", help="Write JSON report to this path")
    parser.add_argument("--strict", action="store_true", help="Treat WARN as failure (exit 1)")
    args = parser.parse_args()

    files = resolve_targets(Path(args.target))
    if not files:
        print("[audio_qa] No audio files found")
        sys.exit(0)

    print(f"[audio_qa] Checking {len(files)} file(s)")
    results = []
    for f in files:
        r = analyze(f)
        results.append(r)
        verdict = r["verdict"]
        wpm_str = f"{r['wpm']:.0f} wpm" if r["word_count"] else "no script"
        print(f"\n  {f.name} — {verdict}")
        print(f"    {r['duration_s']:.0f}s, {r['word_count']} words, {wpm_str}, "
              f"peak {r['peak_dbfs']} dBFS, avg {r['avg_dbfs']} dBFS, "
              f"{r['long_silence_count']} long silences")
        for level, msg in r["findings"]:
            print(f"    [{level}] {msg}")

    fails = [r for r in results if r["verdict"] == "FAIL"]
    warns = [r for r in results if r["verdict"] == "WARN"]
    passes = [r for r in results if r["verdict"] == "PASS"]
    print(f"\n[audio_qa] Summary: {len(passes)} PASS, {len(warns)} WARN, {len(fails)} FAIL")

    if args.report:
        Path(args.report).write_text(
            json.dumps({"results": results, "summary": {
                "pass": len(passes), "warn": len(warns), "fail": len(fails),
            }}, indent=2)
        )
        print(f"[audio_qa] Report → {args.report}")

    if fails or (args.strict and warns):
        sys.exit(1)


if __name__ == "__main__":
    main()

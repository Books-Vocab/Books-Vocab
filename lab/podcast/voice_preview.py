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
"""Render a short voice preview (~15s) from a workspace's EP1 script.

Pulls the first 4 turns (2 per speaker) and synthesizes them with the voices
assigned in plan/overview.md. Used to sanity-check voice pair before running
the full synthesize stage.

Usage:
    uv run voice_preview.py workspaces/<name>
    uv run voice_preview.py workspaces/<name1> workspaces/<name2> ...
"""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if cred and not Path(cred).is_absolute():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ROOT / cred)

sys.path.insert(0, str(ROOT))
import synthesize as syn  # reuse parser + client + render pipeline


def pick_preview_turns(turns: list[dict], per_speaker: int = 2) -> list[dict]:
    """Return first N turns per speaker, preserving order. Truncate long turns."""
    counts = {"Speaker1": 0, "Speaker2": 0}
    picked = []
    for t in turns:
        sp = t["speaker"]
        if counts.get(sp, 0) >= per_speaker:
            continue
        # Truncate to ~2 sentences (~40 words) to keep each turn short
        text = t["text"]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        short = " ".join(sentences[:2])[:350]
        picked.append({"speaker": sp, "text": short})
        counts[sp] = counts.get(sp, 0) + 1
        if all(c >= per_speaker for c in counts.values()):
            break
    return picked


def render_preview(workspace: Path) -> Path:
    overview = workspace / "plan" / "overview.md"
    speaker_map, system_prompt = syn._parse_overview_hosts(overview)

    ep1 = workspace / "scripts" / "ep_1_script.md"
    if not ep1.exists():
        raise FileNotFoundError(f"{ep1} missing")

    all_turns = syn.parse_script(ep1, speaker_map)
    preview_turns = pick_preview_turns(all_turns, per_speaker=2)

    if len(preview_turns) < 2:
        raise RuntimeError(f"Not enough turns extracted from {ep1}")

    print(f"\n  Preview turns ({len(preview_turns)}):")
    for t in preview_turns:
        print(f"    {t['speaker']}: {t['text'][:80]}...")

    client = syn.build_client()
    speech_config = syn.build_speech_config()
    prompt = syn.format_prompt(system_prompt, preview_turns)

    print(f"  Synthesizing with {syn.VOICE_SPEAKER1} + {syn.VOICE_SPEAKER2}...")
    _, segment = syn._synthesize_one(
        client, speech_config, prompt,
        index=0, total=1,
        batch_words=sum(len(t["text"].split()) for t in preview_turns),
        turns_count=len(preview_turns),
    )

    out = workspace / "scripts" / "ep_1_voice_preview.mp3"
    segment.export(out, format="mp3", bitrate=syn.MP3_BITRATE)
    print(f"  → {out} ({len(segment)/1000:.1f}s, {out.stat().st_size//1024}KB)")
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    for arg in sys.argv[1:]:
        ws = Path(arg).resolve()
        if not ws.is_dir():
            print(f"Skip {arg}: not a directory")
            continue
        print(f"\n[{ws.name}]")
        try:
            render_preview(ws)
        except Exception as e:
            print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()

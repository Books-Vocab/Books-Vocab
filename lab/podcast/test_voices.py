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
"""Quick A/B test — render the same 10s dialogue with different voice pairs.

Usage:
    uv run test_voices.py                    # run all default pairs
    uv run test_voices.py Puck Kore          # single pair
"""

import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if cred_path and not Path(cred_path).is_absolute():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ROOT / cred_path)

from google import genai
from google.genai import types as genai_types
from pydub import AudioSegment

MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()

SCRIPT = """Speaker1: So I've been reading this book about habits, and it completely changed how I think about change.
Speaker2: Oh really? What was the big insight for you?
Speaker1: [excited] It's this idea that you don't rise to the level of your goals — you fall to the level of your systems.
Speaker2: Huh. That's actually a pretty big reframe."""

PAIRS = [
    ("Puck", "Kore"),         # current default
    ("Charon", "Leda"),       # informative male + youthful female
    ("Puck", "Aoede"),        # upbeat male + breezy female
    ("Orus", "Sulafat"),      # firm male + warm female
    ("Fenrir", "Zephyr"),     # excitable male + bright female
]

def synthesize(client, s1: str, s2: str) -> AudioSegment:
    cfg = genai_types.SpeechConfig(
        multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker1",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=s1)
                    ),
                ),
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker2",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=s2)
                    ),
                ),
            ]
        )
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=SCRIPT,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=cfg,
        ),
    )
    for cand in resp.candidates:
        for part in cand.content.parts:
            if part.inline_data:
                data = part.inline_data.data
                mime = part.inline_data.mime_type or ""
                if "wav" in mime:
                    return AudioSegment.from_file(io.BytesIO(data), format="wav")
                return AudioSegment(data=data, sample_width=2, frame_rate=24000, channels=1)
    raise RuntimeError("no audio")


def main():
    client = genai.Client(
        vertexai=True,
        project=os.getenv("GCP_PROJECT_ID", "").strip(),
        location=os.getenv("GCP_LOCATION", "us-central1").strip(),
    )
    out = ROOT / "voice_samples"
    out.mkdir(exist_ok=True)

    if len(sys.argv) == 3:
        pairs = [(sys.argv[1], sys.argv[2])]
    else:
        pairs = PAIRS

    for s1, s2 in pairs:
        print(f"Rendering {s1} + {s2}...", flush=True)
        seg = synthesize(client, s1, s2)
        fp = out / f"{s1}_{s2}.mp3"
        seg.export(fp, format="mp3", bitrate="192k")
        print(f"  → {fp} ({len(seg)/1000:.1f}s, {fp.stat().st_size//1024}KB)")

if __name__ == "__main__":
    main()

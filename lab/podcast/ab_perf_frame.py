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
"""A/B test: current narrative TTS frame vs. proposed ### PERFORMANCE / #### TRANSCRIPT
structure for Gemini 3.1 Flash TTS.

Validates whether the 3.1-recommended prompt structure (research: livekit/dev.to)
is safe to adopt — specifically that the model does NOT vocalize the section
headers, does NOT trigger the 655s padding bug, and (subjectively) delivers more
expressive prosody.

Outputs two wavs to voice_samples/ab_*.wav and re-transcribes each via Gemini
audio understanding to auto-check criterion 1 (header leakage) + reports duration
(criterion 2). Criterion 3 (vividness) is for the human ear.

    uv run ab_perf_frame.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

_cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if _cred and not Path(_cred).is_absolute():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ROOT / _cred)

from google import genai
from google.genai import types as genai_types

# Reuse the production audio decoder — Vertex returns raw 24kHz PCM whose mime
# string does NOT always say "pcm", so naive ffmpeg decode fails. synthesize.py
# already handles every return shape correctly.
import synthesize
from tts_config import DEFAULT_TTS_MODEL

TTS_MODEL = os.getenv("TTS_MODEL", DEFAULT_TTS_MODEL).strip()
STT_MODEL = os.getenv("STT_MODEL", "gemini-2.5-flash").strip()
V1, V2 = "Puck", "Kore"
OUT = ROOT / "voice_samples"
OUT.mkdir(exist_ok=True)

# 8-line test dialogue: cold-open (2 substantive lines), emotional range, an
# energy shift, noun-form tags, comma-joined tagged clauses (3.1 rules).
HOSTA = "Maya"
HOSTB = "Kai"
TURNS = [
    ("Speaker1", "Welcome to The Quiet Hour, where we read one hard book slowly. I'm Maya."),
    ("Speaker2", "And I'm Kai. Today: why the same factory job can be heaven for one person and a prison for another."),
    ("Speaker1", "[curiosity] So walk me through it — same assembly line, same paycheck, completely different inner life?"),
    ("Speaker2", "[slow] Same building, same hours, and yet one of them is fully alive while the other is just... counting minutes."),
    ("Speaker1", "[skepticism] Okay, but that sounds suspiciously like telling miserable people it's their own fault."),
    ("Speaker2", "[high energy] No — that's the trap, right, it's not willpower, it's whether the work pulls your full attention or leaves you empty."),
    ("Speaker1", "[melancholy] Yeah. That last part lands a little too close to home."),
    ("Speaker2", "[amusement] Doesn't it always? Let's get into it."),
]

# Per-host performance direction (the Director's Notes payload).
PERF_A = "bright mid-Atlantic, high energy, quick and curious, lifts at the end of questions"
PERF_B = "low warm register, unhurried and grounded, dry wit, lets pauses breathe"

# ── Frame A: current narrative structure (verbatim from _parse_overview_hosts) ──
def frame_a() -> str:
    return "\n".join([
        "Read aloud as a two-host podcast conversation. Warm, intellectual, and engaging "
        "— like two smart friends discussing a book over coffee. Natural pacing with "
        "pauses between speaker turns.",
        "",
        "Voice direction (do NOT speak these character notes — they are style guidance only):",
        f"- {HOSTA} (voiced by Speaker1): relentlessly curious, quick analogies. Performance: {PERF_A}",
        f"- {HOSTB} (voiced by Speaker2): grounded skeptic, concrete examples. Performance: {PERF_B}",
        "",
        "They interrupt each other naturally, react with genuine surprise or amusement, "
        "and think together rather than taking turns lecturing.",
        "The dialogue to perform follows below. Speak ONLY the dialogue; do not read the voice direction.",
    ])


# ── Frame B: 3.1-recommended ### PERFORMANCE + #### TRANSCRIPT structure ──
def frame_b() -> str:
    return "\n".join([
        "Read the transcript below aloud as a two-host podcast conversation between two "
        "smart friends discussing a book. Speak only the dialogue lines; the PERFORMANCE "
        "section is direction, never read it aloud.",
        "",
        "### PERFORMANCE",
        f"- Speaker1 ({HOSTA}): {PERF_A}",
        f"- Speaker2 ({HOSTB}): {PERF_B}",
        "- Overall: warm and intellectual, natural overlaps, let emotional beats land.",
    ])


def dialogue() -> str:
    return "\n".join(f"{s}: {t}" for s, t in TURNS)


def prompt_a() -> str:
    return f"{frame_a()}\n\n{dialogue()}".strip()


def prompt_b() -> str:
    # #### TRANSCRIPT delimiter is the 3.1 official-example structure.
    return f"{frame_b()}\n\n#### TRANSCRIPT\n{dialogue()}".strip()


def speech_config() -> genai_types.SpeechConfig:
    return genai_types.SpeechConfig(
        multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker1",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=V1)
                    ),
                ),
                genai_types.SpeakerVoiceConfig(
                    speaker="Speaker2",
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=V2)
                    ),
                ),
            ]
        )
    )


def synth(client, label: str, prompt: str) -> Path:
    print(f"[{label}] synthesizing ({len(prompt)} chars)...", flush=True)
    resp = client.models.generate_content(
        model=TTS_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"], speech_config=speech_config()
        ),
    )
    data, mime = None, "audio/pcm"
    for c in resp.candidates:
        for p in c.content.parts:
            if p.inline_data:
                data, mime = p.inline_data.data, p.inline_data.mime_type or mime
                break
        if data:
            break
    if not data:
        raise RuntimeError(f"[{label}] no audio returned")

    seg = synthesize.audio_bytes_to_segment(data, mime)

    out = OUT / f"ab_{label}.wav"
    seg.export(out, format="wav")
    print(f"[{label}] -> {out.name}  duration={len(seg)/1000:.1f}s  ({len(data)} bytes)", flush=True)
    return out


def transcribe(client, label: str, wav: Path) -> str:
    """Re-transcribe via Gemini audio understanding to auto-check header leakage."""
    audio = wav.read_bytes()
    resp = client.models.generate_content(
        model=STT_MODEL,
        contents=[
            "Transcribe this audio verbatim. Output ONLY the spoken words, nothing else.",
            genai_types.Part.from_bytes(data=audio, mime_type="audio/wav"),
        ],
    )
    text = (resp.text or "").strip()
    leak = [w for w in ("performance", "transcript", "speaker1", "speaker2", "hash")
            if w in text.lower()]
    verdict = "LEAK: " + ", ".join(leak) if leak else "clean"
    print(f"[{label}] transcript header-check: {verdict}", flush=True)
    print(f"[{label}] transcript: {text[:400]}", flush=True)
    return text


def main() -> int:
    if not os.getenv("GCP_PROJECT_ID", "").strip():
        print("ERROR: GCP_PROJECT_ID not set", file=sys.stderr)
        return 1
    client = genai.Client(
        vertexai=True,
        project=os.getenv("GCP_PROJECT_ID").strip(),
        location=os.getenv("GCP_LOCATION", "us-central1").strip(),
    )
    print(f"TTS={TTS_MODEL}  voices={V1}+{V2}\n", flush=True)

    wav_a = synth(client, "A_narrative", prompt_a())
    wav_b = synth(client, "B_performance", prompt_b())
    print(flush=True)
    transcribe(client, "A_narrative", wav_a)
    transcribe(client, "B_performance", wav_b)
    print("\nDone. Listen to both wavs in voice_samples/ for criterion 3 (vividness).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

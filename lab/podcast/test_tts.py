#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai",
#     "python-dotenv",
# ]
# ///
"""Quick smoke test — send one short prompt to Vertex AI Gemini TTS, confirm audio comes back."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# Resolve credential path relative to script dir
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if cred_path and not Path(cred_path).is_absolute():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(ROOT / cred_path)

from google import genai
from google.genai import types as genai_types

client = genai.Client(
    vertexai=True,
    project=os.getenv("GCP_PROJECT_ID", "").strip(),
    location=os.getenv("GCP_LOCATION", "us-central1").strip(),
)

model = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()

response = client.models.generate_content(
    model=model,
    contents="Say: Hello, this is a test of Gemini TTS on Vertex AI.",
    config=genai_types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name=os.getenv("VOICE_SPEAKER1", "Puck")
                )
            ),
        ),
    ),
)

for candidate in response.candidates:
    for part in candidate.content.parts:
        if part.inline_data:
            data = part.inline_data.data
            mime = part.inline_data.mime_type
            print(f"OK — got {len(data)} bytes, mime: {mime}")
            raise SystemExit(0)

print("FAILED — no audio data in response")
raise SystemExit(1)

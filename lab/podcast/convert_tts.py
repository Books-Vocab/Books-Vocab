#!/usr/bin/env python3
"""Convert podcast script markdown to Gemini TTS format.

Usage:
    python convert_tts.py <script.md> [--output <out.txt>]
"""

import argparse
import re
from pathlib import Path


SYSTEM_PROMPT = """\
Read aloud as a two-host podcast conversation. Warm, intellectual, and engaging — like two smart friends discussing a book over coffee. Natural pacing with pauses between speaker turns.

Speaker 1 (Maya): Warm, conversational, gently skeptical. Shorter sentences, vivid everyday analogies. Curious and grounded. Occasionally pushes back with "But here's what bugs me about that..."

Speaker 2 (Kai): Intellectually enthusiastic, builds layered explanations. Longer sentences when excited, shorter when landing a key point. Quotes research naturally. Gets genuinely delighted by counterintuitive findings.

They interrupt each other naturally, react with genuine surprise or amusement, and think together rather than taking turns lecturing.\
"""

SPEAKER_MAP = {
    "Maya": "Speaker 1",
    "Kai": "Speaker 2",
}


def convert(script_path: str) -> str:
    text = Path(script_path).read_text()

    lines = text.strip().split("\n")
    output = [SYSTEM_PROMPT, ""]

    for line in lines:
        # Match **Maya:** or **Kai:** dialogue lines
        m = re.match(r"\*\*(\w+):\*\*\s*(.*)", line)
        if m:
            name, dialogue = m.group(1), m.group(2)
            speaker = SPEAKER_MAP.get(name, f"Speaker ({name})")
            output.append(f"{speaker}: {dialogue}")
        # Skip markdown headers, hr, blockquotes, empty lines
        elif line.startswith("#") or line.startswith("---") or line.startswith(">"):
            continue
        elif line.startswith("*") and line.endswith("*"):
            # Italic takeaway line — narrator
            output.append(f"Speaker 1: {line.strip('*').strip()}")
        elif line.strip():
            # Continuation of previous speaker's dialogue
            if output and output[-1]:
                output[-1] += " " + line.strip()

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script", help="Path to script markdown file or directory with part files")
    parser.add_argument("--output", "-o", help="Output file or directory (default: stdout)")
    args = parser.parse_args()

    script_path = Path(args.script)

    # If given a directory or a glob pattern, convert all parts
    if script_path.is_dir():
        parts = sorted(script_path.glob("ep_*_part*.md"))
        if not parts:
            print("No part files found")
            return
        out_dir = Path(args.output) if args.output else script_path
        out_dir.mkdir(parents=True, exist_ok=True)
        for p in parts:
            result = convert(str(p))
            out_file = out_dir / p.name.replace(".md", "_tts.txt")
            out_file.write_text(result)
            print(f"Written: {out_file.name}")
    else:
        result = convert(str(script_path))
        if args.output:
            Path(args.output).write_text(result)
            print(f"Written to {args.output}")
        else:
            print(result)


if __name__ == "__main__":
    main()

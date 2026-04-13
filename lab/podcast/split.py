#!/usr/bin/env python3
"""Split episode script into TTS-sized parts at dialogue turn boundaries.

Usage:
    python split.py <workspace> <episode_num> [--target-words 1000]
"""

import argparse
import re
from pathlib import Path

TARGET_WORDS = 1000
MIN_WORDS = 800
MAX_WORDS = 1200


def split_script(script_path: Path, target: int = TARGET_WORDS) -> list[list[str]]:
    """Split script into parts at Speaker turn boundaries."""
    text = script_path.read_text()
    lines = text.strip().split("\n")

    # Skip header (# title, > subtitle, ---)
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Speaker ") or re.match(r"^\*\*\w+:\*\*", line):
            body_start = i
            break

    # Find footer (--- + italic takeaway)
    body_end = len(lines)
    for i in range(len(lines) - 1, body_start, -1):
        if lines[i].startswith("---"):
            body_end = i
            break

    header = lines[:body_start]
    body = lines[body_start:body_end]
    footer = lines[body_end:]

    # Group into dialogue turns (starts with "Speaker N:" or "**Name:**")
    turns = []
    current_turn = []
    for line in body:
        if (re.match(r"^Speaker \d", line) or re.match(r"^\*\*\w+:\*\*", line)) and current_turn:
            turns.append("\n".join(current_turn))
            current_turn = [line]
        else:
            current_turn.append(line)
    if current_turn:
        turns.append("\n".join(current_turn))

    # Accumulate turns into parts
    parts = []
    current_part = []
    current_words = 0

    for turn in turns:
        turn_words = len(turn.split())
        current_part.append(turn)
        current_words += turn_words

        if current_words >= target:
            parts.append(current_part)
            current_part = []
            current_words = 0

    # Remaining turns
    if current_part:
        parts.append(current_part)

    # Post-process: if last part is too short, merge with previous
    if len(parts) > 1:
        last_words = sum(len(t.split()) for t in parts[-1])
        if last_words < MIN_WORDS:
            parts[-2].extend(parts[-1])
            parts.pop()

    return header, parts, footer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", help="Workspace directory")
    parser.add_argument("episode", type=int, help="Episode number")
    parser.add_argument("--target-words", type=int, default=TARGET_WORDS)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    script_path = workspace / "scripts" / f"ep_{args.episode}_script.md"

    if not script_path.exists():
        print(f"ERROR: {script_path} not found")
        return

    header, parts, footer = split_script(script_path, args.target_words)
    total_parts = len(parts)

    print(f"Script: {script_path.name}")
    print(f"Split into {total_parts} parts:")

    for i, part_turns in enumerate(parts, 1):
        part_text = "\n\n".join(part_turns)
        words = len(part_text.split())
        mins = round(words / 120, 1)

        # Build part file
        part_lines = [f"# Episode {args.episode} — Part {i}/{total_parts}", "", "---", ""]
        part_lines.append(part_text)
        part_lines.extend(["", "---"])

        # Add footer only to last part
        if i == total_parts and footer:
            part_lines.extend(footer)

        out_path = workspace / "scripts" / f"ep_{args.episode}_part{i}.md"
        out_path.write_text("\n".join(part_lines))

        preview = part_turns[0][:80].replace("\n", " ")
        print(f"  Part {i}/{total_parts}: {words:>5} words (~{mins} min) | {preview}...")

    # Write summary
    summary_lines = [
        f"# Episode {args.episode} — Split Summary",
        "",
        "| Part | Words | Est. Duration | Starts At |",
        "|------|-------|---------------|-----------|",
    ]
    total_words = 0
    for i, part_turns in enumerate(parts, 1):
        part_text = "\n\n".join(part_turns)
        words = len(part_text.split())
        total_words += words
        mins = f"~{round(words / 120, 1)} min"
        preview = part_turns[0][:60].replace("\n", " ").replace("|", "/")
        summary_lines.append(f"| {i}/{total_parts} | {words} | {mins} | {preview}... |")

    summary_lines.append(f"\nTotal: {total_words} words, ~{round(total_words / 120, 1)} min")

    summary_path = workspace / "scripts" / f"ep_{args.episode}_parts.md"
    summary_path.write_text("\n".join(summary_lines))
    print(f"\nSummary: {summary_path}")


if __name__ == "__main__":
    main()

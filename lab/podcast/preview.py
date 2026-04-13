#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pydub",
#     "audioop-lts",
# ]
# ///
"""Preview podcast with synced subtitles — mirrors iOS player layout.

iOS layout reference (PodcastWordLevelView.swift):
  ▌ [Speaker]  word word WORD word ...
  └ accent bar (3px)
    └ speaker chip (accent/success color)
             └ words, active word reversed with accent bg

Speaker 0 (first host in overview.md) → accent color (blue)
Speaker 1 (second host)               → success color (green)
Unknown                               → muted gray

Usage:
    uv run preview.py workspaces/flow_950f1a7d/scripts/ep_1_pro.mp3
    uv run preview.py workspaces/flow_950f1a7d/scripts/  # auto-find first mp3+srt pair
"""

from __future__ import annotations

import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(s: str) -> int:
    """Length excluding ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


# --- ANSI palette (matches iOS AppTheme.light: accent = blue, success = green) ---
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
# 256-color approximations of AppColors: accent ~ #0A84FF, success ~ #34C759
SPEAKER_COLORS_FG = ["\033[38;5;39m", "\033[38;5;41m"]   # blue, green
SPEAKER_COLORS_BG = ["\033[48;5;39m", "\033[48;5;41m"]   # blue bg, green bg
MUTED_FG = "\033[38;5;244m"

ACCENT_BAR = "▌"   # U+258C left half block — mimics iOS 3px accent bar


@dataclass
class SubtitleCue:
    """A single word cue (new compact SRT format)."""
    index: int
    start: float  # seconds
    end: float
    speaker: str  # extracted from [SpeakerName] prefix
    word: str     # the word text (no tags)


def parse_timestamp(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


_TAG_RE = re.compile(r'<[^>]+>')
_SPEAKER_RE = re.compile(r'^\[([^\]]+)\]\s*')
_SENTENCE_END_RE = re.compile(r'[.!?…][")\']?$')


def parse_srt(path: Path) -> list[SubtitleCue]:
    """Parse compact word-level SRT: one cue = one word, with [Speaker] prefix."""
    text = path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    cues: list[SubtitleCue] = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            continue
        times = lines[1].split(" --> ")
        if len(times) != 2:
            continue
        start = parse_timestamp(times[0].strip())
        end = parse_timestamp(times[1].strip())
        raw = " ".join(lines[2:])

        speaker = ""
        m = _SPEAKER_RE.match(raw)
        if m:
            speaker = m.group(1)
            raw = raw[m.end():]

        word = _TAG_RE.sub("", raw).strip()
        if not word:
            continue
        cues.append(SubtitleCue(index, start, end, speaker, word))

    return cues


def group_sentences(cues: list[SubtitleCue]) -> list[list[SubtitleCue]]:
    """Aggregate word-level cues into sentences.

    Boundary rule: speaker change OR previous word ended with sentence-final
    punctuation (., !, ?, …). Mirrors the aggregation logic the iOS engine
    will need to adopt for the compact SRT format.
    """
    groups: list[list[SubtitleCue]] = []
    current: list[SubtitleCue] = []

    for cue in cues:
        break_here = False
        if current:
            prev = current[-1]
            if cue.speaker != prev.speaker:
                break_here = True
            elif _SENTENCE_END_RE.search(prev.word):
                break_here = True
        if break_here:
            groups.append(current)
            current = []
        current.append(cue)

    if current:
        groups.append(current)

    return groups


def parse_host_names(workspace_dir: Path) -> list[str]:
    """Read host names from plan/overview.md (matches subtitle.py._parse_overview_speakers)."""
    overview = workspace_dir / "plan" / "overview.md"
    if not overview.exists():
        return []
    host_re = re.compile(r"^###\s+(?:Host [AB]:\s*)?(.+?)$", re.MULTILINE)
    hosts = [m.group(1).strip() for m in host_re.finditer(overview.read_text(encoding="utf-8"))]
    return [h for h in hosts if h not in ("Host Dynamics", "Voice Mapping")]


def find_audio_srt(target: Path) -> tuple[Path, Path]:
    if target.is_file():
        audio = target
        srt = target.with_suffix(".srt")
        if not srt.exists():
            print(f"ERROR: {srt.name} not found")
            sys.exit(1)
        return audio, srt
    if target.is_dir():
        for mp3 in sorted(target.glob("*.mp3")):
            srt = mp3.with_suffix(".srt")
            if srt.exists():
                return mp3, srt
        print(f"No mp3+srt pair found in {target}")
        sys.exit(1)
    print(f"ERROR: {target} not found")
    sys.exit(1)


def workspace_root(audio_path: Path) -> Path:
    """Locate workspace root (parent containing plan/ dir)."""
    for p in [audio_path.parent, *audio_path.parents]:
        if (p / "plan" / "overview.md").exists():
            return p
    return audio_path.parent


def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def speaker_index(speaker: str, host_names: list[str]) -> int:
    try:
        return host_names.index(speaker)
    except ValueError:
        return -1


def speaker_chip(speaker: str, host_names: list[str]) -> str:
    """Colored capsule label, mirrors iOS SpeakerChip (bg.opacity(0.12) + fg color)."""
    idx = speaker_index(speaker, host_names)
    if idx < 0 or idx >= len(SPEAKER_COLORS_FG):
        return f"{MUTED_FG} {speaker or '?':<8}{RESET}"
    # Use foreground color on a dimmed block — terminal can't do 12% opacity bg cleanly
    return f"{SPEAKER_COLORS_FG[idx]}{BOLD} {speaker:<8}{RESET}"


def accent_bar(speaker: str, host_names: list[str]) -> str:
    idx = speaker_index(speaker, host_names)
    if idx < 0 or idx >= len(SPEAKER_COLORS_FG):
        return f"{MUTED_FG}{ACCENT_BAR}{RESET}"
    return f"{SPEAKER_COLORS_FG[idx]}{ACCENT_BAR}{RESET}"


def render_sentence(
    group: list[SubtitleCue],
    active_idx: int,
    host_names: list[str],
    max_width: int = 80,
) -> str:
    """Render one sentence row with active word reversed, truncated to max_width.

    To avoid terminal auto-wrap (which breaks `\\r\\033[K` in-place redraws),
    we build a sliding window of words centered on the active one so the total
    visible length fits in `max_width`.
    """
    speaker = group[0].speaker
    idx = speaker_index(speaker, host_names)
    accent_bg = SPEAKER_COLORS_BG[idx] if 0 <= idx < len(SPEAKER_COLORS_BG) else "\033[48;5;244m"

    # Build styled word tokens (paired with plain length for width budgeting).
    tokens: list[tuple[str, int]] = []
    for i, cue in enumerate(group):
        if i == active_idx:
            styled = f"{accent_bg}{BOLD}\033[97m {cue.word} {RESET}"
            # visible length includes the 2 padding spaces
            tokens.append((styled, len(cue.word) + 2))
        else:
            tokens.append((cue.word, len(cue.word)))

    if max_width <= 0 or not tokens:
        return " ".join(t for t, _ in tokens)

    # Center-expand window around active word.
    center = active_idx if 0 <= active_idx < len(tokens) else 0
    left, right = center, center
    used = tokens[center][1]
    while True:
        grew = False
        if left > 0 and used + 1 + tokens[left - 1][1] <= max_width:
            left -= 1
            used += 1 + tokens[left][1]
            grew = True
        if right < len(tokens) - 1 and used + 1 + tokens[right + 1][1] <= max_width:
            right += 1
            used += 1 + tokens[right][1]
            grew = True
        if not grew:
            break

    prefix = "… " if left > 0 else ""
    suffix = " …" if right < len(tokens) - 1 else ""
    body = " ".join(t for t, _ in tokens[left : right + 1])
    return f"{prefix}{body}{suffix}"


def spawn_ffplay(audio_path: Path, offset: float) -> subprocess.Popen:
    """Spawn ffplay starting at `offset` seconds."""
    return subprocess.Popen(
        [
            "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
            "-ss", f"{max(0.0, offset):.3f}",
            str(audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def locate_group(groups: list[list[SubtitleCue]], t: float) -> tuple[int, int]:
    """Find (group_idx, cue_in_group) whose time window contains t."""
    for gi, g in enumerate(groups):
        if t < g[0].start:
            return gi, 0
        if t <= g[-1].end:
            for ci, c in enumerate(g):
                if t <= c.end:
                    return gi, ci
            return gi, len(g) - 1
    return len(groups), 0


def read_key(timeout: float) -> str | None:
    """Non-blocking read of one logical key from stdin (cbreak mode).

    Returns: 'space', 'left', 'right', 'q', or None on timeout.
    """
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return None
    ch = sys.stdin.read(1)
    if ch == " ":
        return "space"
    if ch in ("q", "Q"):
        return "q"
    if ch == "h":
        return "left"
    if ch == "l":
        return "right"
    if ch == "\x1b":
        # Arrow key: ESC [ A/B/C/D — drain remaining chars.
        r2, _, _ = select.select([sys.stdin], [], [], 0.01)
        if r2:
            seq = sys.stdin.read(2)
            if seq.endswith("C"):
                return "right"
            if seq.endswith("D"):
                return "left"
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run preview.py <audio.mp3 or directory>")
        sys.exit(1)

    target = Path(sys.argv[1])
    audio_path, srt_path = find_audio_srt(target)
    ws = workspace_root(audio_path)
    host_names = parse_host_names(ws)

    cues = parse_srt(srt_path)
    groups = group_sentences(cues)
    total_dur = groups[-1][-1].end if groups else 0.0

    print(f"{BOLD}Audio:{RESET} {audio_path.name}")
    print(f"{BOLD}Subs: {RESET} {srt_path.name}")
    if host_names:
        print(f"{BOLD}Hosts:{RESET} " + ", ".join(speaker_chip(h, host_names) for h in host_names))
    else:
        print(f"{BOLD}Hosts:{RESET} {DIM}(none found in overview.md){RESET}")
    print(f"{DIM}{len(cues)} word cues · {len(groups)} sentences · {format_time(total_dur)}{RESET}")
    print(f"{DIM}[space] pause/play   [←/h] −5s   [→/l] +5s   [q] quit{RESET}")
    print()

    # Virtual clock state
    position = 0.0        # audio position in seconds (only updated on pause/seek)
    wall_anchor = time.time()
    playing = True
    proc = spawn_ffplay(audio_path, position)

    def current_position() -> float:
        if playing:
            return position + (time.time() - wall_anchor)
        return position

    def pause():
        nonlocal position, playing, proc
        if not playing:
            return
        position = current_position()
        playing = False
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def resume():
        nonlocal wall_anchor, playing, proc
        if playing:
            return
        wall_anchor = time.time()
        playing = True
        proc = spawn_ffplay(audio_path, position)

    def seek(delta: float):
        nonlocal position, wall_anchor, proc
        new_pos = max(0.0, min(total_dur, current_position() + delta))
        position = new_pos
        wall_anchor = time.time()
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if playing:
            proc = spawn_ffplay(audio_path, position)

    # Switch stdin to cbreak for non-blocking key reads.
    fd = sys.stdin.fileno()
    old_termios = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    # Hide cursor for cleaner redraw
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    group_idx = 0
    cue_in_group = 0
    last_rendered_group = -1

    try:
        while group_idx < len(groups):
            # Handle keys (short timeout so render stays responsive)
            key = read_key(0.03)
            if key == "space":
                if playing:
                    pause()
                else:
                    resume()
            elif key == "left":
                seek(-5.0)
                group_idx, cue_in_group = locate_group(groups, current_position())
                last_rendered_group = -1
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            elif key == "right":
                seek(5.0)
                group_idx, cue_in_group = locate_group(groups, current_position())
                last_rendered_group = -1
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            elif key == "q":
                break

            # End of audio?
            if playing and proc.poll() is not None:
                # Natural finish.
                break

            elapsed = current_position()
            if group_idx >= len(groups):
                break
            group = groups[group_idx]

            # Advance cue cursor within group
            while cue_in_group < len(group) and elapsed > group[cue_in_group].end:
                cue_in_group += 1

            # Terminal width budget (fallback 80 if detection gives bogus value)
            term_cols = shutil.get_terminal_size((80, 24)).columns
            if term_cols < 40:
                term_cols = 80
            bar = accent_bar(group[0].speaker, host_names)
            chip = speaker_chip(group[0].speaker, host_names)
            status = "▶" if playing else "⏸"

            if cue_in_group >= len(group):
                ts = format_time(group[-1].end)
                prefix = f"{DIM}[{ts} {status}]{RESET} {bar} {chip}  "
                body_budget = max(20, term_cols - visible_len(prefix) - 2)
                line = render_sentence(group, -1, host_names, max_width=body_budget)
                sys.stdout.write(f"\r\033[K{prefix}{line}\n")
                sys.stdout.flush()
                group_idx += 1
                cue_in_group = 0
                last_rendered_group = -1
                continue

            cue = group[cue_in_group]
            if elapsed < cue.start:
                continue  # loop will read key + sleep via select timeout

            ts = format_time(elapsed)
            prefix = f"{DIM}[{ts} {status}]{RESET} {bar} {chip}  "
            body_budget = max(20, term_cols - visible_len(prefix) - 2)
            line = render_sentence(group, cue_in_group, host_names, max_width=body_budget)
            sys.stdout.write(f"\r\033[K{prefix}{line}")
            sys.stdout.flush()
            last_rendered_group = group_idx

    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=0.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)
        sys.stdout.write("\033[?25h\n")  # show cursor
        sys.stdout.flush()


if __name__ == "__main__":
    main()

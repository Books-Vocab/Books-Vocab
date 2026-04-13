#!/usr/bin/env python3
"""Podcast Pipeline Orchestrator — EPUB → Prep → Architect → Scriptwriters.

Usage:
    python run.py <path-to-epub> [--episodes N] [--dry-run]

Each stage is a Claude Code CLI invocation with opus[1m].
Agents communicate via the filesystem (workspace directory).
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

PROMPTS_DIR = Path(__file__).parent / "prompts"
WORKSPACES_DIR = Path(__file__).parent / "workspaces"
MODEL = "opus[1m]"
MAX_CHAPTER_CHARS = 80_000  # ~20K tokens


# ─── EPUB Extraction (no LLM needed) ───


def extract_epub(epub_path: str) -> tuple[dict, list[tuple[str, str]]]:
    """Extract metadata + raw chapter texts from EPUB."""
    book = epub.read_epub(epub_path)

    title = book.get_metadata("DC", "title")[0][0]
    author = book.get_metadata("DC", "creator")[0][0]
    lang = book.get_metadata("DC", "language")[0][0]

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 50:
            chapters.append((item.get_name(), text))

    metadata = {
        "title": title,
        "author": author,
        "language": lang,
        "total_raw_chapters": len(chapters),
        "total_raw_chars": sum(len(t) for _, t in chapters),
    }
    return metadata, chapters


def setup_workspace(metadata: dict, chapters: list[tuple[str, str]]) -> Path:
    """Create workspace and write raw chapters + metadata."""
    slug = metadata["title"].lower().replace(" ", "_")[:30]
    book_hash = hashlib.md5(
        f"{metadata['title']}_{metadata['author']}".encode()
    ).hexdigest()[:8]
    workspace = WORKSPACES_DIR / f"{slug}_{book_hash}"

    # Create dirs
    for d in ["source/chapters", "plan/episodes", "scripts", "raw_chapters"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)

    # Write metadata
    meta_lines = [
        f"# {metadata['title']}",
        f"- **Author**: {metadata['author']}",
        f"- **Language**: {metadata['language']}",
        f"- **Raw chapters**: {metadata['total_raw_chapters']}",
        f"- **Raw chars**: {metadata['total_raw_chars']:,}",
    ]
    (workspace / "source" / "metadata.md").write_text("\n".join(meta_lines))

    # Write raw chapters
    for i, (name, text) in enumerate(chapters):
        (workspace / "raw_chapters" / f"raw_ch_{i + 1:02d}.md").write_text(
            f"<!-- source: {name} -->\n\n{text}"
        )

    # Init log
    (workspace / "log.md").write_text(
        f"# Podcast Pipeline Log\n\n"
        f"- Book: {metadata['title']} by {metadata['author']}\n"
        f"- Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    return workspace


# ─── Claude Code CLI Runner ───


def run_claude(
    prompt: str, workspace: Path, label: str, extra_tools: list[str] | None = None
) -> bool:
    """Run a Claude Code CLI agent with the given prompt."""
    print(f"\n{'='*60}")
    print(f"[{label}] Starting...")
    print(f"{'='*60}")

    # Replace {workspace} placeholder in prompt
    prompt = prompt.replace("{workspace}", str(workspace))

    tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    if extra_tools:
        tools.extend(extra_tools)

    t0 = time.time()
    proc = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--model", MODEL,
            "--allowedTools", ",".join(tools),
        ],
        cwd=str(workspace),
        capture_output=False,  # Let output stream to terminal
        text=True,
    )
    elapsed = time.time() - t0

    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"\n[{label}] {status} in {elapsed:.1f}s")

    return proc.returncode == 0


def run_scriptwriter(workspace: Path, ep_num: int) -> tuple[int, bool]:
    """Run a single scriptwriter agent. Used by ProcessPoolExecutor."""
    prompt_template = (PROMPTS_DIR / "scriptwriter.md").read_text()
    prompt = prompt_template.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))
    prompt += f"\n\nYou are writing Episode {ep_num}. Read the overview, then your episode plan at plan/episodes/ep_{ep_num:02d}.md, then the source chapters listed in it."

    print(f"\n[Scriptwriter EP{ep_num}] Starting...")
    t0 = time.time()

    proc = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--model", MODEL,
            "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep",
        ],
        cwd=str(workspace),
        capture_output=False,
        text=True,
    )

    elapsed = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"[Scriptwriter EP{ep_num}] {status} in {elapsed:.1f}s")

    if proc.returncode != 0:
        return ep_num, False

    # Run splitter on completed script
    return run_splitter(workspace, ep_num)


def run_splitter(workspace: Path, ep_num: int) -> tuple[int, bool]:
    """Run splitter agent on a completed episode script."""
    prompt_template = (PROMPTS_DIR / "splitter.md").read_text()
    prompt = prompt_template.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))

    print(f"\n[Splitter EP{ep_num}] Starting...")
    t0 = time.time()

    proc = subprocess.run(
        [
            "claude",
            "-p", prompt,
            "--model", MODEL,
            "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep",
        ],
        cwd=str(workspace),
        capture_output=False,
        text=True,
    )

    elapsed = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"[Splitter EP{ep_num}] {status} in {elapsed:.1f}s")

    return ep_num, proc.returncode == 0


# ─── Pipeline Stages ───


def stage_prep(workspace: Path) -> bool:
    """Stage 1: Prep Agent — classify and extract content chapters."""
    prompt = (PROMPTS_DIR / "prep.md").read_text()
    return run_claude(prompt, workspace, "Prep Agent")


def stage_architect(workspace: Path) -> bool:
    """Stage 2: Architect Agent — read all chapters, write overview + episode plans."""
    prompt = (PROMPTS_DIR / "architect.md").read_text()
    return run_claude(prompt, workspace, "Architect Agent")


def stage_enricher(workspace: Path) -> bool:
    """Stage 3: Enricher Agent — enrich episode plans with real-world connections."""
    prompt = (PROMPTS_DIR / "enricher.md").read_text()
    # Enricher needs web access for research
    return run_claude(
        prompt, workspace, "Enricher Agent",
        extra_tools=["WebSearch", "WebFetch"],
    )


def stage_scriptwriters(workspace: Path, max_parallel: int = 3) -> bool:
    """Stage 3: Scriptwriter Agents — parallel, one per episode."""
    # Discover how many episodes were planned
    ep_files = sorted((workspace / "plan" / "episodes").glob("ep_*.md"))
    if not ep_files:
        print("[Scriptwriters] ERROR: No episode plans found!")
        return False

    ep_nums = []
    for f in ep_files:
        # Extract number from ep_01.md, ep_02.md, etc.
        num = int(f.stem.split("_")[1])
        ep_nums.append(num)

    print(f"[Scriptwriters] Found {len(ep_nums)} episodes: {ep_nums}")
    print(f"[Scriptwriters] Running up to {max_parallel} in parallel")

    results = {}
    with ProcessPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(run_scriptwriter, workspace, n): n for n in ep_nums
        }
        for future in as_completed(futures):
            ep_num, success = future.result()
            results[ep_num] = success

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"[Scriptwriters] FAILED episodes: {failed}")
        return False

    print(f"[Scriptwriters] All {len(ep_nums)} episodes completed!")
    return True


# ─── Main ───


def main():
    parser = argparse.ArgumentParser(description="Book-to-Podcast Pipeline")
    parser.add_argument("epub", help="Path to EPUB file")
    parser.add_argument(
        "--parallel", type=int, default=3, help="Max parallel scriptwriters (default: 3)"
    )
    parser.add_argument(
        "--skip-prep", action="store_true", help="Skip prep stage (reuse existing)"
    )
    parser.add_argument(
        "--skip-architect", action="store_true", help="Skip architect stage (reuse existing)"
    )
    parser.add_argument(
        "--skip-enricher", action="store_true", help="Skip enricher stage (reuse existing)"
    )
    parser.add_argument(
        "--only-episode", type=int, help="Only run scriptwriter for this episode"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Extract EPUB and set up workspace only"
    )
    args = parser.parse_args()

    epub_path = Path(args.epub)
    if not epub_path.exists():
        print(f"ERROR: {epub_path} not found")
        sys.exit(1)

    # Extract EPUB
    print(f"Extracting: {epub_path.name}")
    metadata, chapters = extract_epub(str(epub_path))
    print(f"  Title: {metadata['title']}")
    print(f"  Author: {metadata['author']}")
    print(f"  Chapters: {metadata['total_raw_chapters']}")
    print(f"  Chars: {metadata['total_raw_chars']:,}")

    # Setup workspace
    workspace = setup_workspace(metadata, chapters)
    print(f"  Workspace: {workspace}")

    if args.dry_run:
        print("\n[Dry run] Workspace created. Exiting.")
        return

    # Stage 1: Prep
    if not args.skip_prep:
        if not stage_prep(workspace):
            print("\nPREP FAILED. Check log.md and fix before continuing.")
            sys.exit(1)
    else:
        print("\n[Skipping prep stage]")

    # Stage 2: Architect
    if not args.skip_architect:
        if not stage_architect(workspace):
            print("\nARCHITECT FAILED. Check log.md and fix before continuing.")
            sys.exit(1)
    else:
        print("\n[Skipping architect stage]")

    # Stage 3: Enricher
    if not args.skip_enricher:
        if not stage_enricher(workspace):
            print("\nENRICHER FAILED. Check log.md and fix before continuing.")
            sys.exit(1)
    else:
        print("\n[Skipping enricher stage]")

    # Stage 4: Scriptwriters
    if args.only_episode:
        ep, ok = run_scriptwriter(workspace, args.only_episode)
        if not ok:
            sys.exit(1)
    else:
        if not stage_scriptwriters(workspace, max_parallel=args.parallel):
            print("\nSCRIPTWRITERS FAILED. Check log.md for details.")
            sys.exit(1)

    # Done
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"  Workspace: {workspace}")
    print(f"  Scripts: {workspace / 'scripts'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

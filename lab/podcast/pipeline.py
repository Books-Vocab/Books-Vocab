#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
# ]
# ///
"""Book-to-Podcast Pipeline — EPUB → analysis → plan → scripts → audio → subtitles.

Usage:
    # Full pipeline from EPUB
    uv run pipeline.py <book.epub>

    # Resume from workspace (auto-detect)
    uv run pipeline.py workspaces/flow_950f1a7d/

    # Stage control
    uv run pipeline.py <target> --skip-to synthesize
    uv run pipeline.py <target> --stop-after scriptwrite
    uv run pipeline.py <target> --only-stage scriptwrite

    # Episode control
    uv run pipeline.py <target> --only-episode 2
    uv run pipeline.py <target> --parallel 5

    # Inspect
    uv run pipeline.py workspaces/flow_950f1a7d/ --status
    uv run pipeline.py <book.epub> --dry-run

Stages:
    1. prep          — extract + classify chapters
    2. analyst       — deep book analysis
    3. architect     — plan episodes + host design
    4. plan-review   — QA gate on production plan
    5. enricher-gap  — identify research needs
    6. enricher      — web research enrichment
    7. scriptwrite   — parallel dialogue scripts
    8. script-review — QA gate on scripts
    9. synthesize    — Vertex AI Gemini TTS → MP3
   10. subtitle      — Whisper forced alignment → SRT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# Force line-buffered stdout so pipeline progress is visible in real time
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).parent
PROMPTS_DIR = ROOT / "prompts"
WORKSPACES_DIR = ROOT / "workspaces"
_UNBUF_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}
MODEL = "opus[1m]"

STAGES = [
    "prep", "analyst", "architect", "plan-review",
    "enricher-gap", "enricher", "scriptwrite", "script-review",
    "tts-prep",
    "synthesize", "subtitle",
]

# Stage completion markers — written to workspace after each stage succeeds
_STAGE_MARKER = ".stage_{name}_done"


# ─── Logging ───


class PipelineLog:
    """Structured pipeline log — appends to workspace/pipeline_log.jsonl."""

    def __init__(self, workspace: Path):
        self.path = workspace / "pipeline_log.jsonl"
        self.workspace = workspace

    def _write(self, entry: dict) -> None:
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with self.path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def stage_start(self, stage: str, **extra: object) -> None:
        self._write({"event": "stage_start", "stage": stage, **extra})
        print(f"\n{'='*60}")
        print(f"  STAGE: {stage}")
        for k, v in extra.items():
            print(f"  {k}: {v}")
        print(f"  started: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

    def stage_end(self, stage: str, success: bool, elapsed: float, **extra: object) -> None:
        self._write({"event": "stage_end", "stage": stage, "success": success, "elapsed_s": round(elapsed, 1), **extra})
        status = "OK" if success else "FAILED"
        print(f"\n  [{stage}] {status} in {elapsed:.0f}s")
        # Write completion marker
        if success:
            marker = self.workspace / _STAGE_MARKER.format(name=stage)
            marker.write_text(datetime.now().isoformat())

    def event(self, msg: str, **extra: object) -> None:
        self._write({"event": "info", "msg": msg, **extra})
        print(f"  {msg}")

    def error(self, msg: str, **extra: object) -> None:
        self._write({"event": "error", "msg": msg, **extra})
        print(f"  ERROR: {msg}")


# ─── EPUB Extraction ───


def extract_epub(epub_path: str) -> tuple[dict, list[tuple[str, str]]]:
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

    return {
        "title": title, "author": author, "language": lang,
        "total_raw_chapters": len(chapters),
        "total_raw_chars": sum(len(t) for _, t in chapters),
    }, chapters


def setup_workspace(metadata: dict, chapters: list[tuple[str, str]]) -> Path:
    slug = metadata["title"].lower().replace(" ", "_")[:30]
    book_hash = hashlib.md5(
        f"{metadata['title']}_{metadata['author']}".encode()
    ).hexdigest()[:8]
    workspace = WORKSPACES_DIR / f"{slug}_{book_hash}"

    for d in ["source/chapters", "plan/episodes", "scripts", "raw_chapters"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)

    meta_lines = [
        f"# {metadata['title']}",
        f"- **Author**: {metadata['author']}",
        f"- **Language**: {metadata['language']}",
        f"- **Raw chapters**: {metadata['total_raw_chapters']}",
        f"- **Raw chars**: {metadata['total_raw_chars']:,}",
    ]
    (workspace / "source" / "metadata.md").write_text("\n".join(meta_lines))

    for i, (name, text) in enumerate(chapters):
        (workspace / "raw_chapters" / f"raw_ch_{i + 1:02d}.md").write_text(
            f"<!-- source: {name} -->\n\n{text}"
        )

    (workspace / "log.md").write_text(
        f"# Podcast Pipeline Log\n\n"
        f"- Book: {metadata['title']} by {metadata['author']}\n"
        f"- Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    return workspace


def find_workspace(epub_path: Path) -> Path | None:
    if not WORKSPACES_DIR.exists():
        return None
    book = epub.read_epub(str(epub_path))
    title = book.get_metadata("DC", "title")[0][0]
    author = book.get_metadata("DC", "creator")[0][0]
    slug = title.lower().replace(" ", "_")[:30]
    book_hash = hashlib.md5(f"{title}_{author}".encode()).hexdigest()[:8]
    ws = WORKSPACES_DIR / f"{slug}_{book_hash}"
    return ws if ws.exists() else None


# ─── Claude Code Runner ───


def run_claude(
    prompt: str,
    workspace: Path,
    label: str,
    log: PipelineLog,
    extra_tools: list[str] | None = None,
) -> bool:
    prompt = prompt.replace("{workspace}", str(workspace))
    tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    if extra_tools:
        tools.extend(extra_tools)

    cmd = ["claude", "-p", prompt, "--model", MODEL, "--allowedTools", ",".join(tools)]

    log.event(f"claude invocation", tools=tools, model=MODEL, prompt_len=len(prompt))

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(workspace), capture_output=False, text=True, env=_UNBUF_ENV)
    elapsed = time.time() - t0

    success = proc.returncode == 0
    if not success:
        log.error(f"{label} exited with code {proc.returncode}")
    return success


def run_scriptwriter(workspace: Path, ep_num: int) -> tuple[int, bool]:
    prompt_template = (PROMPTS_DIR / "scriptwriter.md").read_text()
    prompt = prompt_template.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))
    prompt += f"\n\nYou are writing Episode {ep_num}. Read the overview, then your episode plan at plan/episodes/ep_{ep_num:02d}.md, then the source chapters listed in it."

    print(f"\n  [Scriptwriter EP{ep_num}] Starting...")
    t0 = time.time()
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL, "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep"],
        cwd=str(workspace), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    elapsed = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"  [Scriptwriter EP{ep_num}] {status} in {elapsed:.1f}s")
    return ep_num, proc.returncode == 0


def run_script_reviewer(workspace: Path, ep_num: int) -> tuple[int, bool]:
    prompt_template = (PROMPTS_DIR / "script_review.md").read_text()
    prompt = prompt_template.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))
    prompt += f"\n\nReview Episode {ep_num}. Read overview.md, then ep_{ep_num:02d}.md plan, then ep_{ep_num}_script.md."

    print(f"\n  [Script Review EP{ep_num}] Starting...")
    t0 = time.time()
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL, "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep"],
        cwd=str(workspace), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    elapsed = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"  [Script Review EP{ep_num}] {status} in {elapsed:.1f}s")
    return ep_num, proc.returncode == 0


# ─── Stage Completion Detection ───


def stage_done(workspace: Path, stage: str) -> bool:
    """Check if a stage has a completion marker."""
    return (workspace / _STAGE_MARKER.format(name=stage)).exists()


def detect_resume_point(workspace: Path) -> int:
    """Find the first incomplete stage index."""
    for i, stage in enumerate(STAGES):
        if not stage_done(workspace, stage):
            return i
    return len(STAGES)  # all done


# ─── Pipeline Stages ───


def stage_prep(workspace: Path, log: PipelineLog) -> bool:
    return run_claude((PROMPTS_DIR / "prep.md").read_text(), workspace, "Prep", log)


def stage_analyst(workspace: Path, log: PipelineLog) -> bool:
    return run_claude((PROMPTS_DIR / "analyst.md").read_text(), workspace, "Analyst", log)


def stage_architect(workspace: Path, log: PipelineLog) -> bool:
    return run_claude((PROMPTS_DIR / "architect.md").read_text(), workspace, "Architect", log)


def stage_plan_review(workspace: Path, log: PipelineLog) -> bool:
    ok = run_claude((PROMPTS_DIR / "plan_review.md").read_text(), workspace, "Plan Review", log)
    if not ok:
        return False

    # Check review result
    review_file = workspace / "plan" / "review.md"
    if not review_file.exists():
        log.error("Plan review did not produce review.md")
        return False

    content = review_file.read_text()
    if "REWRITE_NEEDED" in content or content.count("FAIL") > 2:
        log.error("Plan review found critical issues — manual intervention needed")
        log.event("Review saved to plan/review.md — read it, fix issues, then resume with --skip-to plan-review")
        return False

    log.event("Plan review passed")
    return True


def stage_enricher_gap(workspace: Path, log: PipelineLog) -> bool:
    return run_claude((PROMPTS_DIR / "enricher_gap.md").read_text(), workspace, "Enricher Gap", log)


def stage_enricher(workspace: Path, log: PipelineLog) -> bool:
    return run_claude(
        (PROMPTS_DIR / "enricher.md").read_text(), workspace, "Enricher", log,
        extra_tools=["WebSearch", "WebFetch"],
    )


def stage_scriptwriters(workspace: Path, log: PipelineLog, max_parallel: int = 3, only_episode: int | None = None) -> bool:
    if only_episode:
        _, ok = run_scriptwriter(workspace, only_episode)
        return ok

    ep_files = sorted((workspace / "plan" / "episodes").glob("ep_*.md"))
    if not ep_files:
        log.error("No episode plans found")
        return False

    ep_nums = [int(f.stem.split("_")[1]) for f in ep_files]
    existing = {int(f.stem.split("_")[1]) for f in (workspace / "scripts").glob("ep_*_script.md")}
    todo = [n for n in ep_nums if n not in existing]

    if not todo:
        log.event(f"All {len(ep_nums)} episodes already have scripts — skipping")
        return True

    log.event(f"{len(todo)} episodes to write: {todo} (existing: {sorted(existing)})")
    log.event(f"Parallel workers: {max_parallel}")

    results = {}
    with ProcessPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(run_scriptwriter, workspace, n): n for n in todo}
        for future in as_completed(futures):
            ep_num, success = future.result()
            results[ep_num] = success

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        log.error(f"Failed episodes: {failed}")
        return False

    log.event(f"All {len(todo)} episodes scripted")
    return True


def stage_script_review(workspace: Path, log: PipelineLog, max_parallel: int = 3, only_episode: int | None = None) -> bool:
    if only_episode:
        _, ok = run_script_reviewer(workspace, only_episode)
        return ok

    script_files = sorted((workspace / "scripts").glob("ep_*_script.md"))
    if not script_files:
        log.error("No scripts found to review")
        return False

    ep_nums = [int(f.stem.split("_")[1]) for f in script_files]
    # Skip episodes that already have reviews
    existing = {int(re.search(r"ep_(\d+)", f.stem).group(1)) for f in (workspace / "scripts").glob("ep_*_review.md")}
    todo = [n for n in ep_nums if n not in existing]

    if not todo:
        log.event(f"All {len(ep_nums)} scripts already reviewed — skipping")
        return True

    log.event(f"{len(todo)} scripts to review: {todo}")

    results = {}
    with ProcessPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(run_script_reviewer, workspace, n): n for n in todo}
        for future in as_completed(futures):
            ep_num, success = future.result()
            results[ep_num] = success

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        log.error(f"Script review failed for episodes: {failed}")
        return False

    # Check for REWRITE_NEEDED verdicts
    rewrite_needed = []
    for n in todo:
        review_file = workspace / "scripts" / f"ep_{n}_review.md"
        if review_file.exists() and "REWRITE_NEEDED" in review_file.read_text():
            rewrite_needed.append(n)

    if rewrite_needed:
        log.error(f"Episodes needing rewrite: {rewrite_needed} — check scripts/ep_N_review.md for details")
        return False

    log.event(f"All {len(todo)} scripts passed review")
    return True


def stage_tts_prep(workspace: Path, log: PipelineLog) -> bool:
    ok = run_claude((PROMPTS_DIR / "tts_prep.md").read_text(), workspace, "TTS Prep", log)
    if not ok:
        return False

    report = workspace / "plan" / "tts_prep.md"
    if not report.exists():
        log.error("TTS prep did not produce plan/tts_prep.md")
        return False

    content = report.read_text()
    if "BLOCKED" in content:
        log.error("TTS prep reported BLOCKED — read plan/tts_prep.md, fix issues, then resume with --skip-to tts-prep")
        return False

    if "READY_FOR_TTS" not in content:
        log.error("TTS prep report missing explicit READY_FOR_TTS verdict")
        return False

    log.event("TTS prep passed — scripts ready for synthesis")
    return True


def stage_synthesize(workspace: Path, log: PipelineLog, only_episode: int | None = None) -> bool:
    scripts_dir = workspace / "scripts"
    target = scripts_dir / f"ep_{only_episode}_script.md" if only_episode else scripts_dir

    proc = subprocess.run(
        ["uv", "run", str(ROOT / "synthesize.py"), str(target)],
        cwd=str(ROOT), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    return proc.returncode == 0


def stage_subtitle(workspace: Path, log: PipelineLog, only_episode: int | None = None) -> bool:
    scripts_dir = workspace / "scripts"
    target = scripts_dir / f"ep_{only_episode}_script.md" if only_episode else scripts_dir

    proc = subprocess.run(
        ["uv", "run", str(ROOT / "subtitle.py"), str(target)],
        cwd=str(ROOT), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    return proc.returncode == 0


# ─── Status ───


def show_status(workspace: Path) -> None:
    print(f"\n{'='*60}")
    print(f"  WORKSPACE: {workspace.name}")
    print(f"{'='*60}")

    # Metadata
    meta_file = workspace / "source" / "metadata.md"
    if meta_file.exists():
        for line in meta_file.read_text().splitlines()[:5]:
            print(f"  {line}")

    # Stage markers
    print(f"\n  Stage Progress:")
    for stage in STAGES:
        marker = workspace / _STAGE_MARKER.format(name=stage)
        if marker.exists():
            ts = marker.read_text().strip()
            print(f"    ✓ {stage:<15} ({ts})")
        else:
            print(f"    · {stage}")

    # File counts
    raw = sorted((workspace / "raw_chapters").glob("raw_ch_*.md"))
    clean = sorted((workspace / "source" / "chapters").glob("ch_*.md"))
    analysis = workspace / "plan" / "analysis.md"
    overview = workspace / "plan" / "overview.md"
    ep_plans = sorted((workspace / "plan" / "episodes").glob("ep_*.md"))
    research = workspace / "plan" / "research_brief.md"
    review = workspace / "plan" / "review.md"

    print(f"\n  Files:")
    print(f"    Raw chapters:    {len(raw)}")
    print(f"    Clean chapters:  {len(clean)}")
    print(f"    Analysis:        {'✓' if analysis.exists() else '·'}")
    print(f"    Overview:        {'✓' if overview.exists() else '·'}")
    print(f"    Episode plans:   {len(ep_plans)}")
    print(f"    Plan review:     {'✓' if review.exists() else '·'}")
    print(f"    Research brief:  {'✓' if research.exists() else '·'}")

    # Per-episode status
    if ep_plans:
        ep_nums = sorted(int(f.stem.split("_")[1]) for f in ep_plans)
        print(f"\n  {'EP':<4} {'script':<8} {'review':<10} {'mp3':<22} {'srt':<12}")
        print(f"  {'─'*4} {'─'*7} {'─'*9} {'─'*21} {'─'*11}")

        for n in ep_nums:
            script_f = workspace / "scripts" / f"ep_{n}_script.md"
            script = "✓" if script_f.exists() else "·"

            review_f = workspace / "scripts" / f"ep_{n}_review.md"
            if review_f.exists():
                content = review_f.read_text()
                if "REWRITE_NEEDED" in content:
                    rev = "✗ REWRITE"
                elif "PASS_WITH_FIXES" in content:
                    rev = "✓ fixed"
                else:
                    rev = "✓"
            else:
                rev = "·"

            mp3_files = list((workspace / "scripts").glob(f"ep_{n}_*.mp3"))
            if mp3_files:
                f = mp3_files[0]
                size_mb = f.stat().st_size / (1024 * 1024)
                mp3 = f"✓ {f.name} ({size_mb:.1f}MB)"
            else:
                mp3 = "·"

            srt_files = list((workspace / "scripts").glob(f"ep_{n}_*.srt"))
            srt = f"✓ ({srt_files[0].stat().st_size / 1024:.0f}KB)" if srt_files else "·"

            print(f"  {n:<4} {script:<8} {rev:<10} {mp3:<22} {srt:<12}")

    # Pipeline log summary
    log_file = workspace / "pipeline_log.jsonl"
    if log_file.exists():
        lines = log_file.read_text().strip().splitlines()
        errors = [json.loads(l) for l in lines if '"error"' in l]
        if errors:
            print(f"\n  Recent Errors ({len(errors)}):")
            for e in errors[-5:]:
                print(f"    [{e.get('ts', '?')}] {e.get('msg', '?')}")

    # Suggest next action + quick reference
    ws = workspace
    resume = detect_resume_point(workspace)

    print(f"\n  ── Quick Actions ──")
    if resume < len(STAGES):
        print(f"  Resume:          uv run pipeline.py {ws}")
        print(f"  Resume from:     uv run pipeline.py {ws} --skip-to {STAGES[resume]}")
    else:
        print(f"  ✓ All stages complete!")

    print(f"\n  ── Stage Control ──")
    print(f"  Run one stage:   uv run pipeline.py {ws} --only-stage <stage>")
    print(f"  Run until:       uv run pipeline.py {ws} --stop-after <stage>")
    print(f"  Run from:        uv run pipeline.py {ws} --skip-to <stage>")
    print(f"  Single episode:  uv run pipeline.py {ws} --only-stage scriptwrite --only-episode 3")
    print(f"  Parallel:        uv run pipeline.py {ws} --parallel 5")

    print(f"\n  ── Stages ──")
    for i, s in enumerate(STAGES, 1):
        print(f"  {i:>2}. {s}")

    print(f"\n  ── Debug ──")
    print(f"  Full log:        cat {ws}/pipeline_log.jsonl | python -m json.tool")
    print(f"  Errors only:     grep '\"error\"' {ws}/pipeline_log.jsonl")
    if (workspace / "plan" / "review.md").exists():
        print(f"  Plan review:     cat {ws}/plan/review.md")
    review_files = sorted((workspace / "scripts").glob("ep_*_review.md"))
    if review_files:
        print(f"  Script reviews:  ls {ws}/scripts/ep_*_review.md")

    print(f"{'='*60}")


# ─── Target Resolution ───


def resolve_target(target_str: str) -> tuple[Path | None, Path | None]:
    target = Path(target_str)
    if not target.exists():
        print(f"ERROR: {target} not found")
        sys.exit(1)

    if target.is_dir() and (target / "log.md").exists():
        return None, target

    if target.is_file() and target.suffix.lower() == ".epub":
        return target, None

    print(f"ERROR: {target} is neither an EPUB file nor a workspace directory")
    sys.exit(1)


# ─── Main ───


def main():
    parser = argparse.ArgumentParser(
        description="Book-to-Podcast Pipeline: EPUB → analysis → plan → scripts → audio → subtitles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""stages (in order):
   1. prep          extract + classify chapters from EPUB
   2. analyst       deep book analysis (structure, arguments, quotes)
   3. architect     production plan (episodes, hosts, pacing)
   4. plan-review   QA gate — verify plan completeness
   5. enricher-gap  identify where external research is needed
   6. enricher      web search to fill research gaps
   7. scriptwrite   parallel dialogue script generation
   8. script-review QA gate — verify script quality
   9. synthesize    TTS audio generation (Vertex AI Gemini)
  10. subtitle      word-level subtitle alignment (Whisper)

examples:
  uv run pipeline.py book.epub                          # full pipeline
  uv run pipeline.py workspaces/my_book/                # auto-resume
  uv run pipeline.py workspaces/my_book/ --status       # show progress + commands

  # stage control
  uv run pipeline.py ws/ --skip-to enricher             # start from enricher
  uv run pipeline.py ws/ --stop-after architect          # stop after architect
  uv run pipeline.py ws/ --only-stage scriptwrite        # run exactly one stage

  # episode control
  uv run pipeline.py ws/ --only-stage scriptwrite --only-episode 4
  uv run pipeline.py ws/ --parallel 5                    # 5 parallel writers

  # individual tools
  uv run synthesize.py ws/scripts/ep_1_script.md         # TTS one episode
  uv run subtitle.py ws/scripts/                         # subtitles for all
  uv run preview.py ws/scripts/ep_1_pro.mp3              # play audio""",
    )
    parser.add_argument("target", help="Path to EPUB file or workspace directory")
    parser.add_argument("--parallel", type=int, default=3, help="Max parallel workers (default: 3)")
    parser.add_argument("--only-episode", type=int, help="Only process this episode number")
    parser.add_argument("--skip-to", choices=STAGES, help="Start from this stage")
    parser.add_argument("--stop-after", choices=STAGES, help="Stop after this stage")
    parser.add_argument("--only-stage", choices=STAGES, help="Run exactly one stage")
    parser.add_argument("--status", action="store_true", help="Show workspace status and exit")
    parser.add_argument("--dry-run", action="store_true", help="Extract EPUB and setup workspace only")
    args = parser.parse_args()

    if args.only_stage:
        if args.skip_to or args.stop_after:
            parser.error("--only-stage cannot be combined with --skip-to or --stop-after")
        args.skip_to = args.only_stage
        args.stop_after = args.only_stage

    epub_path, workspace = resolve_target(args.target)

    if args.status:
        if workspace:
            show_status(workspace)
        elif epub_path:
            ws = find_workspace(epub_path)
            if ws:
                show_status(ws)
            else:
                print("No workspace found for this EPUB.")
        return

    # Determine stage range
    start_idx = STAGES.index(args.skip_to) if args.skip_to else 0
    stop_idx = STAGES.index(args.stop_after) if args.stop_after else len(STAGES) - 1

    if start_idx > stop_idx:
        parser.error(f"--skip-to {args.skip_to} is after --stop-after {args.stop_after}")

    # Resolve workspace
    if workspace:
        if not args.skip_to:
            resume = detect_resume_point(workspace)
            if resume > 0:
                start_idx = max(start_idx, resume)
                print(f"Auto-resume: {STAGES[start_idx]} (stages 0-{resume-1} have completion markers)")
        print(f"Workspace: {workspace}")
    elif epub_path:
        if start_idx > 0:
            workspace = find_workspace(epub_path)
            if not workspace:
                print("ERROR: No existing workspace found. Run without --skip-to first.")
                sys.exit(1)
            print(f"Resuming: {workspace}")
        else:
            print(f"Extracting: {epub_path.name}")
            metadata, chapters = extract_epub(str(epub_path))
            print(f"  Title:    {metadata['title']}")
            print(f"  Author:   {metadata['author']}")
            print(f"  Chapters: {metadata['total_raw_chapters']}")
            print(f"  Chars:    {metadata['total_raw_chars']:,}")
            workspace = setup_workspace(metadata, chapters)
            print(f"  Workspace: {workspace}")

    if args.dry_run:
        print("\n[Dry run] Workspace created.")
        show_status(workspace)
        return

    log = PipelineLog(workspace)
    t0 = time.time()

    # Build stage dispatch table
    stage_funcs = {
        "prep": lambda: stage_prep(workspace, log),
        "analyst": lambda: stage_analyst(workspace, log),
        "architect": lambda: stage_architect(workspace, log),
        "plan-review": lambda: stage_plan_review(workspace, log),
        "enricher-gap": lambda: stage_enricher_gap(workspace, log),
        "enricher": lambda: stage_enricher(workspace, log),
        "scriptwrite": lambda: stage_scriptwriters(workspace, log, args.parallel, args.only_episode),
        "script-review": lambda: stage_script_review(workspace, log, args.parallel, args.only_episode),
        "tts-prep": lambda: stage_tts_prep(workspace, log),
        "synthesize": lambda: stage_synthesize(workspace, log, args.only_episode),
        "subtitle": lambda: stage_subtitle(workspace, log, args.only_episode),
    }

    stages_to_run = STAGES[start_idx:stop_idx + 1]
    total_stages = len(stages_to_run)

    print(f"\nPlan: {' → '.join(stages_to_run)}")
    if args.only_episode:
        print(f"Episode filter: {args.only_episode}")
    print()

    for i, stage_name in enumerate(stages_to_run, 1):
        stage_t0 = time.time()
        log.stage_start(stage_name, step=f"{i}/{total_stages}")

        if not stage_funcs[stage_name]():
            elapsed = time.time() - t0
            log.stage_end(stage_name, success=False, elapsed=time.time() - stage_t0)
            print(f"\n{'='*60}")
            print(f"  PIPELINE FAILED at: {stage_name} ({elapsed:.0f}s total)")
            print(f"  Workspace: {workspace}")
            print(f"  Resume: uv run pipeline.py {workspace} --skip-to {stage_name}")
            print(f"  Debug: cat {workspace}/pipeline_log.jsonl | python -m json.tool")
            print(f"{'='*60}")
            sys.exit(1)

        log.stage_end(stage_name, success=True, elapsed=time.time() - stage_t0)

    elapsed = time.time() - t0

    # Final summary
    mp3s = sorted((workspace / "scripts").glob("*.mp3"))
    srts = sorted((workspace / "scripts").glob("*.srt"))
    total_audio_mb = sum(f.stat().st_size for f in mp3s) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE — {elapsed:.0f}s")
    print(f"  Stages: {' → '.join(stages_to_run)}")
    print(f"  Workspace: {workspace}")
    if mp3s:
        print(f"  Audio: {len(mp3s)} files, {total_audio_mb:.1f} MB")
        for f in mp3s:
            print(f"    {f.name} ({f.stat().st_size / (1024 * 1024):.1f} MB)")
    if srts:
        print(f"  Subtitles: {len(srts)} files")

    if stop_idx < len(STAGES) - 1:
        print(f"\n  Next: uv run pipeline.py {workspace} --skip-to {STAGES[stop_idx + 1]}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()

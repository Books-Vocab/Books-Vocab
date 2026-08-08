#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "boto3",
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

Stages (v1 baseline; runtime order comes from workflow_versions/<v>/workflow.json):
    1.  prep           — extract + classify chapters
    2.  analyst        — deep book analysis
    3.  architect      — plan episodes + host design
    4.  plan-review    — QA gate on production plan
    5.  enricher-gap   — identify research needs
    6.  enricher       — web research enrichment
    7.  scriptwrite    — parallel dialogue scripts
    8.  series-polish  — cross-episode callbacks / running bits / persona drift
    9.  script-review  — QA gate on scripts
    10. tts-prep       — pick voice pair + fix parse-breaks + resolve (TBD)
    11. synthesize     — Vertex AI Gemini TTS → MP3 (loudnorm mastering)
    12. audio-qa       — wpm / silence / clipping checks (hard gate)
    13. subtitle       — Whisper forced alignment → word-level SRT
    14. cover          — generate series cover art
    15. publish        — upload workspace → S3 + verify live in catalog index
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# Force line-buffered stdout so pipeline progress is visible in real time
sys.stdout.reconfigure(line_buffering=True)

import archetypes
import saga
import tts_tags
from tts_config import (
    ALLOWED_TTS_MODELS,
    DEFAULT_TTS_MODEL,
    sanitize_slug as _sanitize_slug,
    tts_family,
)

ROOT = Path(__file__).parent
_LOGGER = logging.getLogger("podcast.pipeline")
PROMPTS_DIR = ROOT / "prompts"
WORKFLOW_VERSIONS_DIR = ROOT / "workflow_versions"
WORKSPACES_DIR = ROOT / "workspaces"
DEFAULT_WORKFLOW_VERSION = "v1"
WORKFLOW_MANIFEST = "workflow_manifest.json"
STAGE_PROVENANCE_DIR = "stage_provenance"
# Stage 1-10 agent runner profile → its default model. Single source of truth
# for the CLI choices and the monitor allowlist; add a key here to plug in
# another billing backend (it must speak the Anthropic-compatible CLI contract).
_PROFILE_DEFAULT_MODEL = {"claude": "opus[1m]"}
AGENT_PROFILES = tuple(_PROFILE_DEFAULT_MODEL)


def _normalize_agent_profile(profile: str | None) -> str:
    value = (profile or os.getenv("PODCAST_AGENT_PROFILE") or "claude").strip().lower()
    if value not in AGENT_PROFILES:
        raise ValueError(f"unknown agent profile {value!r}; allowed: {', '.join(AGENT_PROFILES)}")
    return value


def _resolve_agent_model(profile: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_model = os.getenv("PODCAST_AGENT_MODEL", "").strip()
    if env_model:
        return env_model
    # Backward compatibility for existing scripts.
    legacy = os.getenv("PODCAST_CLAUDE_MODEL", "").strip()
    if legacy:
        return legacy
    # Default opus[1m] is intentional: pipeline agents (scriptwriter / enricher /
    # series-polish) reason over multi-chapter context and benefit from 1M window.
    return _PROFILE_DEFAULT_MODEL[profile]


AGENT_PROFILE = _normalize_agent_profile(None)
MODEL = _resolve_agent_model(AGENT_PROFILE)


def configure_agent(profile: str | None = None, model: str | None = None) -> None:
    """Configure the process-wide stage-agent runner.

    Also mirrors the resolved values into os.environ so ProcessPoolExecutor
    workers spawned for parallel scriptwrite/script-review inherit the same
    profile even when the platform starts fresh Python interpreters.
    """
    global AGENT_PROFILE, MODEL
    AGENT_PROFILE = _normalize_agent_profile(profile)
    MODEL = _resolve_agent_model(AGENT_PROFILE, model)
    os.environ["PODCAST_AGENT_PROFILE"] = AGENT_PROFILE
    os.environ["PODCAST_AGENT_MODEL"] = MODEL


def _agent_subprocess_env() -> dict[str, str]:
    # The claude profile inherits the user's own Claude Code auth — no endpoint
    # or token injection. A future third-party profile would add it here.
    return {**os.environ, "PYTHONUNBUFFERED": "1"}


# Stream claude CLI tool-use events live via stream-json. Default ON so the
# dashboard has cost data. Set PODCAST_VERBOSE=0 to opt out (smaller log files,
# but loses per-stage cost tracking + tool-use feed in dashboard).
_STREAM_JSON = os.getenv("PODCAST_VERBOSE", "1") != "0"
_VERBOSE_FLAGS = ["--output-format", "stream-json", "--verbose"] if _STREAM_JSON else []
_UNBUF_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}

# Dashboard auto-launch — single-command UX. Set PODCAST_NO_DASHBOARD=1 to skip.
_DASHBOARD_ENABLED = os.getenv("PODCAST_NO_DASHBOARD", "0") != "1"
_DASHBOARD_PORT = int(os.getenv("PODCAST_DASHBOARD_PORT", "8765"))


def _ensure_dashboard_running(workspace: Path | None = None) -> str | None:
    """Idempotent: start ./start.sh if monitor isn't already up on the port,
    then open the user's browser to the workspace's dashboard view. Returns
    the dashboard URL (or None if disabled / startup failed).

    Why here: pipelines are long-running. Forcing two terminals (one for
    dashboard, one for pipeline) is the obvious friction point. The dashboard
    is just an idempotent localhost server; starting it on demand from the
    pipeline keeps a single-command flow without any orchestration layer.
    """
    if not _DASHBOARD_ENABLED:
        return None

    import socket
    import webbrowser

    # 1. Probe if dashboard is already up on the port (cheap TCP check).
    def _port_alive() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            try:
                s.connect(("127.0.0.1", _DASHBOARD_PORT))
                return True
            except OSError as exc:
                _LOGGER.debug("dashboard port probe failed for %s: %s", _DASHBOARD_PORT, exc)
                return False

    if not _port_alive():
        start_sh = ROOT / "start.sh"
        if not start_sh.exists():
            print(f"[dashboard] {start_sh} missing — skipping auto-start")
            return None
        print(f"[dashboard] starting monitor on :{_DASHBOARD_PORT} ...")
        # Pass --bg so start.sh nohup-detaches uvicorn and returns the readiness
        # banner. Default start.sh mode is now foreground (humans want to see
        # the logs); the pipeline auto-launch path needs the legacy detach.
        try:
            subprocess.run(
                ["bash", str(start_sh), "--bg", str(_DASHBOARD_PORT)],
                cwd=str(ROOT), check=False, timeout=15,
            )
        except subprocess.TimeoutExpired:
            print("[dashboard] start.sh timed out — check monitor.log")
            return None

    # 2. Open browser. Browsers dedupe to existing tab if URL matches.
    url = f"http://127.0.0.1:{_DASHBOARD_PORT}/"
    if workspace:
        url += f"?ws={workspace.name}"
    print(f"[dashboard] {url}")
    try:
        webbrowser.open(url)
    except Exception as exc:
        # Keep URL as fallback path for manual open, but record reason.
        print(f"[pipeline] failed to open dashboard URL automatically: {exc}", file=sys.stderr)
    return url

# Authoritative stage order. When changing this list, also update the module
# docstring stage list above and `.claude/skills/podcast/SKILL.md` §管線總覽.
STAGES = [
    "prep", "analyst", "architect", "plan-review",
    "enricher-gap", "enricher", "scriptwrite",
    "series-polish",
    "script-review",
    "tts-prep",
    "synthesize", "audio-qa", "subtitle",
    "cover",
    "publish",
]

# Stage completion markers — written to workspace after each stage succeeds
_STAGE_MARKER = ".stage_{name}_done"

# Series-wide stages that ignore --only-episode: series-polish LLM-rewrites ALL
# episode scripts, publish re-publishes the whole series. A bare full-loop
# `pipeline.py <ws> --only-episode N` (producer patching one episode) must NOT
# trigger either — wrong semantics + wasted cost. They still run when the
# producer EXPLICITLY drives them via --only-stage (a deliberate full-series op).
_SERIES_WIDE_STAGES = {"series-polish", "cover", "publish"}


def _should_skip_for_only_episode(stage_name: str, args) -> bool:
    """True iff `stage_name` is a series-wide stage that must be skipped because
    the run is filtered to a single episode via a bare full loop.

    Skip only when --only-episode is set AND the stage was not explicitly
    selected via --only-stage. `--only-stage series-polish/publish` is the
    producer's deliberate full-series drive → never skipped.
    """
    return (
        bool(args.only_episode)
        and stage_name in _SERIES_WIDE_STAGES
        and args.only_stage != stage_name
    )

# ─── Archetype prompt resolution + mode sidecars ────────────────────────────
# An archetype selects a prompt SET via filename suffix. `_prompt` returns the
# variant `<name>_<suffix>.md` when it exists, else the base `<name>.md`. So an
# archetype only forks the stages it ships a variant for, and the default
# nonfiction archetype (suffix=None) provably always uses the base prompt.
_MODE_SIDECAR = ".mode"
_SPOILER_SIDECAR = ".spoiler_mode"
# TTS model is frozen at workspace creation and read back by stage_synthesize —
# the single restore point so every spawn path (/start, /resume, /approve, manual
# `--skip-to synthesize`) injects the same TTS_MODEL. The family marker records
# which TTS family scriptwrite authored for, so a cross-family synth is loud.
_TTS_MODEL_SIDECAR = ".tts_model"
_SCRIPT_TTS_FAMILY_SIDECAR = ".script_tts_family"
_AGENT_PROFILE_SIDECAR = ".agent_profile"
_AGENT_MODEL_SIDECAR = ".agent_model"


def available_workflow_versions() -> list[str]:
    if not WORKFLOW_VERSIONS_DIR.exists():
        return []
    return sorted(
        p.name for p in WORKFLOW_VERSIONS_DIR.iterdir()
        if p.is_dir() and (p / "workflow.json").is_file()
    )


def load_workflow_definition(workflow_version: str) -> dict:
    workflow_file = WORKFLOW_VERSIONS_DIR / workflow_version / "workflow.json"
    if not workflow_file.is_file():
        raise ValueError(f"unknown workflow version {workflow_version!r}")
    data = json.loads(workflow_file.read_text())
    if data.get("workflow_version") != workflow_version:
        raise ValueError(f"{workflow_file} workflow_version mismatch")
    return data


def workflow_stage_order(workflow_version: str) -> list[str]:
    stages = load_workflow_definition(workflow_version).get("stage_order")
    if not isinstance(stages, list) or not stages or not all(isinstance(s, str) for s in stages):
        raise ValueError(f"workflow {workflow_version!r} has invalid stage_order")
    return stages


def all_workflow_stage_names() -> list[str]:
    names: set[str] = set(STAGES)
    for version in available_workflow_versions():
        names.update(workflow_stage_order(version))
    return sorted(names, key=lambda s: (STAGES.index(s) if s in STAGES else 10_000, s))


def _workflow_prompt_dir(workflow_version: str) -> Path:
    workflow = load_workflow_definition(workflow_version)
    return WORKFLOW_VERSIONS_DIR / workflow_version / workflow.get("prompt_dir", "prompts")


def prompt_path(name: str, archetype: str, workflow_version: str) -> Path:
    """Resolve a stage prompt for an archetype within a versioned snapshot."""
    suffix = archetypes.get(archetype)["suffix"]
    # Tests and ad hoc tools historically monkeypatch PROMPTS_DIR to exercise
    # archetype resolution without materializing workflow_versions. Preserve
    # that override; production keeps PROMPTS_DIR at ROOT/prompts and uses the
    # versioned snapshot.
    prompt_dir = PROMPTS_DIR if PROMPTS_DIR != ROOT / "prompts" else _workflow_prompt_dir(workflow_version)
    if suffix:
        variant = prompt_dir / f"{name}_{suffix}.md"
        if variant.exists():
            return variant
    return prompt_dir / f"{name}.md"


def prompt_text(name: str, archetype: str, workflow_version: str) -> str:
    return prompt_path(name, archetype, workflow_version).read_text()


def active_workflow_version() -> str:
    return os.getenv("PODCAST_WORKFLOW_VERSION", DEFAULT_WORKFLOW_VERSION)


def configure_workflow(workflow_version: str) -> None:
    load_workflow_definition(workflow_version)
    os.environ["PODCAST_WORKFLOW_VERSION"] = workflow_version


def _prompt(name: str, archetype: str) -> str:
    return prompt_text(name, archetype, active_workflow_version())


def read_workflow_manifest(workspace: Path) -> dict | None:
    manifest = workspace / WORKFLOW_MANIFEST
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"{manifest} is not valid JSON: {e}") from e


def resolve_workspace_workflow(workspace: Path, requested: str | None) -> str:
    manifest = read_workflow_manifest(workspace)
    saved = manifest.get("workflow_version") if manifest else None
    if saved:
        load_workflow_definition(str(saved))
        if requested and requested != saved:
            raise ValueError(
                f"workspace was created with workflow_version {saved}; "
                f"cannot resume as {requested}"
            )
        return str(saved)
    version = requested or DEFAULT_WORKFLOW_VERSION
    load_workflow_definition(version)
    return version


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _prompt_fingerprints(workflow_version: str) -> dict[str, str]:
    prompt_dir = _workflow_prompt_dir(workflow_version)
    return {
        str(p.relative_to(WORKFLOW_VERSIONS_DIR / workflow_version)): _sha256_file(p)
        for p in sorted(prompt_dir.glob("*.md"))
    }


def _pipeline_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT.parent.parent),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _LOGGER.warning("cannot resolve git commit from repo root: %s", exc)
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def write_workflow_manifest(
    workspace: Path,
    *,
    workflow_version: str,
    agent_profile: str,
    agent_model: str,
    tts_model: str,
) -> dict:
    workflow = load_workflow_definition(workflow_version)
    existing = read_workflow_manifest(workspace) or {}
    if existing.get("workflow_version") and existing.get("pipeline_commit") and existing.get("prompt_fingerprints"):
        if existing["workflow_version"] != workflow_version:
            raise ValueError(
                f"workspace was created with workflow_version {existing['workflow_version']}; "
                f"cannot rewrite manifest as {workflow_version}"
            )
        return existing
    created_at = existing.get("created_at") or datetime.now().isoformat(timespec="seconds")
    manifest = {
        "workflow_version": workflow_version,
        "pipeline_commit": _pipeline_commit(),
        "prompt_fingerprints": _prompt_fingerprints(workflow_version),
        "agent_profile": agent_profile,
        "agent_model": agent_model,
        "tts_model": tts_model,
        "validator_versions": workflow.get("validator_versions", {}),
        "stage_contracts": {
            "stage_order": workflow.get("stage_order", STAGES),
            "qa_thresholds": workflow.get("qa_thresholds", {}),
            "tts_policy": workflow.get("tts_policy", {}),
            "cover_policy": workflow.get("cover_policy", {}),
        },
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (workspace / WORKFLOW_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def write_mode_sidecar(workspace: Path, archetype: str, spoiler_mode: str | None) -> None:
    """Persist the production mode so resume re-reads it (never trusts argv)."""
    (workspace / _MODE_SIDECAR).write_text(archetype)
    sp = workspace / _SPOILER_SIDECAR
    if spoiler_mode:
        sp.write_text(spoiler_mode)
    elif sp.exists():
        sp.unlink()  # clearing a previously-set mode (e.g. mode change on resume)


def read_mode(workspace: Path) -> str:
    """Read the archetype sidecar; legacy workspaces with none → nonfiction."""
    f = workspace / _MODE_SIDECAR
    return f.read_text().strip() if f.exists() else archetypes.DEFAULT_ARCHETYPE


def read_spoiler_mode(workspace: Path) -> str | None:
    f = workspace / _SPOILER_SIDECAR
    return f.read_text().strip() if f.exists() else None


def read_tts_model(workspace: Path) -> str | None:
    """Read the frozen TTS model sidecar; None → synthesize.py's env default."""
    f = workspace / _TTS_MODEL_SIDECAR
    return f.read_text().strip() if f.exists() else None


def read_agent_sidecars(workspace: Path) -> tuple[str | None, str | None]:
    profile_f = workspace / _AGENT_PROFILE_SIDECAR
    model_f = workspace / _AGENT_MODEL_SIDECAR
    profile = profile_f.read_text().strip() if profile_f.exists() else None
    model = model_f.read_text().strip() if model_f.exists() else None
    return profile or None, model or None


def write_agent_sidecars(workspace: Path) -> None:
    (workspace / _AGENT_PROFILE_SIDECAR).write_text(AGENT_PROFILE)
    (workspace / _AGENT_MODEL_SIDECAR).write_text(MODEL)


def resolve_tts_family(workspace: Path) -> str:
    """The TTS family the scripts will actually be synthesized on.

    Mirrors stage_synthesize's model resolution (sidecar → env default) so the
    authoring/review/prep prompts get the palette for the SAME family that synth
    will use. No sidecar → DEFAULT_TTS_MODEL (the env/.env default lives there).
    """
    return tts_family(read_tts_model(workspace) or DEFAULT_TTS_MODEL)


def inject_tts_palette(prompt: str, workspace: Path) -> str:
    """Fill {tts_family}/{tts_engine}/{tts_palette} for the synthesis family.

    Loud-fail on a family with no registered palette: authoring a script for a
    family we cannot render tags for would silently ship mis-tagged audio. The
    fix is to register the family in tts_tags.TAG_CONCEPTS, not to guess.
    """
    fam = resolve_tts_family(workspace)
    if fam not in tts_tags.KNOWN_FAMILIES:
        raise RuntimeError(
            f"No audio-tag palette registered for TTS family {fam!r} "
            f"(model {read_tts_model(workspace) or DEFAULT_TTS_MODEL}). "
            f"Add it to tts_tags.TAG_CONCEPTS before authoring."
        )
    return (
        prompt.replace("{tts_family}", fam)
        .replace("{tts_engine}", tts_tags.engine_name(fam))
        .replace("{tts_palette}", tts_tags.render_palette_md(fam))
    )


def is_saga(workspace: Path) -> bool:
    """A saga workspace is identified by its series manifest."""
    return (workspace / "series.md").exists()


def build_saga_context(workspace: Path) -> str:
    """Build the `{saga_context}` injection for analyst/architect prompts.

    Returns "" for a single-book workspace (so base prompts are unchanged), or a
    block describing the reading order, per-book chapter boundaries, and the
    spoiler policy (from the .spoiler_mode sidecar) for a saga. This is what makes
    the unified feed book-aware: episodes stay within book boundaries and, in
    readalong mode, never reference a later book while discussing an earlier one.
    """
    if not is_saga(workspace):
        return ""
    # is_saga() already confirmed series.md exists. A read/parse failure here is
    # an INTEGRITY error, not a "treat as single book" signal: silently returning
    # "" would strip all spoiler protection + book boundaries from a run the user
    # explicitly asked to protect. Fail loud (fail-closed), matching the
    # deterministic marker guard in stage_prep.
    books = saga.parse_series_manifest((workspace / "series.md").read_text())
    spoiler_mode = read_spoiler_mode(workspace) or "readalong"
    order = "\n".join(
        f"  {b.index}. {b.title} — {b.author}  (chapters tagged `<!-- saga_book: {b.index} -->`)"
        for b in books
    )
    if spoiler_mode == "readalong":
        policy = (
            "SPOILER POLICY = readalong (STRICT reading order). When planning or "
            "writing any episode whose chapters belong to book K, you MUST NOT "
            "reference, foreshadow, or reveal ANYTHING from books with index > K "
            "— no character fates, plot turns, or twists the listener hasn't "
            "reached yet. Treat each later book as if it does not exist yet. "
            "Earlier books (index < K) are fair game for callbacks."
        )
    else:
        policy = (
            "SPOILER POLICY = retrospective (whole saga assumed read). You may "
            "freely cross-reference any book in either direction; lean into "
            "foreshadowing payoffs and long-arc callbacks across the series."
        )
    return (
        "\n\n## SAGA CONTEXT (multi-book continuous feed)\n\n"
        "This workspace is a multi-book saga rendered as ONE continuous podcast "
        "feed. Source chapters from all books are flattened into one numbered "
        "`source/chapters/ch_*.md` sequence; each chapter carries a "
        "`<!-- saga_book: N -->` comment identifying its source book. The "
        "authoritative reading order + per-book chapter ranges are in "
        "`{workspace}/series.md` (read it).\n\n"
        f"Reading order:\n{order}\n\n"
        "Episode numbering is CONTINUOUS across the whole saga (book 1 = EP1..n, "
        "book 2 continues at EP n+1, …). Keep every episode within a single "
        "book's chapters — do not blend chapters from different books into one "
        "episode. Open each new book with a brief recap of where the prior book "
        "left off.\n\n"
        f"{policy}\n"
    )


_SAGA_MARKER_RE = re.compile(r"<!--\s*saga_book:\s*\d+")


def check_saga_marker_coverage(workspace: Path) -> list[str]:
    """Return cleaned chapter files missing their `<!-- saga_book: N -->` marker.

    The cross-book spoiler horizon depends on every cleaned chapter knowing which
    book it came from. prep is told to copy the marker (prep.md), but that's an
    LLM instruction — this is the deterministic guard that turns a silently
    dropped marker into a fail-fast instead of an unrecoverable downstream
    spoiler leak. Empty list = full coverage.
    """
    missing: list[str] = []
    for ch in sorted((workspace / "source" / "chapters").glob("ch_*.md")):
        if not _SAGA_MARKER_RE.search(ch.read_text(encoding="utf-8")):
            missing.append(ch.name)
    return missing


# ─── Approval gates (human-in-the-loop) ─────────────────────────────────────
# Two producer checkpoints split the 13 stages into 3 phases. The autonomous
# run STOPS at each gate until the producer writes the approval marker, so a
# bad plan never burns scriptwrite tokens and a bad script never burns TTS:
#     PLAN(prep→enricher) ┃.plan_approved┃ SCRIPT(scriptwrite→script-review)
#                         ┃.script_approved┃ AUDIO(tts-prep→subtitle)
# Each gate keys on the FIRST stage of the phase it guards.
_APPROVAL_GATES = {
    "scriptwrite": ".plan_approved",   # gate 1 — PLAN done → produce SCRIPTs
    "tts-prep": ".script_approved",    # gate 2 — SCRIPT done → produce AUDIO
}


def approval_gate_block(
    stage_name: str,
    workspace: Path,
    *,
    explicit_skip_idx: int | None = None,
    ignore_gates: bool = False,
    stages: list[str] | None = None,
) -> str | None:
    """Return the approval-marker filename blocking entry to `stage_name`, or
    None if the stage may run.

    A gate blocks the autonomous forward run from crossing into an expensive
    phase until the producer writes the marker (dashboard "approve" or
    `touch workspace/<marker>`). Bypassed when:
      - ``ignore_gates`` (the --ignore-gates escape hatch / fully autonomous run),
      - the marker already exists (approved), or
      - the run was EXPLICITLY told to start at/after the gated stage via
        --skip-to / --only-stage. That is the producer's deliberate drive and
        counts as approval.

    Critically this tests the EXPLICIT skip index, NOT the auto-resume start
    index: re-running ``pipeline.py <ws>`` on a plan-complete-but-unapproved
    workspace auto-resumes start_idx to scriptwrite, and trusting that index
    would silently jump the gate. Pass ``explicit_skip_idx=None`` for an
    auto-resume run so the gate still holds.
    """
    marker = _APPROVAL_GATES.get(stage_name)
    if not marker or ignore_gates:
        return None
    stage_order = stages or STAGES
    gate_idx = stage_order.index(stage_name)
    if explicit_skip_idx is not None and explicit_skip_idx >= gate_idx:
        return None
    if (workspace / marker).exists():
        return None
    return marker


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

    def stage_end(self, stage: str, success: bool, elapsed: float, only_episode: bool = False, **extra: object) -> None:
        self._write({"event": "stage_end", "stage": stage, "success": success, "elapsed_s": round(elapsed, 1), **extra})
        status = "OK" if success else "FAILED"
        print(f"\n  [{stage}] {status} in {elapsed:.0f}s")
        # Write the whole-stage completion marker — but NOT for a single-episode
        # run. `--only-episode N` processes one episode through the normal stage
        # loop; if it wrote .stage_<name>_done, a later bare `pipeline.py <ws>`
        # would see the marker, skip the stage via detect_resume_point, and
        # silently leave every other episode unprocessed. Single-episode runs
        # must therefore force the producer to drive subsequent work explicitly.
        if success and not only_episode:
            marker = self.workspace / _STAGE_MARKER.format(name=stage)
            marker.write_text(datetime.now().isoformat())

    def gate_wait(self, stage: str, marker: str, phase: str) -> None:
        """Pipeline paused at an approval gate — NOT a failure (exit 0). The
        dashboard derives AWAITING_*_APPROVAL from disk state; this event also
        drives the live activity feed."""
        self._write({"event": "gate_wait", "stage": stage, "marker": marker, "phase": phase})
        print(f"\n  ⏸ awaiting {phase} approval — paused before {stage}")

    def event(self, msg: str, **extra: object) -> None:
        self._write({"event": "info", "msg": msg, **extra})
        print(f"  {msg}")

    def error(self, msg: str, **extra: object) -> None:
        self._write({"event": "error", "msg": msg, **extra})
        print(f"  ERROR: {msg}")


# ─── EPUB Extraction ───


_DC_SENTINEL = object()


def _dc(book: object, field: str, default: object = _DC_SENTINEL) -> str:
    """Safely read a Dublin Core metadata field.

    ebooklib's ``get_metadata("DC", field)`` returns ``[]`` for absent fields,
    so the naive ``[0][0]`` raises ``IndexError`` on calibre-made / scanned
    books that omit DC fields. This returns ``default`` when the field is
    missing; if no default is given the field is treated as required and a
    clear ``ValueError`` is raised (callers pass a filename via the message).
    """
    meta = book.get_metadata("DC", field)
    if meta and meta[0] and meta[0][0]:
        return meta[0][0]
    if default is _DC_SENTINEL:
        raise ValueError(f"EPUB missing required DC:{field}")
    return default


def _doc_items_in_spine(book: object) -> list:
    """Return ITEM_DOCUMENT items in *spine* (reading) order.

    ``get_items_of_type(ITEM_DOCUMENT)`` yields manifest order, which is not
    guaranteed to match reading order — books whose manifest is shuffled relative
    to the spine would get mis-numbered ``raw_ch_NN`` and corrupt every
    downstream stage (saga boundaries, spoiler horizon) silently. The spine is
    the authoritative reading order, so we walk it and resolve each idref to its
    document item. Falls back to manifest order (loud-logged) if the spine is
    missing or yields nothing.
    """
    docs: list = []
    for idref, _ in getattr(book, "spine", None) or []:
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            docs.append(item)
    if docs:
        return docs
    print("  WARN: EPUB spine empty/unresolvable — falling back to manifest order")
    return list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))


def extract_epub(epub_path: str) -> tuple[dict, list[tuple[str, str]]]:
    book = epub.read_epub(epub_path)
    try:
        title = _dc(book, "title")
    except ValueError as e:
        raise ValueError(f"{e} (file: {epub_path})") from e
    author = _dc(book, "creator", "Unknown")
    lang = _dc(book, "language", "en")

    chapters = []
    for item in _doc_items_in_spine(book):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 50:
            chapters.append((item.get_name(), text))

    return {
        "title": title, "author": author, "language": lang,
        "total_raw_chapters": len(chapters),
        "total_raw_chars": sum(len(t) for _, t in chapters),
    }, chapters


def book_workspace_dirname(title: str, author: str) -> str:
    """Deterministic single-book workspace dirname (mirrors saga.saga_dirname).

    The dirname rule lives here only — both setup_workspace (which creates the
    dir) and find_workspace (which must locate the same dir) call this, so a
    change to the slug rule or hash payload can never desync the two.
    """
    slug = _sanitize_slug(title)
    book_hash = hashlib.md5(f"{title}_{author}".encode()).hexdigest()[:8]
    return f"{slug}_{book_hash}"


def setup_workspace(metadata: dict, chapters: list[tuple[str, str]]) -> Path:
    workspace = WORKSPACES_DIR / book_workspace_dirname(
        metadata["title"], metadata["author"]
    )

    for d in ["plan/episodes", "scripts"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)
    # source/chapters, raw_chapters, and metadata.md are written by the shared
    # per-book helper (same layout each saga sub-book gets).
    _write_book_dir(workspace, metadata, chapters)

    (workspace / "log.md").write_text(
        f"# Podcast Pipeline Log\n\n"
        f"- Book: {metadata['title']} by {metadata['author']}\n"
        f"- Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    return workspace


def _write_book_dir(book_dir: Path, metadata: dict, chapters: list[tuple[str, str]]) -> None:
    """Materialize one book's source layout under ``book_dir`` (shared by the
    single-book and saga paths)."""
    for d in ["source/chapters", "raw_chapters"]:
        (book_dir / d).mkdir(parents=True, exist_ok=True)
    meta_lines = [
        f"# {metadata['title']}",
        f"- **Author**: {metadata['author']}",
        f"- **Language**: {metadata.get('language', 'en')}",
        f"- **Raw chapters**: {metadata['total_raw_chapters']}",
        f"- **Raw chars**: {metadata['total_raw_chars']:,}",
    ]
    (book_dir / "source" / "metadata.md").write_text("\n".join(meta_lines))
    for i, (name, text) in enumerate(chapters):
        (book_dir / "raw_chapters" / f"raw_ch_{i + 1:02d}.md").write_text(
            f"<!-- source: {name} -->\n\n{text}"
        )


def setup_saga_workspace(
    saga_title: str, books: list[tuple[dict, list[tuple[str, str]]]]
) -> Path:
    """Create ONE saga workspace grouping N books in reading order.

    `books` is an ordered list (reading order = list order) of
    ``(metadata, chapters)`` tuples as produced by `extract_epub`. Layout:

        workspaces/<saga_slug>_<hash>/
          series.md                 ← reading order + spoiler-horizon SoT
          books/NN_<slug>/source/…  ← per-book source, reading-order prefixed
          plan/ scripts/            ← series-level plan + unified episode feed
          log.md                    ← saga run log

    The .mode/.spoiler_mode sidecars are written later by main() (the CLI
    integration phase), same as the single-book path — not here.

    Returns the saga workspace path. Idempotent on re-run: existing book dirs are
    overwritten with the same content; series.md is rewritten from the manifest.
    """
    book_metas = [m for m, _ in books]
    entries = saga.plan_books(book_metas)
    dirname = saga.saga_dirname(saga_title, [m["title"] for m in book_metas])
    workspace = WORKSPACES_DIR / dirname

    for d in ["plan/episodes", "scripts", "books"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)

    # Per-book provenance copy (books/NN_slug/) — durable record of the original
    # split, used by series-level review and any future per-book resume.
    for entry, (metadata, chapters) in zip(entries, books):
        _write_book_dir(workspace / "books" / entry.slug, metadata, chapters)

    # Approach B: also write a FLATTENED root-level raw_chapters/ with continuous
    # cross-book numbering, so the existing single-book prep/analyst stages run
    # UNCHANGED on a saga. Each raw chapter records its source book in a comment
    # so prep can preserve the boundary, and series.md carries the authoritative
    # chapter→book map + spoiler horizon.
    flat = saga.flatten_chapters(entries, [ch for _, ch in books])
    (workspace / "raw_chapters").mkdir(parents=True, exist_ok=True)
    for fc in flat:
        (workspace / "raw_chapters" / f"raw_ch_{fc.seq:02d}.md").write_text(
            f"<!-- saga_book: {fc.book_index} ({fc.book_slug}) -->\n"
            f"<!-- source: {fc.name} -->\n\n{fc.text}"
        )
    (workspace / "source").mkdir(parents=True, exist_ok=True)
    (workspace / "source" / "chapters").mkdir(parents=True, exist_ok=True)
    total_chars = sum(len(fc.text) for fc in flat)
    saga_meta = [
        f"# {saga_title}",
        f"- **Saga**: {saga_title} ({len(entries)} books)",
        "- **Books (reading order)**: "
        + "; ".join(f"{e.index}. {e.title} — {e.author}" for e in entries),
        f"- **Raw chapters**: {len(flat)}",
        f"- **Raw chars**: {total_chars:,}",
    ]
    (workspace / "source" / "metadata.md").write_text("\n".join(saga_meta))

    (workspace / "series.md").write_text(
        saga.render_series_manifest(saga_title, entries)
        + saga.render_chapter_map(flat)
    )
    (workspace / "log.md").write_text(
        f"# Podcast Pipeline Log (Saga)\n\n"
        f"- Saga: {saga_title}\n"
        f"- Books ({len(entries)}): "
        + ", ".join(f"{e.index}. {e.title}" for e in entries)
        + f"\n- Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return workspace


def find_workspace(epub_path: Path) -> Path | None:
    if not WORKSPACES_DIR.exists():
        return None
    book = epub.read_epub(str(epub_path))
    try:
        title = _dc(book, "title")
    except ValueError as e:
        raise ValueError(f"{e} (file: {epub_path})") from e
    author = _dc(book, "creator", "Unknown")
    ws = WORKSPACES_DIR / book_workspace_dirname(title, author)
    return ws if ws.exists() else None


def find_saga_workspace(saga_title: str, epub_paths: list[Path]) -> Path | None:
    """Return the existing saga workspace for this title + ordered EPUB set, or None.

    Reads only DC metadata from each EPUB (cheap — no chapter extraction) to
    reproduce the deterministic dirname that ``setup_saga_workspace`` would
    produce. Mirrors ``find_workspace`` for the multi-book path.
    """
    if not WORKSPACES_DIR.exists():
        return None
    book_titles = []
    for p in epub_paths:
        b = epub.read_epub(str(p))
        try:
            book_titles.append(_dc(b, "title"))
        except ValueError as e:
            raise ValueError(f"{e} (file: {p})") from e
    dirname = saga.saga_dirname(saga_title, book_titles)
    ws = WORKSPACES_DIR / dirname
    return ws if ws.exists() else None


# ─── Claude Code Runner ───


# Per-stage timeout in seconds. Enricher does WebFetch and may legitimately take
# longer; scriptwriter/reviewer are single-pass writes; default for misc agents.
_STAGE_TIMEOUTS = {
    "Enricher": 2700,
    "Scriptwriter": 1800,
    "Script Review": 1200,
    "TTS Prep": 1200,
}
_DEFAULT_TIMEOUT = 1500

# ─── Transient-failure retry ───
# Agent stages shell out to `claude -p`. Its agent loop occasionally dies on a
# transient API error — most notably `400 ... thinking/redacted_thinking blocks
# ... cannot be modified`, a CLI-internal message-history corruption that a FRESH
# conversation sidesteps (the poisoned thinking block lives in the saved
# transcript, so --resume/--continue/--fork all reproduce it; only a brand-new
# `claude -p` escapes it). Retrying here turns a whole-pipeline abort into a
# self-healing blip. Idempotent stages re-read on-disk artifacts, so a retry
# resumes work rather than redoing it — disk is the durable checkpoint, the
# conversation is disposable.
_STAGE_RETRY_ATTEMPTS = int(os.getenv("PODCAST_STAGE_RETRIES", "3"))  # total tries
_STAGE_RETRY_BASE = float(os.getenv("PODCAST_STAGE_RETRY_BASE", "5"))  # backoff base (s)

# HTTP statuses worth retrying with a fresh conversation.
_RETRYABLE_HTTP = {"408", "409", "425", "429", "500", "502", "503", "504", "529"}
# Phrases that mark a transient/recoverable failure regardless of status code.
_RETRYABLE_PHRASES = (
    "overloaded", "rate limit", "rate_limit", "service unavailable",
    "internal server error", "bad gateway", "gateway timeout",
    "connection reset", "connection error", "econnreset", "etimedout",
    "temporarily unavailable", "please try again",
)
# Phrases that mark a deterministic/fatal failure — never retry (fail fast).
_FATAL_PHRASES = (
    "authentication", "unauthorized", "invalid x-api-key", "invalid api key",
    "permission denied", "permission_error", "invalid model", "not_found_error",
)


class _ClaudeFailure(NamedTuple):
    """Why a `claude -p` invocation failed. `status` is the API HTTP status
    coerced to str (the wire `api_error_status` is an int, e.g. 400 → "400")
    when known, else a tag like "timeout". May be None (status-less stderr)."""
    status: str | None
    reason: str


def _is_retryable_claude_failure(status: str | None, reason: str) -> bool:
    """Classify a `claude -p` failure as retryable (fresh-conversation may fix)
    vs fatal (deterministic — retrying just burns tokens).

    Retryable: transient API statuses (429/5xx), overload/rate-limit/connection
    phrases, AND the 400 thinking-block corruption (a CLI-loop bug a new
    conversation escapes). Fatal: auth/permission/config errors, generic 400
    bad-requests, and subprocess timeouts (retrying a 25-min timeout 3× is pure
    waste — raise PODCAST_STAGE_TIMEOUT instead).
    """
    text = (reason or "").lower()
    code = (str(status).strip().lower() if status is not None else "")

    # Subprocess timeout: deterministic-enough that retrying is too costly.
    if code == "timeout" or "timeout after" in text:
        return False
    # Fatal config/auth errors — fail fast.
    if any(p in text for p in _FATAL_PHRASES):
        return False
    # The 400 thinking/redacted_thinking corruption — a fresh conversation fixes
    # it. Must come BEFORE the generic-400 fallthrough below.
    if ("thinking" in text or "redacted_thinking" in text) and (
        "block" in text or "modified" in text
    ):
        return True
    # Transient HTTP statuses.
    if code in _RETRYABLE_HTTP:
        return True
    # Transient phrases (covers status-less stderr/connection failures).
    if any(p in text for p in _RETRYABLE_PHRASES):
        return True
    return False


def _fmt_tool_event(event: dict) -> str | None:
    """Turn a stream-json event into a one-line human summary. Returns None to skip."""
    etype = event.get("type")
    if etype == "system":
        sub = event.get("subtype", "")
        if sub == "init":
            return f"  · agent started (cwd={event.get('cwd', '?')})"
        return None
    if etype == "assistant":
        msg = event.get("message", {})
        lines: list[str] = []
        for part in msg.get("content", []):
            ptype = part.get("type")
            if ptype == "tool_use":
                name = part.get("name", "?")
                inp = part.get("input", {})
                if name in {"Read", "Write", "Edit"}:
                    fp = inp.get("file_path", "")
                    lines.append(f"  → {name} {fp}")
                elif name == "Bash":
                    cmd = inp.get("command", "")[:100]
                    lines.append(f"  → Bash: {cmd}")
                elif name == "Grep":
                    lines.append(f"  → Grep '{inp.get('pattern', '')}' in {inp.get('path', '.')}")
                elif name == "Glob":
                    lines.append(f"  → Glob '{inp.get('pattern', '')}'")
                elif name in {"WebFetch", "WebSearch"}:
                    lines.append(f"  → {name}: {inp.get('url') or inp.get('query', '')[:80]}")
                else:
                    lines.append(f"  → {name}")
            elif ptype == "text":
                txt = (part.get("text") or "").strip()
                if txt:
                    # Claude's natural-language reply between tool calls — show first line
                    first = txt.splitlines()[0][:160]
                    lines.append(f"  💬 {first}")
        return "\n".join(lines) if lines else None
    if etype == "result":
        dur = event.get("duration_ms", 0) / 1000
        return f"  · done ({dur:.0f}s, turns={event.get('num_turns', '?')})"
    return None


def _run_claude_subprocess(
    cmd: list[str],
    workspace: Path,
    label: str,
    log: PipelineLog | None,
    timeout: int,
    prompt: str | None = None,
) -> tuple[bool, float]:
    """Shared subprocess runner with timeout + stderr tail capture.

    If PODCAST_VERBOSE=1 (stream-json), stdout is piped through a line-reader
    that pretty-prints tool-use events live. Otherwise stdout is inherited
    (claude's natural-language summary goes straight to TTY).

    ``prompt`` is delivered via stdin to avoid exposing book content / workspace
    paths in argv (visible to any local user via ps/proc listings).
    """
    t0 = time.time()
    stderr_log = workspace / f"claude_{label.lower().replace(' ', '_')}.stderr.log"
    stdin_bytes = prompt.encode() if prompt else b""
    try:
        proc_env = _agent_subprocess_env()
    except RuntimeError as e:
        if log:
            log.error(f"{label} agent configuration error", profile=AGENT_PROFILE, reason=str(e))
        return False, 0.0, _ClaudeFailure("auth", str(e))

    if _STREAM_JSON:
        # Live tool-use rendering via stream-json NDJSON. Also tees each event
        # (wrapped with current stage label + timestamp) to workspace/events.jsonl
        # so the monitor dashboard can stream tool-use + token usage live.
        events_path = workspace / "events.jsonl"
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=proc_env,
            bufsize=0,
        )
        try:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        except BrokenPipeError:
            print(
                f"[pipeline] stdin closed/closed by child before full input: events_path={events_path}",
                file=sys.stderr,
            )
        result_event: dict | None = None
        try:
            with events_path.open("a", encoding="utf-8") as ev_f:
                for raw_line in proc.stdout:  # type: ignore[union-attr]
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Skipping malformed pipeline child event line: %r", line)
                        continue
                # The terminal `result` event carries is_error / api_error_status
                # even when the agent printed an error and the CLI still exits 0
                # — capture it as the authoritative success signal.
                if event.get("type") == "result":
                    result_event = event
                # Wrap with stage/label/ts for the monitor to correlate
                wrapped = {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "stage_label": label,
                    "event": event,
                }
                ev_f.write(json.dumps(wrapped, ensure_ascii=False) + "\n")
                ev_f.flush()
                rendered = _fmt_tool_event(event)
                if rendered:
                    print(rendered, flush=True)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            elapsed = time.time() - t0
            raw = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
            if raw:
                stderr_log.write_text(raw[-2000:])
            if log:
                log.error(f"{label} TIMEOUT after {timeout}s",
                          timeout=True, elapsed_s=round(elapsed, 1),
                          stderr_tail=raw[-500:])
            return False, elapsed, _ClaudeFailure("timeout", f"TIMEOUT after {timeout}s")
        elapsed = time.time() - t0
        stderr_text = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
        # An is_error result event means the agent loop failed (e.g. API 400)
        # even if subtype=="success" and the CLI exit code is 0 — trust is_error.
        api_error = bool(result_event and result_event.get("is_error"))
        success = proc.returncode == 0 and not api_error
        if success:
            return True, elapsed, None
        status = None
        reason = ""
        if result_event:
            status = str(result_event.get("api_error_status") or "").strip() or None
            reason = str(result_event.get("result") or "").strip()
        if not reason:
            reason = stderr_text[-500:].strip() or f"exit code {proc.returncode}"
        if stderr_text:
            stderr_log.write_text(stderr_text)
        if log:
            log.error(f"{label} failed (exit={proc.returncode}, api_error={api_error})",
                      api_error_status=status, stderr_tail=stderr_text[-500:],
                      reason=reason[:300])
        return False, elapsed, _ClaudeFailure(status, reason)

    # Non-verbose mode: inherit stdout
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            input=stdin_bytes,
            stdout=None,
            stderr=subprocess.PIPE,
            env=proc_env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - t0
        raw = e.stderr
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        tail = (raw or "")[-2000:]
        if tail:
            stderr_log.write_text(tail)
        if log:
            log.error(
                f"{label} TIMEOUT after {timeout}s",
                timeout=True, elapsed_s=round(elapsed, 1),
                stderr_tail=tail[-500:],
            )
        return False, elapsed, _ClaudeFailure("timeout", f"TIMEOUT after {timeout}s")

    elapsed = time.time() - t0
    success = proc.returncode == 0
    if success:
        return True, elapsed, None
    # Non-stream mode has no result event — classify from stderr text alone.
    stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace")
    if stderr_text:
        stderr_log.write_text(stderr_text)
    reason = stderr_text[-500:].strip() or f"exit code {proc.returncode}"
    if log:
        log.error(
            f"{label} exited with code {proc.returncode}",
            stderr_tail=stderr_text[-500:],
        )
    return False, elapsed, _ClaudeFailure(None, reason)


def _run_claude_with_retry(
    cmd: list[str],
    workspace: Path | None,
    label: str,
    log: "PipelineLog | None",
    timeout: int,
    prompt: str | None = None,
) -> tuple[bool, float]:
    """Run `claude -p` with bounded retries on transient failures.

    Each attempt is a FRESH `claude -p` invocation (no --resume): a new
    conversation escapes the poisoned thinking-block history that makes the 400
    reproduce. Idempotent stages re-read on-disk artifacts, so a retry resumes
    work. Fatal failures (auth/config/timeout) fail fast — no wasted retries.
    """
    import random
    attempts = max(1, _STAGE_RETRY_ATTEMPTS)
    last_elapsed = 0.0
    for attempt in range(1, attempts + 1):
        success, elapsed, failure = _run_claude_subprocess(cmd, workspace, label, log, timeout, prompt)
        last_elapsed = elapsed
        if success:
            if attempt > 1 and log:
                log.event(f"{label} recovered on attempt {attempt}/{attempts}")
            return True, elapsed
        retryable = failure is not None and _is_retryable_claude_failure(failure.status, failure.reason)
        reason = (failure.reason if failure else "unknown")[:160]
        if not retryable or attempt >= attempts:
            if log:
                log.error(f"{label} failed permanently",
                          attempt=attempt, attempts=attempts, retryable=retryable,
                          status=(failure.status if failure else None), reason=reason)
            return False, elapsed
        backoff = min(90.0, _STAGE_RETRY_BASE * (2 ** (attempt - 1))) + random.random() * 2
        # 429 = per-minute quota exhausted; needs ≥60s for the window to reset.
        if failure and str(failure.status) == "429":
            backoff = max(backoff, 60.0)
        if log:
            log.event(f"{label} transient failure — retry {attempt + 1}/{attempts}",
                      status=(failure.status if failure else None),
                      reason=reason, backoff_s=round(backoff, 1))
        print(f"  [{label}] transient failure (attempt {attempt}/{attempts}) — "
              f"retry in {backoff:.0f}s: {reason}", flush=True)
        time.sleep(backoff)
    return False, last_elapsed


def run_claude(
    prompt: str,
    workspace: Path,
    label: str,
    log: PipelineLog,
    extra_tools: list[str] | None = None,
    inject_tts: bool = False,
) -> bool:
    prompt = prompt.replace("{saga_context}", build_saga_context(workspace))
    prompt = prompt.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{podcast_root}", str(ROOT))  # cover stage drives cover_tool.py by abs path
    if inject_tts:
        prompt = inject_tts_palette(prompt, workspace)
    tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    if extra_tools:
        tools.extend(extra_tools)

    # Prompt is passed via stdin (not argv) to avoid exposing content in ps listings.
    cmd = ["claude", "-p", "-", *_VERBOSE_FLAGS, "--model", MODEL, "--allowedTools", ",".join(tools)]
    timeout = _STAGE_TIMEOUTS.get(label, _DEFAULT_TIMEOUT)

    log.event("claude invocation", tools=tools, profile=AGENT_PROFILE, model=MODEL,
              prompt_len=len(prompt), timeout_s=timeout)

    success, _ = _run_claude_with_retry(cmd, workspace, label, log, timeout, prompt)
    return success


def run_scriptwriter(workspace: Path, ep_num: int) -> tuple[int, bool]:
    prompt_template = _prompt("scriptwriter", read_mode(workspace))
    prompt = prompt_template.replace("{saga_context}", build_saga_context(workspace))
    prompt = prompt.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))
    prompt = inject_tts_palette(prompt, workspace)
    prompt += f"\n\nYou are writing Episode {ep_num}. Read the overview, then your episode plan at plan/episodes/ep_{ep_num:02d}.md, then the source chapters listed in it."

    # Prompt is passed via stdin (not argv) to avoid exposing content in ps listings.
    cmd = ["claude", "-p", "-", *_VERBOSE_FLAGS, "--model", MODEL, "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep"]
    label = f"Scriptwriter EP{ep_num}"
    timeout = _STAGE_TIMEOUTS["Scriptwriter"]

    # Each worker runs in its OWN process (ProcessPoolExecutor), so it builds its
    # own PipelineLog instead of inheriting the parent's. PipelineLog holds no
    # shared state and appends single short lines via open("a") (O_APPEND →
    # atomic append-to-EOF on POSIX), so concurrent workers writing the same
    # pipeline_log.jsonl never interleave or clobber each other. Passing log=None
    # here used to silently swallow agent failures — the `if log:` guards in
    # _run_claude_subprocess skip the timeout/api_error/exit logging — so the
    # dashboard's `grep '"error"'` saw nothing for parallel-stage failures.
    log = PipelineLog(workspace)
    print(f"\n  [{label}] Starting (timeout {timeout}s)...")
    success, elapsed = _run_claude_with_retry(cmd, workspace, label, log, timeout, prompt)
    status = "OK" if success else "FAILED"
    print(f"  [{label}] {status} in {elapsed:.1f}s")
    return ep_num, success


def run_script_reviewer(workspace: Path, ep_num: int) -> tuple[int, bool]:
    prompt_template = _prompt("script_review", read_mode(workspace))
    prompt = prompt_template.replace("{saga_context}", build_saga_context(workspace))
    prompt = prompt.replace("{workspace}", str(workspace))
    prompt = prompt.replace("{N}", str(ep_num))
    prompt = inject_tts_palette(prompt, workspace)
    prompt += f"\n\nReview Episode {ep_num}. Read overview.md, then ep_{ep_num:02d}.md plan, then ep_{ep_num}_script.md."

    # Prompt is passed via stdin (not argv) to avoid exposing content in ps listings.
    cmd = ["claude", "-p", "-", *_VERBOSE_FLAGS, "--model", MODEL, "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep"]
    label = f"Script Review EP{ep_num}"
    timeout = _STAGE_TIMEOUTS["Script Review"]

    # Own-process worker → own PipelineLog (see run_scriptwriter for the O_APPEND
    # safety rationale). Replaces the former log=None that swallowed failures.
    log = PipelineLog(workspace)
    print(f"\n  [{label}] Starting (timeout {timeout}s)...")
    success, elapsed = _run_claude_with_retry(cmd, workspace, label, log, timeout, prompt)
    status = "OK" if success else "FAILED"
    print(f"  [{label}] {status} in {elapsed:.1f}s")
    return ep_num, success


# ─── Stage Completion Detection ───


def stage_done(workspace: Path, stage: str) -> bool:
    """Check if a stage has a completion marker."""
    return (workspace / _STAGE_MARKER.format(name=stage)).exists()


def detect_resume_point(workspace: Path, stages: list[str] | None = None) -> int:
    """Find the first incomplete stage index."""
    stage_order = stages or STAGES
    for i, stage in enumerate(stage_order):
        if not stage_done(workspace, stage):
            return i
    return len(stage_order)  # all done


# ─── Workflow provenance ───


_STAGE_ARTIFACT_GLOBS = {
    "prep": {
        "input": ["raw_chapters/*.md", "series.md", "source/metadata.md"],
        "output": ["source/chapters/*.md", "source/metadata.md"],
    },
    "analyst": {
        "input": ["source/**/*.md", "series.md"],
        "output": ["plan/analysis.md"],
    },
    "architect": {
        "input": ["source/**/*.md", "series.md", "plan/analysis.md"],
        "output": ["plan/overview.md", "plan/episodes/*.md"],
    },
    "plan-review": {
        "input": ["plan/overview.md", "plan/episodes/*.md"],
        "output": ["plan/review.md"],
    },
    "enricher-gap": {
        "input": ["plan/overview.md", "plan/episodes/*.md", "plan/review.md"],
        "output": ["plan/research_brief.md"],
    },
    "enricher": {
        "input": ["plan/research_brief.md", "plan/episodes/*.md"],
        "output": ["plan/episodes/*.md"],
    },
    "scriptwrite": {
        "input": ["plan/overview.md", "plan/episodes/*.md"],
        "output": ["scripts/ep_*_script.md", _SCRIPT_TTS_FAMILY_SIDECAR],
    },
    "series-polish": {
        "input": ["plan/overview.md", "scripts/ep_*_script.md"],
        "output": ["scripts/ep_*_script.md", "plan/series_polish.md"],
    },
    "script-review": {
        "input": ["plan/overview.md", "scripts/ep_*_script.md"],
        "output": ["scripts/ep_*_review.md"],
    },
    "tts-prep": {
        "input": ["plan/overview.md", "scripts/ep_*_script.md", "scripts/ep_*_review.md"],
        "output": ["plan/overview.md", "plan/tts_prep.md", "scripts/ep_*_script.md"],
    },
    "synthesize": {
        "input": ["scripts/ep_*_script.md", _TTS_MODEL_SIDECAR, _SCRIPT_TTS_FAMILY_SIDECAR],
        "output": ["scripts/ep_*.mp3", "scripts/ep_*.m4a", "scripts/ep_*.meta.json"],
    },
    "audio-qa": {
        "input": ["scripts/ep_*.mp3", "scripts/ep_*.m4a"],
        "output": ["audio_qa.json"],
    },
    "subtitle": {
        "input": ["scripts/ep_*_script.md", "scripts/ep_*.mp3", "scripts/ep_*.m4a"],
        "output": ["scripts/ep_*.srt"],
    },
    "cover": {
        "input": ["plan/overview.md"],
        "output": ["plan/cover.png", "plan/cover_meta.json"],
    },
    "publish": {
        "input": ["plan/cover.png", "scripts/ep_*.mp3", "scripts/ep_*.m4a", "scripts/ep_*.srt"],
        "output": [],
    },
}

_LINEAGE_STAGES = {"scriptwrite", "series-polish", "script-review", "producer-cut", "tts-prep"}


def _artifact_matches_episode(rel: str, only_episode: int | None) -> bool:
    if only_episode is None or not rel.startswith("scripts/ep_"):
        return True
    m = re.match(r"scripts/ep_(\d+)_", rel)
    return bool(m and int(m.group(1)) == only_episode)


def _collect_artifacts(
    workspace: Path,
    patterns: list[str],
    *,
    only_episode: int | None = None,
) -> dict[str, dict[str, object]]:
    artifacts: dict[str, dict[str, object]] = {}
    for pattern in patterns:
        matches = [workspace / pattern] if not any(ch in pattern for ch in "*?[") else list(workspace.glob(pattern))
        for p in sorted(matches):
            if not p.is_file():
                continue
            rel = p.relative_to(workspace).as_posix()
            if not _artifact_matches_episode(rel, only_episode):
                continue
            stat = p.stat()
            artifacts[rel] = {
                "sha256": _sha256_file(p),
                "bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
    return artifacts


def capture_stage_inputs(
    workspace: Path,
    stage: str,
    only_episode: int | None,
) -> dict[str, dict[str, object]]:
    spec = _STAGE_ARTIFACT_GLOBS.get(stage, {})
    return _collect_artifacts(workspace, spec.get("input", []), only_episode=only_episode)


def _capture_stage_outputs(
    workspace: Path,
    stage: str,
    only_episode: int | None,
) -> dict[str, dict[str, object]]:
    spec = _STAGE_ARTIFACT_GLOBS.get(stage, {})
    return _collect_artifacts(workspace, spec.get("output", []), only_episode=only_episode)


def _stage_prompt_metadata(workspace: Path, stage: str) -> dict[str, object] | None:
    prompt_names = {
        "prep": "prep",
        "analyst": "analyst",
        "architect": "architect",
        "plan-review": "plan_review",
        "enricher-gap": "enricher_gap",
        "enricher": "enricher",
        "scriptwrite": "scriptwriter",
        "series-polish": "series_polish",
        "script-review": "script_review",
        "tts-prep": "tts_prep",
        "cover": "cover",
    }
    prompt_name = prompt_names.get(stage)
    if not prompt_name:
        return None
    workflow_version = resolve_workspace_workflow(workspace, None)
    p = prompt_path(prompt_name, read_mode(workspace), workflow_version)
    root = WORKFLOW_VERSIONS_DIR / workflow_version
    return {
        "version": workflow_version,
        "name": prompt_name,
        "path": p.relative_to(root).as_posix(),
        "sha256": _sha256_file(p),
    }


def _validator_result(workspace: Path, stage: str) -> dict[str, object] | None:
    workflow = load_workflow_definition(resolve_workspace_workflow(workspace, None))
    thresholds = workflow.get("qa_thresholds", {})
    stage_thresholds = thresholds.get(stage, {}) if isinstance(thresholds, dict) else {}
    if stage == "plan-review":
        f = workspace / "plan" / "review.md"
        if not f.exists():
            return {"status": "missing", "artifact": "plan/review.md"}
        text = f.read_text()
        rewrite_marker = stage_thresholds.get("rewrite_marker", "REWRITE_NEEDED")
        max_fail_count = int(stage_thresholds.get("max_fail_count", 2))
        fail_count = text.count("FAIL")
        return {
            "status": "pass" if rewrite_marker not in text and fail_count <= max_fail_count else "fail",
            "rewrite_marker": rewrite_marker,
            "rewrite_needed": rewrite_marker in text,
            "fail_count": fail_count,
            "max_fail_count": max_fail_count,
        }
    if stage == "series-polish":
        f = workspace / "plan" / "series_polish.md"
        if not f.exists():
            return {"status": "missing", "artifact": "plan/series_polish.md"}
        text = f.read_text()
        block_marker = stage_thresholds.get("block_marker", "STRUCTURAL_ISSUES_NEED_RESCRIPT")
        return {
            "status": "fail" if block_marker in text else "pass",
            "block_marker": block_marker,
            "structural_issues": block_marker in text,
        }
    if stage == "script-review":
        rewrite_marker = stage_thresholds.get("rewrite_marker", "REWRITE_NEEDED")
        rewrite = []
        for f in sorted((workspace / "scripts").glob("ep_*_review.md")):
            if rewrite_marker in f.read_text():
                m = re.search(r"ep_(\d+)", f.stem)
                rewrite.append(int(m.group(1)) if m else f.name)
        return {"status": "fail" if rewrite else "pass", "rewrite_marker": rewrite_marker, "rewrite_needed": rewrite}
    if stage == "tts-prep":
        f = workspace / "plan" / "tts_prep.md"
        if not f.exists():
            return {"status": "missing", "artifact": "plan/tts_prep.md"}
        text = f.read_text()
        ready_marker = stage_thresholds.get("ready_marker", "READY_FOR_TTS")
        block_marker = stage_thresholds.get("block_marker", "BLOCKED")
        return {
            "status": "pass" if ready_marker in text and block_marker not in text else "fail",
            "ready_marker": ready_marker,
            "block_marker": block_marker,
            "ready": ready_marker in text,
            "blocked": block_marker in text,
        }
    if stage == "audio-qa":
        f = workspace / "audio_qa.json"
        if not f.exists():
            return {"status": "missing", "artifact": "audio_qa.json"}
        try:
            report = json.loads(f.read_text())
        except json.JSONDecodeError as exc:
            _LOGGER.warning("cannot parse %s: %s", f, exc)
            return {"status": "unreadable", "artifact": "audio_qa.json"}
        summary = report.get("summary") or {}
        fail = int(summary.get("fail") or 0)
        warn = int(summary.get("warn") or 0)
        strict = bool(stage_thresholds.get("strict", False))
        return {
            "status": "fail" if fail or (strict and warn) else "pass",
            "artifact": "audio_qa.json",
            "strict": strict,
            "summary": summary,
        }
    return None


def _audio_qa_strict(workspace: Path) -> bool:
    workflow = load_workflow_definition(resolve_workspace_workflow(workspace, None))
    thresholds = workflow.get("qa_thresholds", {})
    if not isinstance(thresholds, dict):
        return False
    audio_qa = thresholds.get("audio-qa", {})
    return bool(audio_qa.get("strict", False)) if isinstance(audio_qa, dict) else False


def _approval_marker_for_stage(workspace: Path, stage: str) -> dict[str, object] | None:
    marker = _APPROVAL_GATES.get(stage)
    if not marker:
        return None
    path = workspace / marker
    return {"marker": marker, "approved": path.exists()}


def _stage_label_prefixes(stage: str) -> tuple[str, ...]:
    return {
        "prep": ("prep",),
        "analyst": ("analyst",),
        "architect": ("architect",),
        "plan-review": ("plan review",),
        "enricher-gap": ("enricher gap",),
        "enricher": ("enricher",),
        "scriptwrite": ("scriptwriter",),
        "series-polish": ("series polish",),
        "script-review": ("script review",),
        "tts-prep": ("tts prep",),
        "synthesize": ("synthesize", "tts"),
        "cover": ("cover",),
    }.get(stage, (stage.replace("-", " "),))


def _event_has_cost_payload(event: dict) -> bool:
    payload = event.get("event", {})
    if payload.get("type") in {"tts_usage", "image_usage"}:
        return True
    if payload.get("type") == "result":
        usage = payload.get("modelUsage")
        return bool(usage)
    return False


def _stage_cost_event_refs(workspace: Path, stage: str) -> list[str]:
    events_path = workspace / "events.jsonl"
    if not events_path.exists():
        return []
    prefixes = _stage_label_prefixes(stage)
    refs: list[str] = []
    for idx, line in enumerate(events_path.read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            _LOGGER.debug("Skipping malformed event at events.jsonl:%s", idx)
            continue
        label = str(event.get("stage_label", "")).strip().lower()
        if not any(label.startswith(prefix) for prefix in prefixes):
            continue
        if _event_has_cost_payload(event):
            refs.append(f"events.jsonl:{idx}")
    return refs


def _lineage_bucket(stage: str) -> str:
    return stage.replace("-", "_")


def _script_hash(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _update_episode_lineage(
    workspace: Path,
    stage: str,
    *,
    input_artifacts: dict[str, dict[str, object]],
    prompt: dict[str, object] | None,
    only_episode: int | None,
) -> None:
    if stage not in _LINEAGE_STAGES:
        return
    scripts = sorted((workspace / "scripts").glob("ep_*_script.md"))
    if only_episode is not None:
        scripts = [p for p in scripts if p.name.startswith(f"ep_{only_episode}_")]
    bucket = _lineage_bucket(stage)
    workflow_version = resolve_workspace_workflow(workspace, None)
    for script in scripts:
        m = re.match(r"ep_(\d+)_script\.md", script.name)
        if not m:
            continue
        episode = int(m.group(1))
        rel = script.relative_to(workspace).as_posix()
        before_hash = (input_artifacts.get(rel) or {}).get("sha256")
        after_hash = _script_hash(script)
        lineage_path = workspace / "scripts" / f"ep_{episode}_lineage.json"
        if lineage_path.exists():
            lineage = json.loads(lineage_path.read_text())
        else:
            lineage = {
                "episode": episode,
                "workflow_version": workflow_version,
                "scriptwrite": [],
                "series_polish": [],
                "script_review": [],
                "producer_cut": [],
                "tts_prep": [],
                "events": [],
            }
        event = {
            "stage": stage,
            "workflow_version": workflow_version,
            "prompt": prompt,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "changed": before_hash != after_hash,
            "edit_summary": "recorded deterministic before/after script hash",
            "human_approved": (workspace / ".script_approved").exists() if stage == "tts-prep" else None,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        lineage.setdefault(bucket, []).append(event)
        lineage.setdefault("events", []).append(event)
        lineage_path.write_text(json.dumps(lineage, ensure_ascii=False, indent=2) + "\n")


def write_stage_provenance(
    workspace: Path,
    *,
    stage: str,
    success: bool,
    elapsed_s: float,
    input_artifacts: dict[str, dict[str, object]],
    only_episode: int | None,
) -> dict:
    workflow_version = resolve_workspace_workflow(workspace, None)
    prompt = _stage_prompt_metadata(workspace, stage)
    output_artifacts = _capture_stage_outputs(workspace, stage, only_episode)
    provenance = {
        "stage": stage,
        "workflow_version": workflow_version,
        "pipeline_commit": _pipeline_commit(),
        "success": success,
        "elapsed_s": round(elapsed_s, 1),
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "prompt": prompt,
        "model": {
            "agent_profile": AGENT_PROFILE,
            "agent_model": MODEL,
            "tts_model": read_tts_model(workspace) or DEFAULT_TTS_MODEL,
        },
        "command": {
            "entrypoint": "pipeline.py",
            "stage": stage,
            "only_episode": only_episode,
        },
        "cost_event_ids": _stage_cost_event_refs(workspace, stage),
        "validator_result": _validator_result(workspace, stage),
        "manual_approval_marker": _approval_marker_for_stage(workspace, stage),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_dir = workspace / STAGE_PROVENANCE_DIR
    out_dir.mkdir(exist_ok=True)
    suffix = f"_ep_{only_episode}" if only_episode is not None else ""
    (out_dir / f"{stage}{suffix}.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    )
    _update_episode_lineage(
        workspace,
        stage,
        input_artifacts=input_artifacts,
        prompt=prompt,
        only_episode=only_episode,
    )
    return provenance


# ─── Pipeline Stages ───


def stage_prep(workspace: Path, log: PipelineLog) -> bool:
    if not run_claude(_prompt("prep", read_mode(workspace)), workspace, "Prep", log):
        return False
    # Saga guard: prep must preserve every chapter's book-membership marker, or
    # the cross-book spoiler horizon silently breaks. Deterministic fail-fast.
    if is_saga(workspace):
        missing = check_saga_marker_coverage(workspace)
        if missing:
            log.error(
                f"Saga prep dropped the saga_book marker on {len(missing)} chapter(s): "
                f"{', '.join(missing[:10])}{' …' if len(missing) > 10 else ''}. "
                f"Each ch_*.md must keep its <!-- saga_book: N --> comment; "
                f"re-run prep (the markers are in raw_chapters/)."
            )
            return False
        log.event("Saga marker coverage OK (all chapters tagged with source book)")
    return True


def stage_analyst(workspace: Path, log: PipelineLog) -> bool:
    return run_claude(_prompt("analyst", read_mode(workspace)), workspace, "Analyst", log)


def stage_architect(workspace: Path, log: PipelineLog) -> bool:
    return run_claude(_prompt("architect", read_mode(workspace)), workspace, "Architect", log)


def stage_plan_review(workspace: Path, log: PipelineLog) -> bool:
    ok = run_claude(_prompt("plan_review", read_mode(workspace)), workspace, "Plan Review", log)
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
    return run_claude(_prompt("enricher_gap", read_mode(workspace)), workspace, "Enricher Gap", log)


def stage_enricher(workspace: Path, log: PipelineLog) -> bool:
    return run_claude(
        _prompt("enricher", read_mode(workspace)), workspace, "Enricher", log,
        extra_tools=["WebSearch", "WebFetch"],
    )


def stage_scriptwriters(workspace: Path, log: PipelineLog, max_parallel: int = 3, only_episode: int | None = None) -> bool:
    if only_episode:
        _, ok = run_scriptwriter(workspace, only_episode)
        if ok:
            # Record the authored TTS family even on the single-episode path, or a
            # ws built purely via --only-episode never gets the sidecar →
            # stage_synthesize defaults to "3.1" → spurious cross-family mismatch
            # notices (backstop still safe; this just kills the noise). Mirrors the
            # full-run write below.
            (workspace / _SCRIPT_TTS_FAMILY_SIDECAR).write_text(resolve_tts_family(workspace))
        return ok

    ep_files = sorted((workspace / "plan" / "episodes").glob("ep_*.md"))
    if not ep_files:
        log.error("No episode plans found")
        return False

    ep_nums = [int(f.stem.split("_")[1]) for f in ep_files]

    # A script is "complete" only if it ends with the sentinel marker that
    # scriptwriter.md mandates. Files without it are partial writes (agent
    # crashed/timed-out mid-generation) — re-run them.
    existing: set[int] = set()
    incomplete: list[int] = []
    for f in (workspace / "scripts").glob("ep_*_script.md"):
        n = int(f.stem.split("_")[1])
        tail = f.read_text(encoding="utf-8")[-200:]
        if "END_OF_SCRIPT" in tail:
            existing.add(n)
        else:
            incomplete.append(n)
            f.unlink(missing_ok=True)  # remove partial so re-run starts clean

    if incomplete:
        log.event(f"Discarded {len(incomplete)} partial scripts (missing END_OF_SCRIPT): {sorted(incomplete)}")

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
            ep_num = futures[future]
            # A worker that OOMs / SIGKILLs / segfaults dies before it can return
            # (ep, False), so future.result() raises BrokenProcessPool (which would
            # propagate out of the `with` block, discarding every sibling's already-
            # collected result and aborting the stage non-gracefully). Catch it (and
            # any other worker exception) → mark just that episode failed, keep the
            # siblings, and let the stage report which episodes failed below.
            try:
                ep_num, success = future.result()
            except BrokenProcessPool as e:
                log.error(f"Scriptwriter EP{ep_num} worker crashed (BrokenProcessPool: {e})")
                success = False
            except Exception as e:  # noqa: BLE001 — worker death must not abort the stage
                log.error(f"Scriptwriter EP{ep_num} worker raised {type(e).__name__}: {e}")
                success = False
            results[ep_num] = success

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        log.error(f"Failed episodes: {failed}")
        return False

    # Record which TTS family these scripts were authored for. The scriptwriter
    # prompt was injected with this family's palette (inject_tts_palette), so the
    # sidecar records the REAL family — stage_synthesize compares it to .tts_model
    # to detect a later cross-family synth.
    (workspace / _SCRIPT_TTS_FAMILY_SIDECAR).write_text(resolve_tts_family(workspace))

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
    existing = {int(m.group(1)) for f in (workspace / "scripts").glob("ep_*_review.md") if (m := re.search(r"ep_(\d+)", f.stem))}
    todo = [n for n in ep_nums if n not in existing]

    if not todo:
        log.event(f"All {len(ep_nums)} scripts already reviewed — skipping")
        return True

    log.event(f"{len(todo)} scripts to review: {todo}")

    results = {}
    with ProcessPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(run_script_reviewer, workspace, n): n for n in todo}
        for future in as_completed(futures):
            ep_num = futures[future]
            # Same crash-resilience as stage_scriptwriters: a worker that dies
            # before returning raises BrokenProcessPool; catch it (and any other
            # worker exception) so one crashed episode never discards the siblings'
            # results or aborts the stage non-gracefully.
            try:
                ep_num, success = future.result()
            except BrokenProcessPool as e:
                log.error(f"Script Review EP{ep_num} worker crashed (BrokenProcessPool: {e})")
                success = False
            except Exception as e:  # noqa: BLE001 — worker death must not abort the stage
                log.error(f"Script Review EP{ep_num} worker raised {type(e).__name__}: {e}")
                success = False
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


def stage_series_polish(workspace: Path, log: PipelineLog) -> bool:
    """Cross-episode polish pass: callbacks, running bits, character drift, series arc."""
    ok = run_claude(_prompt("series_polish", read_mode(workspace)), workspace, "Series Polish", log)
    if not ok:
        return False

    report = workspace / "plan" / "series_polish.md"
    if not report.exists():
        log.error("Series polish did not produce plan/series_polish.md")
        return False

    content = report.read_text()
    if "STRUCTURAL_ISSUES_NEED_RESCRIPT" in content:
        log.error("Series polish flagged structural drift — read plan/series_polish.md and re-scriptwrite flagged episodes")
        return False

    # Guard: every script must still end with the sentinel (polish mustn't have stripped it)
    for f in (workspace / "scripts").glob("ep_*_script.md"):
        if "END_OF_SCRIPT" not in f.read_text()[-200:]:
            log.error(f"Series polish removed END_OF_SCRIPT marker from {f.name} — manual fix required")
            return False

    log.event("Series polish complete — cross-episode coherence strengthened")
    return True


def stage_tts_prep(workspace: Path, log: PipelineLog) -> bool:
    ok = run_claude(_prompt("tts_prep", read_mode(workspace)), workspace, "TTS Prep", log, inject_tts=True)
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

    # Restore the frozen TTS model here — the single point every spawn path
    # funnels through, mirroring how every stage reads .mode via read_mode().
    env = _UNBUF_ENV
    chosen = read_tts_model(workspace)
    if chosen:
        env = {**_UNBUF_ENV, "TTS_MODEL": chosen}
        # Cross-family check. Scripts carry the 3.1 tag palette, so synthesizing
        # on another family needs the 3.1-only tags neutralized — synthesize.py's
        # _sanitize_dialogue does that at the choke point (tts_tags.sanitize_tags
        # _for_family). A MISSING sidecar means a legacy (pre-2026-06) workspace,
        # which was also 3.1-authored — default to "3.1" so legacy runs trip the
        # notice too (the old `if exists()` guard let them synth silently).
        wrote_for = workspace / _SCRIPT_TTS_FAMILY_SIDECAR
        sf = wrote_for.read_text().strip() if wrote_for.exists() else "3.1"
        mf = tts_family(chosen)
        if sf != mf:
            log.event(
                f"TTS family mismatch: scripts authored for {sf} palette, "
                f"synthesizing with {chosen} (family {mf}) — synthesize.py will "
                f"rewrite/strip {sf}-only audio tags so they are never voiced"
            )

    proc = subprocess.run(
        ["uv", "run", str(ROOT / "synthesize.py"), str(target)],
        cwd=str(ROOT), capture_output=False, text=True, env=env,
    )
    return proc.returncode == 0


def stage_audio_qa(workspace: Path, log: PipelineLog, only_episode: int | None = None) -> bool:
    scripts_dir = workspace / "scripts"
    if only_episode:
        # Exact-match episode number: ep_1_pro.{mp3,m4a} must NOT catch ep_10_pro.
        # m4a is the post-Track-B default; mp3 stays for legacy series.
        pattern = re.compile(rf"^ep_{only_episode}_[A-Za-z]+\.(?:mp3|m4a)$")
        candidates = sorted(
            f for f in (
                *scripts_dir.glob("ep_*.mp3"),
                *scripts_dir.glob("ep_*.m4a"),
            ) if pattern.match(f.name)
        )
        if not candidates:
            log.error(f"No audio for episode {only_episode}")
            return False
        target = candidates[0]
    else:
        target = scripts_dir

    report = workspace / "audio_qa.json"
    cmd = ["uv", "run", str(ROOT / "audio_qa.py"), str(target), "--report", str(report)]
    if _audio_qa_strict(workspace):
        cmd.append("--strict")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    if proc.returncode != 0:
        log.error(f"audio_qa found FAIL findings — see {report}")
        return False
    log.event(f"audio_qa passed — report at {report.relative_to(workspace)}")
    return True


def stage_subtitle(workspace: Path, log: PipelineLog, only_episode: int | None = None) -> bool:
    scripts_dir = workspace / "scripts"
    target = scripts_dir / f"ep_{only_episode}_script.md" if only_episode else scripts_dir

    proc = subprocess.run(
        ["uv", "run", str(ROOT / "subtitle.py"), str(target)],
        cwd=str(ROOT), capture_output=False, text=True, env=_UNBUF_ENV,
    )
    return proc.returncode == 0


def _emit_cover_usage(workspace: Path) -> None:
    """Append an image_usage provenance event to events.jsonl (same wrapped shape
    as run_claude's stream tee). Pexels is free → cost_usd 0; the event records
    which photo backs the cover so the dashboard / cost breakdown can show it."""
    meta_path = workspace / "plan" / "cover_meta.json"
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            _LOGGER.debug("Failed to parse cover/metadata JSON: %s", meta_path)
            meta = {}
    event = {
        "type": "image_usage",
        "source": meta.get("source", "pexels"),
        "pexels_id": meta.get("pexels_id"),
        "count": 1,
        "cost_usd": 0.0,  # Pexels free license — no per-image charge
    }
    wrapped = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "stage_label": "Cover",
        "event": event,
    }
    with (workspace / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(wrapped, ensure_ascii=False) + "\n")


def stage_cover(workspace: Path, log: PipelineLog) -> bool:
    """Series cover art. The agent reads the theme from overview.md, then drives
    the cover_tool.py funnel (search → contact → render) to pick a theme-relevant
    Pexels photo and render plan/cover.png with the duo treatment. The finished
    cover.png is picked up + uploaded by publish (ops/podcast_upload.sh).

    Idempotent: skips if plan/cover.png exists. Series-wide (one per series, so
    --only-episode skips it via _SERIES_WIDE_STAGES). Loud-fails if the agent
    finishes without producing cover.png (never leaves a half-state silently).
    """
    cover_png = workspace / "plan" / "cover.png"
    if cover_png.exists():
        log.event("cover: plan/cover.png exists — skip (idempotent)")
        return True
    if not run_claude(_prompt("cover", read_mode(workspace)), workspace, "Cover", log):
        return False
    if not cover_png.exists():
        log.error("cover: agent finished but plan/cover.png missing — no cover produced")
        return False
    _emit_cover_usage(workspace)
    log.event("cover: plan/cover.png produced")
    return True


# 375MB+ over a slow uplink can take a while; cap so a hung upload can't block
# the pipeline forever (a failed attempt retries).
_PUBLISH_TIMEOUT = 1800  # seconds


def _verify_published(series_id: str) -> bool:
    """Read the bucket's index.json and confirm series_id is present — proves
    the upload actually made the series visible to /api/podcasts, not just
    that the upload command exited 0."""
    bucket = os.getenv("PODCAST_BUCKET")
    if not bucket:
        return False
    import boto3  # local import: keeps non-publish runs off boto3
    kwargs = {"region_name": os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1")}
    endpoint = os.getenv("PODCAST_BUCKET_ENDPOINT_URL") or None
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    s3 = boto3.client("s3", **kwargs)
    try:
        body = s3.get_object(Bucket=bucket, Key="index.json")["Body"].read()
        idx = json.loads(body)
    except Exception as e:  # noqa: BLE001 — verify is best-effort; miss → retry/fail
        print(f"[verify] {type(e).__name__}: {e}", flush=True)
        return False
    return isinstance(idx, list) and any(
        isinstance(e, dict) and e.get("id") == series_id for e in idx
    )


def stage_publish(workspace: Path, log: PipelineLog, *, max_retries: int = 3) -> bool:
    """Closed-loop publish: upload the finished workspace to S3 via
    ops/podcast_upload.sh, then verify the series is live in the catalog index.
    Runs automatically as the terminal stage so a completed pipeline
    self-publishes — no manual dashboard upload, no silent disk↔S3 drift.

    Loud-fails (returns False, never crashes) when PODCAST_BUCKET / AWS creds
    are absent from the environment, or when the series can't be confirmed in
    the index after max_retries upload+verify attempts.
    """
    if not os.getenv("PODCAST_BUCKET"):
        log.error("publish: PODCAST_BUCKET not set — export it + AWS creds before "
                  "running the pipeline so the finished series uploads to S3.")
        return False

    upload_sh = (ROOT.parent.parent / "ops" / "podcast_upload.sh").resolve()
    if not upload_sh.is_file():
        log.error(f"publish: upload script missing at {upload_sh}")
        return False

    series_id = workspace.name
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            proc = subprocess.run(
                ["bash", str(upload_sh), str(workspace.resolve())],
                cwd=str(ROOT.parent.parent), capture_output=False, text=True,
                env=os.environ.copy(), timeout=_PUBLISH_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # A hung upload (network stall / half-dead creds) must not block the
            # pipeline forever — treat as a failed attempt and retry.
            log.error(f"publish attempt {attempt}/{max_retries} timed out after "
                      f"{_PUBLISH_TIMEOUT}s")
            if attempt < max_retries:
                time.sleep(backoff)
                backoff *= 2
            continue
        if proc.returncode == 0 and _verify_published(series_id):
            log.event(f"publish: {series_id} live in S3 catalog (attempt {attempt})")
            return True
        log.error(f"publish attempt {attempt}/{max_retries} failed "
                  f"(upload rc={proc.returncode}, verified={proc.returncode == 0})")
        if attempt < max_retries:
            time.sleep(backoff)
            backoff *= 2

    log.error(f"publish: {series_id} not confirmed in S3 index after {max_retries} attempts")
    return False


# ─── Status ───


def _try_parse_json(line: str) -> dict | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        _LOGGER.debug("non-JSON status line skipped: %r (%s)", line, exc)
        return None


def show_status(workspace: Path) -> None:
    try:
        stages = workflow_stage_order(resolve_workspace_workflow(workspace, None))
    except ValueError as exc:
        _LOGGER.warning("Using legacy stage list for %s (workflow parse failed: %s)", workspace, exc)
        stages = STAGES
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
    for stage in stages:
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

            audio_files = list((workspace / "scripts").glob(f"ep_{n}_*.mp3")) \
                        + list((workspace / "scripts").glob(f"ep_{n}_*.m4a"))
            if audio_files:
                f = audio_files[0]
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
        errors = [obj for l in lines if '"error"' in l for obj in [_try_parse_json(l)] if obj]
        if errors:
            print(f"\n  Recent Errors ({len(errors)}):")
            for e in errors[-5:]:
                print(f"    [{e.get('ts', '?')}] {e.get('msg', '?')}")

    # Suggest next action + quick reference
    ws = workspace
    resume = detect_resume_point(workspace, stages)

    print(f"\n  ── Quick Actions ──")
    if resume < len(stages):
        print(f"  Resume:          uv run pipeline.py {ws}")
        print(f"  Resume from:     uv run pipeline.py {ws} --skip-to {stages[resume]}")
    else:
        print(f"  ✓ All stages complete!")

    print(f"\n  ── Stage Control ──")
    print(f"  Run one stage:   uv run pipeline.py {ws} --only-stage <stage>")
    print(f"  Run until:       uv run pipeline.py {ws} --stop-after <stage>")
    print(f"  Run from:        uv run pipeline.py {ws} --skip-to <stage>")
    print(f"  Single episode:  uv run pipeline.py {ws} --only-stage scriptwrite --only-episode 3")
    print(f"  Parallel:        uv run pipeline.py {ws} --parallel 5")

    print(f"\n  ── Stages ──")
    for i, s in enumerate(stages, 1):
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
        epilog="""stages (in order; ┃ = human approval gate, run pauses until approved):
   1. prep          extract + classify chapters from EPUB
   2. analyst       deep book analysis (structure, arguments, quotes)
   3. architect     production plan (episodes, hosts, pacing)
   4. plan-review   QA gate — verify plan completeness
   5. enricher-gap  identify where external research is needed
   6. enricher      web search to fill research gaps
  ┃ .plan_approved  ── approve the plan before scripts are written ──
   7. scriptwrite   parallel dialogue script generation
   8. series-polish cross-episode continuity polish
   9. script-review QA gate — verify script quality
  ┃ .script_approved ── approve scripts before audio is synthesized (TTS $$) ──
  10. tts-prep       prepare scripts for TTS
  11. synthesize     TTS audio generation (Vertex AI Gemini)
  12. audio-qa       audio quality check
  13. subtitle       word-level subtitle alignment
  14. cover          series cover art
  15. publish        upload workspace to S3 + verify catalog

examples:
  uv run pipeline.py book.epub                          # run until plan gate, then pause
  uv run pipeline.py workspaces/my_book/                # auto-resume to next gate / finish
  uv run pipeline.py workspaces/my_book/ --status       # show progress + commands

  # approval gates
  touch workspaces/my_book/.plan_approved               # approve plan → next run writes scripts
  uv run pipeline.py ws/ --ignore-gates                 # run straight through, no pausing

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
    parser.add_argument(
        "target", nargs="+",
        help="One EPUB / workspace dir for a single book; OR multiple EPUBs (in "
        "reading order) with --saga to build one continuous multi-book feed.",
    )
    parser.add_argument(
        "--saga", metavar="TITLE",
        help="Group the given EPUBs (reading order = argument order) into one "
        "saga workspace titled TITLE. Implies --mode saga; requires --spoiler-mode.",
    )
    parser.add_argument("--parallel", type=int, default=3, help="Max parallel workers (default: 3)")
    parser.add_argument("--only-episode", type=int, help="Only process this episode number")
    stage_choices = all_workflow_stage_names()
    parser.add_argument("--skip-to", choices=stage_choices, help="Start from this stage")
    parser.add_argument("--stop-after", choices=stage_choices, help="Stop after this stage")
    parser.add_argument("--only-stage", choices=stage_choices, help="Run exactly one stage")
    parser.add_argument(
        "--mode", choices=list(archetypes.ARCHETYPES),
        help="Production archetype (default: nonfiction). Selects the prompt set. "
        "On resume the workspace's saved .mode wins; a conflicting --mode errors.",
    )
    parser.add_argument(
        "--spoiler-mode", choices=["readalong", "retrospective"],
        help="Spoiler policy for narrative archetypes (required for fiction/saga, "
        "forbidden otherwise).",
    )
    parser.add_argument(
        "--tts-model", choices=list(ALLOWED_TTS_MODELS),
        help="TTS model to synthesize with, frozen for the workspace at creation "
        "(written to .tts_model, read back by the synthesize stage). On resume the "
        "saved sidecar wins; a conflicting --tts-model errors. Omit to use the "
        "synthesize.py env default.",
    )
    parser.add_argument(
        "--agent-profile", choices=list(AGENT_PROFILES),
        help="Stage 1-10 coding-agent billing/profile. claude uses the normal "
        "Claude Code account. Can also be set with PODCAST_AGENT_PROFILE.",
    )
    parser.add_argument(
        "--agent-model",
        help="Stage 1-10 agent model override. Default: claude=opus[1m]. "
        "PODCAST_AGENT_MODEL also works; legacy PODCAST_CLAUDE_MODEL remains "
        "supported.",
    )
    parser.add_argument(
        "--workflow-version",
        choices=available_workflow_versions(),
        help="Versioned workflow contract to use for prompts, validators and "
        "provenance. Fresh workspaces default to v1; resume uses the saved "
        "workflow_manifest.json value.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass prereq marker check when using --skip-to / --only-stage. "
        "Use only after manually verifying earlier stages' artifacts exist.",
    )
    parser.add_argument(
        "--ignore-gates",
        action="store_true",
        help="Run straight through the plan/script approval gates without "
        "pausing (restores the old fully-autonomous end-to-end run).",
    )
    parser.add_argument("--status", action="store_true", help="Show workspace status and exit")
    parser.add_argument("--dry-run", action="store_true", help="Extract EPUB and setup workspace only")
    args = parser.parse_args()

    try:
        configure_agent(args.agent_profile, args.agent_model)
    except ValueError as e:
        parser.error(str(e))

    if args.only_stage:
        if args.skip_to or args.stop_after:
            parser.error("--only-stage cannot be combined with --skip-to or --stop-after")
        args.skip_to = args.only_stage
        args.stop_after = args.only_stage

    # Saga vs single-book input resolution. A saga is the ONLY case that takes
    # multiple targets; everything else takes exactly one (EPUB or workspace dir).
    saga_epubs: list[Path] | None = None
    epub_path = workspace = None
    if args.saga is not None:
        if args.mode and args.mode != "saga":
            parser.error(f"--saga implies --mode saga; got --mode {args.mode}")
        args.mode = "saga"
        if len(args.target) < 2:
            parser.error("--saga needs at least 2 EPUBs (reading order = argument order)")
        saga_epubs = []
        for t in args.target:
            p = Path(t)
            if not (p.is_file() and p.suffix.lower() == ".epub"):
                parser.error(f"--saga targets must be EPUB files; got {t}")
            saga_epubs.append(p)
    else:
        if len(args.target) != 1:
            parser.error("multiple targets are only allowed with --saga")
        epub_path, workspace = resolve_target(args.target[0])

    # Build the saga workspace up-front (extract every EPUB, group + flatten).
    # After this the saga is just a normal workspace the 13 stages run against.
    if saga_epubs is not None:
        workspace = find_saga_workspace(args.saga, saga_epubs)
        if workspace is None:
            print(f"Saga: {args.saga} ({len(saga_epubs)} books)")
            books = []
            for i, p in enumerate(saga_epubs, 1):
                meta, chapters = extract_epub(str(p))
                print(f"  {i}. {meta['title']} — {meta['total_raw_chapters']} ch, {meta['total_raw_chars']:,} chars")
                books.append((meta, chapters))
            workspace = setup_saga_workspace(args.saga, books)
            print(f"  Workspace: {workspace}")
        else:
            print(f"Resuming saga: {args.saga} → {workspace}")

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

    # Resolve workspace
    if workspace:
        print(f"Workspace: {workspace}")
    elif epub_path:
        if args.skip_to:
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

    saved_agent_profile, saved_agent_model = read_agent_sidecars(workspace)
    if not args.agent_profile and not args.agent_model and saved_agent_profile:
        try:
            configure_agent(saved_agent_profile, saved_agent_model)
        except ValueError as e:
            parser.error(str(e))
    else:
        write_agent_sidecars(workspace)

    # Resolve production mode. Fresh setup takes it from argv (default nonfiction);
    # resume takes it from the saved sidecar, and a conflicting --mode is an error
    # (mixing prompt sets mid-run corrupts the workspace). The sidecar is the
    # single source of truth every stage reads via read_mode().
    saved_mode = read_mode(workspace) if (workspace / _MODE_SIDECAR).exists() else None
    if saved_mode is not None:
        if args.mode and args.mode != saved_mode:
            parser.error(
                f"workspace was created with --mode {saved_mode}; cannot resume as "
                f"--mode {args.mode}. Omit --mode to use the saved one."
            )
        effective_mode = saved_mode
        effective_spoiler = read_spoiler_mode(workspace)
        # Allow tightening/setting spoiler mode on resume only if not yet set.
        if args.spoiler_mode and effective_spoiler is None:
            effective_spoiler = args.spoiler_mode
    else:
        effective_mode = args.mode or archetypes.DEFAULT_ARCHETYPE
        effective_spoiler = args.spoiler_mode

    spoiler_err = archetypes.validate_spoiler_mode(effective_mode, effective_spoiler)
    if spoiler_err:
        parser.error(spoiler_err)
    write_mode_sidecar(workspace, effective_mode, effective_spoiler)
    if effective_mode != archetypes.DEFAULT_ARCHETYPE:
        label = archetypes.get(effective_mode)["label"]
        print(f"Mode: {effective_mode} ({label})"
              + (f" · spoiler={effective_spoiler}" if effective_spoiler else ""))
    write_agent_sidecars(workspace)
    print(f"Agent: {AGENT_PROFILE} ({MODEL})")

    try:
        workflow_version = resolve_workspace_workflow(workspace, args.workflow_version)
        configure_workflow(workflow_version)
    except ValueError as e:
        parser.error(str(e))
    print(f"Workflow: {workflow_version}")
    stages = workflow_stage_order(workflow_version)
    for selected in (args.skip_to, args.stop_after):
        if selected and selected not in stages:
            parser.error(f"stage {selected!r} is not in workflow {workflow_version} stage_order")

    # Determine stage range from the selected workflow, not the v1 global list.
    start_idx = stages.index(args.skip_to) if args.skip_to else 0
    stop_idx = stages.index(args.stop_after) if args.stop_after else len(stages) - 1

    # Explicit start index for approval-gate bypass — set ONLY when the user
    # passed --skip-to / --only-stage (a deliberate drive past the gate). Stays
    # None for auto-resume runs so the gate still holds (see approval_gate_block).
    explicit_skip_idx = stages.index(args.skip_to) if args.skip_to else None

    if start_idx > stop_idx:
        parser.error(f"--skip-to {args.skip_to} is after --stop-after {args.stop_after}")

    if not args.skip_to:
        resume = detect_resume_point(workspace, stages)
        if resume > 0:
            start_idx = max(start_idx, resume)
            if start_idx < len(stages):
                print(f"Auto-resume: {stages[start_idx]} (stages 0-{resume-1} have completion markers)")

    # Freeze the TTS model the same way as .mode: fresh setup takes it from argv,
    # resume reads the saved sidecar and a conflicting --tts-model is an error.
    saved_tts = read_tts_model(workspace)
    if saved_tts is not None:
        if args.tts_model and args.tts_model != saved_tts:
            parser.error(
                f"workspace was created with --tts-model {saved_tts}; cannot resume "
                f"as --tts-model {args.tts_model}. Omit it to use the saved one."
            )
    elif args.tts_model:
        (workspace / _TTS_MODEL_SIDECAR).write_text(args.tts_model)
        print(f"TTS model: {args.tts_model} (family {tts_family(args.tts_model)})")

    write_workflow_manifest(
        workspace,
        workflow_version=workflow_version,
        agent_profile=AGENT_PROFILE,
        agent_model=MODEL,
        tts_model=read_tts_model(workspace) or DEFAULT_TTS_MODEL,
    )

    # Saga preflight: build_saga_context() raises on a corrupt series.md (fail
    # closed — never run a saga spoiler-blind). Validate it ONCE here with a
    # friendly error + resume hint, before any stage spends tokens, instead of
    # surfacing a raw traceback deep inside stage_prep.
    if is_saga(workspace):
        try:
            build_saga_context(workspace)
        except (OSError, ValueError) as e:
            print(f"\nERROR: saga manifest is unreadable — {e}")
            print(f"  Workspace: {workspace}")
            print(f"  Fix {workspace}/series.md (it needs a valid READING_ORDER block), then re-run.")
            sys.exit(1)

    if args.dry_run:
        print("\n[Dry run] Workspace created.")
        show_status(workspace)
        return

    # If spawned by the dashboard JobTracker, drop a sidecar so the dashboard
    # can pair this pipeline run with the workspace it'll end up writing into.
    # JobTracker injects PODCAST_JOB_ID into the env; absent for manual CLI runs.
    _job_id = os.getenv("PODCAST_JOB_ID")
    if _job_id:
        try:
            (workspace / ".pipeline_job_id").write_text(_job_id)
        except OSError as err:
            # sidecar is best-effort; never block the actual pipeline
            print(f"[pipeline] unable to write .pipeline_job_id={_job_id}: {err}", file=sys.stderr)

    # Auto-start dashboard + open browser — single-command UX.
    # Idempotent: no-op if already running. Skip with PODCAST_NO_DASHBOARD=1.
    _ensure_dashboard_running(workspace)

    # Prereq marker check: --skip-to X (incl. --only-stage X which rewrites
    # to skip_to=stop_after=X) requires earlier workflow stages all to have completion
    # markers. Catches the footgun where user jumps to e.g. scriptwrite on a
    # workspace where architect/plan-review never ran — downstream stage will
    # crash trying to read missing plan/overview.md. --force opts out for
    # advanced cases (e.g. cherry-picked workspace, manual artifact stitching).
    if args.skip_to and start_idx > 0 and not args.force:
        missing = [s for s in stages[:start_idx] if not stage_done(workspace, s)]
        if missing:
            print(f"ERROR: --skip-to {args.skip_to} requires earlier stages completed.")
            print(f"  Missing markers: {', '.join(missing)}")
            print(f"  Either resume from the earliest missing stage:")
            print(f"    uv run pipeline.py {workspace} --skip-to {missing[0]}")
            print(f"  Or pass --force to override (downstream may fail on absent artifacts).")
            print(f"  See .claude/skills/podcast/SKILL.md §階段控制 for details.")
            sys.exit(1)

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
        "series-polish": lambda: stage_series_polish(workspace, log),
        "script-review": lambda: stage_script_review(workspace, log, args.parallel, args.only_episode),
        "tts-prep": lambda: stage_tts_prep(workspace, log),
        "synthesize": lambda: stage_synthesize(workspace, log, args.only_episode),
        "audio-qa": lambda: stage_audio_qa(workspace, log, args.only_episode),
        "subtitle": lambda: stage_subtitle(workspace, log, args.only_episode),
        "cover": lambda: stage_cover(workspace, log),
        "publish": lambda: stage_publish(workspace, log),
    }
    unimplemented = [s for s in stages if s not in stage_funcs]
    if unimplemented:
        parser.error(
            f"workflow {workflow_version} references unimplemented stage(s): "
            f"{', '.join(unimplemented)}"
        )

    stages_to_run = stages[start_idx:stop_idx + 1]

    # Drop series-wide stages (series-polish / publish) from a bare single-episode
    # full loop: they re-process the WHOLE series, never honoring --only-episode.
    # Filtering here (vs loop `continue`) keeps step x/y counts honest and never
    # writes their completion markers, so a later bare full-series run still runs
    # them. Explicit --only-stage series-polish/publish is unaffected (the stage
    # IS the selection → _should_skip returns False).
    skipped_series_wide = [
        s for s in stages_to_run if _should_skip_for_only_episode(s, args)
    ]
    if skipped_series_wide:
        stages_to_run = [s for s in stages_to_run if s not in skipped_series_wide]
        for s in skipped_series_wide:
            print(
                f"  ↷ skip {s}: series-wide stage incompatible with --only-episode "
                f"{args.only_episode}; run without --only-episode to {s} the whole series"
            )

    total_stages = len(stages_to_run)

    print(f"\nPlan: {' → '.join(stages_to_run)}")
    if args.only_episode:
        print(f"Episode filter: {args.only_episode}")
    print()

    for i, stage_name in enumerate(stages_to_run, 1):
        # Human-in-the-loop approval gate: pause (exit 0) before entering an
        # expensive phase until the producer approves the prior one.
        blocked_by = approval_gate_block(
            stage_name, workspace,
            explicit_skip_idx=explicit_skip_idx,
            ignore_gates=args.ignore_gates,
            stages=stages,
        )
        if blocked_by:
            phase = "plan" if blocked_by == ".plan_approved" else "script"
            next_phase = "scripts" if phase == "plan" else "audio"
            elapsed = time.time() - t0
            log.gate_wait(stage_name, blocked_by, phase)
            print(f"\n{'='*60}")
            print(f"  ⏸ AWAITING {phase.upper()} APPROVAL ({elapsed:.0f}s so far)")
            print(f"  {phase.capitalize()} phase complete — review it, then approve to produce {next_phase}:")
            print(f"    Dashboard: click ▶ APPROVE in the episode panel")
            print(f"    CLI:       touch {workspace}/{blocked_by} && uv run pipeline.py {workspace}")
            print(f"    Bypass:    uv run pipeline.py {workspace} --ignore-gates")
            print(f"  Workspace: {workspace}")
            print(f"{'='*60}")
            return  # paused, not failed

        stage_t0 = time.time()
        log.stage_start(stage_name, step=f"{i}/{total_stages}")
        input_artifacts = capture_stage_inputs(workspace, stage_name, args.only_episode)

        success = stage_funcs[stage_name]()
        stage_elapsed = time.time() - stage_t0
        write_stage_provenance(
            workspace,
            stage=stage_name,
            success=success,
            elapsed_s=stage_elapsed,
            input_artifacts=input_artifacts,
            only_episode=args.only_episode,
        )

        if not success:
            elapsed = time.time() - t0
            log.stage_end(stage_name, success=False, elapsed=stage_elapsed, only_episode=bool(args.only_episode))
            print(f"\n{'='*60}")
            print(f"  PIPELINE FAILED at: {stage_name} ({elapsed:.0f}s total)")
            print(f"  Workspace: {workspace}")
            print(f"  Resume: uv run pipeline.py {workspace} --skip-to {stage_name}")
            print(f"  Debug: cat {workspace}/pipeline_log.jsonl | python -m json.tool")
            print(f"{'='*60}")
            sys.exit(1)

        log.stage_end(stage_name, success=True, elapsed=stage_elapsed, only_episode=bool(args.only_episode))

    elapsed = time.time() - t0

    # Final summary
    audio_files = sorted(
        list((workspace / "scripts").glob("*.mp3"))
        + list((workspace / "scripts").glob("*.m4a"))
    )
    srts = sorted((workspace / "scripts").glob("*.srt"))
    total_audio_mb = sum(f.stat().st_size for f in audio_files) / (1024 * 1024)

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE — {elapsed:.0f}s")
    print(f"  Stages: {' → '.join(stages_to_run)}")
    print(f"  Workspace: {workspace}")
    if audio_files:
        print(f"  Audio: {len(audio_files)} files, {total_audio_mb:.1f} MB")
        for f in audio_files:
            print(f"    {f.name} ({f.stat().st_size / (1024 * 1024):.1f} MB)")
    if srts:
        print(f"  Subtitles: {len(srts)} files")

    if stop_idx < len(stages) - 1:
        print(f"\n  Next: uv run pipeline.py {workspace} --skip-to {stages[stop_idx + 1]}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
#     "python-multipart",
# ]
# ///
"""Podcast pipeline monitor — FastAPI dashboard serving SSE from events.jsonl.

Usage:
    uv run monitor/server.py                           # all workspaces selectable
    uv run monitor/server.py --ws the_let_them_theory  # pre-select
    uv run monitor/server.py --port 8765

Then open http://localhost:8765 in a browser.

Streams:
  - pipeline_log.jsonl (stage boundaries, errors)
  - events.jsonl (per-stage claude tool-use + usage) — only if PODCAST_VERBOSE=1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Make `monitor/` importable when launched as a script via `uv run monitor/server.py`.
sys.path.insert(0, str(Path(__file__).parent))
# Saga (multi-book continuous-feed) modules live one level up in lab/podcast/.
sys.path.insert(0, str(Path(__file__).parent.parent))
from cost import aggregate_workspace  # noqa: E402
from jobs import tracker as jobs, JobLimitReached  # noqa: E402
import remote as remote_ops  # noqa: E402
import saga  # noqa: E402  — parse series.md for the workspace summary
import archetypes  # noqa: E402  — validate spoiler_mode for a saga upload

# Cap pipeline upload at 200MB — typical EPUB is <10MB; anything 200MB+ is
# almost certainly someone uploading the wrong file by accident. Protects
# the 2GB VPS from getting wedged by a runaway multipart body.
MAX_EPUB_BYTES = int(os.getenv("PODCAST_MAX_EPUB_BYTES", str(200 * 1024 * 1024)))

ROOT = Path(__file__).parent.parent
WORKSPACES_DIR = ROOT / "workspaces"
STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_STAGING = ROOT / "monitor" / ".uploads"
UPLOAD_STAGING.mkdir(parents=True, exist_ok=True)

# Workspace name regex — same constraint as backend _SERIES_ID_RE plus a
# safety guard against `..` / absolute paths sneaking in via FastAPI path params.
_WS_NAME_RE = re.compile(r"\A[a-z0-9_]+\Z")
# Pipeline stage order (mirror of pipeline.py STAGES) — used for the
# marker-based resume point. Keep in sync with pipeline.py.
_STAGES_ORDERED = (
    "prep", "analyst", "architect", "plan-review",
    "enricher-gap", "enricher", "scriptwrite",
    "series-polish", "script-review",
    "tts-prep", "synthesize", "audio-qa", "subtitle",
)
_STAGE_NAMES = set(_STAGES_ORDERED)


def _resolve_ws(ws_name: str) -> Path:
    """Validate + resolve a workspace name. 404 on miss / 400 on bad shape."""
    if not _WS_NAME_RE.match(ws_name):
        raise HTTPException(400, f"invalid workspace name {ws_name!r}")
    ws = WORKSPACES_DIR / ws_name
    # Defense-in-depth: confirm resolved path is still under WORKSPACES_DIR
    # even though the regex already blocks `..` and `/`.
    try:
        ws.resolve(strict=True).relative_to(WORKSPACES_DIR.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, f"workspace {ws_name!r} not found") from exc
    if not ws.is_dir():
        raise HTTPException(404, f"workspace {ws_name!r} not found")
    return ws


app = FastAPI(title="Podcast Pipeline Monitor")


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """Force the dashboard's HTML/JS/CSS to always revalidate.

    Default browser caching of `static/app.js` was the worst class of bug to
    debug — Phase 4 added modal close handlers, the user's browser kept
    serving the Phase 3 app.js, and ✕ / CANCEL silently no-op'd because the
    listeners weren't attached. For a single-user localhost dashboard,
    aggressive no-cache is cheap and removes a whole category of "did you
    hard-refresh?" surprise.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def _active_job_for_ws(ws_name: str, running: dict | None = None) -> dict | None:
    """Return `{job_id,label,kind}` for a running job bound to this workspace,
    or None.

    Pairs jobs to workspaces via two routes (same logic the sidebar list uses):
      1. `metadata.workspace` — upload / rerun / approve / resume jobs know the
         workspace at spawn time (caller passed it in).
      2. `<ws>/.pipeline_job_id` sidecar — written by pipeline.py once it
         resolves EPUB→workspace, used by full-pipeline jobs whose spawn-time
         metadata only knows the EPUB filename.

    `running` may be passed in to amortize `jobs.list()` across many lookups
    (list_workspaces calls this once per ws); if omitted we fetch ourselves.
    Used both for the sidebar's `active_job` field and as the per-workspace
    concurrency guard on every spawn endpoint — two pipeline.py on the same
    workspace would race on markers/scripts/mp3s with no mutual exclusion.
    """
    if running is None:
        running = {j.id: j for j in jobs.list(limit=200) if j.status == "running"}
    # Route 1: explicit metadata.workspace.
    for j in running.values():
        if (j.metadata or {}).get("workspace") == ws_name:
            return {"job_id": j.id, "label": j.label, "kind": j.kind}
    # Route 2: sidecar.
    try:
        jid = (WORKSPACES_DIR / ws_name / ".pipeline_job_id").read_text().strip()
    except OSError:
        return None
    j = running.get(jid)
    return {"job_id": j.id, "label": j.label, "kind": j.kind} if j else None


@app.get("/api/workspaces")
def list_workspaces(full: bool = Query(False)):
    """List workspaces. `?full=1` returns rich summaries (status, progress,
    cost, episodes, last_updated) for the sidebar list view — single call
    avoids N+1 per-workspace fetches. Bare call still returns `[name, ...]`
    for back-compat with callers that only need names.
    """
    if not WORKSPACES_DIR.exists():
        return []
    names = sorted(p.name for p in WORKSPACES_DIR.iterdir() if p.is_dir())
    if not full:
        return names

    # Pair running jobs back to their workspaces via the shared helper. Fetch
    # the running-jobs map ONCE and pass it in so this stays O(jobs) for the
    # whole list instead of O(workspaces × jobs).
    running_jobs = {j.id: j for j in jobs.list(limit=200) if j.status == "running"}
    return [
        _workspace_summary(WORKSPACES_DIR / n, _active_job_for_ws(n, running_jobs))
        for n in names
    ]


# Total stage count, surfaced in the summary so the frontend can render
# progress without hardcoding the number (and stay correct if we add stages).
_STAGE_COUNT = len(_STAGE_NAMES)
# Final stage — when its done-marker exists, the whole workspace is "done".
_FINAL_STAGE = "subtitle"


def _scan_pipeline_log_status(plog: Path, stages_done: set[str]) -> bool:
    """Return True if any stage's *latest* stage_end was success=false AND that
    stage lacks a done marker (i.e. the failure was never resolved by a rerun).

    A stage that failed once then succeeded on rerun gets its done marker
    written, so `stages_done` membership already absolves it — we only flag
    truly-unresolved failures. Reading the tail (last 64KB) is sufficient:
    a stage_end is one line, even a verbose run rarely produces >64KB after
    the latest failure.
    """
    if not plog.exists():
        return False
    try:
        size = plog.stat().st_size
        with plog.open("rb") as f:
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False

    # Track latest stage_end success-flag per stage from the tail window.
    latest: dict[str, bool] = {}
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "stage_end":
            stage = obj.get("stage")
            if stage:
                latest[stage] = bool(obj.get("success", True))

    return any(
        success is False and stage not in stages_done
        for stage, success in latest.items()
    )


# ─── Milestone progress (artifact-derived, NOT marker-derived) ──────────────
#
# Stage done-markers (.stage_<n>_done) are the pipeline's self-accounting and
# DRIFT from reality: a rerun drops a marker, a partial restore loses them,
# a manual clean wipes them — while the actual audio/scripts survive. Real
# data proved markers are near-INVERSELY correlated with "how close to a
# finished product": `flow` had 0 markers but 8 finished mp3s, while four
# other workspaces showed 9/13 markers with zero audio (scripts only).
#
# So progress is derived from ARTIFACTS, the only trustworthy source. The
# producer's mental model isn't 13 stages — it's four gates:
#     PLAN → SCRIPT → AUDIO → SUBTITLE (shippable)
# Each gate's completion ratio is (artifacts present / target episode count).
# The frontend renders these as four depth-shaded segments of one bar.
_MILESTONE_KEYS = ("plan", "script", "audio", "subtitle")


def _milestones(ws: Path) -> tuple[list[dict], float]:
    """Derive the four production gates from on-disk artifacts.

    Returns (milestones, overall_progress) where milestones is a list of
    {key,label,done,total,ratio} (one per gate, in pipeline order) and
    overall_progress is the 0..1 bar fill = mean of the four ratios.

    Target episode count = max(planned episodes, scripts, audio, subtitle) so
    a gate ratio never exceeds 1.0 even when, say, audio was synthesized for
    more episodes than the plan dir currently lists.
    """
    scripts = ws / "scripts"
    plan_eps = ws / "plan" / "episodes"

    n_plan_eps = len(list(plan_eps.glob("ep_*.md"))) if plan_eps.is_dir() else 0
    if scripts.is_dir():
        n_script = sum(1 for _ in scripts.glob("ep_*_script.md"))
        n_audio = sum(
            1 for f in scripts.glob("ep_*.mp3")
            if re.match(r"ep_\d+_(pro|flash)\.mp3$", f.name)
        )
        n_srt = sum(
            1 for f in scripts.glob("ep_*.srt")
            if re.match(r"ep_\d+_(pro|flash)\.srt$", f.name)
        )
    else:
        n_script = n_audio = n_srt = 0

    target = max(n_plan_eps, n_script, n_audio, n_srt)
    has_plan = (ws / "plan" / "overview.md").exists()

    # PLAN gate is binary on overview.md (the architect's deliverable); the
    # other three scale with episode artifacts against `target`.
    def ratio(done: int) -> float:
        return min(1.0, done / target) if target else 0.0

    milestones = [
        {"key": "plan", "label": "PLAN",
         "done": 1 if has_plan else 0, "total": 1,
         "ratio": 1.0 if has_plan else 0.0},
        {"key": "script", "label": "SCRIPT",
         "done": n_script, "total": target, "ratio": ratio(n_script)},
        {"key": "audio", "label": "AUDIO",
         "done": n_audio, "total": target, "ratio": ratio(n_audio)},
        {"key": "subtitle", "label": "SUBTITLE",
         "done": n_srt, "total": target, "ratio": ratio(n_srt)},
    ]
    overall = sum(m["ratio"] for m in milestones) / len(milestones)
    return milestones, overall


# ─── Per-episode artifact gates (durable, disk-derived) ─────────────────────
#
# The sidebar milestone bar aggregates four gates into ratios; the dashboard
# matrix needs the SAME four gates resolved PER EPISODE so the producer can see
# (and individually re-run) "ep 3 has a script but no audio". This is the only
# source that works for an *idle* workspace — live SSE `parallelEps` is empty
# the moment a run ends. Episode set = plan ∪ scripts so a script that exists
# without its plan (manual restore, deleted plan) is still surfaced.
_EP_PLAN_RE = re.compile(r"ep_0*(\d+)\.md$")
_EP_SCRIPT_RE = re.compile(r"ep_0*(\d+)_script\.md$")
_EP_AUDIO_RE = re.compile(r"ep_0*(\d+)_(pro|flash)\.mp3$")
_EP_SRT_RE = re.compile(r"ep_0*(\d+)_(pro|flash)\.srt$")


def _episode_status(ws: Path) -> list[dict]:
    """Per-episode gate status from on-disk artifacts.

    Returns a list (sorted by episode number) of
    {ep, plan, script, audio, subtitle, variant, audio_bytes}. `variant` /
    `audio_bytes` describe the chosen mp3 (pro preferred over flash) or are
    None when no audio exists. Decoy files (ep_N_review.md,
    ep_N_voice_preview.mp3) are excluded by the strict regexes.
    """
    plan_eps = ws / "plan" / "episodes"
    scripts = ws / "scripts"

    eps: set[int] = set()
    plan_set: set[int] = set()
    if plan_eps.is_dir():
        for f in plan_eps.glob("ep_*.md"):
            m = _EP_PLAN_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                plan_set.add(n)

    script_set: set[int] = set()
    srt_set: set[int] = set()
    audio: dict[int, dict] = {}  # ep -> {variant, bytes}; pro wins over flash
    if scripts.is_dir():
        for f in scripts.glob("ep_*_script.md"):
            m = _EP_SCRIPT_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                script_set.add(n)
        for f in scripts.glob("ep_*.mp3"):
            m = _EP_AUDIO_RE.match(f.name)
            if not m:
                continue  # skip ep_N_voice_preview.mp3 etc.
            n = int(m.group(1))
            variant = m.group(2)
            eps.add(n)
            cur = audio.get(n)
            if cur is None or (cur["variant"] == "flash" and variant == "pro"):
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                audio[n] = {"variant": variant, "bytes": size}
        for f in scripts.glob("ep_*.srt"):
            m = _EP_SRT_RE.match(f.name)
            if m:
                n = int(m.group(1))
                eps.add(n)
                srt_set.add(n)

    out: list[dict] = []
    for n in sorted(eps):
        a = audio.get(n)
        out.append({
            "ep": n,
            "plan": n in plan_set,
            "script": n in script_set,
            "audio": a is not None,
            "subtitle": n in srt_set,
            "variant": a["variant"] if a else None,
            "audio_bytes": a["bytes"] if a else None,
        })
    return out


# ─── Approval-gate states (Phase 2 gates → dashboard tri-state) ─────────────
#
# pipeline.py pauses at two gates (.plan_approved before scriptwrite,
# .script_approved before tts-prep). The dashboard derives each gate's state
# from disk so it works for idle workspaces AND legacy ones (artifacts but no
# approval markers — those count as de-facto approved because the next phase's
# artifacts only exist if the gate was crossed).
def _gate_states(
    ws: Path, *, has_plan: bool, n_script: int, n_audio: int, target: int,
) -> list[dict]:
    """Tri-state for the two approval gates: passed / awaiting / pending.

    gate1 (plan→script):
      passed   — n_script>0 OR .plan_approved exists (de-facto or explicit)
      awaiting — plan complete, no scripts yet, not approved
      pending  — plan not complete
    gate2 (script→audio):
      passed   — n_audio>0 OR .script_approved exists
      awaiting — scripts complete (n_script==target>0), no audio, not approved
      pending  — scripts not complete
    """
    if n_script > 0 or (ws / ".plan_approved").exists():
        g1 = "passed"
    elif has_plan:
        g1 = "awaiting"
    else:
        g1 = "pending"

    scripts_complete = target > 0 and n_script >= target
    if n_audio > 0 or (ws / ".script_approved").exists():
        g2 = "passed"
    elif scripts_complete:
        g2 = "awaiting"
    else:
        g2 = "pending"

    return [{"key": "plan", "state": g1}, {"key": "script", "state": g2}]


def _ensure_created(ws: Path) -> float:
    """Return the workspace 'added' timestamp (epoch seconds), backfilling it.

    Ground truth is a `.created` sidecar holding an epoch float. If absent
    (every pre-existing workspace), seed it from the directory's real birth
    time — st_birthtime on APFS/macOS, falling back to st_mtime on filesystems
    that don't track it (Linux ext4). Persisting it to `.created` shields the
    value from later rsync/restore operations that would otherwise reset the
    inode's birth time.
    """
    marker = ws / ".created"
    try:
        raw = marker.read_text().strip()
        return float(raw)
    except (OSError, ValueError):
        pass
    # No (or unreadable) sidecar — derive from inode birth time. Guard the
    # stat() too: the dir can vanish in the TOCTOU window between the route's
    # directory listing and this call. Returning 0.0 keeps the contract that
    # one bad workspace never breaks the whole sidebar list.
    try:
        st = ws.stat()
    except OSError:
        return 0.0
    bt = getattr(st, "st_birthtime", None)
    created = bt if bt is not None else st.st_mtime  # 0.0 birthtime is valid, don't `or`
    try:
        marker.write_text(f"{created}\n")
    except OSError:
        pass  # read-only mount etc. — still return the derived value
    return created


def _workspace_summary(ws: Path, active_job: dict | None) -> dict:
    """Cheap-ish per-workspace summary for the sidebar list.

    Cost: one `aggregate_workspace` call (reads events.jsonl) + small dir
    scans. For ~70 workspaces this stays under ~200ms total on warm cache;
    if it ever becomes a bottleneck, add mtime-keyed memoization at this
    layer (events.jsonl mtime alone is enough since cost only depends on it).
    """
    name = ws.name

    # ─── Stage progress (from done markers) — kept for status cascade + the
    # legacy n_stages_* fields; progress display now uses _milestones() below.
    stages_done: set[str] = set()
    for marker in ws.glob(".stage_*_done"):
        stages_done.add(marker.name.replace(".stage_", "").replace("_done", ""))
    n_done = len(stages_done)

    # ─── Episodes (synthesized audio count) — needed before status so the
    # "fresh" cascade can account for workspaces that have audio artifacts
    # but lost their done-markers (e.g. partial restore from backup).
    scripts = ws / "scripts"
    episodes: set[int] = set()
    if scripts.is_dir():
        for f in scripts.glob("ep_*.mp3"):
            m = re.match(r"ep_(\d+)_(pro|flash)\.mp3$", f.name)
            if m:
                episodes.add(int(m.group(1)))

    # ─── Artifact-derived progress + approval-gate states ───
    # Computed BEFORE status so the AWAITING state derives from the gate
    # frontier. Defensive: one bad glob/stat must never 500 the ?full=1 list.
    try:
        milestones, progress = _milestones(ws)
    except Exception:
        milestones, progress = [], 0.0
    _ms = {m["key"]: m for m in milestones}
    has_plan = bool(_ms.get("plan", {}).get("done"))
    n_script = int(_ms.get("script", {}).get("done", 0))
    n_audio = int(_ms.get("audio", {}).get("done", 0))
    target = int(_ms.get("script", {}).get("total", 0))
    try:
        gates = _gate_states(ws, has_plan=has_plan, n_script=n_script,
                             n_audio=n_audio, target=target)
    except Exception:
        gates = []
    _gate_state = {g["key"]: g["state"] for g in gates}

    # Marker-based resume point (what flagless `pipeline.py <ws>` auto-resume
    # would do) + whether it DRIFTS behind the artifacts. Markers can lag
    # reality (a rerun drops them, a restore loses them); if the resume stage
    # is earlier than the artifacts already reach, a plain resume would redo +
    # overwrite finished work. The dashboard surfaces resume_drift as a loud
    # warning on the RESUME action so the producer isn't surprised by a full
    # re-run + re-spend.
    resume_stage = next((s for s in _STAGES_ORDERED if s not in stages_done), None)
    resume_drift = False
    if resume_stage is not None:
        ridx = _STAGES_ORDERED.index(resume_stage)
        n_srt = int(_ms.get("subtitle", {}).get("done", 0))
        frontier = -1
        if has_plan:     frontier = max(frontier, _STAGES_ORDERED.index("architect"))
        if n_script > 0: frontier = max(frontier, _STAGES_ORDERED.index("scriptwrite"))
        if n_audio > 0:  frontier = max(frontier, _STAGES_ORDERED.index("synthesize"))
        if n_srt > 0:    frontier = max(frontier, _STAGES_ORDERED.index("subtitle"))
        resume_drift = frontier > ridx

    # ─── Status (running > done > failed > awaiting > idle > fresh) ───
    # "awaiting" = paused at an approval gate (Phase 2). Disk-derived so legacy
    # workspaces (artifacts but no *_approved markers) classify by the gate
    # frontier, not by marker presence.
    if active_job:
        status = "running"
    elif _FINAL_STAGE in stages_done:
        status = "done"
    elif _scan_pipeline_log_status(ws / "pipeline_log.jsonl", stages_done):
        status = "failed"
    elif "awaiting" in (_gate_state.get("plan"), _gate_state.get("script")):
        status = "awaiting"
    elif n_done == 0 and not episodes:
        # Truly untouched — no markers, no artifacts.
        status = "fresh"
    else:
        status = "idle"

    # ─── last_updated (max mtime among activity-indicating files) ───
    candidates: list[float] = []
    for rel in ("events.jsonl", "pipeline_log.jsonl"):
        p = ws / rel
        if p.exists():
            try:
                candidates.append(p.stat().st_mtime)
            except OSError:
                pass
    if scripts.is_dir():
        # Newest script artifact (mp3 / srt / json) — caught by stat on dir
        # iter; we cap to 200 entries so a synthesize stage with hundreds of
        # chunk files doesn't dominate.
        try:
            for f in list(scripts.iterdir())[:200]:
                try:
                    candidates.append(f.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            pass
    # Added-date — computed here so a truly-fresh workspace (no events /
    # scripts) can fall back to its creation time for last_updated instead of
    # ws.stat().st_mtime, which _ensure_created itself pollutes by writing the
    # .created sidecar. Both new calls are wrapped: per the file invariant, one
    # bad workspace must never break the whole sidebar list.
    try:
        created = _ensure_created(ws)
    except Exception:
        created = 0.0
    if not candidates:
        candidates.append(created)
    last_updated = max(candidates)

    # ─── Cost (totals only; full breakdown stays on /cost endpoint) ───
    # Split by *model family*, not by stage: the synthesize stage logs BOTH
    # Claude calls (labelled "Synthesize EP*") and Vertex tts_usage events
    # into by_stage["synthesize"], so attributing that whole bucket to TTS
    # would double-count any Claude work. by_model is the clean axis.
    total_usd = claude_usd = tts_usd = 0.0
    has_cost_data = False
    try:
        cost = aggregate_workspace(ws)
        total_usd = float(cost.get("total_usd") or 0.0)
        for model, mb in (cost.get("by_model") or {}).items():
            usd = float(mb.get("usd") or 0.0)
            ml = model.lower()
            # TTS bucket: must be an actual TTS model. Gemini base models
            # (gemini-2.5-pro, gemini-2.5-flash) are general LLMs; if a future
            # stage routes Claude → Gemini for non-audio work, those costs
            # belong in the LLM bucket, not "tts".
            if "tts" in ml:
                tts_usd += usd
            else:
                # Everything else (Claude, base Gemini, other LLMs) → claude_usd
                # bucket. Frontend labels this as "LLM" in the sidebar; the full
                # /cost endpoint still shows per-model breakdown.
                claude_usd += usd
        has_cost_data = (ws / "events.jsonl").exists() and total_usd > 0
    except Exception:
        # Never let a bad workspace break the whole sidebar list.
        pass

    # ─── Saga (multi-book continuous feed) fields ───
    # A workspace is a saga iff it carries a series.md manifest. All saga
    # parsing is wrapped: a legacy/single-book workspace, or a saga with a
    # malformed manifest, must degrade gracefully and never raise (this runs
    # once per workspace in the ?full=1 sidebar list).
    is_saga = (ws / "series.md").exists()
    saga_fields: dict = {"is_saga": is_saga}
    if is_saga:
        book_count = 0
        display = name
        try:
            books = saga.parse_series_manifest((ws / "series.md").read_text(encoding="utf-8"))
            book_count = len(books)
        except Exception:
            pass
        # Saga display title = the manifest's H1 ("# <title>"); fall back to the
        # workspace dir name if the heading is missing/unreadable.
        try:
            for line in (ws / "series.md").read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    display = line[2:].strip() or name
                    break
        except Exception:
            pass
        spoiler_mode = ""
        try:
            spoiler_mode = (ws / ".spoiler_mode").read_text(encoding="utf-8").strip()
        except Exception:
            pass
        saga_fields.update(
            book_count=book_count, spoiler_mode=spoiler_mode, display=display
        )

    return {
        "name": name,
        "status": status,
        **saga_fields,
        # Legacy marker fields — retained for back-compat; NOT used for the
        # progress bar anymore (see _milestones docstring for why markers lie).
        "stages_done": sorted(stages_done),
        "n_stages_done": n_done,
        "n_stages_total": _STAGE_COUNT,
        # Honest progress: four artifact-derived gates + overall fill.
        "milestones": milestones,
        # Two approval-gate tri-states (plan→script, script→audio) for the
        # sidebar's 3-phase / 2-gate track + the AWAITING status.
        "gates": gates,
        # Marker-based resume point + drift warning for the RESUME action.
        "resume_stage": resume_stage,
        "resume_drift": resume_drift,
        "progress": round(progress, 4),
        "episode_count": len(episodes),
        "created": created,
        "last_updated": last_updated,
        "total_usd": round(total_usd, 4),
        "claude_usd": round(max(claude_usd, 0.0), 4),
        "tts_usd": round(tts_usd, 4),
        "has_cost_data": has_cost_data,
        "active_job": active_job,
    }


@app.get("/api/workspace/{ws_name}/snapshot")
def snapshot(ws_name: str):
    """Initial state — all past events in order, for page load."""
    ws = _resolve_ws(ws_name)

    events: list[dict] = []
    for fname, kind in [("pipeline_log.jsonl", "pipeline"), ("events.jsonl", "stream")]:
        f = ws / fname
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append({"kind": kind, "data": obj})

    # Stage marker summary
    stages_done = sorted(
        f.name.replace(".stage_", "").replace("_done", "")
        for f in ws.glob(".stage_*_done")
    )

    return {
        "workspace": ws_name,
        "events": events,
        "stages_done": stages_done,
    }


@app.get("/api/workspace/{ws_name}/cost")
def cost(ws_name: str):
    """Aggregate USD spend across all stages — Claude (from CLI result events)
    + Vertex TTS (computed from per-batch tts_usage events)."""
    ws = _resolve_ws(ws_name)
    return aggregate_workspace(ws)


async def _tail(path: Path, last_size: int) -> tuple[str, int]:
    """Return (new_content, new_size) since last_size."""
    if not path.exists():
        return "", 0
    size = path.stat().st_size
    if size <= last_size:
        return "", last_size
    with path.open("rb") as f:
        f.seek(last_size)
        data = f.read(size - last_size)
    try:
        return data.decode("utf-8"), size
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), size


@app.get("/api/workspace/{ws_name}/stream")
async def stream(ws_name: str):
    """SSE — tails pipeline_log.jsonl + events.jsonl and emits new events live."""
    ws = _resolve_ws(ws_name)

    pipeline_log = ws / "pipeline_log.jsonl"
    events_log = ws / "events.jsonl"

    # Start at end of files (snapshot already delivered past events)
    pos_pipeline = pipeline_log.stat().st_size if pipeline_log.exists() else 0
    pos_events = events_log.stat().st_size if events_log.exists() else 0

    async def event_gen():
        nonlocal pos_pipeline, pos_events
        # Send heartbeat every 15s, poll files every 0.5s
        tick = 0
        while True:
            new_pipeline, pos_pipeline = await _tail(pipeline_log, pos_pipeline)
            new_events, pos_events = await _tail(events_log, pos_events)

            for line in new_pipeline.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield f"event: pipeline\ndata: {json.dumps(obj)}\n\n"

            for line in new_events.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield f"event: stream\ndata: {json.dumps(obj)}\n\n"

            tick += 1
            if tick % 30 == 0:  # 15s heartbeat (30 × 0.5s)
                yield ": heartbeat\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Per-episode asset serving (inline player) ──────────────────────────────


def _ep_file(ws: Path, ep: int, suffixes: tuple[str, ...]) -> Path | None:
    """Find `ep_<n>_<suffix>.<ext>` matching any (suffix, ext) pair.

    Naming in lab/podcast/scripts/ follows: ep_N_pro.mp3 / ep_N_pro.srt
    (or _flash for the flash model variant). We prefer _pro if both exist.
    """
    scripts = ws / "scripts"
    for sfx, ext in suffixes:
        candidates = sorted(scripts.glob(f"ep_{ep}_{sfx}.{ext}"))
        if candidates:
            return candidates[0]
    return None


@app.get("/api/workspace/{ws_name}/episode/{ep}/audio")
def episode_audio(ws_name: str, ep: int):
    ws = _resolve_ws(ws_name)
    if not 1 <= ep <= 999:
        raise HTTPException(400, "ep out of range")
    f = _ep_file(ws, ep, (("pro", "mp3"), ("flash", "mp3")))
    if not f:
        raise HTTPException(404, f"no audio for ep {ep}")
    # FileResponse handles Range requests, content-type, length headers, and
    # the conditional GET dance browsers do when seeking inside <audio>.
    return FileResponse(str(f), media_type="audio/mpeg", filename=f.name)


@app.get("/api/workspace/{ws_name}/episode/{ep}/subtitle")
def episode_subtitle(ws_name: str, ep: int):
    """Return the SRT as plain text so the client can parse for word-sync.
    iOS-style inline-in-metadata-json is overkill here — we're on localhost."""
    ws = _resolve_ws(ws_name)
    if not 1 <= ep <= 999:
        raise HTTPException(400, "ep out of range")
    f = _ep_file(ws, ep, (("pro", "srt"), ("flash", "srt")))
    if not f:
        raise HTTPException(404, f"no subtitle for ep {ep}")
    return PlainTextResponse(f.read_text(encoding="utf-8"), media_type="text/plain")


@app.get("/api/workspace/{ws_name}/episodes")
def workspace_episodes(ws_name: str):
    """List episodes that have audio + indicate subtitle availability.
    Powers the inline player's episode list — UI uses ep number to call
    /audio + /subtitle above.
    """
    ws = _resolve_ws(ws_name)
    scripts = ws / "scripts"
    if not scripts.is_dir():
        return []
    seen: dict[int, dict] = {}
    for f in sorted(scripts.glob("ep_*.mp3")):
        # ep_N_pro.mp3 / ep_N_flash.mp3
        m = re.match(r"ep_(\d+)_(pro|flash)\.mp3$", f.name)
        if not m:
            continue
        n = int(m.group(1))
        variant = m.group(2)
        # Prefer pro over flash when both exist (mirrors podcast_upload.sh).
        if n in seen and seen[n]["variant"] == "pro":
            continue
        srt = scripts / f"ep_{n}_{variant}.srt"
        # Sidecar `ep_N_<variant>.meta.json` written by synthesize.py carries
        # the full TTS model id (e.g. "gemini-2.5-flash-tts"). Filename alone
        # collapses 2.5-pro and 3.1-pro to the same `_pro` tag; the sidecar
        # is what lets the UI distinguish generations. Pre-sidecar files
        # (synthesized before this change shipped) return model=None and the
        # UI falls back to showing the legacy short tag.
        meta_path = scripts / f"ep_{n}_{variant}.meta.json"
        model_id: str | None = None
        if meta_path.is_file():
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                m_id = data.get("tts_model")
                if isinstance(m_id, str) and m_id.strip():
                    model_id = m_id.strip()
            except (OSError, ValueError):
                pass
        seen[n] = {
            "episode": n,
            "variant": variant,
            "model": model_id,
            "audio_bytes": f.stat().st_size,
            "has_subtitle": srt.exists(),
        }
    return [seen[n] for n in sorted(seen)]


@app.get("/api/workspace/{ws_name}/episodes/status")
def episode_status(ws_name: str):
    """Per-episode gate status (plan/script/audio/subtitle) from disk artifacts.

    Powers the dashboard's episode matrix. Unlike /episodes (audio-only, for
    the player), this lists EVERY planned/scripted episode with each gate's
    boolean so the producer can spot + individually re-run gaps on an idle
    workspace. See _episode_status for the artifact contract.
    """
    ws = _resolve_ws(ws_name)
    return _episode_status(ws)


# ─── Job-spawning actions (Phase 1 producer surface) ─────────────────────────


@app.post("/api/workspace/{ws_name}/upload")
def upload_workspace(ws_name: str):
    """Spawn ops/podcast_upload.sh to push this workspace to the Lightsail
    backend. Returns the job id; client polls /api/jobs/<id> for progress.

    Pre-flight: workspace must have plan/overview.md + at least one
    scripts/ep_*_pro.mp3 or _flash.mp3. We let the bash script do the full
    validation (same regex) — we just guard the obvious "no audio yet" case
    so the user gets a clean 422 instead of a spawned subprocess that
    immediately exits.
    """
    ws = _resolve_ws(ws_name)
    if not (ws / "plan" / "overview.md").exists():
        raise HTTPException(422, "plan/overview.md missing — run pipeline first")
    scripts = ws / "scripts"
    if not scripts.is_dir() or not any(
        scripts.glob("ep_*_pro.mp3")
    ) and not any(scripts.glob("ep_*_flash.mp3")):
        raise HTTPException(422, "no ep_*_pro.mp3 or _flash.mp3 — synthesize stage incomplete")

    upload_sh = (ROOT.parent.parent / "ops" / "podcast_upload.sh").resolve()
    if not upload_sh.exists():
        raise HTTPException(500, f"upload script missing at {upload_sh}")

    busy = _active_job_for_ws(ws_name)
    if busy:
        raise HTTPException(409, f"a job is already running for {ws_name} (job {busy['job_id']})")

    try:
        job = jobs.spawn(
            ["bash", str(upload_sh), str(ws)],
            label=f"upload:{ws_name}",
            kind="upload",
            cwd=ROOT.parent.parent,  # repo root (rsync uses relative ops/ path internally)
            metadata={"workspace": ws_name},
        )
    except JobLimitReached as e:
        raise HTTPException(429, str(e)) from e
    return {"job_id": job.id, "status": job.status, "label": job.label}


@app.delete("/api/workspace/{ws_name}")
def delete_workspace(ws_name: str, confirm: str = Query(...)):
    """Delete a local workspace. Requires `?confirm=<ws_name>` to match —
    a guard against the dashboard fat-fingering DELETE on the wrong row.
    Does NOT touch the remote server (use /api/remote/series/<id> for that).
    """
    ws = _resolve_ws(ws_name)
    if confirm != ws_name:
        raise HTTPException(400, "confirm param must equal workspace name")
    shutil.rmtree(ws)
    return {"deleted": ws_name}


@app.post("/api/workspace/{ws_name}/rerun")
def rerun_stage(
    ws_name: str,
    stage: str = Query(...),
    episode: int | None = Query(None, ge=1, le=999),
    drop_marker: bool = Query(True),
):
    """Spawn `uv run pipeline.py <ws> --only-stage <stage> [--only-episode N]`.

    `drop_marker=true` (default): deletes `.stage_<name>_done` first so the
    stage actually re-executes. Set false to dry-run / no-op skip-check.
    """
    ws = _resolve_ws(ws_name)
    if stage not in _STAGE_NAMES:
        raise HTTPException(400, f"unknown stage {stage!r}")

    # Busy guard MUST run before any state mutation: a 409 must leave the ws
    # untouched, otherwise a concurrent pipeline.py would see the deleted
    # stage_done marker and think the stage isn't complete.
    busy = _active_job_for_ws(ws_name)
    if busy:
        raise HTTPException(409, f"a job is already running for {ws_name} (job {busy['job_id']})")

    if drop_marker:
        # Per-stage marker → re-execute. Some stages (parallel scriptwrite/
        # script-review) use per-episode artifacts too; the pipeline knows to
        # skip cached episodes when --only-episode N is set so we don't need
        # to delete those manually here.
        marker = ws / f".stage_{stage}_done"
        marker.unlink(missing_ok=True)

    cmd = ["uv", "run", "pipeline.py", str(ws), "--only-stage", stage]
    if episode is not None:
        cmd += ["--only-episode", str(episode)]

    try:
        job = jobs.spawn(
            cmd,
            label=f"rerun:{ws_name}:{stage}" + (f":ep{episode}" if episode else ""),
            kind="rerun",
            cwd=ROOT,
            # Producer-triggered reruns inherit dashboard's verbose setting; user
            # already opted into events.jsonl by being here.
            env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
            metadata={"workspace": ws_name, "stage": stage, "episode": episode},
        )
    except JobLimitReached as e:
        raise HTTPException(429, str(e)) from e
    return {"job_id": job.id, "status": job.status, "label": job.label}


_GATE_MARKERS = {"plan": ".plan_approved", "script": ".script_approved"}


@app.post("/api/workspace/{ws_name}/approve")
def approve_gate(ws_name: str, gate: str = Query(...)):
    """Approve an approval gate → write the marker + resume production.

    `gate=plan` writes `.plan_approved` and spawns the SCRIPT phase;
    `gate=script` writes `.script_approved` and spawns the AUDIO phase. The
    spawned `pipeline.py <ws>` auto-resumes and pauses at the NEXT gate (or
    completes). Idempotent: re-approving a passed gate just re-touches it.
    Guarded: a `pending` gate (prior phase incomplete) is rejected 409 so the
    producer can't approve work that doesn't exist yet.
    """
    ws = _resolve_ws(ws_name)
    marker = _GATE_MARKERS.get(gate)
    if marker is None:
        raise HTTPException(400, f"unknown gate {gate!r} (expect 'plan' or 'script')")

    # Readiness guard — reuse the same disk-derived tri-state the sidebar shows.
    milestones, _ = _milestones(ws)
    _ms = {m["key"]: m for m in milestones}
    gst = _gate_states(
        ws,
        has_plan=bool(_ms.get("plan", {}).get("done")),
        n_script=int(_ms.get("script", {}).get("done", 0)),
        n_audio=int(_ms.get("audio", {}).get("done", 0)),
        target=int(_ms.get("script", {}).get("total", 0)),
    )
    state = next((g["state"] for g in gst if g["key"] == gate), None)
    if state == "pending":
        raise HTTPException(409, f"gate {gate!r} not ready — prior phase incomplete")

    busy = _active_job_for_ws(ws_name)
    if busy:
        raise HTTPException(409, f"a job is already running for {ws_name} (job {busy['job_id']})")

    (ws / marker).write_text(time.strftime("approved %Y-%m-%dT%H:%M:%S\n"))

    try:
        job = jobs.spawn(
            ["uv", "run", "pipeline.py", str(ws)],
            label=f"produce:{ws_name}:{gate}",
            kind="pipeline",
            cwd=ROOT,
            env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
            metadata={"workspace": ws_name, "gate": gate},
        )
    except JobLimitReached as e:
        raise HTTPException(429, str(e)) from e
    return {"job_id": job.id, "status": job.status, "label": job.label, "approved": gate}


@app.post("/api/workspace/{ws_name}/resume")
def resume_workspace(ws_name: str):
    """Resume the pipeline from where it left off — spawn `pipeline.py <ws>`
    (flagless auto-resume: continues from the first stage without a completion
    marker, pausing at the next approval gate or running to completion).

    Distinct from /rerun (one stage only) and /approve (write a gate marker
    THEN resume). Used when a workspace is idle/failed mid-production and not
    parked at a gate.
    """
    ws = _resolve_ws(ws_name)
    busy = _active_job_for_ws(ws_name)
    if busy:
        raise HTTPException(409, f"a job is already running for {ws_name} (job {busy['job_id']})")
    try:
        job = jobs.spawn(
            ["uv", "run", "pipeline.py", str(ws)],
            label=f"resume:{ws_name}",
            kind="pipeline",
            cwd=ROOT,
            env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
            metadata={"workspace": ws_name},
        )
    except JobLimitReached as e:
        raise HTTPException(429, str(e)) from e
    return {"job_id": job.id, "status": job.status, "label": job.label}


@app.post("/api/pipeline/start")
async def start_pipeline(
    epub: UploadFile = File(...),
    parallel: int = Form(3, ge=1, le=10),
):
    """Receive an EPUB upload, save to staging, spawn pipeline.py.
    Returns job_id immediately; the new workspace name appears in the
    pipeline's first few seconds of stdout (or after extract_epub finishes).

    `parallel` is bounded 1-10 — typical books have <=10 episodes and 10 is
    already aggressive for the 2GB VPS during scriptwrite/script-review.
    """
    if not epub.filename or not epub.filename.lower().endswith(".epub"):
        raise HTTPException(415, "expected .epub file")
    # Strip leading dots/hyphens so `....epub` doesn't land as a hidden file.
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", epub.filename).lstrip(".-") or "upload.epub"
    # Prefix with a monotonic timestamp so concurrent uploads of the same
    # filename don't race on the destination (last-writer-wins corruption).
    dest = UPLOAD_STAGING / f"{int(time.time())}_{safe_name}"

    written = 0
    try:
        with dest.open("wb") as f:
            # Stream to avoid loading large EPUBs into memory; enforce the
            # cap inline so we never spool the whole oversized body to disk.
            while chunk := await epub.read(1 << 20):
                written += len(chunk)
                if written > MAX_EPUB_BYTES:
                    raise HTTPException(
                        413,
                        f"epub too large (>{MAX_EPUB_BYTES // (1 << 20)}MB) — "
                        "this is almost certainly the wrong file",
                    )
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise

    cmd = ["uv", "run", "pipeline.py", str(dest), "--parallel", str(parallel)]
    try:
        job = jobs.spawn(
            cmd,
            label=f"pipeline:{safe_name}",
            kind="pipeline",
            cwd=ROOT,
            env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
            metadata={"epub": safe_name, "parallel": parallel, "bytes": written},
        )
    except JobLimitReached as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(429, str(e)) from e
    return {"job_id": job.id, "status": job.status, "label": job.label, "epub": safe_name}


@app.post("/api/pipeline/start-saga")
async def start_saga(
    epubs: list[UploadFile] = File(...),
    title: str = Form(...),
    spoiler_mode: str = Form(...),
    parallel: int = Form(3, ge=1, le=10),
):
    """Receive >=2 EPUB uploads + a saga title + spoiler policy, stage every
    file, then spawn `pipeline.py <epub>... --saga <title> --spoiler-mode <m>
    --parallel <n>`. `--saga` implies `--mode saga` in pipeline.py, so we never
    pass `--mode` here.

    On ANY failure (validation, oversize, job-limit) EVERY already-staged file
    is unlinked — a partial upload must not leave orphaned EPUBs in staging.
    EPUB order is the saga reading order, so staged paths are passed to argv in
    exactly the order received.
    """
    title = title.strip()
    if not title:
        raise HTTPException(400, "saga title is required")
    if len(epubs) < 2:
        raise HTTPException(400, "a saga needs at least 2 EPUBs")
    # Spoiler mode is validated against the saga archetype's allowed set
    # (readalong | retrospective). validate_spoiler_mode returns an error
    # string (not an exception) or None when the pair is valid.
    err = archetypes.validate_spoiler_mode("saga", spoiler_mode)
    if err:
        raise HTTPException(400, err)
    for up in epubs:
        if not up.filename or not up.filename.lower().endswith(".epub"):
            raise HTTPException(400, "all saga files must be .epub")

    UPLOAD_STAGING.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    # Monotonic ms prefix + per-file index so concurrent same-name uploads
    # don't collide and reading order survives in the staged filename.
    ts = int(time.time() * 1000)
    try:
        for i, up in enumerate(epubs):
            # Same sanitize as start_pipeline; strip leading dots/hyphens so a
            # crafted name can't land as a hidden file.
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", up.filename).lstrip(".-") or "upload.epub"
            dest = UPLOAD_STAGING / f"{ts}_{i}_{safe_name}"
            staged.append(dest)
            written = 0
            with dest.open("wb") as f:
                while chunk := await up.read(1 << 20):
                    written += len(chunk)
                    if written > MAX_EPUB_BYTES:
                        raise HTTPException(
                            413,
                            f"epub too large (>{MAX_EPUB_BYTES // (1 << 20)}MB) — "
                            "this is almost certainly the wrong file",
                        )
                    f.write(chunk)
    except HTTPException:
        for p in staged:
            p.unlink(missing_ok=True)
        raise

    cmd = [
        "uv", "run", "pipeline.py",
        *[str(p) for p in staged],
        "--saga", title,
        "--spoiler-mode", spoiler_mode,
        "--parallel", str(parallel),
    ]
    try:
        job = jobs.spawn(
            cmd,
            label=title,
            kind="pipeline",
            cwd=ROOT,
            env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
            metadata={"saga": title, "books": len(staged), "parallel": parallel},
        )
    except JobLimitReached as e:
        for p in staged:
            p.unlink(missing_ok=True)
        raise HTTPException(429, str(e)) from e
    return {
        "job_id": job.id,
        "status": job.status,
        "label": title,
        "books": len(staged),
    }


# ─── Job introspection ──────────────────────────────────────────────────────


@app.get("/api/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=200)):
    return [j.to_dict() for j in jobs.list(limit=limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, log_bytes: int = Query(32768, ge=0, le=1 << 20)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    d = job.to_dict()
    if log_bytes > 0:
        d["log_tail"] = jobs.tail_log(job_id, max_bytes=log_bytes)
    return d


@app.post("/api/jobs/{job_id}/kill")
def kill_job(job_id: str):
    if not jobs.kill(job_id):
        raise HTTPException(409, "job not running or not killable")
    return {"killed": job_id}


# ─── Remote (Lightsail) management ──────────────────────────────────────────


@app.get("/api/remote/series")
def remote_series():
    try:
        return remote_ops.list_remote_series()
    except remote_ops.RemoteError as e:
        raise HTTPException(502, f"remote ssh failed (exit {e.code}): {e.stderr[:200]}") from e


@app.get("/api/remote/disk")
def remote_disk():
    try:
        return remote_ops.remote_disk_usage()
    except remote_ops.RemoteError as e:
        raise HTTPException(502, f"remote ssh failed (exit {e.code}): {e.stderr[:200]}") from e


def _workspace_has_audio(ws: Path) -> bool:
    """A workspace counts as 'synthesized' once it holds an audio artifact that
    ops/podcast_upload.sh would actually publish. MUST mirror upload.sh's stage
    glob (ep_*_{pro,flash}.{m4a,mp3}, :64-67) — matching a looser ep_*.mp3 would
    flag a workspace holding only intermediate audio (e.g. ep_1_raw.mp3) as
    synthesized, stranding it as permanently 'drifted' since upload.sh would
    stage nothing for it."""
    scripts = ws / "scripts"
    if not scripts.is_dir():
        return False
    return any(
        any(scripts.glob(f"ep_*_{variant}.{ext}"))
        for variant in ("pro", "flash")
        for ext in ("m4a", "mp3")
    )


def reconcile_workspaces(workspaces_dir: Path, published_ids: set[str]) -> list[dict]:
    """Drift report: workspaces that have synthesized audio but whose series id
    is absent from the S3 catalog — i.e. publish never succeeded. This is the
    forward-looking net that catches a silently-failed auto-upload, distinct
    from the served-disk↔S3 reconcile (ops/podcast_backfill_disk.py --check)
    which covers the legacy instance-disk series."""
    if not workspaces_dir.exists():
        return []
    drifted = []
    for ws in sorted(p for p in workspaces_dir.iterdir() if p.is_dir()):
        if _workspace_has_audio(ws) and ws.name not in published_ids:
            drifted.append({"workspace": ws.name, "reason": "synthesized_not_published"})
    return drifted


@app.get("/api/remote/reconcile")
def remote_reconcile():
    """Surface synthesized-but-unpublished workspaces (workspace↔S3 drift)."""
    try:
        series = remote_ops.list_remote_series()
    except remote_ops.RemoteError as e:
        raise HTTPException(502, f"remote ssh failed (exit {e.code}): {e.stderr[:200]}") from e
    # Orphans (in-bucket-but-not-indexed, orphan=True) are intentionally folded
    # in: the audio DID reach the bucket (publish succeeded, only index regen
    # lagged), so this workspace↔S3 net must not false-flag it. The distinct
    # bucket-has-files-but-index-missing concern is surfaced by /api/remote/series.
    published_ids = {e.get("id") for e in series if isinstance(e, dict)}
    drifted = reconcile_workspaces(WORKSPACES_DIR, published_ids)
    return {"drifted": drifted, "publishedCount": len(published_ids)}


@app.delete("/api/remote/series/{series_id}")
def remote_delete(series_id: str, confirm: str = Query(...)):
    """SSH rm -rf + rebuild remote index.json. confirm must match series_id —
    same guard as workspace delete."""
    try:
        remote_ops.validate_series_id(series_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if confirm != series_id:
        raise HTTPException(400, "confirm param must equal series_id")
    try:
        return remote_ops.delete_remote_series(series_id)
    except remote_ops.RemoteError as e:
        raise HTTPException(502, f"remote ssh failed (exit {e.code}): {e.stderr[:200]}") from e


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main():
    parser = argparse.ArgumentParser(description="Podcast pipeline live monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ws", help="Pre-select workspace name (optional)")
    args = parser.parse_args()

    if args.ws:
        print(f"→ http://{args.host}:{args.port}/?ws={args.ws}")
    else:
        print(f"→ http://{args.host}:{args.port}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

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
from cost import aggregate_workspace  # noqa: E402
from jobs import tracker as jobs, JobLimitReached  # noqa: E402
import remote as remote_ops  # noqa: E402

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
_STAGE_NAMES = {
    "prep", "analyst", "architect", "plan-review",
    "enricher-gap", "enricher", "scriptwrite",
    "series-polish", "script-review",
    "tts-prep", "synthesize", "audio-qa", "subtitle",
}


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

    # Single job-table scan, then O(1) lookup per workspace.
    active_by_ws: dict[str, dict] = {}
    for j in jobs.list(limit=200):
        if j.status != "running":
            continue
        ws = (j.metadata or {}).get("workspace")
        if ws and ws not in active_by_ws:
            active_by_ws[ws] = {
                "job_id": j.id,
                "label": j.label,
                "kind": j.kind,
            }

    return [_workspace_summary(WORKSPACES_DIR / n, active_by_ws.get(n)) for n in names]


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


def _workspace_summary(ws: Path, active_job: dict | None) -> dict:
    """Cheap-ish per-workspace summary for the sidebar list.

    Cost: one `aggregate_workspace` call (reads events.jsonl) + small dir
    scans. For ~70 workspaces this stays under ~200ms total on warm cache;
    if it ever becomes a bottleneck, add mtime-keyed memoization at this
    layer (events.jsonl mtime alone is enough since cost only depends on it).
    """
    name = ws.name

    # ─── Stage progress (from done markers) ───
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

    # ─── Status (running > done > failed > idle > fresh) ───
    if active_job:
        status = "running"
    elif _FINAL_STAGE in stages_done:
        status = "done"
    elif _scan_pipeline_log_status(ws / "pipeline_log.jsonl", stages_done):
        status = "failed"
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
    if not candidates:
        try:
            candidates.append(ws.stat().st_mtime)
        except OSError:
            candidates.append(0.0)
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
            if ml.startswith("claude"):
                claude_usd += usd
            elif "gemini" in ml or "tts" in ml or ml.startswith("vertex"):
                tts_usd += usd
            else:
                # Unknown model — bucket into claude side conservatively so
                # the totals still match (rather than vanishing).
                claude_usd += usd
        has_cost_data = (ws / "events.jsonl").exists() and total_usd > 0
    except Exception:
        # Never let a bad workspace break the whole sidebar list.
        pass

    return {
        "name": name,
        "status": status,
        "stages_done": sorted(stages_done),
        "n_stages_done": n_done,
        "n_stages_total": _STAGE_COUNT,
        "episode_count": len(episodes),
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
        seen[n] = {
            "episode": n,
            "variant": variant,
            "audio_bytes": f.stat().st_size,
            "has_subtitle": srt.exists(),
        }
    return [seen[n] for n in sorted(seen)]


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

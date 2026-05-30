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
import re
import shutil
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Make `monitor/` importable when launched as a script via `uv run monitor/server.py`.
sys.path.insert(0, str(Path(__file__).parent))
from cost import aggregate_workspace  # noqa: E402
from jobs import tracker as jobs  # noqa: E402
import remote as remote_ops  # noqa: E402

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


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/workspaces")
def list_workspaces():
    if not WORKSPACES_DIR.exists():
        return []
    return sorted(p.name for p in WORKSPACES_DIR.iterdir() if p.is_dir())


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

    job = jobs.spawn(
        ["bash", str(upload_sh), str(ws)],
        label=f"upload:{ws_name}",
        kind="upload",
        cwd=ROOT.parent.parent,  # repo root (rsync uses relative ops/ path internally)
        metadata={"workspace": ws_name},
    )
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
    return {"job_id": job.id, "status": job.status, "label": job.label}


@app.post("/api/pipeline/start")
async def start_pipeline(
    epub: UploadFile = File(...),
    parallel: int = Form(3),
):
    """Receive an EPUB upload, save to staging, spawn pipeline.py.
    Returns job_id immediately; the new workspace name appears in the
    pipeline's first few seconds of stdout (or after extract_epub finishes).
    """
    if not epub.filename or not epub.filename.lower().endswith(".epub"):
        raise HTTPException(415, "expected .epub file")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", epub.filename)
    dest = UPLOAD_STAGING / safe_name
    with dest.open("wb") as f:
        # Stream to avoid loading large EPUBs into memory.
        while chunk := await epub.read(1 << 20):
            f.write(chunk)

    cmd = ["uv", "run", "pipeline.py", str(dest), "--parallel", str(parallel)]
    job = jobs.spawn(
        cmd,
        label=f"pipeline:{safe_name}",
        kind="pipeline",
        cwd=ROOT,
        env={"PODCAST_VERBOSE": "1", "PODCAST_NO_DASHBOARD": "1"},
        metadata={"epub": safe_name, "parallel": parallel},
    )
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

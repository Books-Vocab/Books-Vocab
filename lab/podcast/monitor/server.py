#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
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
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent.parent
WORKSPACES_DIR = ROOT / "workspaces"
STATIC_DIR = Path(__file__).parent / "static"

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
    ws = WORKSPACES_DIR / ws_name
    if not ws.is_dir():
        return JSONResponse({"error": "workspace not found"}, status_code=404)

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
    ws = WORKSPACES_DIR / ws_name
    if not ws.is_dir():
        return JSONResponse({"error": "workspace not found"}, status_code=404)

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

r"""Podcast read API.

Authorization model: **public-read for any authenticated user**. Podcasts are
shared editorial content (curated audio + transcripts shipped by ops via
``ops/podcast_upload.sh``); they are not per-user content and have no owner.
Every endpoint here therefore only checks ``Depends(get_current_user)`` —
authentication, not authorization — and serves the same payload to all callers.

Hardening already in place:

* ``series_id`` is constrained to ``\A[a-z0-9_]+\Z`` via ``_SERIES_ID_RE`` so
  path traversal (``../etc``), uppercase, dots, slashes, and trailing newlines
  are all rejected with a 404 before any filesystem access. The ``\A``/``\Z``
  anchors are chosen over ``^``/``$`` so that ``series_a\n`` is rejected too
  (Python's ``$`` matches end-of-string *or* just before a trailing ``\n``).
* ``ep_num`` is a FastAPI ``Path()`` parameter with ``ge=1, le=_MAX_EPISODE_NUM``
  so non-integer / out-of-range values are rejected at the framework boundary
  with a 422.
* Corrupt JSON is logged and returned as a clean 500 instead of leaking a
  ``JSONDecodeError`` traceback.

If a future product decision turns podcasts into per-user content, the right
move is to add an ``owner_id`` field to ``metadata.json`` and compare it to
``user["id"]`` here — **not** to remove ``get_current_user`` and rely on the
StaticFiles ``/api/podcast-media/`` mount being private (it is not).
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import podcast_progress as progress_store
from ..deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_MAX_EPISODE_NUM = 999


def _podcasts_dir(request: Request | None = None) -> Path:
    if request is not None:
        return request.app.state.kg_settings.podcasts_dir
    from ..settings import load_settings
    return load_settings().podcasts_dir


def _read_json_file(path: Path, *, context: str):
    """Read + parse JSON with a clear 500 on corruption instead of a raw
    JSONDecodeError trace."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("Podcast %s corrupt at %s: %s", context, path, e)
        raise HTTPException(500, detail=f"Malformed {context}")


@router.get("/api/podcasts")
def list_podcasts(request: Request, user: dict = Depends(get_current_user)):
    index_file = _podcasts_dir(request) / "index.json"
    if not index_file.exists():
        return []
    return _read_json_file(index_file, context="index")


# ---------------------------------------------------------------------------
# Per-user playback progress
# ---------------------------------------------------------------------------
#
# CloudKit drift between devices was the original symptom: a user resuming
# on phone after listening on Mac would land at zero. The fix here is to
# treat the backend as the durable, cross-device anchor for `(position_sec,
# duration_sec, updated_at)` per `(user, series, episode)`. iOS still owns
# its local SwiftData copy for offline + scrubbing latency; this endpoint
# is the merge point on app foreground / background save.
#
# The routes below are registered BEFORE `/api/podcasts/{series_id}` so the
# literal `progress` and `{ep_num}/progress` paths win over the dynamic
# series-detail route. (FastAPI matches by registration order.)


class _ProgressPayload(BaseModel):
    position_sec: float = Field(ge=0.0)
    duration_sec: float = Field(ge=0.0)
    updated_at: str


def _canonical_updated_at(raw: str) -> str:
    """Validate + canonicalise ``updated_at`` to UTC ISO8601.

    Done as a helper rather than a Pydantic ``field_validator`` because
    Pydantic v2 stuffs the originating exception object into the error
    ``ctx``, which the project's existing validation_error_handler then
    cannot JSON-serialise (it returns ``exc.errors()`` verbatim). Raising
    ``HTTPException(422)`` from the route body sidesteps that path entirely.
    """
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="updated_at must be ISO8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@router.get("/api/podcasts/progress")
def list_user_progress(user: dict = Depends(get_current_user)):
    """Return every progress row for the calling user."""
    items = progress_store.list_for_user(user_id=user["id"])
    return {"items": items}


@router.post("/api/podcasts/{series_id}/{ep_num}/progress")
def upsert_user_progress(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    payload: _ProgressPayload,
    user: dict = Depends(get_current_user),
):
    """Last-write-wins upsert keyed by ``(user, series, ep)``.

    A stale write (older ``updated_at`` than the stored row) is accepted at
    the HTTP layer (200) but discarded at the store layer — the response
    body reflects the current authoritative row so the client can converge
    its local copy without a second GET.
    """
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    return progress_store.upsert(
        user_id=user["id"],
        series_id=series_id,
        ep_num=ep_num,
        position_sec=payload.position_sec,
        duration_sec=payload.duration_sec,
        updated_at=_canonical_updated_at(payload.updated_at),
    )


@router.get("/api/podcasts/{series_id}/{ep_num}/progress")
def get_user_progress(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    user: dict = Depends(get_current_user),
):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    row = progress_store.get_single(
        user_id=user["id"], series_id=series_id, ep_num=ep_num,
    )
    if row is None:
        raise HTTPException(404, detail="No progress")
    return row


@router.get("/api/podcasts/{series_id}")
def get_podcast_series(series_id: str, request: Request, user: dict = Depends(get_current_user)):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    meta_file = _podcasts_dir(request) / series_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(404, detail="Series not found")
    return _read_json_file(meta_file, context="metadata")


_AUDIO_CHUNK_SIZE = 64 * 1024  # 64 KiB per network read — balances RAM vs syscalls.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range ``Range: bytes=...`` header per RFC 7233.

    Returns ``(start, end)`` inclusive byte offsets, or ``None`` if the
    header is malformed (caller should fall back to a 200 full-body response).
    Raises ``HTTPException(416)`` for syntactically valid but unsatisfiable
    ranges (start beyond EOF), per RFC 7233 §4.4.

    Multi-range is intentionally not supported — AVPlayer / iOS only ever
    issues single ranges, and multipart/byteranges adds complexity without
    a real consumer.
    """
    m = _RANGE_RE.match(range_header.strip())
    if not m:
        return None
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        # bytes=-N → last N bytes
        try:
            suffix = int(end_s)
        except ValueError:
            return None
        if suffix <= 0:
            return None
        start = max(0, file_size - suffix)
        end = file_size - 1
        return (start, end)
    try:
        start = int(start_s)
    except ValueError:
        return None
    if end_s == "":
        end = file_size - 1
    else:
        try:
            end = int(end_s)
        except ValueError:
            return None
        end = min(end, file_size - 1)
    if start >= file_size:
        raise HTTPException(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
            detail="Range not satisfiable",
        )
    if end < start:
        return None
    return (start, end)


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = _AUDIO_CHUNK_SIZE):
    """Yield ``[start, end]`` (inclusive) bytes from ``path`` in chunks."""
    remaining = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            buf = fh.read(min(chunk_size, remaining))
            if not buf:
                break
            remaining -= len(buf)
            yield buf


@router.get("/api/podcasts/{series_id}/{ep_num}/audio")
def get_podcast_audio(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    request: Request,
    user: dict = Depends(get_current_user),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
):
    """Authenticated audio stream with HTTP Range / 206 Partial Content support.

    Replaces the public ``/api/podcast-media/.../audio.mp3`` StaticFiles mount
    (which bypasses FastAPI auth). The legacy mount is retained for backward
    compatibility with shipped iOS clients but emits a deprecation warning on
    every hit (see ``api.py``).

    Implementation note: we use a hand-rolled Range handler rather than
    Starlette's ``FileResponse`` because ``FileResponse`` only learned about
    Range in Starlette 0.45 (2025-01); pinning to that is unnecessary risk
    when the Range protocol is ~30 lines of code.
    """
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    audio_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / "audio.mp3"
    if not audio_file.exists():
        raise HTTPException(404, detail="Audio not found")

    file_size = audio_file.stat().st_size
    common_headers = {
        "Accept-Ranges": "bytes",
        # No-transform avoids gzipping by intermediaries (binary audio gains nothing).
        "Cache-Control": "private, no-transform",
    }

    if range_header:
        parsed = _parse_range_header(range_header, file_size)
        if parsed is not None:
            start, end = parsed
            length = end - start + 1
            headers = {
                **common_headers,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
            }
            return StreamingResponse(
                _iter_file_range(audio_file, start, end),
                status_code=206,
                media_type="audio/mpeg",
                headers=headers,
            )
        # parsed is None → malformed Range header; RFC 7233 says ignore + 200.

    # Full body. Use StreamingResponse to avoid loading the whole file into RAM.
    headers = {**common_headers, "Content-Length": str(file_size)}
    return StreamingResponse(
        _iter_file_range(audio_file, 0, file_size - 1),
        status_code=200,
        media_type="audio/mpeg",
        headers=headers,
    )


@router.get("/api/podcasts/{series_id}/{ep_num}/subtitle")
def get_podcast_subtitle(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    request: Request,
    user: dict = Depends(get_current_user),
):
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)
    srt_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / "subtitle.srt"
    if not srt_file.exists():
        raise HTTPException(404, detail="Subtitle not found")
    return PlainTextResponse(srt_file.read_text(encoding="utf-8"))

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
``user["id"]`` here — and route all media through this authenticated router.
(The legacy public StaticFiles ``/api/podcast-media/`` mount, which bypassed
auth entirely, was removed in 2026-05.)
"""

import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import podcast_progress as progress_store
from ..deps import get_current_user
from ..settings import KGSettings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_MAX_EPISODE_NUM = 999


def _podcasts_dir(request: Request | None = None) -> Path:
    if request is not None:
        return request.app.state.kg_settings.podcasts_dir
    from ..settings import load_settings
    return load_settings().podcasts_dir


def _settings(request: Request) -> KGSettings:
    return request.app.state.kg_settings


def _using_s3(request: Request) -> bool:
    return bool(_settings(request).podcast_bucket)


# boto3 clients are thread-safe and recommend reuse — cache one per
# (bucket, region, endpoint) so we don't pay the credential-resolution +
# HTTPS pool setup cost on every audio chunk request.
@lru_cache(maxsize=4)
def _s3_client_cached(region: str, endpoint_url: str | None):
    import boto3  # local import: keeps disk-mode tests off boto3 entirely
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        # Default signature works for both standard S3 and Lightsail Object
        # Storage. Read-heavy workload → larger pool to avoid serialization.
        config=Config(
            signature_version="s3v4",
            max_pool_connections=32,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _s3_client(request: Request):
    cfg = _settings(request)
    return _s3_client_cached(cfg.podcast_bucket_region, cfg.podcast_bucket_endpoint_url)


# Per-(bucket, series) resolved audio extension. A series' format is fixed at
# publish time (all episodes share one format), so resolving it once and
# caching avoids an S3 metadata read on every Range request during streaming.
# Cleared implicitly on process restart — acceptable staleness for a re-publish
# that changes format (rare; restart or a new bucket clears it).
_S3_AUDIO_FMT_CACHE: dict[tuple[str | None, str], str] = {}


def _s3_audio_format(request: Request, series_id: str) -> str:
    """Resolve a series' audio extension (``"m4a"`` / ``"mp3"``) in S3 mode.

    Trusts ``metadata.json``'s ``audioFormat`` field (written by
    ``ops/podcast_upload.sh`` / the backfill script). Legacy series whose
    metadata predates that field fall back to probing the bucket in
    m4a → mp3 order. Result cached per ``(bucket, series_id)``.
    """
    cfg = _settings(request)
    cache_key = (cfg.podcast_bucket, series_id)
    cached = _S3_AUDIO_FMT_CACHE.get(cache_key)
    if cached:
        return cached

    fmt: str | None = None
    meta = _read_json_from_s3(request, f"{series_id}/metadata.json", context="metadata")
    if isinstance(meta, dict):
        raw = meta.get("audioFormat")
        if isinstance(raw, str) and raw in ("m4a", "mp3"):
            fmt = raw

    if fmt is None:
        # Legacy metadata without audioFormat — probe ep_01 (representative,
        # since all episodes in a series share one format).
        s3 = _s3_client(request)
        for cand in ("m4a", "mp3"):
            try:
                s3.head_object(Bucket=cfg.podcast_bucket, Key=f"{series_id}/ep_01/audio.{cand}")
                fmt = cand
                break
            except Exception:  # noqa: BLE001 — any miss → try next candidate
                continue

    fmt = fmt or "m4a"
    _S3_AUDIO_FMT_CACHE[cache_key] = fmt
    return fmt


def _audio_filename(request: Request, series_id: str, ep_num: int) -> str:
    """Resolve the audio filename for an episode, honouring m4a-first / mp3-fallback.

    For S3-backed deployments we trust ``metadata.json``'s ``audioFormat``
    field (written by ``ops/podcast_upload.sh``). For disk deployments we
    probe the filesystem in m4a → mp3 order so series uploaded before
    Track B keep playing without manual migration.
    """
    if _using_s3(request):
        return f"audio.{_s3_audio_format(request, series_id)}"
    base = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}"
    for name in ("audio.m4a", "audio.mp3"):
        if (base / name).exists():
            return name
    return "audio.m4a"


def _media_type_for(filename: str) -> str:
    return "audio/mp4" if filename.endswith(".m4a") else "audio/mpeg"


def _read_json_file(path: Path, *, context: str):
    """Read + parse JSON with a clear 500 on corruption instead of a raw
    JSONDecodeError trace."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("Podcast %s corrupt at %s: %s", context, path, e)
        raise HTTPException(500, detail=f"Malformed {context}") from e


def _read_json_from_s3(request: Request, key: str, *, context: str):
    """Read + parse JSON from the configured podcast bucket.

    Returns ``None`` if the object does not exist (so callers can mirror the
    disk path's ``Path.exists()`` branch); raises ``HTTPException(500)`` on
    malformed JSON to preserve the corruption-handling semantics of the
    disk path.
    """
    cfg = _settings(request)
    s3 = _s3_client(request)
    try:
        obj = s3.get_object(Bucket=cfg.podcast_bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as exc:  # noqa: BLE001
        # Lightsail Object Storage occasionally returns ClientError("404") for
        # missing keys instead of NoSuchKey. Treat any 404 the same.
        code = getattr(getattr(exc, "response", {}), "get", lambda *_: {})("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return None
        logger.error("Podcast %s S3 read failed for s3://%s/%s: %s",
                     context, cfg.podcast_bucket, key, exc)
        raise HTTPException(502, detail=f"Storage error reading {context}") from exc
    body = obj["Body"].read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("Podcast %s corrupt in s3://%s/%s: %s",
                     context, cfg.podcast_bucket, key, e)
        raise HTTPException(500, detail=f"Malformed {context}") from e


@router.get("/api/podcasts")
def list_podcasts(request: Request, user: dict = Depends(get_current_user)):
    if _using_s3(request):
        data = _read_json_from_s3(request, "index.json", context="index")
        if data is None:
            return []
    else:
        index_file = _podcasts_dir(request) / "index.json"
        if not index_file.exists():
            return []
        data = _read_json_file(index_file, context="index")
    if not isinstance(data, list):
        logger.error("Podcast index malformed (expected list)")
        raise HTTPException(500, detail="Malformed index")
    return data


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
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="updated_at must be ISO8601") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


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
    if _using_s3(request):
        data = _read_json_from_s3(
            request, f"{series_id}/metadata.json", context="metadata",
        )
        if data is None:
            raise HTTPException(404, detail="Series not found")
        return data
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


def _iter_s3_body(body, chunk_size: int = _AUDIO_CHUNK_SIZE):
    """Yield chunks from a botocore StreamingBody, closing it at the end.

    botocore's StreamingBody is iterable but doesn't expose a context-manager
    interface; wrapping the iteration in try/finally guarantees the socket
    returns to the pool even if the client drops the connection mid-stream.
    """
    try:
        while True:
            buf = body.read(chunk_size)
            if not buf:
                break
            yield buf
    finally:
        try:
            body.close()
        except Exception:  # noqa: BLE001
            pass


def _serve_audio_from_s3(
    request: Request,
    series_id: str,
    ep_num: int,
    range_header: str | None,
):
    cfg = _settings(request)
    s3 = _s3_client(request)
    filename = _audio_filename(request, series_id, ep_num)
    key = f"{series_id}/ep_{ep_num:02d}/{filename}"
    media_type = _media_type_for(filename)

    get_kwargs = {"Bucket": cfg.podcast_bucket, "Key": key}
    if range_header:
        # S3 implements RFC 7233 Range natively. Pass the client's header through
        # so we don't reinvent suffix-range / open-ended-range parsing here.
        get_kwargs["Range"] = range_header

    try:
        obj = s3.get_object(**get_kwargs)
    except s3.exceptions.NoSuchKey:
        raise HTTPException(404, detail="Audio not found") from None
    except Exception as exc:  # noqa: BLE001
        err = getattr(exc, "response", {}).get("Error", {}) if hasattr(exc, "response") else {}
        code = err.get("Code", "")
        http_status = int(getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0)) \
            if hasattr(exc, "response") else 0
        if code in ("NoSuchKey", "404") or http_status == 404:
            raise HTTPException(404, detail="Audio not found") from None
        if http_status == 416:
            # Surface the 416 with the Content-Range S3 returned, mirroring
            # what _parse_range_header would have done.
            raise HTTPException(416, detail="Range not satisfiable") from None
        logger.error("S3 GetObject failed for %s: %s", key, exc)
        raise HTTPException(502, detail="Storage error fetching audio") from exc

    body = obj["Body"]
    status_code = obj.get("ResponseMetadata", {}).get("HTTPStatusCode", 200)
    content_length = obj.get("ContentLength")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-transform",
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if "ContentRange" in obj:
        headers["Content-Range"] = obj["ContentRange"]
    return StreamingResponse(
        _iter_s3_body(body),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


@router.get("/api/podcasts/{series_id}/{ep_num}/audio")
def get_podcast_audio(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    request: Request,
    user: dict = Depends(get_current_user),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
):
    """Authenticated audio stream with HTTP Range / 206 Partial Content support.

    Two backends:

    * **S3 (production, post-Track-B)** — proxy via boto3 ``get_object`` with
      the client's Range header forwarded. S3 returns 206 + ``Content-Range``
      natively; we just relay status/headers back to the client. We do NOT
      redirect to a presigned URL because iOS ``AVURLAssetHTTPHeaderFields``
      re-attaches the ``Authorization: Bearer`` header to every redirect
      target, which AWS rejects (409 — pre-signed request signature clash).
      Proxy mode keeps iOS zero-change.
    * **Disk (dev / transition)** — hand-rolled Range handler against the
      filesystem. The legacy public StaticFiles mount was removed in 2026-05.
    """
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(404)

    if _using_s3(request):
        return _serve_audio_from_s3(request, series_id, ep_num, range_header)

    # ── disk-mode fallback (m4a → mp3 probe) ──
    filename = _audio_filename(request, series_id, ep_num)
    audio_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / filename
    if not audio_file.exists():
        raise HTTPException(404, detail="Audio not found")

    media_type = _media_type_for(filename)
    file_size = audio_file.stat().st_size
    common_headers = {
        "Accept-Ranges": "bytes",
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
                media_type=media_type,
                headers=headers,
            )
        # parsed is None → malformed Range header; RFC 7233 says ignore + 200.

    headers = {**common_headers, "Content-Length": str(file_size)}
    return StreamingResponse(
        _iter_file_range(audio_file, 0, file_size - 1),
        status_code=200,
        media_type=media_type,
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

    if _using_s3(request):
        cfg = _settings(request)
        s3 = _s3_client(request)
        key = f"{series_id}/ep_{ep_num:02d}/subtitle.srt"
        try:
            obj = s3.get_object(Bucket=cfg.podcast_bucket, Key=key)
        except s3.exceptions.NoSuchKey:
            raise HTTPException(404, detail="Subtitle not found") from None
        except Exception as exc:  # noqa: BLE001
            err = getattr(exc, "response", {}).get("Error", {}) if hasattr(exc, "response") else {}
            if err.get("Code") in ("NoSuchKey", "404"):
                raise HTTPException(404, detail="Subtitle not found") from None
            logger.error("S3 GetObject failed for %s: %s", key, exc)
            raise HTTPException(502, detail="Storage error fetching subtitle") from exc
        text = obj["Body"].read().decode("utf-8", errors="replace")
        return PlainTextResponse(text)

    srt_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / "subtitle.srt"
    if not srt_file.exists():
        raise HTTPException(404, detail="Subtitle not found")
    return PlainTextResponse(srt_file.read_text(encoding="utf-8"))

r"""Podcast read API.

Authorization model: **tiered access** (guest / free / pro), enforced here and
defined in :mod:`kg.podcast_access`. Podcasts are shared editorial content
(curated audio + transcripts shipped by ops via ``ops/podcast_upload.sh``) with
no per-user owner, but access is *not* uniform:

* **Browse** (``GET /api/podcasts``, ``/{series_id}``, ``/{series_id}/cover``)
  uses :func:`get_current_user_optional` — **guests included**. Anyone may see
  the catalog, series detail, and covers (the streaming-platform showcase).
* **Playback** (``GET /{series_id}/{ep_num}/audio``) is gated by tier:
  guest → ``401 auth_required``; free → only the *preview* clip of episode 1
  (``403 upgrade_required`` otherwise); pro → full audio. The free caller is
  served a physically separate ``preview.*`` object, so the full audio is never
  partially exposed — a progressive MP4 cannot be byte-truncated cleanly (its
  single ``moov`` advertises the full duration), which is exactly why the
  preview is a pre-generated asset rather than a Range cap.
* **Per-user** routes (``progress``, ``subtitle``) keep ``get_current_user`` —
  they require a real user id / only matter during (authenticated) playback.

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
from collections.abc import Callable
from email.utils import formatdate
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import Response, StreamingResponse

from ..api_models.podcast import (
    PodcastProgressListResponse,
    PodcastProgressRequest,
    PodcastProgressResponse,
    PodcastSeriesDetail,
    PodcastSeriesSummary,
)
from .. import podcast_progress as progress_store
from ..deps import CurrentUser, OptionalCurrentUser
from ..podcast_access import (
    ERR_AUTH_REQUIRED,
    ERR_UPGRADE_REQUIRED,
    FULL_AUDIO_STEM,
    PREVIEW_AUDIO_STEM,
    is_free_previewable_episode,
    resolve_podcast_tier,
)
from ..settings import KGSettings
from ..types import UserRecord

logger = logging.getLogger(__name__)

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_MAX_EPISODE_NUM = 999


def _validate_series_id(series_id: str) -> None:
    """Reject path-unsafe series ids with a 404 (don't leak existence)."""
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(status_code=404)


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


def _is_s3_not_found(exc: Exception, s3) -> bool:
    """True iff ``exc`` is a 404 / NoSuchKey (Lightsail sometimes returns a
    ClientError("404") instead of NoSuchKey for missing keys). Any other error
    is a real fault the caller must surface, not swallow."""
    if isinstance(exc, s3.exceptions.NoSuchKey):
        return True
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return code in ("NoSuchKey", "404")


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
            except Exception as exc:  # noqa: BLE001
                if _is_s3_not_found(exc, s3):
                    continue
                # Loud-fail on real faults (perms / throttle / network): caching
                # a default here would pin a wrong format until restart and mask
                # the error as a downstream 404. Mirror _read_json_from_s3.
                logger.error("Podcast audio-format probe failed for %s/ep_01/audio.%s: %s",
                             series_id, cand, exc)
                raise HTTPException(status_code=502, detail="Storage error resolving audio format") from exc

    fmt = fmt or "m4a"
    _S3_AUDIO_FMT_CACHE[cache_key] = fmt
    return fmt


def _audio_filename(request: Request, series_id: str, ep_num: int, *, stem: str = FULL_AUDIO_STEM) -> str:
    """Resolve the audio filename for an episode, honouring m4a-first / mp3-fallback.

    ``stem`` selects the asset: ``"audio"`` (full episode) or ``"preview"`` (the
    free-tier clip). The preview is produced by stream-copy from the full audio
    so it shares the series' container/format — hence the same ``audioFormat``
    resolution applies to both.

    For S3-backed deployments we trust ``metadata.json``'s ``audioFormat``
    field (written by ``ops/podcast_upload.sh``). For disk deployments we
    probe the filesystem in m4a → mp3 order so series uploaded before
    Track B keep playing without manual migration.
    """
    if _using_s3(request):
        return f"{stem}.{_s3_audio_format(request, series_id)}"
    base = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}"
    for name in (f"{stem}.m4a", f"{stem}.mp3"):
        if (base / name).exists():
            return name
    return f"{stem}.m4a"


def _media_type_for(filename: str) -> str:
    return "audio/mp4" if filename.endswith(".m4a") else "audio/mpeg"


def _read_json_file(path: Path, *, context: str):
    """Read + parse JSON with a clear 500 on corruption instead of a raw
    JSONDecodeError trace."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("Podcast %s corrupt at %s: %s", context, path, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Malformed {context}") from e


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
    except Exception as exc:  # noqa: BLE001
        # Lightsail Object Storage occasionally returns ClientError("404") for
        # missing keys instead of NoSuchKey. Treat any 404 the same.
        if _is_s3_not_found(exc, s3):
            return None
        logger.error("Podcast %s S3 read failed for s3://%s/%s: %s",
                     context, cfg.podcast_bucket, key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Storage error reading {context}") from exc
    body = obj["Body"].read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("Podcast %s corrupt in s3://%s/%s: %s",
                     context, cfg.podcast_bucket, key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Malformed {context}") from e


def _get_object_from_s3(request: Request, key: str, *, context: str):
    cfg = _settings(request)
    s3 = _s3_client(request)
    try:
        return s3.get_object(Bucket=cfg.podcast_bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        # Lightsail Object Storage occasionally returns ClientError("404") for
        # missing keys instead of NoSuchKey. Treat any 404 the same.
        if _is_s3_not_found(exc, s3):
            return None
        logger.error("S3 GetObject failed for %s: %s", key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Storage error fetching {context}") from exc


def _read_bytes_from_s3(request: Request, key: str, *, context: str) -> bytes | None:
    """Read raw object bytes from the configured podcast bucket.

    Returns ``None`` if the object does not exist (so callers can mirror the
    disk path's ``Path.exists()`` branch); raises ``HTTPException(502)`` on a
    real storage fault. The bytes-oriented sibling of ``_read_json_from_s3``,
    used by subtitle media proxies that need an in-memory text transform.
    """
    obj = _get_object_from_s3(request, key, context=context)
    if obj is None:
        return None
    return obj["Body"].read()


def _s3_static_headers(obj: dict, base_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(base_headers or {})
    content_length = obj.get("ContentLength")
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if etag := obj.get("ETag"):
        headers["ETag"] = str(etag)
    if last_modified := obj.get("LastModified"):
        if hasattr(last_modified, "timestamp"):
            headers["Last-Modified"] = formatdate(last_modified.timestamp(), usegmt=True)
        else:
            headers["Last-Modified"] = str(last_modified)
    return headers


def _serve_static_media(
    request: Request,
    series_id: str,
    rel_key: str,
    *,
    media_type: str,
    context: str,
    headers: dict[str, str] | None = None,
    transform: Callable[[bytes], bytes | str] = lambda b: b,
    stream_s3: bool = False,
):
    """Serve a single static media object (subtitle / cover) over the shared
    disk-exists / S3-404 dichotomy.

    ``rel_key`` is the path under the series root (``ep_NN/subtitle.srt`` or
    ``cover.png``); the S3 key is ``{series_id}/{rel_key}`` and the disk path is
    ``_podcasts_dir/series_id/rel_key``. ``transform`` lets the subtitle path
    decode bytes → text (round-tripped through ``PlainTextResponse``) while the
    cover path passes raw bytes through unchanged.
    """
    if _using_s3(request) and stream_s3:
        obj = _get_object_from_s3(request, f"{series_id}/{rel_key}", context=context)
        if obj is None:
            raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
        return StreamingResponse(
            _iter_s3_body(obj["Body"]),
            media_type=media_type,
            headers=_s3_static_headers(obj, headers),
        )

    if _using_s3(request):
        raw = _read_bytes_from_s3(request, f"{series_id}/{rel_key}", context=context)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
        return Response(content=transform(raw), media_type=media_type, headers=headers)

    disk_file = _podcasts_dir(request) / series_id / rel_key
    if not disk_file.exists():
        raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
    return Response(
        content=transform(disk_file.read_bytes()),
        media_type=media_type,
        headers=headers,
    )


@router.get(
    "/api/podcasts",
    response_model=list[PodcastSeriesSummary],
    response_model_exclude_unset=True,
)
def list_podcasts(request: Request, user: OptionalCurrentUser):
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
        raise HTTPException(status_code=500, detail="Malformed podcast index")
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


def _canonical_updated_at(raw: str) -> str:
    """Validate + canonicalise ``updated_at`` to UTC ISO8601.

    Done as a helper rather than a Pydantic ``field_validator`` because
    Pydantic v2 stuffs the originating exception object into the error
    ``ctx``, which the project's existing validation_error_handler then
    cannot JSON-serialise (it returns ``exc.errors()`` verbatim). Raising
    ``HTTPException(422)`` from the route body sidesteps that path entirely.

    Parsing/normalisation is delegated to
    :func:`podcast_progress.parse_instant` — the same canonicaliser the LWW
    store uses — so the HTTP-layer and store-layer agree bit-for-bit; this
    helper only maps its ``None`` sentinel to a 422 and serialises to ISO8601.
    """
    dt = progress_store.parse_instant(raw)
    if dt is None:
        raise HTTPException(status_code=422, detail="updated_at must be ISO8601")
    return dt.isoformat()


@router.get("/api/podcasts/progress", response_model=PodcastProgressListResponse)
def list_user_progress(user: CurrentUser):
    """Return every progress row for the calling user."""
    items = progress_store.list_for_user(user_id=user["id"])
    return {"items": items}


@router.post("/api/podcasts/{series_id}/{ep_num}/progress", response_model=PodcastProgressResponse)
def upsert_user_progress(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    payload: PodcastProgressRequest,
    user: CurrentUser,
):
    """Last-write-wins upsert keyed by ``(user, series, ep)``.

    A stale write (older ``updated_at`` than the stored row) is accepted at
    the HTTP layer (200) but discarded at the store layer — the response
    body reflects the current authoritative row so the client can converge
    its local copy without a second GET.
    """
    _validate_series_id(series_id)
    return progress_store.upsert(
        user_id=user["id"],
        series_id=series_id,
        ep_num=ep_num,
        position_sec=payload.position_sec,
        duration_sec=payload.duration_sec,
        updated_at=_canonical_updated_at(payload.updated_at),
    )


@router.get("/api/podcasts/{series_id}/{ep_num}/progress", response_model=PodcastProgressResponse)
def get_user_progress(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    user: CurrentUser,
):
    _validate_series_id(series_id)
    row = progress_store.get_single(
        user_id=user["id"], series_id=series_id, ep_num=ep_num,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No playback progress found")
    return row


@router.get(
    "/api/podcasts/{series_id}",
    response_model=PodcastSeriesDetail,
    response_model_exclude_unset=True,
)
def get_podcast_series(series_id: str, request: Request, user: OptionalCurrentUser):
    _validate_series_id(series_id)
    if _using_s3(request):
        data = _read_json_from_s3(
            request, f"{series_id}/metadata.json", context="metadata",
        )
        if data is None:
            raise HTTPException(status_code=404, detail="Series not found")
        return data
    meta_file = _podcasts_dir(request) / series_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Series not found")
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
            detail="Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
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
    *,
    stem: str = FULL_AUDIO_STEM,
):
    cfg = _settings(request)
    s3 = _s3_client(request)
    filename = _audio_filename(request, series_id, ep_num, stem=stem)
    key = f"{series_id}/ep_{ep_num:02d}/{filename}"
    media_type = _media_type_for(filename)

    get_kwargs = {"Bucket": cfg.podcast_bucket, "Key": key}
    if range_header:
        # S3 implements RFC 7233 Range natively. Pass the client's header through
        # so we don't reinvent suffix-range / open-ended-range parsing here.
        get_kwargs["Range"] = range_header

    try:
        obj = s3.get_object(**get_kwargs)
    except Exception as exc:  # noqa: BLE001
        http_status = int(getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0)) \
            if hasattr(exc, "response") else 0
        if _is_s3_not_found(exc, s3) or http_status == 404:
            raise HTTPException(status_code=404, detail="Audio not found") from None
        if http_status == 416:
            # Surface the 416 with the Content-Range S3 returned, mirroring
            # what _parse_range_header would have done.
            raise HTTPException(status_code=416, detail="Range not satisfiable") from None
        logger.error("S3 GetObject failed for %s: %s", key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Storage error fetching audio") from exc

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


def _require_episode_access(user: UserRecord | None, ep_num: int) -> str:
    """Shared tier gate for *episode media* (audio + transcript): both must obey
    the same wall, else a free user could read the full transcript of a Pro-only
    episode whose audio is 403'd. Returns the caller's tier; raises:

    * guest → ``401 auth_required`` (must sign in to access any episode media).
    * free + non-previewable episode → ``403 upgrade_required``.
    * free + previewable episode / pro → returns the tier.

    Errors carry a machine code in ``detail`` so the client routes to the login
    sheet vs the paywall without parsing a human string.
    """
    tier = resolve_podcast_tier(user)
    if tier == "guest":
        raise HTTPException(
            status_code=401,
            detail={"code": ERR_AUTH_REQUIRED, "message": "Sign in to play podcasts"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if tier == "free" and not is_free_previewable_episode(ep_num):
        raise HTTPException(
            status_code=403,
            detail={"code": ERR_UPGRADE_REQUIRED, "message": "Upgrade to Pro to play this episode"},
        )
    return tier


def _gate_audio_access(user: UserRecord | None, ep_num: int) -> str:
    """Resolve the audio asset stem after the tier gate: free → ``preview``
    (ep 1 only), pro → full ``audio``."""
    tier = _require_episode_access(user, ep_num)
    return PREVIEW_AUDIO_STEM if tier == "free" else FULL_AUDIO_STEM


@router.get("/api/podcasts/{series_id}/{ep_num}/audio")
def get_podcast_audio(
    series_id: str,
    ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
    request: Request,
    user: OptionalCurrentUser,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
):
    """Tiered audio stream with HTTP Range / 206 Partial Content support.

    Access is gated by :func:`_gate_audio_access` (guest → 401, free → preview
    of ep 1 only, pro → full). The resolved *stem* (``audio`` / ``preview``)
    then drives the same S3-proxy / disk-Range machinery — a free caller is
    served a *physically separate* ``preview.*`` object, so the full audio is
    never partially exposed.

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
    _validate_series_id(series_id)
    stem = _gate_audio_access(user, ep_num)

    if _using_s3(request):
        return _serve_audio_from_s3(request, series_id, ep_num, range_header, stem=stem)

    # ── disk-mode fallback (m4a → mp3 probe) ──
    filename = _audio_filename(request, series_id, ep_num, stem=stem)
    audio_file = _podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / filename
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

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
    user: OptionalCurrentUser,
):
    _validate_series_id(series_id)
    # Same wall as audio: a free caller must not read the full transcript of a
    # Pro-only episode. guest → 401, free → ep1 only, pro → all.
    _require_episode_access(user, ep_num)
    # errors="replace" on both backends: a stray non-UTF-8 byte in a subtitle
    # file must degrade gracefully, not surface as an uncaught 500. The decoded
    # str is re-encoded by Response exactly as PlainTextResponse did before.
    return _serve_static_media(
        request,
        series_id,
        f"ep_{ep_num:02d}/subtitle.srt",
        media_type="text/plain",
        context="subtitle",
        transform=lambda raw: raw.decode("utf-8", errors="replace"),
    )


@router.get("/api/podcasts/{series_id}/cover")
def get_podcast_cover(
    series_id: str,
    request: Request,
    user: OptionalCurrentUser,
):
    """Authenticated series cover image (PNG), produced by the pipeline ``cover``
    stage and uploaded as ``<sid>/cover.png``. Mirrors the subtitle proxy: S3
    ``get_object`` in production, disk fallback in dev. 404 when the series has
    no cover (legacy / pre-cover series) — the client then renders a procedural
    cover from ``color``/``coverPattern``.

    Two path segments (``{series_id}/cover``) — distinct from the 1-segment
    ``/{series_id}`` detail and 3-segment ``/{series_id}/{ep_num}/*`` routes, so
    there is no route-matching collision.
    """
    _validate_series_id(series_id)
    return _serve_static_media(
        request,
        series_id,
        "cover.png",
        media_type="image/png",
        context="cover",
        headers={"Cache-Control": "private, max-age=86400"},
        stream_s3=True,
    )

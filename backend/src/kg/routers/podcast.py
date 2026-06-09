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

import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated  # noqa: F401

from fastapi import APIRouter, Header, HTTPException, Request  # noqa: F401
from fastapi import Path as PathParam  # noqa: F401
from fastapi.responses import StreamingResponse  # noqa: F401

from ..api_models.podcast import PodcastProgressRequest  # noqa: F401
from ..deps import CurrentUser, OptionalCurrentUser  # noqa: F401
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
from . import podcast_media as _podcast_media
from . import podcast_playback as _podcast_playback
from .podcast_browse import build_podcast_browse_router
from .podcast_playback import build_podcast_playback_router
from .podcast_progress import build_podcast_progress_router

logger = logging.getLogger(__name__)

router = APIRouter(tags=["podcast"])
_SERIES_ID_RE = re.compile(r"\A[a-z0-9_]+\Z")
_MAX_EPISODE_NUM = 999


def _validate_series_id(series_id: str) -> None:
    """Reject path-unsafe series ids with a 404 (don't leak existence)."""
    if not _SERIES_ID_RE.match(series_id):
        raise HTTPException(status_code=404)


# Register the literal /progress paths before the dynamic /{series_id} detail
# route so FastAPI doesn't greedy-match "progress" as a series id.
router.include_router(
    build_podcast_progress_router(validate_series_id=_validate_series_id)
)


def _podcasts_dir(request: Request | None = None) -> Path:
    return _podcast_media._podcasts_dir(request)


def _settings(request: Request) -> KGSettings:
    return _podcast_media._settings(request)


def _using_s3(request: Request) -> bool:
    return _podcast_media._using_s3(request)


def _s3_client_cached(region: str, endpoint_url: str | None):
    return _podcast_media._s3_client_cached(region, endpoint_url)


def _s3_client(request: Request):
    return _podcast_media._s3_client(request)


def _is_s3_not_found(exc: Exception, s3) -> bool:
    return _podcast_media._is_s3_not_found(exc, s3)


_S3_AUDIO_FMT_CACHE = _podcast_media._S3_AUDIO_FMT_CACHE


def _s3_audio_format(request: Request, series_id: str) -> str:
    return _podcast_media._s3_audio_format(
        request,
        series_id,
        settings_fn=_settings,
        read_json_from_s3=_read_json_from_s3,
        s3_client_fn=_s3_client,
        is_s3_not_found_fn=_is_s3_not_found,
        logger_=logger,
        cache=_S3_AUDIO_FMT_CACHE,
    )


def _audio_filename(request: Request, series_id: str, ep_num: int, *, stem: str = FULL_AUDIO_STEM) -> str:
    return _podcast_media._audio_filename(
        request,
        series_id,
        ep_num,
        stem=stem,
        using_s3=_using_s3,
        s3_audio_format=_s3_audio_format,
        podcasts_dir=_podcasts_dir,
    )


def _media_type_for(filename: str) -> str:
    return _podcast_media._media_type_for(filename)


def _read_json_file(path: Path, *, context: str):
    return _podcast_media._read_json_file(path, context=context, logger_=logger)


def _read_json_from_s3(request: Request, key: str, *, context: str):
    return _podcast_media._read_json_from_s3(
        request,
        key,
        context=context,
        settings_fn=_settings,
        s3_client_fn=_s3_client,
        is_s3_not_found_fn=_is_s3_not_found,
        logger_=logger,
    )


def _get_object_from_s3(request: Request, key: str, *, context: str):
    return _podcast_media._get_object_from_s3(
        request,
        key,
        context=context,
        settings_fn=_settings,
        s3_client_fn=_s3_client,
        is_s3_not_found_fn=_is_s3_not_found,
        logger_=logger,
    )


def _read_bytes_from_s3(request: Request, key: str, *, context: str) -> bytes | None:
    return _podcast_media._read_bytes_from_s3(
        request,
        key,
        context=context,
        get_object_from_s3=_get_object_from_s3,
    )


def _s3_static_headers(obj: dict, base_headers: dict[str, str] | None = None) -> dict[str, str]:
    return _podcast_media._s3_static_headers(obj, base_headers)


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
    return _podcast_media._serve_static_media(
        request,
        series_id,
        rel_key,
        media_type=media_type,
        context=context,
        headers=headers,
        transform=transform,
        stream_s3=stream_s3,
        using_s3=_using_s3,
        get_object_from_s3=_get_object_from_s3,
        iter_s3_body=_iter_s3_body,
        s3_static_headers=_s3_static_headers,
        read_bytes_from_s3=_read_bytes_from_s3,
        podcasts_dir=_podcasts_dir,
    )


router.include_router(
    build_podcast_browse_router(
        validate_series_id=_validate_series_id,
        using_s3=_using_s3,
        read_json_from_s3=_read_json_from_s3,
        podcasts_dir=_podcasts_dir,
        read_json_file=_read_json_file,
        serve_static_media=_serve_static_media,
    )
)


_AUDIO_CHUNK_SIZE = 64 * 1024  # 64 KiB per network read — balances RAM vs syscalls.


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    return _podcast_playback._parse_range_header(range_header, file_size)


def _iter_file_range(
    path: Path,
    start: int,
    end: int,
    chunk_size: int = _AUDIO_CHUNK_SIZE,
) -> Iterator[bytes]:
    return _podcast_playback._iter_file_range(path, start, end, chunk_size)


def _iter_s3_body(body, chunk_size: int = _AUDIO_CHUNK_SIZE):
    return _podcast_media._iter_s3_body(body, chunk_size)


def _serve_audio_from_s3(
    request: Request,
    series_id: str,
    ep_num: int,
    range_header: str | None,
    *,
    stem: str = FULL_AUDIO_STEM,
):
    return _podcast_media._serve_audio_from_s3(
        request,
        series_id,
        ep_num,
        range_header,
        stem=stem,
        settings_fn=_settings,
        s3_client_fn=_s3_client,
        audio_filename=_audio_filename,
        media_type_for=_media_type_for,
        is_s3_not_found_fn=_is_s3_not_found,
        iter_s3_body=_iter_s3_body,
        logger_=logger,
    )


def _require_episode_access(user: UserRecord | None, ep_num: int) -> str:
    return _podcast_playback._require_episode_access(
        user,
        ep_num,
        resolve_podcast_tier=resolve_podcast_tier,
        is_free_previewable_episode=is_free_previewable_episode,
        auth_required_code=ERR_AUTH_REQUIRED,
        upgrade_required_code=ERR_UPGRADE_REQUIRED,
    )


def _gate_audio_access(user: UserRecord | None, ep_num: int) -> str:
    return _podcast_playback._gate_audio_access(
        user,
        ep_num,
        require_episode_access=_require_episode_access,
        preview_audio_stem=PREVIEW_AUDIO_STEM,
        full_audio_stem=FULL_AUDIO_STEM,
    )


router.include_router(
    build_podcast_playback_router(
        validate_series_id=_validate_series_id,
        using_s3=_using_s3,
        serve_audio_from_s3=_serve_audio_from_s3,
        gate_audio_access=_gate_audio_access,
        audio_filename=_audio_filename,
        podcasts_dir=_podcasts_dir,
        media_type_for=_media_type_for,
        parse_range_header=_parse_range_header,
        iter_file_range=_iter_file_range,
        require_episode_access=_require_episode_access,
        serve_static_media=_serve_static_media,
    )
)

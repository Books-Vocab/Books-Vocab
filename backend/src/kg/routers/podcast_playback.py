from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import StreamingResponse

from ..deps import OptionalCurrentUser
from ..types import UserRecord

_MAX_EPISODE_NUM = 999
_AUDIO_CHUNK_SIZE = 64 * 1024  # 64 KiB per network read — balances RAM vs syscalls.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class ServeAudioFromS3(Protocol):
    def __call__(
        self,
        request: Request,
        series_id: str,
        ep_num: int,
        range_header: str | None,
        *,
        stem: str,
    ) -> StreamingResponse:
        ...


class ServeStaticMedia(Protocol):
    def __call__(
        self,
        request: Request,
        series_id: str,
        rel_key: str,
        *,
        media_type: str,
        context: str,
        headers: dict[str, str] | None = None,
        transform: Callable[[bytes], bytes | str] = lambda b: b,
        stream_s3: bool = False,
    ) -> StreamingResponse:
        ...


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range ``Range: bytes=...`` header per RFC 7233."""
    m = _RANGE_RE.match(range_header.strip())
    if not m:
        return None
    start_s, end_s = m.group(1), m.group(2)
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
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


def _iter_file_range(
    path: Path,
    start: int,
    end: int,
    chunk_size: int = _AUDIO_CHUNK_SIZE,
) -> Iterator[bytes]:
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


def _require_episode_access(
    user: UserRecord | None,
    ep_num: int,
    *,
    resolve_podcast_tier: Callable[[UserRecord | None], str],
    is_free_previewable_episode: Callable[[int], bool],
    auth_required_code: str,
    upgrade_required_code: str,
) -> str:
    """Shared tier gate for episode media (audio + transcript)."""
    tier = resolve_podcast_tier(user)
    if tier == "guest":
        raise HTTPException(
            status_code=401,
            detail={"code": auth_required_code, "message": "Sign in to play podcasts"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if tier == "free" and not is_free_previewable_episode(ep_num):
        raise HTTPException(
            status_code=403,
            detail={"code": upgrade_required_code, "message": "Upgrade to Pro to play this episode"},
        )
    return tier


def _gate_audio_access(
    user: UserRecord | None,
    ep_num: int,
    *,
    require_episode_access: Callable[[UserRecord | None, int], str],
    preview_audio_stem: str,
    full_audio_stem: str,
) -> str:
    """Resolve the audio asset stem after the tier gate."""
    tier = require_episode_access(user, ep_num)
    return preview_audio_stem if tier == "free" else full_audio_stem


def build_podcast_playback_router(
    *,
    validate_series_id: Callable[[str], None],
    using_s3: Callable[[Request], bool],
    serve_audio_from_s3: ServeAudioFromS3,
    gate_audio_access: Callable[[UserRecord | None, int], str],
    audio_filename: Callable[[Request, str, int], str],
    podcasts_dir: Callable[[Request], Path],
    media_type_for: Callable[[str], str],
    parse_range_header: Callable[[str, int], tuple[int, int] | None],
    iter_file_range: Callable[[Path, int, int], Iterator[bytes]],
    require_episode_access: Callable[[UserRecord | None, int], str],
    serve_static_media: ServeStaticMedia,
) -> APIRouter:
    router = APIRouter(tags=["podcast"])

    @router.get("/api/podcasts/{series_id}/{ep_num}/audio")
    def get_podcast_audio(
        series_id: str,
        ep_num: Annotated[int, PathParam(ge=1, le=_MAX_EPISODE_NUM)],
        request: Request,
        user: OptionalCurrentUser,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ):
        validate_series_id(series_id)
        stem = gate_audio_access(user, ep_num)

        if using_s3(request):
            return serve_audio_from_s3(request, series_id, ep_num, range_header, stem=stem)

        filename = audio_filename(request, series_id, ep_num, stem=stem)
        audio_file = podcasts_dir(request) / series_id / f"ep_{ep_num:02d}" / filename
        if not audio_file.exists():
            raise HTTPException(status_code=404, detail="Audio not found")

        media_type = media_type_for(filename)
        file_size = audio_file.stat().st_size
        common_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-transform",
        }

        if range_header:
            parsed = parse_range_header(range_header, file_size)
            if parsed is not None:
                start, end = parsed
                length = end - start + 1
                headers = {
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                }
                return StreamingResponse(
                    iter_file_range(audio_file, start, end),
                    status_code=206,
                    media_type=media_type,
                    headers=headers,
                )

        headers = {**common_headers, "Content-Length": str(file_size)}
        return StreamingResponse(
            iter_file_range(audio_file, 0, file_size - 1),
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
        validate_series_id(series_id)
        require_episode_access(user, ep_num)
        return serve_static_media(
            request,
            series_id,
            f"ep_{ep_num:02d}/subtitle.srt",
            media_type="text/plain",
            context="subtitle",
            transform=lambda raw: raw.decode("utf-8", errors="replace"),
        )

    return router

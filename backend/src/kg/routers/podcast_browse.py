from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..api_models.podcast import PodcastSeriesDetail, PodcastSeriesSummary
from ..deps import OptionalCurrentUser
from ..podcast_access import is_free_previewable_episode, resolve_podcast_tier

logger = logging.getLogger(__name__)


class ReadJsonFromS3(Protocol):
    def __call__(self, request: Request, key: str, *, context: str) -> Any: ...


class ReadJsonFile(Protocol):
    def __call__(self, path: Path, *, context: str) -> Any: ...


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
    ) -> StreamingResponse: ...


def _allows_inline_subtitle(value: dict[str, Any], tier: str) -> bool:
    if tier != "free":
        return False
    for key in ("episodeNumber", "epNum"):
        episode_number = value.get(key)
        if type(episode_number) is int and is_free_previewable_episode(episode_number):
            return True
    return False


def _filter_inline_subtitles(value: Any, tier: str) -> Any:
    """Keep browse metadata from exposing transcript bodies to unauthorized tiers."""
    if tier == "pro":
        return value
    if isinstance(value, list):
        return [_filter_inline_subtitles(item, tier) for item in value]
    if not isinstance(value, dict):
        return value

    allow_subtitle = _allows_inline_subtitle(value, tier)
    return {
        key: _filter_inline_subtitles(item, tier)
        for key, item in value.items()
        if key != "subtitleContent" or allow_subtitle
    }


def build_podcast_browse_router(
    *,
    validate_series_id: Callable[[str], None],
    using_s3: Callable[[Request], bool],
    read_json_from_s3: ReadJsonFromS3,
    podcasts_dir: Callable[[Request], Path],
    read_json_file: ReadJsonFile,
    serve_static_media: ServeStaticMedia,
) -> APIRouter:
    router = APIRouter(tags=["podcast"])

    @router.get(
        "/api/podcasts",
        response_model=list[PodcastSeriesSummary],
        response_model_exclude_unset=True,
    )
    def list_podcasts(request: Request, user: OptionalCurrentUser):
        if using_s3(request):
            data = read_json_from_s3(request, "index.json", context="index")
            if data is None:
                return []
        else:
            index_file = podcasts_dir(request) / "index.json"
            if not index_file.exists():
                return []
            data = read_json_file(index_file, context="index")
        if not isinstance(data, list):
            logger.error("Podcast index malformed (expected list)")
            raise HTTPException(status_code=500, detail="Malformed podcast index")
        return _filter_inline_subtitles(data, resolve_podcast_tier(user))

    @router.get(
        "/api/podcasts/{series_id}",
        response_model=PodcastSeriesDetail,
        response_model_exclude_unset=True,
    )
    def get_podcast_series(series_id: str, request: Request, user: OptionalCurrentUser):
        validate_series_id(series_id)
        if using_s3(request):
            data = read_json_from_s3(
                request,
                f"{series_id}/metadata.json",
                context="metadata",
            )
            if data is None:
                raise HTTPException(status_code=404, detail="Series not found")
            return _filter_inline_subtitles(data, resolve_podcast_tier(user))
        meta_file = podcasts_dir(request) / series_id / "metadata.json"
        if not meta_file.exists():
            raise HTTPException(status_code=404, detail="Series not found")
        data = read_json_file(meta_file, context="metadata")
        return _filter_inline_subtitles(data, resolve_podcast_tier(user))

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
        validate_series_id(series_id)
        return serve_static_media(
            request,
            series_id,
            "cover.png",
            media_type="image/png",
            context="cover",
            headers={"Cache-Control": "private, max-age=86400"},
            stream_s3=True,
        )

    return router

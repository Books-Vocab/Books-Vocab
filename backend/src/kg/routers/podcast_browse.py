from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..api_models.podcast import PodcastSeriesDetail, PodcastSeriesSummary
from ..deps import OptionalCurrentUser

logger = logging.getLogger(__name__)


class ReadJsonFromS3(Protocol):
    def __call__(self, request: Request, key: str, *, context: str) -> Any:
        ...


class ReadJsonFile(Protocol):
    def __call__(self, path: Path, *, context: str) -> Any:
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
        return data

    @router.get(
        "/api/podcasts/{series_id}",
        response_model=PodcastSeriesDetail,
        response_model_exclude_unset=True,
    )
    def get_podcast_series(series_id: str, request: Request, user: OptionalCurrentUser):
        validate_series_id(series_id)
        if using_s3(request):
            data = read_json_from_s3(
                request, f"{series_id}/metadata.json", context="metadata",
            )
            if data is None:
                raise HTTPException(status_code=404, detail="Series not found")
            return data
        meta_file = podcasts_dir(request) / series_id / "metadata.json"
        if not meta_file.exists():
            raise HTTPException(status_code=404, detail="Series not found")
        return read_json_file(meta_file, context="metadata")

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

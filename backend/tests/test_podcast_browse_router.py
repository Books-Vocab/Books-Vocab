from __future__ import annotations

from fastapi import APIRouter

from kg.routers.podcast_browse import (
    _filter_inline_subtitles,
    build_podcast_browse_router,
)


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}


def test_build_podcast_browse_router_returns_named_surface():
    router = build_podcast_browse_router(
        validate_series_id=lambda _series_id: None,
        using_s3=lambda _request: False,
        read_json_from_s3=lambda _request, _key, *, context: None,
        podcasts_dir=lambda _request: None,
        read_json_file=lambda _path, *, context: None,
        serve_static_media=lambda *args, **kwargs: None,
    )

    assert isinstance(router, APIRouter)
    assert _route_surface(router) == {
        ("/api/podcasts", ("GET",)),
        ("/api/podcasts/{series_id}", ("GET",)),
        ("/api/podcasts/{series_id}/cover", ("GET",)),
    }


def test_free_tier_hides_inline_subtitle_when_preview_is_unavailable():
    detail = {
        "id": "series_a",
        "episodes": [
            {
                "episodeNumber": 1,
                "previewAvailable": False,
                "subtitleContent": "full transcript must stay hidden",
            }
        ],
    }

    filtered = _filter_inline_subtitles(detail, "free")

    assert "subtitleContent" not in filtered["episodes"][0]

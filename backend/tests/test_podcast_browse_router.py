from __future__ import annotations

import json

from fastapi import APIRouter, Response
from starlette.requests import Request

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


def test_tiered_browse_responses_are_not_shared_across_authorization_tiers(tmp_path):
    podcasts_dir = tmp_path / "podcasts"
    series_dir = podcasts_dir / "series_a"
    series_dir.mkdir(parents=True)
    (podcasts_dir / "index.json").write_text(json.dumps([{"id": "series_a"}]))
    (series_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "series_a",
                "episodes": [{"episodeNumber": 1, "subtitleContent": "private transcript"}],
            }
        )
    )

    router = build_podcast_browse_router(
        validate_series_id=lambda _series_id: None,
        using_s3=lambda _request: False,
        read_json_from_s3=lambda _request, _key, *, context: None,
        podcasts_dir=lambda _request: podcasts_dir,
        read_json_file=lambda path, *, context: json.loads(path.read_text()),
        serve_static_media=lambda *args, **kwargs: None,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/podcasts",
            "headers": [],
            "query_string": b"",
        }
    )

    list_endpoint = next(route.endpoint for route in router.routes if route.path == "/api/podcasts")
    detail_endpoint = next(route.endpoint for route in router.routes if route.path == "/api/podcasts/{series_id}")
    for endpoint, kwargs in (
        (list_endpoint, {}),
        (detail_endpoint, {"series_id": "series_a"}),
    ):
        response = Response()
        endpoint(request=request, user=None, response=response, **kwargs)

        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Authorization"

from __future__ import annotations

from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BeforeValidator

from kg.api import app
from kg.api_models.podcast import PodcastProgressRequest
from kg.routers import podcast
from kg.routers.podcast_progress import build_podcast_progress_router


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}


def test_build_podcast_progress_router_returns_named_surface():
    router = build_podcast_progress_router(validate_series_id=lambda _series_id: None)

    assert isinstance(router, APIRouter)
    assert _route_surface(router) == {
        ("/api/podcasts/progress", ("GET",)),
        ("/api/podcasts/{series_id}/{ep_num}/progress", ("GET",)),
        ("/api/podcasts/{series_id}/{ep_num}/progress", ("POST",)),
    }


def test_progress_payload_annotation_resolves_from_parent_router_module_globals():
    post_route = next(
        route
        for route in podcast.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/podcasts/{series_id}/{ep_num}/progress"
        and route.methods == {"POST"}
    )

    hints = get_type_hints(
        post_route.endpoint,
        globalns=vars(podcast),
        include_extras=True,
    )

    payload_hint = hints["payload"]
    assert get_origin(payload_hint) is Annotated
    assert get_args(payload_hint)[0] is PodcastProgressRequest
    assert any(isinstance(metadata, BeforeValidator) for metadata in get_args(payload_hint)[1:])


def test_progress_payload_preserves_openapi_request_schema():
    app.openapi_schema = None
    request_schema = app.openapi()["paths"]["/api/podcasts/{series_id}/{ep_num}/progress"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]

    assert request_schema == {"$ref": "#/components/schemas/PodcastProgressRequest"}


@pytest.mark.parametrize("field", ["position_sec", "duration_sec"])
def test_progress_rejects_boolean_seconds_before_persistence(isolated_api, field):
    payload = {
        "position_sec": 12.5,
        "duration_sec": 120.0,
        "updated_at": "2026-08-31T00:00:00Z",
    }
    payload[field] = True

    response = isolated_api.client.post(
        "/api/podcasts/sample/1/progress",
        json=payload,
        headers=isolated_api.headers,
    )

    assert response.status_code == 422
    assert (
        isolated_api.client.get(
            "/api/podcasts/sample/1/progress",
            headers=isolated_api.headers,
        ).status_code
        == 404
    )

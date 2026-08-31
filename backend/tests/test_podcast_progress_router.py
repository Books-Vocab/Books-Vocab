from __future__ import annotations

import pytest
from fastapi import APIRouter

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

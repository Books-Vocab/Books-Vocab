from __future__ import annotations

from fastapi import APIRouter

from kg.routers.podcast_progress import build_podcast_progress_router


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or ())))
        for route in router.routes
    }


def test_build_podcast_progress_router_returns_named_surface():
    router = build_podcast_progress_router(validate_series_id=lambda _series_id: None)

    assert isinstance(router, APIRouter)
    assert _route_surface(router) == {
        ("/api/podcasts/progress", ("GET",)),
        ("/api/podcasts/{series_id}/{ep_num}/progress", ("GET",)),
        ("/api/podcasts/{series_id}/{ep_num}/progress", ("POST",)),
    }

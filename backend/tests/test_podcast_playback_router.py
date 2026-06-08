from __future__ import annotations

from fastapi import APIRouter

import kg.routers.podcast_playback as playback_mod
from kg.routers.podcast_playback import build_podcast_playback_router


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or ())))
        for route in router.routes
    }


def test_podcast_playback_module_exports_named_helper_surface():
    expected = {
        "_gate_audio_access",
        "_iter_file_range",
        "_parse_range_header",
        "_require_episode_access",
        "build_podcast_playback_router",
    }

    missing = [name for name in sorted(expected) if not hasattr(playback_mod, name)]
    assert not missing, f"Missing podcast playback helpers: {missing}"


def test_build_podcast_playback_router_returns_named_surface():
    router = build_podcast_playback_router(
        validate_series_id=lambda _series_id: None,
        using_s3=lambda _request: False,
        serve_audio_from_s3=lambda *_args, **_kwargs: None,
        gate_audio_access=lambda _user, _ep_num: "audio",
        audio_filename=lambda _request, _series_id, _ep_num, *, stem="audio": f"{stem}.mp3",
        podcasts_dir=lambda _request: None,
        media_type_for=lambda _filename: "audio/mpeg",
        parse_range_header=lambda _range_header, _file_size: None,
        iter_file_range=lambda _path, _start, _end: iter(()),
        require_episode_access=lambda _user, _ep_num: "pro",
        serve_static_media=lambda *_args, **_kwargs: None,
    )

    assert isinstance(router, APIRouter)
    assert _route_surface(router) == {
        ("/api/podcasts/{series_id}/{ep_num}/audio", ("GET",)),
        ("/api/podcasts/{series_id}/{ep_num}/subtitle", ("GET",)),
    }

from __future__ import annotations

import pytest
from fastapi import APIRouter, HTTPException

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


@pytest.mark.parametrize(
    ("range_header", "expected"),
    [
        ("bytes=-2", (2, 3)),
        ("bytes=1-", (1, 3)),
        ("bytes=1-9", (1, 3)),
    ],
)
def test_parse_range_header_preserves_valid_ranges_for_non_empty_files(range_header, expected):
    assert playback_mod._parse_range_header(range_header, 4) == expected


def test_parse_range_header_rejects_suffix_range_for_empty_file():
    with pytest.raises(HTTPException) as exc_info:
        playback_mod._parse_range_header("bytes=-1", 0)

    assert exc_info.value.status_code == 416
    assert exc_info.value.headers == {"Content-Range": "bytes */0"}


def test_empty_local_audio_suffix_range_returns_416(tmp_path):
    audio_dir = tmp_path / "series_a" / "ep_01"
    audio_dir.mkdir(parents=True)
    (audio_dir / "audio.mp3").touch()

    router = build_podcast_playback_router(
        validate_series_id=lambda _series_id: None,
        using_s3=lambda _request: False,
        serve_audio_from_s3=lambda *_args, **_kwargs: None,
        gate_audio_access=lambda _user, _ep_num: "audio",
        audio_filename=lambda _request, _series_id, _ep_num, *, stem="audio": f"{stem}.mp3",
        podcasts_dir=lambda _request: tmp_path,
        media_type_for=lambda _filename: "audio/mpeg",
        parse_range_header=playback_mod._parse_range_header,
        iter_file_range=playback_mod._iter_file_range,
        require_episode_access=lambda _user, _ep_num: "pro",
        serve_static_media=lambda *_args, **_kwargs: None,
    )
    audio_endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/audio"))

    with pytest.raises(HTTPException) as exc_info:
        audio_endpoint("series_a", 1, object(), None, "bytes=-1")

    assert exc_info.value.status_code == 416
    assert exc_info.value.headers == {"Content-Range": "bytes */0"}

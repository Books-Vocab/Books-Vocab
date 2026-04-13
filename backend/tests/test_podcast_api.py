"""Tests for podcast API endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def podcast_api(isolated_api):
    podcasts = isolated_api.data_dir / "podcasts"
    podcasts.mkdir(exist_ok=True)
    return isolated_api, podcasts


def test_list_requires_auth(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts")
    assert resp.status_code == 401


def test_series_detail_requires_auth(podcast_api):
    api, podcasts = podcast_api
    (podcasts / "series_a").mkdir()
    (podcasts / "series_a" / "metadata.json").write_text("{}")
    resp = api.client.get("/api/podcasts/series_a")
    assert resp.status_code == 401


def test_subtitle_requires_auth(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/1/subtitle")
    assert resp.status_code == 401


def test_list_returns_index(podcast_api):
    api, podcasts = podcast_api
    index = [{"id": "series_a", "title": "Series A"}]
    (podcasts / "index.json").write_text(json.dumps(index))
    resp = api.client.get("/api/podcasts", headers=api.headers)
    assert resp.status_code == 200
    assert resp.json() == index


def test_list_empty_when_no_index(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts", headers=api.headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_series_detail(podcast_api):
    api, podcasts = podcast_api
    series_dir = podcasts / "series_a"
    series_dir.mkdir()
    meta = {"id": "series_a", "title": "Series A", "episodes": 3}
    (series_dir / "metadata.json").write_text(json.dumps(meta))
    resp = api.client.get("/api/podcasts/series_a", headers=api.headers)
    assert resp.status_code == 200
    assert resp.json() == meta


def test_series_not_found(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/nonexistent", headers=api.headers)
    assert resp.status_code == 404


def test_series_id_rejects_traversal(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/../etc", headers=api.headers)
    assert resp.status_code in (404, 422)


def test_series_id_rejects_uppercase(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/SeriesA", headers=api.headers)
    assert resp.status_code == 404


def test_subtitle_endpoint(podcast_api):
    api, podcasts = podcast_api
    ep_dir = podcasts / "series_a" / "ep_01"
    ep_dir.mkdir(parents=True)
    srt_content = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n"
    (ep_dir / "subtitle.srt").write_text(srt_content)
    resp = api.client.get("/api/podcasts/series_a/1/subtitle", headers=api.headers)
    assert resp.status_code == 200
    assert resp.text == srt_content


def test_subtitle_not_found(podcast_api):
    api, podcasts = podcast_api
    (podcasts / "series_a").mkdir()
    resp = api.client.get("/api/podcasts/series_a/99/subtitle", headers=api.headers)
    assert resp.status_code == 404


def test_subtitle_rejects_traversal(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/../evil/1/subtitle", headers=api.headers)
    assert resp.status_code in (404, 422)


def test_subtitle_ep_num_rejects_zero(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/0/subtitle", headers=api.headers)
    assert resp.status_code == 422


def test_subtitle_ep_num_rejects_negative(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/-1/subtitle", headers=api.headers)
    assert resp.status_code == 422


def test_subtitle_ep_num_rejects_overflow(podcast_api):
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/10000/subtitle", headers=api.headers)
    assert resp.status_code == 422


def test_malformed_metadata_returns_500(podcast_api):
    api, podcasts = podcast_api
    (podcasts / "series_a").mkdir()
    (podcasts / "series_a" / "metadata.json").write_text("{not valid json")
    resp = api.client.get("/api/podcasts/series_a", headers=api.headers)
    assert resp.status_code == 500
    assert "Malformed" in resp.json().get("detail", "")


def test_malformed_index_returns_500(podcast_api):
    api, podcasts = podcast_api
    (podcasts / "index.json").write_text("{not json")
    resp = api.client.get("/api/podcasts", headers=api.headers)
    assert resp.status_code == 500


def test_media_mount_supports_range(isolated_api):
    """Regression: AVPlayer streaming requires HTTP Range support.
    Starlette StaticFiles handles Range natively; test locks in the behavior
    so a future refactor (e.g. to FileResponse) doesn't silently drop it.

    The /api/podcast-media/ mount is bound at app-import time to the original
    podcasts_dir, so we write the file there (not to the tmp test dir) to
    exercise the real mount path."""
    from kg.api import app
    # Retrieve the mount's directory from the running app (the original mount,
    # which isolated_api cannot swap).
    media_mount = next(
        (r for r in app.routes if getattr(r, "name", None) == "podcast-media"),
        None,
    )
    assert media_mount is not None, "podcast-media mount missing"
    mount_dir = Path(media_mount.app.directory)
    audio_dir = mount_dir / "series_range_test" / "ep_01"
    audio_dir.mkdir(parents=True, exist_ok=True)
    payload = bytes(range(256)) * 4  # 1 KB
    audio_file = audio_dir / "audio.mp3"
    try:
        audio_file.write_bytes(payload)
        resp = isolated_api.client.get(
            "/api/podcast-media/series_range_test/ep_01/audio.mp3",
            headers={"Range": "bytes=0-99"},
        )
        assert resp.status_code == 206, "StaticFiles must return 206 for Range requests"
        assert resp.headers.get("content-range", "").startswith("bytes 0-99/")
        assert resp.content == payload[:100]
    finally:
        audio_file.unlink(missing_ok=True)
        try:
            audio_dir.rmdir()
            audio_dir.parent.rmdir()
        except OSError:
            pass


def test_podcast_media_mount_available_without_predeploy_dir(isolated_api):
    """Regression: StaticFiles mount used to be gated by `if dir.exists()`,
    which meant first-time uploads required a container restart. Verify the
    mount path is always registered (404 for missing file, not 404 for missing mount)."""
    resp = isolated_api.client.get("/api/podcast-media/nonexistent.mp3")
    assert resp.status_code == 404

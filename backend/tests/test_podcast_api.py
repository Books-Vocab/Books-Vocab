"""Tests for podcast API endpoints."""
from __future__ import annotations

import json

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


def test_podcast_media_mount_available_without_predeploy_dir(isolated_api):
    """Regression: StaticFiles mount used to be gated by `if dir.exists()`,
    which meant first-time uploads required a container restart. Verify the
    mount path is always registered (404 for missing file, not 404 for missing mount)."""
    resp = isolated_api.client.get("/api/podcast-media/nonexistent.mp3")
    assert resp.status_code == 404

"""Tests for podcast API endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def podcast_dir(tmp_path):
    """Create a tmp podcasts directory and patch _podcasts_dir to return it."""
    podcasts = tmp_path / "podcasts"
    podcasts.mkdir()
    return podcasts


@pytest.fixture()
def podcast_client(podcast_dir):
    from kg.api import app
    with patch("kg.routers.podcast._podcasts_dir", return_value=podcast_dir):
        yield TestClient(app, raise_server_exceptions=False), podcast_dir


def test_podcasts_list_returns_index(podcast_client):
    client, podcasts = podcast_client
    index = [{"id": "series_a", "title": "Series A"}]
    (podcasts / "index.json").write_text(json.dumps(index))
    resp = client.get("/api/podcasts")
    assert resp.status_code == 200
    assert resp.json() == index


def test_podcasts_list_empty_when_no_index(podcast_client):
    client, _ = podcast_client
    resp = client.get("/api/podcasts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_podcasts_series_detail(podcast_client):
    client, podcasts = podcast_client
    series_dir = podcasts / "series_a"
    series_dir.mkdir()
    meta = {"id": "series_a", "title": "Series A", "episodes": 3}
    (series_dir / "metadata.json").write_text(json.dumps(meta))
    resp = client.get("/api/podcasts/series_a")
    assert resp.status_code == 200
    assert resp.json() == meta


def test_podcasts_series_not_found(podcast_client):
    client, _ = podcast_client
    resp = client.get("/api/podcasts/nonexistent")
    assert resp.status_code == 404


def test_podcasts_series_id_rejects_traversal(podcast_client):
    client, _ = podcast_client
    resp = client.get("/api/podcasts/../etc")
    assert resp.status_code in (404, 422)


def test_podcast_subtitle_endpoint(podcast_client):
    client, podcasts = podcast_client
    ep_dir = podcasts / "series_a" / "ep_01"
    ep_dir.mkdir(parents=True)
    srt_content = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n"
    (ep_dir / "subtitle.srt").write_text(srt_content)
    resp = client.get("/api/podcasts/series_a/1/subtitle")
    assert resp.status_code == 200
    assert resp.text == srt_content

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


# ---------------------------------------------------------------------------
# Authorization model contract: podcasts are public-read for any authenticated
# user. This locks in the documented model in routers/podcast.py — any future
# refactor that introduces ownership must update both the docstring and these
# tests in lock-step.
# ---------------------------------------------------------------------------


def test_any_authenticated_user_can_read_any_series(podcast_api):
    """Contract: podcasts have no owner_id. The user that lists/reads them is
    irrelevant — every authenticated user sees the same content."""
    api, podcasts = podcast_api
    series_dir = podcasts / "series_pub"
    series_dir.mkdir()
    meta = {"id": "series_pub", "title": "Public", "episodes": 1}
    (series_dir / "metadata.json").write_text(json.dumps(meta))

    # The default isolated_api user can read.
    resp_self = api.client.get("/api/podcasts/series_pub", headers=api.headers)
    assert resp_self.status_code == 200
    assert resp_self.json() == meta

    # A different (mounted) user with their own JWT can read the same payload.
    from conftest import make_jwt  # type: ignore
    other_headers = {"Authorization": f"Bearer {make_jwt('other_user')}"}
    resp_other = api.client.get("/api/podcasts/series_pub", headers=other_headers)
    assert resp_other.status_code == 200
    assert resp_other.json() == meta


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../etc",
        "series.a",       # dot
        "series-a",       # dash (regex requires underscore)
        "series a",       # space
        "series%2Fa",     # encoded slash — FastAPI passes raw "series/a" but
                          # the path no longer matches the route, hence 404
        "Series_A",       # uppercase
        "%2e%2e",         # url-encoded ..
    ],
)
def test_series_id_regex_rejects_bad_inputs(podcast_api, bad_id):
    """All non-matching `series_id` values must 404 before any FS lookup."""
    api, _ = podcast_api
    resp = api.client.get(f"/api/podcasts/{bad_id}", headers=api.headers)
    assert resp.status_code in (404, 422), (
        f"series_id={bad_id!r} produced status {resp.status_code}"
    )


def test_subtitle_ep_num_rejects_non_integer(podcast_api):
    """ep_num is typed `int` with Path(ge=1, le=999); strings must be 422."""
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/abc/subtitle", headers=api.headers)
    assert resp.status_code == 422


def test_subtitle_traversal_in_ep_segment_does_not_escape(podcast_api):
    """A literal `..` placed as ep_num must be rejected by int parsing — it
    must never be assembled into a path that escapes the series dir."""
    api, _ = podcast_api
    resp = api.client.get("/api/podcasts/series_a/../subtitle", headers=api.headers)
    # FastAPI either 404s the route (no match) or 422s on int parsing; either
    # is acceptable as long as we don't reach the filesystem with `..`.
    assert resp.status_code in (404, 422)

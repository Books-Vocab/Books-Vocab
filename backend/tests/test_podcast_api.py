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


def test_legacy_podcast_media_mount_removed(isolated_api):
    """The legacy public /api/podcast-media/ StaticFiles mount has been removed.

    Production deprecation logs showed ZERO hits on the mount over a 12-day
    window (container up since 2026-05-18) while the authenticated
    /api/podcasts/{series_id}/{ep_num}/audio endpoint served 734 podcast
    requests — every shipped client had already migrated off the mount. The
    unauthenticated StaticFiles mount was the sole public-read bypass of
    podcast auth; removing it closes that surface. This test locks in the
    removal so the mount can't silently reappear in a future refactor.
    """
    from kg.api import app
    media_mount = next(
        (r for r in app.routes if getattr(r, "name", None) == "podcast-media"),
        None,
    )
    assert media_mount is None, "legacy podcast-media mount must stay removed"
    # With no StaticFiles catch-all, the path falls through to normal routing
    # and 404s (no route matches).
    resp = isolated_api.client.get("/api/podcast-media/anything/ep_01/audio.mp3")
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


# ---------------------------------------------------------------------------
# Phase 0: S3-mode audio filename resolution must honour metadata audioFormat.
#
# Regression: `_audio_filename` previously returned a hardcoded "audio.m4a" in
# S3 mode, ignoring metadata. Legacy series are mp3 → audio endpoint built the
# wrong key (audio.m4a) → 404. Masked only because the prod bucket was empty.
# These unit-test the resolver directly (S3 mode needs no HTTP fixture).
# ---------------------------------------------------------------------------
from types import SimpleNamespace  # noqa: E402

from kg.routers import podcast as _podcast_mod  # noqa: E402


def _s3_request(bucket: str = "kg-podcasts-prod"):
    settings = SimpleNamespace(
        podcast_bucket=bucket,
        podcast_bucket_region="ap-northeast-1",
        podcast_bucket_endpoint_url=None,
    )
    app = SimpleNamespace(state=SimpleNamespace(kg_settings=settings))
    return SimpleNamespace(app=app)


@pytest.fixture()
def _clear_audio_fmt_cache():
    _podcast_mod._S3_AUDIO_FMT_CACHE.clear()
    yield
    _podcast_mod._S3_AUDIO_FMT_CACHE.clear()


def test_audio_format_honoured_from_metadata_s3(monkeypatch, _clear_audio_fmt_cache):
    req = _s3_request()
    monkeypatch.setattr(
        _podcast_mod, "_read_json_from_s3",
        lambda request, key, *, context: {"audioFormat": "mp3"},
    )
    assert _podcast_mod._audio_filename(req, "flow_x", 1) == "audio.mp3"


def test_audio_format_m4a_from_metadata_s3(monkeypatch, _clear_audio_fmt_cache):
    req = _s3_request()
    monkeypatch.setattr(
        _podcast_mod, "_read_json_from_s3",
        lambda request, key, *, context: {"audioFormat": "m4a"},
    )
    assert _podcast_mod._audio_filename(req, "flow_x", 1) == "audio.m4a"


def test_audio_format_probes_bucket_when_metadata_lacks_field(monkeypatch, _clear_audio_fmt_cache):
    """Legacy metadata.json without audioFormat → probe bucket; mp3 wins when
    only mp3 exists (m4a head_object 404s)."""
    req = _s3_request()
    monkeypatch.setattr(
        _podcast_mod, "_read_json_from_s3",
        lambda request, key, *, context: {"title": "x"},  # no audioFormat
    )

    class _NoSuchKey(Exception):
        pass

    class _FakeS3:
        exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

        def head_object(self, Bucket, Key):  # noqa: N803
            if Key.endswith("audio.m4a"):
                raise _NoSuchKey()
            return {"ContentLength": 10}

    monkeypatch.setattr(_podcast_mod, "_s3_client", lambda request: _FakeS3())
    assert _podcast_mod._audio_filename(req, "legacy_mp3", 1) == "audio.mp3"


def test_audio_format_cached_per_series_s3(monkeypatch, _clear_audio_fmt_cache):
    """Format resolved once per (bucket, series): metadata read is not repeated
    on subsequent audio requests (streaming issues many Range calls)."""
    req = _s3_request()
    calls = {"n": 0}

    def _meta(request, key, *, context):
        calls["n"] += 1
        return {"audioFormat": "mp3"}

    monkeypatch.setattr(_podcast_mod, "_read_json_from_s3", _meta)
    _podcast_mod._audio_filename(req, "flow_x", 1)
    _podcast_mod._audio_filename(req, "flow_x", 2)
    _podcast_mod._audio_filename(req, "flow_x", 3)
    assert calls["n"] == 1

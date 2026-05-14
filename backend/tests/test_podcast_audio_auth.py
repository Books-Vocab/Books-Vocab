"""Tests for the authenticated podcast audio endpoint.

Background: `/api/podcast-media/` is mounted as Starlette StaticFiles, which
bypasses FastAPI auth dependencies. This file locks in the contract for the
authenticated replacement at
``GET /api/podcasts/{series_id}/{ep_num}/audio``.

Covers:
* 401 without auth
* 200 + correct headers on full GET
* 206 Partial Content on Range request (AVPlayer hard-requires this)
* path-traversal rejection via existing ``_SERIES_ID_RE`` + ``Path()`` guards
* 404 when file missing
"""
from __future__ import annotations

import pytest


PAYLOAD = bytes(range(256)) * 8  # 2 KB deterministic payload


@pytest.fixture()
def audio_api(isolated_api):
    podcasts = isolated_api.data_dir / "podcasts"
    podcasts.mkdir(exist_ok=True)
    ep_dir = podcasts / "series_a" / "ep_01"
    ep_dir.mkdir(parents=True)
    (ep_dir / "audio.mp3").write_bytes(PAYLOAD)
    return isolated_api, podcasts


def test_audio_requires_auth(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/1/audio")
    assert resp.status_code == 401


def test_audio_returns_full_body(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/1/audio", headers=api.headers)
    assert resp.status_code == 200
    assert resp.content == PAYLOAD
    assert resp.headers.get("content-type", "").startswith("audio/mpeg")
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-length") == str(len(PAYLOAD))


def test_audio_supports_range_206(audio_api):
    """AVPlayer issues Range requests — endpoint MUST honor them."""
    api, _ = audio_api
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.content == PAYLOAD[:100]
    cr = resp.headers.get("content-range", "")
    assert cr == f"bytes 0-99/{len(PAYLOAD)}"
    assert resp.headers.get("content-length") == "100"
    assert resp.headers.get("accept-ranges") == "bytes"


def test_audio_range_open_ended(audio_api):
    """`bytes=N-` (open-ended suffix) must serve [N, total-1]."""
    api, _ = audio_api
    start = len(PAYLOAD) - 200
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": f"bytes={start}-"},
    )
    assert resp.status_code == 206
    assert resp.content == PAYLOAD[start:]
    cr = resp.headers.get("content-range", "")
    assert cr == f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"


def test_audio_range_suffix(audio_api):
    """`bytes=-N` (last N bytes) must serve the trailing N bytes."""
    api, _ = audio_api
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": "bytes=-50"},
    )
    assert resp.status_code == 206
    assert resp.content == PAYLOAD[-50:]


def test_audio_range_unsatisfiable_416(audio_api):
    """Range start beyond EOF must be 416."""
    api, _ = audio_api
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": f"bytes={len(PAYLOAD) + 10}-"},
    )
    assert resp.status_code == 416
    assert resp.headers.get("content-range") == f"bytes */{len(PAYLOAD)}"


@pytest.mark.parametrize(
    "bad_range",
    [
        "garbage",
        "bytes=garbage",
        "bytes=-0",  # suffix=0 — zero-length suffix, treat as malformed
        "bytes=-",  # bare dash, no numbers
        "bytes=0-50,60-70",  # multi-range — not supported, fall back
        "bytes=-5-10",  # negative start
        "bytes=abc-def",  # non-numeric bounds
        "bytes=10-5",  # end < start
    ],
)
def test_audio_malformed_range_falls_back_to_200(audio_api, bad_range):
    """RFC 7233: invalid/unsupported Range header should be ignored (200 full body)."""
    api, _ = audio_api
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": bad_range},
    )
    assert resp.status_code == 200, f"Range={bad_range!r} should fall back to 200"
    assert resp.content == PAYLOAD


def test_audio_not_found(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/99/audio", headers=api.headers)
    assert resp.status_code == 404


def test_audio_series_not_found(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/nonexistent/1/audio", headers=api.headers)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../etc",
        "series.a",
        "series-a",
        "Series_A",
        "%2e%2e",
    ],
)
def test_audio_series_id_rejects_bad_inputs(audio_api, bad_id):
    """Path traversal / regex-violating series_id must be rejected."""
    api, _ = audio_api
    resp = api.client.get(f"/api/podcasts/{bad_id}/1/audio", headers=api.headers)
    assert resp.status_code in (404, 422)


def test_audio_ep_num_rejects_zero(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/0/audio", headers=api.headers)
    assert resp.status_code == 422


def test_audio_ep_num_rejects_negative(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/-1/audio", headers=api.headers)
    assert resp.status_code == 422


def test_audio_ep_num_rejects_overflow(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/10000/audio", headers=api.headers)
    assert resp.status_code == 422


def test_audio_ep_num_rejects_non_integer(audio_api):
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/abc/audio", headers=api.headers)
    assert resp.status_code == 422


def test_static_mount_still_accessible_for_backward_compat(audio_api):
    """The legacy public StaticFiles mount must remain functional so older
    iOS clients keep working until they upgrade. This is a deliberate
    backward-compat guarantee, not an oversight."""
    api, _ = audio_api
    # The StaticFiles mount is bound at app-import time to the original
    # podcasts_dir (see test_media_mount_supports_range), so we cannot route
    # to the test tmp dir. Instead, just assert the mount route is present.
    from kg.api import app
    media_mount = next(
        (r for r in app.routes if getattr(r, "name", None) == "podcast-media"),
        None,
    )
    assert media_mount is not None, "legacy podcast-media mount must stay registered"


def test_static_mount_logs_deprecation_hit(audio_api, caplog):
    """Each hit on the legacy public mount must emit an INFO log so we can
    track real-world usage and pick a safe deprecation date.

    Level is INFO (not WARNING) because legacy traffic from shipped iOS
    clients is *expected* during the deprecation window — alerting on it
    would be noise. See review feedback on PR worktree-agent-ab37cf664ac45cf2c.

    The middleware sees the request before StaticFiles 404s it, so we can
    test on a path that doesn't need a real file."""
    import logging
    api, _ = audio_api
    with caplog.at_level(logging.INFO, logger="kg.podcast_media_deprecation"):
        api.client.get("/api/podcast-media/anything/audio.mp3")
    records = [r for r in caplog.records if r.name == "kg.podcast_media_deprecation"]
    msgs = [r.getMessage() for r in records]
    assert any("podcast-media" in m for m in msgs), (
        f"expected deprecation log, got: {msgs}"
    )
    # Verify level is INFO, not WARNING (review feedback).
    assert all(r.levelno == logging.INFO for r in records), (
        f"deprecation logs must be INFO, got: {[(r.levelname, r.getMessage()) for r in records]}"
    )

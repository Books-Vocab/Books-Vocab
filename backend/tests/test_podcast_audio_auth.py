"""Tests for the authenticated podcast audio endpoint.

Background: `/api/podcast-media/` was previously mounted as Starlette
StaticFiles, which bypassed FastAPI auth. That legacy public mount has been
removed (zero production traffic over a 12-day window while the authenticated
endpoint served all podcast requests); this endpoint is now the sole path to
podcast audio.

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


def test_audio_reversed_range_returns_416(audio_api):
    """A syntactically valid but unsatisfiable reversed range is rejected."""
    api, _ = audio_api
    resp = api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**api.headers, "Range": "bytes=10-5"},
    )
    assert resp.status_code == 416
    assert resp.headers.get("content-range") == f"bytes */{len(PAYLOAD)}"


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


@pytest.mark.parametrize(
    "bad_ep_num",
    [
        "0",  # zero — ep_num is 1-indexed
        "-1",  # negative
        "10000",  # overflow — beyond allowed bound
        "abc",  # non-integer
    ],
)
def test_audio_ep_num_rejects_bad_inputs(audio_api, bad_ep_num):
    """Out-of-range / non-integer ep_num must be rejected with 422."""
    api, _ = audio_api
    resp = api.client.get(f"/api/podcasts/series_a/{bad_ep_num}/audio", headers=api.headers)
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Track B (2026-06): disk-mode m4a + m4a-over-mp3 precedence.
# These cover the audio-format transition window. S3 mode is exercised
# separately (it requires a moto/botocore fixture); these prove the on-disk
# fallback layer that keeps dev and pre-bucket prod working.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def m4a_only_api(isolated_api):
    podcasts = isolated_api.data_dir / "podcasts"
    podcasts.mkdir(exist_ok=True)
    ep_dir = podcasts / "series_m" / "ep_01"
    ep_dir.mkdir(parents=True)
    (ep_dir / "audio.m4a").write_bytes(PAYLOAD)
    return isolated_api, podcasts


@pytest.fixture()
def m4a_and_mp3_api(isolated_api):
    """Series with BOTH m4a and mp3 present — m4a must win (post-Track-B default)."""
    podcasts = isolated_api.data_dir / "podcasts"
    podcasts.mkdir(exist_ok=True)
    ep_dir = podcasts / "series_dual" / "ep_01"
    ep_dir.mkdir(parents=True)
    (ep_dir / "audio.m4a").write_bytes(PAYLOAD)
    # different payload so we can tell which one was served
    (ep_dir / "audio.mp3").write_bytes(b"\x00" * len(PAYLOAD))
    return isolated_api, podcasts


def test_audio_m4a_served_with_audio_mp4_content_type(m4a_only_api):
    """Post-Track-B series uploaded as m4a must serve with `audio/mp4`.

    The Content-Type is wire-load-bearing: AVPlayer chooses the demuxer
    by MIME and rejects an mp4 container labelled `audio/mpeg`.
    """
    api, _ = m4a_only_api
    resp = api.client.get("/api/podcasts/series_m/1/audio", headers=api.headers)
    assert resp.status_code == 200
    assert resp.content == PAYLOAD
    assert resp.headers.get("content-type", "").startswith("audio/mp4")
    assert resp.headers.get("accept-ranges") == "bytes"


def test_audio_m4a_supports_range_206(m4a_only_api):
    api, _ = m4a_only_api
    resp = api.client.get(
        "/api/podcasts/series_m/1/audio",
        headers={**api.headers, "Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.content == PAYLOAD[:100]
    assert resp.headers.get("content-type", "").startswith("audio/mp4")
    assert resp.headers.get("content-range") == f"bytes 0-99/{len(PAYLOAD)}"


def test_audio_m4a_wins_over_mp3_when_both_present(m4a_and_mp3_api):
    """Transition-window guarantee: m4a probed first, mp3 only if missing."""
    api, _ = m4a_and_mp3_api
    resp = api.client.get("/api/podcasts/series_dual/1/audio", headers=api.headers)
    assert resp.status_code == 200
    # Served body must be the m4a payload, not the all-zero mp3 stub.
    assert resp.content == PAYLOAD
    assert resp.headers.get("content-type", "").startswith("audio/mp4")


def test_audio_mp3_fallback_still_works_when_only_mp3_present(audio_api):
    """Legacy (pre-Track-B) series with only audio.mp3 keep working."""
    api, _ = audio_api
    resp = api.client.get("/api/podcasts/series_a/1/audio", headers=api.headers)
    assert resp.status_code == 200
    assert resp.content == PAYLOAD
    assert resp.headers.get("content-type", "").startswith("audio/mpeg")

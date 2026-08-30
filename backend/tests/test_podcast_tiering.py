"""Tiered podcast access: guest / free / pro.

Replaces the legacy "public-read for any authenticated user" model. The wall:

* **guest** (no/invalid-absent token) — may *browse* (list / series detail /
  cover) but any audio playback is gated with ``401 auth_required``.
* **free** (authenticated, no active Pro entitlement) — may stream only the
  *preview* asset of episode 1 of each series; every other episode is gated
  with ``403 upgrade_required``.
* **pro** (active Pro entitlement) — full access to every episode's full audio.

The gate is server-authoritative: a free/guest caller never receives a byte of
the full ``audio.*`` asset for a gated episode — the preview is a *separate*
object (``ep_01/preview.*``) so there is nothing to truncate or bypass.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from conftest import make_jwt

FULL_EP1 = b"FULL-EP1-" + bytes(range(256)) * 4
PREVIEW_EP1 = b"PREVIEW-1-" + bytes(range(128)) * 4
FULL_EP2 = b"FULL-EP2-" + bytes(range(256)) * 4


@pytest.fixture()
def tier_api(isolated_api):
    """Disk-mode podcast fixture + free/guest/pro credential sets.

    The default ``isolated_api`` user carries an active subscription → **pro**.
    A freshly-minted JWT for an unknown ``sub`` resolves to an empty record →
    **free** (``resolve_current_user`` tolerates unknown users). Guest = no
    Authorization header at all.
    """
    api = isolated_api
    podcasts = api.data_dir / "podcasts"
    podcasts.mkdir(exist_ok=True)
    series = podcasts / "series_a"
    (series / "ep_01").mkdir(parents=True)
    (series / "ep_02").mkdir(parents=True)
    (series / "ep_01" / "audio.mp3").write_bytes(FULL_EP1)
    (series / "ep_01" / "preview.mp3").write_bytes(PREVIEW_EP1)
    (series / "ep_01" / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nep1\n")
    (series / "ep_02" / "audio.mp3").write_bytes(FULL_EP2)
    (series / "ep_02" / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nep2-secret\n")
    (podcasts / "index.json").write_text(json.dumps([{"id": "series_a", "title": "A"}]))
    (series / "metadata.json").write_text(
        json.dumps(
            {
                "id": "series_a",
                "title": "A",
                "episodes": [
                    {"episodeNumber": 1, "subtitleContent": "ep1-inline"},
                    {"episodeNumber": 2, "subtitleContent": "ep2-inline-secret"},
                ],
            }
        )
    )

    free_headers = {"Authorization": f"Bearer {make_jwt('u_free')}"}
    return SimpleNamespace(
        client=api.client,
        pro_headers=api.headers,
        free_headers=free_headers,
        # guest = no headers
    )


# ── browse: guests allowed ──────────────────────────────────────────────────


def test_guest_can_list_podcasts(tier_api):
    resp = tier_api.client.get("/api/podcasts")
    assert resp.status_code == 200
    assert resp.json() == [{"id": "series_a", "title": "A"}]


def test_guest_can_read_series_detail(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a")
    assert resp.status_code == 200
    assert resp.json()["id"] == "series_a"


def test_guest_series_detail_does_not_leak_inline_subtitles(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a")
    assert resp.status_code == 200
    assert all("subtitleContent" not in episode for episode in resp.json()["episodes"])


def test_free_series_detail_exposes_inline_subtitle_only_for_ep1(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a", headers=tier_api.free_headers)
    assert resp.status_code == 200
    episodes = {episode["episodeNumber"]: episode for episode in resp.json()["episodes"]}
    assert episodes[1]["subtitleContent"] == "ep1-inline"
    assert "subtitleContent" not in episodes[2]


def test_pro_series_detail_preserves_inline_subtitles(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a", headers=tier_api.pro_headers)
    assert resp.status_code == 200
    episodes = {episode["episodeNumber"]: episode for episode in resp.json()["episodes"]}
    assert episodes[1]["subtitleContent"] == "ep1-inline"
    assert episodes[2]["subtitleContent"] == "ep2-inline-secret"


def test_invalid_token_on_browse_still_401(tier_api):
    """A *present* but bogus token is a client-side auth error, not a guest —
    fail loud rather than silently downgrade to guest."""
    resp = tier_api.client.get("/api/podcasts", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer"])
def test_malformed_authorization_on_browse_still_401(tier_api, authorization):
    resp = tier_api.client.get("/api/podcasts", headers={"Authorization": authorization})
    assert resp.status_code == 401


# ── audio gate: guest ────────────────────────────────────────────────────────


def test_guest_audio_blocked_auth_required(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a/1/audio")
    assert resp.status_code == 401
    body = resp.json()
    assert _error_code(body) == "auth_required"


# ── audio gate: free ─────────────────────────────────────────────────────────


def test_free_ep1_serves_preview_asset(tier_api):
    """Free tier on episode 1 gets the *preview* bytes, never the full audio."""
    resp = tier_api.client.get("/api/podcasts/series_a/1/audio", headers=tier_api.free_headers)
    assert resp.status_code == 200
    assert resp.content == PREVIEW_EP1
    assert resp.content != FULL_EP1


def test_free_ep1_preview_supports_range(tier_api):
    resp = tier_api.client.get(
        "/api/podcasts/series_a/1/audio",
        headers={**tier_api.free_headers, "Range": "bytes=0-9"},
    )
    assert resp.status_code == 206
    assert resp.content == PREVIEW_EP1[:10]
    assert resp.headers.get("content-range") == f"bytes 0-9/{len(PREVIEW_EP1)}"


def test_free_ep2_blocked_upgrade_required(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a/2/audio", headers=tier_api.free_headers)
    assert resp.status_code == 403
    assert _error_code(resp.json()) == "upgrade_required"


# ── audio gate: pro ──────────────────────────────────────────────────────────


def test_pro_ep1_serves_full_audio(tier_api):
    """Pro gets the FULL audio on ep1 — not the preview stub."""
    resp = tier_api.client.get("/api/podcasts/series_a/1/audio", headers=tier_api.pro_headers)
    assert resp.status_code == 200
    assert resp.content == FULL_EP1


def test_pro_ep2_serves_full_audio(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a/2/audio", headers=tier_api.pro_headers)
    assert resp.status_code == 200
    assert resp.content == FULL_EP2


# ── subtitle gate (same wall as audio — no transcript leak of Pro episodes) ──


def test_guest_subtitle_blocked_auth_required(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a/1/subtitle")
    assert resp.status_code == 401
    assert _error_code(resp.json()) == "auth_required"


def test_free_ep1_subtitle_allowed(tier_api):
    """ep1 is the free sample episode → its transcript is readable."""
    resp = tier_api.client.get("/api/podcasts/series_a/1/subtitle", headers=tier_api.free_headers)
    assert resp.status_code == 200
    assert "ep1" in resp.text


def test_free_ep2_subtitle_blocked_upgrade_required(tier_api):
    """The full transcript of a Pro-only episode must NOT leak to free tier."""
    resp = tier_api.client.get("/api/podcasts/series_a/2/subtitle", headers=tier_api.free_headers)
    assert resp.status_code == 403
    assert _error_code(resp.json()) == "upgrade_required"
    assert "secret" not in resp.text


def test_pro_ep2_subtitle_allowed(tier_api):
    resp = tier_api.client.get("/api/podcasts/series_a/2/subtitle", headers=tier_api.pro_headers)
    assert resp.status_code == 200
    assert "ep2-secret" in resp.text


# ── helper ───────────────────────────────────────────────────────────────────


def _error_code(body: dict) -> str:
    """The gate returns ``{"detail": {"code": ...}}`` — tolerate either a dict
    detail or a flat ``code`` key so the assertion documents the contract."""
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        return detail.get("code", "")
    return body.get("code", "")

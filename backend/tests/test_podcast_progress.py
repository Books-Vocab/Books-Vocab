"""Tests for /api/podcasts/*/progress endpoints.

Contract:
* Authenticated endpoints: 401 without Bearer.
* POST writes per-user (series_id, ep_num, position_sec, duration_sec,
  updated_at). Last-write-wins by `updated_at` (older payload ignored).
* GET list returns all of the caller's progress rows.
* GET single returns 404 when no row exists.
* Cross-user isolation: user A cannot see user B's progress.
* series_id / ep_num validation matches the existing podcast routes.
"""
from __future__ import annotations

import pytest


_ISO_NOW = "2026-05-14T12:00:00+00:00"
_ISO_LATER = "2026-05-14T12:05:00+00:00"
_ISO_EARLIER = "2026-05-14T11:55:00+00:00"


def _post_progress(api, series, ep, *, position, duration, updated_at, headers=None):
    return api.client.post(
        f"/api/podcasts/{series}/{ep}/progress",
        json={
            "position_sec": position,
            "duration_sec": duration,
            "updated_at": updated_at,
        },
        headers=headers or api.headers,
    )


# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------


def test_post_progress_requires_auth(isolated_api):
    resp = isolated_api.client.post(
        "/api/podcasts/series_a/1/progress",
        json={"position_sec": 10.0, "duration_sec": 100.0, "updated_at": _ISO_NOW},
    )
    assert resp.status_code == 401


def test_get_progress_list_requires_auth(isolated_api):
    resp = isolated_api.client.get("/api/podcasts/progress")
    assert resp.status_code == 401


def test_get_progress_single_requires_auth(isolated_api):
    resp = isolated_api.client.get("/api/podcasts/series_a/1/progress")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_post_progress_creates_row(isolated_api):
    resp = _post_progress(
        isolated_api, "series_a", 1,
        position=42.5, duration=300.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["series_id"] == "series_a"
    assert body["ep_num"] == 1
    assert body["position_sec"] == 42.5
    assert body["duration_sec"] == 300.0
    assert body["updated_at"] == _ISO_NOW


def test_get_single_after_post(isolated_api):
    _post_progress(
        isolated_api, "series_a", 1,
        position=42.5, duration=300.0, updated_at=_ISO_NOW,
    )
    resp = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=isolated_api.headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["series_id"] == "series_a"
    assert body["ep_num"] == 1
    assert body["position_sec"] == 42.5


def test_get_single_404_when_no_row(isolated_api):
    resp = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=isolated_api.headers,
    )
    assert resp.status_code == 404


def test_get_list_returns_all_rows(isolated_api):
    _post_progress(
        isolated_api, "series_a", 1,
        position=10.0, duration=100.0, updated_at=_ISO_NOW,
    )
    _post_progress(
        isolated_api, "series_a", 2,
        position=20.0, duration=200.0, updated_at=_ISO_NOW,
    )
    _post_progress(
        isolated_api, "series_b", 1,
        position=30.0, duration=300.0, updated_at=_ISO_NOW,
    )
    resp = isolated_api.client.get("/api/podcasts/progress", headers=isolated_api.headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    keys = {(it["series_id"], it["ep_num"]) for it in items}
    assert keys == {("series_a", 1), ("series_a", 2), ("series_b", 1)}


def test_get_list_empty_returns_empty_items(isolated_api):
    resp = isolated_api.client.get("/api/podcasts/progress", headers=isolated_api.headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


# ---------------------------------------------------------------------------
# Last-write-wins
# ---------------------------------------------------------------------------


def test_repost_with_newer_updated_at_overwrites(isolated_api):
    _post_progress(
        isolated_api, "series_a", 1,
        position=10.0, duration=300.0, updated_at=_ISO_NOW,
    )
    _post_progress(
        isolated_api, "series_a", 1,
        position=120.0, duration=300.0, updated_at=_ISO_LATER,
    )
    resp = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=isolated_api.headers,
    )
    body = resp.json()
    assert body["position_sec"] == 120.0
    assert body["updated_at"] == _ISO_LATER


def test_repost_with_older_updated_at_ignored(isolated_api):
    _post_progress(
        isolated_api, "series_a", 1,
        position=120.0, duration=300.0, updated_at=_ISO_NOW,
    )
    # Older payload arrives (e.g. delayed sync from another device) — must not clobber.
    resp = _post_progress(
        isolated_api, "series_a", 1,
        position=10.0, duration=300.0, updated_at=_ISO_EARLIER,
    )
    assert resp.status_code == 200
    body = resp.json()
    # Returned row should reflect the latest (existing) record, not the stale write.
    assert body["position_sec"] == 120.0
    assert body["updated_at"] == _ISO_NOW

    resp_get = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=isolated_api.headers,
    )
    assert resp_get.json()["position_sec"] == 120.0


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


def test_cross_user_isolation_single(isolated_api):
    from conftest import make_jwt  # type: ignore

    _post_progress(
        isolated_api, "series_a", 1,
        position=42.5, duration=300.0, updated_at=_ISO_NOW,
    )
    other_headers = {"Authorization": f"Bearer {make_jwt('other_user')}"}
    resp = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=other_headers,
    )
    # Other user has no row → 404, never leaks user A's progress.
    assert resp.status_code == 404


def test_cross_user_isolation_list(isolated_api):
    from conftest import make_jwt  # type: ignore

    _post_progress(
        isolated_api, "series_a", 1,
        position=42.5, duration=300.0, updated_at=_ISO_NOW,
    )
    other_headers = {"Authorization": f"Bearer {make_jwt('other_user')}"}
    resp = isolated_api.client.get("/api/podcasts/progress", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_cross_user_independent_writes(isolated_api):
    from conftest import make_jwt  # type: ignore

    other_headers = {"Authorization": f"Bearer {make_jwt('other_user')}"}
    _post_progress(
        isolated_api, "series_a", 1,
        position=10.0, duration=100.0, updated_at=_ISO_NOW,
    )
    _post_progress(
        isolated_api, "series_a", 1,
        position=80.0, duration=100.0, updated_at=_ISO_NOW, headers=other_headers,
    )
    resp_self = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=isolated_api.headers,
    )
    resp_other = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress", headers=other_headers,
    )
    assert resp_self.json()["position_sec"] == 10.0
    assert resp_other.json()["position_sec"] == 80.0


# ---------------------------------------------------------------------------
# Validation (series_id regex + ep_num bounds + body schema)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    ["..", "../etc", "series.a", "series-a", "Series_A", "%2e%2e"],
)
def test_post_series_id_rejects_bad_inputs(isolated_api, bad_id):
    resp = _post_progress(
        isolated_api, bad_id, 1,
        position=10.0, duration=100.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code in (404, 422)


def test_post_ep_num_rejects_zero(isolated_api):
    resp = _post_progress(
        isolated_api, "series_a", 0,
        position=10.0, duration=100.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code == 422


def test_post_ep_num_rejects_overflow(isolated_api):
    resp = _post_progress(
        isolated_api, "series_a", 10000,
        position=10.0, duration=100.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code == 422


def test_post_rejects_malformed_updated_at(isolated_api):
    resp = isolated_api.client.post(
        "/api/podcasts/series_a/1/progress",
        json={"position_sec": 10.0, "duration_sec": 100.0, "updated_at": "not-iso"},
        headers=isolated_api.headers,
    )
    assert resp.status_code == 422


def test_post_rejects_negative_position(isolated_api):
    resp = _post_progress(
        isolated_api, "series_a", 1,
        position=-1.0, duration=100.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code == 422


def test_post_rejects_negative_duration(isolated_api):
    resp = _post_progress(
        isolated_api, "series_a", 1,
        position=10.0, duration=-100.0, updated_at=_ISO_NOW,
    )
    assert resp.status_code == 422


def test_get_single_series_id_rejects_traversal(isolated_api):
    resp = isolated_api.client.get(
        "/api/podcasts/../etc/1/progress", headers=isolated_api.headers,
    )
    assert resp.status_code in (404, 422)


def test_get_single_ep_num_rejects_zero(isolated_api):
    resp = isolated_api.client.get(
        "/api/podcasts/series_a/0/progress", headers=isolated_api.headers,
    )
    assert resp.status_code == 422

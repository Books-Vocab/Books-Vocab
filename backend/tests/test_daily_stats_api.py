from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import kg.routers.vocab as vocab_router_mod
from conftest import _DummyEmbeddingStore


# ---------------------------------------------------------------------------
# GET /api/vocab/daily-stats — empty state
# ---------------------------------------------------------------------------

def test_daily_stats_get_empty(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers

    r = client.get("/api/vocab/daily-stats", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"entries": []}


# ---------------------------------------------------------------------------
# PATCH /api/vocab/daily-stats — push then GET round-trip
# ---------------------------------------------------------------------------

def test_daily_stats_push_and_pull(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers

    payload = {
        "entries": [
            {"day_key": "2026-03-17", "total": 20, "remembered": 15, "forgot": 5},
            {"day_key": "2026-03-18", "total": 10, "remembered": 8, "forgot": 2},
        ]
    }

    r_push = client.patch("/api/vocab/daily-stats", json=payload, headers=headers)
    assert r_push.status_code == 200, r_push.text
    assert r_push.json()["upserted"] == 2

    r_get = client.get("/api/vocab/daily-stats", headers=headers)
    assert r_get.status_code == 200, r_get.text
    entries = r_get.json()["entries"]
    assert len(entries) == 2
    by_day = {e["day_key"]: e for e in entries}
    assert by_day["2026-03-17"]["total"] == 20
    assert by_day["2026-03-17"]["remembered"] == 15
    assert by_day["2026-03-17"]["forgot"] == 5
    assert by_day["2026-03-18"]["total"] == 10


def test_daily_stats_upsert_updates_existing(isolated_api):
    """Re-pushing the same day_key should upsert (update in place)."""
    client = isolated_api.client
    headers = isolated_api.headers

    client.patch(
        "/api/vocab/daily-stats",
        json={"entries": [{"day_key": "2026-03-17", "total": 10, "remembered": 8, "forgot": 2}]},
        headers=headers,
    )

    r = client.patch(
        "/api/vocab/daily-stats",
        json={"entries": [{"day_key": "2026-03-17", "total": 30, "remembered": 25, "forgot": 5}]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 1

    entries = client.get("/api/vocab/daily-stats", headers=headers).json()["entries"]
    assert len(entries) == 1
    assert entries[0]["total"] == 30


def test_daily_stats_since_filter(isolated_api):
    """`since` param should filter entries by day_key."""
    client = isolated_api.client
    headers = isolated_api.headers

    client.patch(
        "/api/vocab/daily-stats",
        json={
            "entries": [
                {"day_key": "2026-03-15", "total": 5, "remembered": 4, "forgot": 1},
                {"day_key": "2026-03-18", "total": 10, "remembered": 8, "forgot": 2},
            ]
        },
        headers=headers,
    )

    r = client.get("/api/vocab/daily-stats", params={"since": "2026-03-16"}, headers=headers)
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    day_keys = {e["day_key"] for e in entries}
    assert "2026-03-18" in day_keys
    assert "2026-03-15" not in day_keys


def test_daily_stats_push_empty_entries(isolated_api):
    """Pushing an empty list should succeed with upserted=0."""
    client = isolated_api.client
    headers = isolated_api.headers

    r = client.patch("/api/vocab/daily-stats", json={"entries": []}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 0


# ---------------------------------------------------------------------------
# PATCH /api/vocab/review — push review state for an existing card
# ---------------------------------------------------------------------------

def test_push_review_updates_existing_card(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers
    emb = _DummyEmbeddingStore()

    # Create a card first
    with patch.object(vocab_router_mod, "_embedding_store", return_value=emb):
        r_add = client.post(
            "/api/vocab",
            json=[{"word": "serendipity", "translation": "意外發現", "context": "A happy accident."}],
            headers=headers,
        )
        assert r_add.status_code == 200, r_add.text
        assert r_add.json()["created"] == 1

    last_reviewed = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    next_review = (datetime.now(tz=UTC) + timedelta(hours=24)).isoformat()

    review_payload = {
        "entries": [
            {
                "word": "serendipity",
                "review_interval_hours": 24.0,
                "next_review_at": next_review,
                "last_reviewed_at": last_reviewed,
                "review_count": 3,
                "lapse_count": 1,
                "review_streak": 2,
                "last_review_feedback": 4,
            }
        ]
    }

    r_review = client.patch("/api/vocab/review", json=review_payload, headers=headers)
    assert r_review.status_code == 200, r_review.text
    body = r_review.json()
    assert body["updated"] == 1
    assert body["skipped"] == 0


def test_push_review_skips_unknown_word(isolated_api):
    """Pushing review for a word that doesn't exist should skip, not error."""
    client = isolated_api.client
    headers = isolated_api.headers

    next_review = (datetime.now(tz=UTC) + timedelta(hours=24)).isoformat()
    last_reviewed = datetime.now(tz=UTC).isoformat()

    r = client.patch(
        "/api/vocab/review",
        json={
            "entries": [
                {
                    "word": "nonexistentword",
                    "review_interval_hours": 24.0,
                    "next_review_at": next_review,
                    "last_reviewed_at": last_reviewed,
                    "review_count": 1,
                    "lapse_count": 0,
                    "review_streak": 1,
                    "last_review_feedback": 3,
                }
            ]
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 0
    assert body["skipped"] == 1


def test_push_review_empty_entries(isolated_api):
    """Pushing empty review list should succeed with updated=0, skipped=0."""
    client = isolated_api.client
    headers = isolated_api.headers

    r = client.patch("/api/vocab/review", json={"entries": []}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 0
    assert body["skipped"] == 0

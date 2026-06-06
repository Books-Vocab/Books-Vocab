from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _payload(event_id: str = "evt-api-1", *, reviewed_at: datetime | None = None) -> dict:
    reviewed = reviewed_at or datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    return {
        "event_id": event_id,
        "card_id": "card-api-1",
        "word_snapshot": "serendipity",
        "notebook_id": "default",
        "feedback": 1,
        "reviewed_at": reviewed.isoformat(),
        "created_at": (reviewed + timedelta(seconds=3)).isoformat(),
    }


def test_review_events_get_empty(isolated_api):
    r = isolated_api.client.get("/api/vocab/review-events", headers=isolated_api.headers)

    assert r.status_code == 200, r.text
    assert r.json() == {"entries": [], "cursor": None}


def test_review_events_push_and_pull(isolated_api):
    payload = {
        "entries": [
            _payload("evt-api-2", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC)),
            _payload("evt-api-1", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC)),
        ]
    }

    r_push = isolated_api.client.patch(
        "/api/vocab/review-events",
        json=payload,
        headers=isolated_api.headers,
    )
    assert r_push.status_code == 200, r_push.text
    assert r_push.json() == {"inserted": 2, "skipped": 0}

    r_get = isolated_api.client.get("/api/vocab/review-events", headers=isolated_api.headers)
    assert r_get.status_code == 200, r_get.text
    body = r_get.json()
    assert {event["event_id"] for event in body["entries"]} == {"evt-api-1", "evt-api-2"}
    assert body["cursor"] is not None


def test_review_events_duplicate_patch_skips(isolated_api):
    payload = {"entries": [_payload("evt-api-dup")]}

    first = isolated_api.client.patch("/api/vocab/review-events", json=payload, headers=isolated_api.headers)
    second = isolated_api.client.patch("/api/vocab/review-events", json=payload, headers=isolated_api.headers)

    assert first.status_code == 200, first.text
    assert first.json() == {"inserted": 1, "skipped": 0}
    assert second.status_code == 200, second.text
    assert second.json() == {"inserted": 0, "skipped": 1}


def test_review_events_since_filter(isolated_api):
    # First ingestion, capture the returned cursor.
    isolated_api.client.patch(
        "/api/vocab/review-events",
        json={"entries": [_payload("evt-old", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))]},
        headers=isolated_api.headers,
    )
    cursor = isolated_api.client.get(
        "/api/vocab/review-events", headers=isolated_api.headers
    ).json()["cursor"]

    # Second ingestion after the cursor.
    isolated_api.client.patch(
        "/api/vocab/review-events",
        json={"entries": [_payload("evt-new", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC))]},
        headers=isolated_api.headers,
    )

    r = isolated_api.client.get(
        "/api/vocab/review-events",
        params={"since": cursor},
        headers=isolated_api.headers,
    )

    assert r.status_code == 200, r.text
    assert [event["event_id"] for event in r.json()["entries"]] == ["evt-new"]


def test_review_events_since_malformed_returns_400(isolated_api):
    r = isolated_api.client.get(
        "/api/vocab/review-events",
        params={"since": "garbage"},
        headers=isolated_api.headers,
    )

    assert r.status_code == 400, r.text


def test_review_events_patch_rejects_non_iso_timestamps(isolated_api):
    payload = {"entries": [_payload("evt-bad-time")]}
    payload["entries"][0]["reviewed_at"] = "1717668000"

    r = isolated_api.client.patch(
        "/api/vocab/review-events",
        json=payload,
        headers=isolated_api.headers,
    )

    assert r.status_code == 400, r.text


def test_review_events_require_auth(isolated_api):
    r = isolated_api.client.get("/api/vocab/review-events")

    assert r.status_code in {401, 403}

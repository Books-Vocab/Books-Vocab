from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


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


@pytest.mark.parametrize("event_id", ["", " ", "\t\n"])
def test_review_events_patch_rejects_blank_event_id_without_write(isolated_api, event_id):
    r = isolated_api.client.patch(
        "/api/vocab/review-events",
        json={"entries": [_payload(event_id)]},
        headers=isolated_api.headers,
    )

    assert r.status_code == 422, r.text

    stored = isolated_api.client.get("/api/vocab/review-events", headers=isolated_api.headers)
    assert stored.status_code == 200, stored.text
    assert stored.json() == {"entries": [], "cursor": None}


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


def test_review_events_since_with_literal_plus_is_not_corrupted(isolated_api):
    """回歸：2026-06-08 下載死鎖。帶 '+00:00' offset 的 watermark 以裸 '+' 走 query
    （URLComponents 不會 percent-encode 它），Starlette 依 x-www-form-urlencoded 解成空格。
    server 必須仍把它當 cursor 用、而非 400。以原始 URL 字串送（**不**走 params=，否則
    httpx 會 percent-encode 成 %2B 而蓋掉 bug — 與 test_review_events_since_filter 對照）。"""
    isolated_api.client.patch(
        "/api/vocab/review-events",
        json={"entries": [_payload("evt-old", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))]},
        headers=isolated_api.headers,
    )
    cursor = isolated_api.client.get(
        "/api/vocab/review-events", headers=isolated_api.headers
    ).json()["cursor"]
    isolated_api.client.patch(
        "/api/vocab/review-events",
        json={"entries": [_payload("evt-new", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC))]},
        headers=isolated_api.headers,
    )

    # 模擬現場舊格式 '+00:00' watermark，以裸 '+' 回送。
    legacy_since = cursor.replace("Z", "+00:00")
    assert "+" in legacy_since, legacy_since
    r = isolated_api.client.get(
        f"/api/vocab/review-events?since={legacy_since}",
        headers=isolated_api.headers,
    )

    assert r.status_code == 200, r.text
    assert [e["event_id"] for e in r.json()["entries"]] == ["evt-new"]


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

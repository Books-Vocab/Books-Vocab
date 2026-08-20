from __future__ import annotations

import re
import sys
from typing import Any

sys.path.insert(0, "ops")

from sentry_contract import (
    HEALTH_SCHEMA,
    ISSUE_SCHEMA,
    normalize_health,
    normalize_issue,
    route_for_issue,
    safe_endpoint,
    safe_message,
)


def _payload_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for pair in value.items() for item in _payload_strings(pair)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _payload_strings(child)]
    return [value] if isinstance(value, str) else []


def _diagnostic_event() -> dict[str, Any]:
    return {
        "eventID": "0123456789abcdef0123456789abcdef",
        "platform": "cocoa",
        "tags": [
            {"key": "environment", "value": "production"},
            {"key": "release", "value": "com.example.app@2.0.1+10"},
            {"key": "request_id", "value": "req-123"},
        ],
        "exception": {
            "values": [
                {
                    "type": "NetworkError",
                    "value": "the user's book title",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "/Users/example/BooksAndVocab.swift?token=secret-token",
                                "function": "syncBooks",
                                "module": "BooksAndVocab",
                                "lineNo": 42,
                                "inApp": True,
                            }
                        ]
                    },
                }
            ]
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "http",
                    "message": "GET /api/books?token=secret-token",
                    "data": {
                        "url": "/api/books?token=secret-token",
                        "request_id": "req-123",
                        "status_code": 500,
                        "Authorization": "Bearer secret-token",
                        "response_body": "raw body",
                    },
                }
            ]
        },
        "contexts": {
            "device": {"model": "iPhone 17 Pro Max", "id": "private-device-id"},
            "os": {"name": "iOS", "version": "18.0"},
        },
    }


def test_normalize_issue_keeps_diagnostic_shape_and_redacts_payloads() -> None:
    issue = normalize_issue(
        {
            "id": "123",
            "shortId": "IOS-1",
            "title": "Book title from user",
            "status": "unresolved",
            "level": "error",
            "project": {"slug": "ios", "platform": "cocoa"},
            "count": "2",
            "userCount": 1,
            "release": "com.example.app@2.0.1+10",
            "firstSeen": "2026-08-20T01:02:03Z",
            "lastSeen": "2026-08-20T02:02:03Z",
        },
        event=_diagnostic_event(),
        environment_hint="production",
    )

    assert issue["schema"] == ISSUE_SCHEMA
    assert issue["issue"] == {
        **issue["issue"],
        "id": "123",
        "short_id": "IOS-1",
        "title": "NetworkError",
        "project": "ios",
        "count": 2,
        "user_count": 1,
    }
    assert issue["evidence"]["latest_event_id"] == "0123456789abcdef0123456789abcdef"
    assert issue["evidence"]["request_ids"] == ["req-123"]
    assert issue["evidence"]["stacktrace"][0]["filename"] == "BooksAndVocab.swift"
    assert issue["evidence"]["device"]["model"] == "iPhone 17 Pro Max"
    assert issue["routing"]["surface"] == "ios"
    assert issue["routing"]["suggestions"][-1]["worker"] == "backend-correlation-worker"

    serialized = "\n".join(_payload_strings(issue))
    for forbidden in ("secret-token", "person@example.com", "the user's book title", "raw body", "Bearer "):
        assert forbidden not in serialized
    assert "?" not in serialized
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", serialized)
    assert issue["redaction"]["applied"] is True


def test_health_verdict_distinguishes_blocked_ready_and_unchecked() -> None:
    keys = (
        "source_present",
        "package_present",
        "target_linked",
        "build_can_import",
        "api_configured",
        "api_authenticated",
        "project_reachable",
        "runtime_event_seen",
        "symbolication_ready",
    )
    blocked = normalize_health(
        local_readiness={"source_present": False, "package_present": True, "target_linked": True},
        project="ios",
    )
    assert blocked["schema"] == HEALTH_SCHEMA
    assert blocked["verdict"] == "blocked"

    ready = normalize_health(
        local_readiness={key: True for key in keys},
        project="ios",
    )
    assert ready["verdict"] == "ready"

    unchecked = normalize_health(local_readiness={}, project="ios")
    assert unchecked["verdict"] == "unchecked"


def test_route_marks_incomplete_evidence_without_guessing_root_cause() -> None:
    routing = route_for_issue(
        project="ios",
        platform="swift",
        release=None,
        request_ids=[],
        stacktrace=[],
        status="unresolved",
    )
    assert routing["worker"] == "ios-worker"
    assert routing["evidence_incomplete"] is True
    assert routing["suggestions"][-1] == {
        "worker": "evidence-collector",
        "reason": "evidence_incomplete; do not guess root cause",
    }


def test_endpoint_and_message_redaction_keep_only_safe_diagnostic_shape() -> None:
    assert safe_endpoint("https://user:password@example.test/api/vocab/secret-book?token=secret") is None
    assert safe_endpoint("/api/vocab/user-supplied-book") == "/api/vocab"
    assert safe_endpoint("/api/private-user-input") is None
    assert safe_message("GET /api/vocab/user-supplied-book?token=secret") == "GET /api/vocab"
    assert safe_message("NetworkError") is None
    assert safe_message("the user's book title") is None


def test_exception_type_is_not_an_arbitrary_user_string() -> None:
    issue = normalize_issue(
        {"id": "123", "project": {"slug": "ios"}},
        event={"exception": {"values": [{"type": "the user's book title"}]}},
    )
    assert issue["evidence"]["exception_type"] is None

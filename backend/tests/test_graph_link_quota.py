"""Quota gate regression for POST /api/graph/links (manual link creation).

`create_graph_link` builds a `ManualLinkJudge` + `TrackedLLM` and makes a real
LLM call to classify the link kind. Like every other LLM-spending endpoint
(`add_vocab`, `run_pipeline`, the translate family) it MUST be guarded by the
daily quota gate — otherwise an over-quota user can hammer manual-link POSTs
and burn unbounded LLM cost.

These tests pin the contract at the HTTP layer by patching
`kg.quota_service.check_and_get_quota` (the chokepoint `_check_quota` calls).
"""

from __future__ import annotations

from unittest.mock import patch

QUOTA_EXCEEDED = {"exceeded": True, "fraction": 0.0, "reset_seconds": 3600}
QUOTA_OK = {"exceeded": False, "fraction": 1.0, "reset_seconds": 86400}


class TestCreateGraphLinkQuotaGate:
    def test_over_quota_user_is_blocked_with_429(self, isolated_api):
        """Over-quota user POSTing a manual link must be rejected with 429,
        before any LLM call is made."""
        with patch("kg.quota_service.check_and_get_quota", return_value=QUOTA_EXCEEDED):
            r = isolated_api.client.post(
                "/api/graph/links",
                params={"notebook_id": "default"},
                json={"from_id": "card-a", "to_id": "card-b"},
                headers=isolated_api.headers,
            )
        assert r.status_code == 429, f"Expected 429, got {r.status_code}: {r.text}"
        # QuotaExceededError contract: zero fraction header on block.
        assert r.headers.get("X-Quota-Fraction") == "0.0"

    def test_under_quota_user_is_not_blocked(self, isolated_api):
        """A user within quota must not be 429'd by the gate. The cards do not
        exist so the request fails downstream (404), proving the gate opened
        and the request reached the handler."""
        with patch("kg.quota_service.check_and_get_quota", return_value=QUOTA_OK):
            r = isolated_api.client.post(
                "/api/graph/links",
                params={"notebook_id": "default"},
                json={"from_id": "card-a", "to_id": "card-b"},
                headers=isolated_api.headers,
            )
        assert r.status_code != 429, f"Quota gate wrongly blocked: {r.text}"
        assert r.status_code == 404, f"Expected 404 (missing cards), got {r.status_code}: {r.text}"

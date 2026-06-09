from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kg.exceptions import QuotaExceededError
from kg.judge import ManualLinkJudge
from kg.tracked_llm import TrackedLLM


def _make_client(response_json: str):
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = response_json
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    client.chat.completions.create.return_value = resp
    return client

class TestManualLinkJudge:
    def test_returns_judgement_with_kind_and_reason(self):
        client = _make_client('{"link": "contrasts_with", "confidence": 0.9, "reason": "測試原因"}')
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.link in ("contrasts_with", "shares_usage")
        assert result.reason == "測試原因"
        assert result.confidence == 1.0  # always 1.0

    def test_never_returns_none_for_low_confidence(self):
        client = _make_client('{"link": "shares_usage", "confidence": 0.3, "reason": "弱關聯"}')
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.confidence == 1.0

    def test_not_applicable_falls_back_to_shares_usage(self):
        client = _make_client('{"link": "not_applicable", "confidence": 0.5, "reason": "無明顯關聯"}')
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.link == "shares_usage"

    def test_invalid_kind_falls_back_to_shares_usage(self):
        client = _make_client('{"link": "unknown_kind", "confidence": 0.8, "reason": "某原因"}')
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result.link == "shares_usage"

    def test_empty_response_returns_fallback(self):
        client = _make_client('')
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.link == "shares_usage"

    def test_transport_failure_returns_degraded_judgement(self, monkeypatch):
        """Provider 5xx穿透 SDK max_retries 後不外漏例外，走與 parse 失敗
        同一條 graceful fallback（never returns None），不碰 quota。"""
        import httpx
        from openai import APIError

        request = httpx.Request("POST", "https://api.test/chat")
        client = MagicMock()
        client.chat.completions.create.side_effect = APIError(
            "provider 5xx", request, body=None
        )
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))

        # sync_retry sleeps 2 s → 4 s between attempts; mock it out so the
        # test exercises the retry/degrade logic, not wall-clock patience.
        monkeypatch.setattr("kg.retry.time.sleep", lambda _d: None)

        # 改前：例外外漏 → 此處 raise，紅燈。
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")

        assert result is not None
        assert result.link == "shares_usage"
        assert result.confidence == 1.0
        assert result.reason  # degraded reason 非空

    def test_quota_exceeded_is_not_degraded(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = QuotaExceededError(reset_seconds=3600)
        judge = ManualLinkJudge(TrackedLLM(client, "test_user"))

        with pytest.raises(QuotaExceededError):
            judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")

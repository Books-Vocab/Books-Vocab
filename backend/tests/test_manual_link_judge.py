from __future__ import annotations
from unittest.mock import MagicMock
import pytest
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

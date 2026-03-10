from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.judge import Judge, Judgement


def _make_client(content: str | None):
    """Build a mock OpenAI client returning given content string."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage = None
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


def _judge_with(content: str | None) -> Judge:
    return Judge(client=_make_client(content))


VALID_JSON = '{"link": "confusable", "confidence": 0.9, "reason": "similar spelling"}'


class TestJudgeEvaluateNormalResponse:
    def test_valid_json_returns_judgement(self):
        judge = _judge_with(VALID_JSON)
        result = judge.evaluate("affect", "to influence", "effect", "a result")
        assert isinstance(result, Judgement)
        assert result.link == "confusable"
        assert result.confidence == 0.9
        assert result.reason == "similar spelling"


class TestJudgeLowConfidence:
    def test_confidence_below_07_returns_none(self):
        content = '{"link": "confusable", "confidence": 0.5, "reason": "some reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "to influence", "effect", "a result")
        assert result is None

    def test_confidence_exactly_07_returns_judgement(self):
        content = '{"link": "confusable", "confidence": 0.7, "reason": "reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "to influence", "effect", "a result")
        assert isinstance(result, Judgement)

    def test_not_applicable_returns_none(self):
        content = '{"link": "not_applicable", "confidence": 0.95, "reason": "unrelated"}'
        judge = _judge_with(content)
        result = judge.evaluate("cat", "a feline", "democracy", "political system")
        assert result is None


class TestJudgeRegexFallback:
    def test_json_embedded_in_text_uses_regex_fallback(self):
        # First call fails to parse (wrapped in text), second call (retry) returns clean JSON
        mock_client = MagicMock()
        mock_resp1 = MagicMock()
        mock_resp1.choices = [MagicMock()]
        mock_resp1.choices[0].message.content = "Here is my answer: not valid json at all !!!"
        mock_resp1.usage = None

        mock_resp2 = MagicMock()
        mock_resp2.choices = [MagicMock()]
        mock_resp2.choices[0].message.content = VALID_JSON
        mock_resp2.usage = None

        mock_client.chat.completions.create.side_effect = [mock_resp1, mock_resp2]
        judge = Judge(client=mock_client)
        result = judge.evaluate("affect", "influence", "effect", "result")
        assert isinstance(result, Judgement)

    def test_json_object_embedded_in_prose(self):
        content = 'Sure! {"link": "confusable", "confidence": 0.85, "reason": "ok"} done.'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        assert isinstance(result, Judgement)
        assert result.link == "confusable"


class TestJudgeMissingFields:
    def test_missing_link_returns_none(self):
        content = '{"confidence": 0.9, "reason": "reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        # link defaults to "not_applicable" via dict.get default, returns None
        assert result is None

    def test_missing_confidence_returns_none(self):
        content = '{"link": "confusable", "reason": "reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        # confidence defaults to 0.0 < 0.7
        assert result is None

    def test_missing_reason_returns_none_or_judgement(self):
        # reason defaults to "" which is falsy but not a blocking condition
        content = '{"link": "confusable", "confidence": 0.9}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        assert isinstance(result, Judgement)
        assert result.reason == ""


class TestJudgeInvalidLinkKind:
    def test_invalid_link_kind_returns_none(self):
        content = '{"link": "totally_invalid_kind", "confidence": 0.95, "reason": "reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        assert result is None


class TestJudgeAPIFailure:
    def test_consecutive_api_failures_return_none(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        judge = Judge(client=mock_client)
        with pytest.raises(Exception):
            judge.evaluate("a", "meaning a", "b", "meaning b")

    def test_both_calls_fail_json_parse_returns_none(self):
        mock_client = MagicMock()
        bad_resp = MagicMock()
        bad_resp.choices = [MagicMock()]
        bad_resp.choices[0].message.content = "completely unparseable !!!"
        bad_resp.usage = None
        mock_client.chat.completions.create.return_value = bad_resp
        judge = Judge(client=mock_client)
        result = judge.evaluate("a", "meaning a", "b", "meaning b")
        assert result is None


class TestJudgeEmptyContent:
    def test_content_none_returns_none(self):
        judge = _judge_with(None)
        result = judge.evaluate("a", "meaning a", "b", "meaning b")
        assert result is None

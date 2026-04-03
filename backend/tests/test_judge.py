from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kg.judge import Judge, Judgement, _parse_batch_response


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
    from kg.tracked_llm import TrackedLLM
    return Judge(llm=TrackedLLM(_make_client(content), "test_user"))


# ── Single evaluate (backward compat) ──

VALID_JSON = '{"link": "contrasts_with", "confidence": 0.9, "reason": "opposite meanings"}'


class TestJudgeEvaluateSingle:
    def test_valid_single_object(self):
        judge = _judge_with(VALID_JSON)
        result = judge.evaluate("affect", "to influence", "effect", "a result")
        assert isinstance(result, Judgement)
        assert result.link == "contrasts_with"
        assert result.confidence == 0.9

    def test_valid_array_response(self):
        content = '[{"word": "effect", "link": "contrasts_with", "confidence": 0.85, "reason": "ok"}]'
        judge = _judge_with(content)
        result = judge.evaluate("affect", "influence", "effect", "result")
        assert isinstance(result, Judgement)

    def test_not_applicable_returns_none(self):
        content = '{"link": "not_applicable", "confidence": 0.95, "reason": "unrelated"}'
        judge = _judge_with(content)
        result = judge.evaluate("cat", "a feline", "democracy", "political system")
        assert result is None

    def test_low_confidence_returns_none(self):
        content = '{"link": "contrasts_with", "confidence": 0.5, "reason": "some reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("a", "x", "b", "y")
        assert result is None

    def test_none_content_returns_none(self):
        judge = _judge_with(None)
        result = judge.evaluate("a", "x", "b", "y")
        assert result is None

    def test_unparseable_returns_none(self):
        judge = _judge_with("completely broken !!!")
        result = judge.evaluate("a", "x", "b", "y")
        assert result is None

    def test_invalid_link_kind_returns_none(self):
        content = '{"link": "totally_invalid", "confidence": 0.95, "reason": "reason"}'
        judge = _judge_with(content)
        result = judge.evaluate("a", "x", "b", "y")
        assert result is None


# ── Batch evaluate ──

class TestJudgeEvaluateBatch:
    def test_batch_with_array_response(self):
        content = (
            '[{"word": "hunkered", "link": "shares_usage", "confidence": 0.8, "reason": "r1"},'
            ' {"word": "stately", "link": "contrasts_with", "confidence": 0.9, "reason": "r2"}]'
        )
        judge = _judge_with(content)
        results = judge.evaluate_batch("cowering", "畏縮", [
            ("id1", "hunkered", "蹲伏"),
            ("id2", "stately", "莊嚴的"),
        ])
        assert results["id1"].link == "shares_usage"
        assert results["id2"].link == "contrasts_with"

    def test_batch_with_wrapped_response(self):
        content = '{"results": [{"word": "x", "link": "shares_usage", "confidence": 0.8, "reason": "r"}]}'
        judge = _judge_with(content)
        results = judge.evaluate_batch("a", "m", [("id1", "x", "mx")])
        assert results["id1"].link == "shares_usage"

    def test_batch_partial_response(self):
        # LLM returns fewer items than candidates
        content = '[{"word": "x", "link": "shares_usage", "confidence": 0.8, "reason": "r"}]'
        judge = _judge_with(content)
        results = judge.evaluate_batch("a", "m", [
            ("id1", "x", "mx"),
            ("id2", "y", "my"),
        ])
        assert results["id1"] is not None
        assert results["id2"] is None

    def test_batch_not_applicable_filtered(self):
        content = '[{"word": "x", "link": "not_applicable", "confidence": 0.9, "reason": "r"}]'
        judge = _judge_with(content)
        results = judge.evaluate_batch("a", "m", [("id1", "x", "mx")])
        assert results["id1"] is None

    def test_batch_empty_candidates(self):
        judge = _judge_with("[]")
        assert judge.evaluate_batch("a", "m", []) == {}

    def test_batch_none_content(self):
        judge = _judge_with(None)
        results = judge.evaluate_batch("a", "m", [("id1", "x", "mx")])
        assert results["id1"] is None


# ── _parse_batch_response unit tests ──

class TestParseBatchResponse:
    def test_positional_matching(self):
        content = '[{"link": "shares_usage", "confidence": 0.8, "reason": "r1"}, {"link": "contrasts_with", "confidence": 0.9, "reason": "r2"}]'
        results = _parse_batch_response(content, [("id1", "a", "ma"), ("id2", "b", "mb")])
        assert results["id1"].link == "shares_usage"
        assert results["id2"].link == "contrasts_with"

    def test_missing_items_return_none(self):
        content = '[{"link": "shares_usage", "confidence": 0.8, "reason": "r"}]'
        results = _parse_batch_response(content, [("id1", "a", "ma"), ("id2", "b", "mb")])
        assert results["id1"] is not None
        assert results["id2"] is None

    def test_none_content(self):
        results = _parse_batch_response(None, [("id1", "a", "ma")])
        assert results["id1"] is None

    def test_invalid_json(self):
        results = _parse_batch_response("broken!!!", [("id1", "a", "ma")])
        assert results["id1"] is None

    def test_single_object_unwrap(self):
        content = '{"link": "shares_usage", "confidence": 0.8, "reason": "r"}'
        results = _parse_batch_response(content, [("id1", "a", "ma")])
        assert results["id1"].link == "shares_usage"

    def test_reordered_response_uses_word_fallback(self):
        """LLM returns items in wrong order — word-keyed fallback should fix."""
        content = (
            '[{"word": "beta", "link": "contrasts_with", "confidence": 0.9, "reason": "r2"},'
            ' {"word": "alpha", "link": "shares_usage", "confidence": 0.8, "reason": "r1"}]'
        )
        results = _parse_batch_response(content, [
            ("id1", "alpha", "ma"),
            ("id2", "beta", "mb"),
        ])
        # Despite reversed order, word fallback assigns correctly
        assert results["id1"].link == "shares_usage"
        assert results["id2"].link == "contrasts_with"

    def test_missing_middle_item_uses_word_fallback(self):
        """LLM skips an item — remaining items matched by word."""
        content = (
            '[{"word": "alpha", "link": "shares_usage", "confidence": 0.8, "reason": "r1"},'
            ' {"word": "gamma", "link": "contrasts_with", "confidence": 0.9, "reason": "r3"}]'
        )
        results = _parse_batch_response(content, [
            ("id1", "alpha", "ma"),
            ("id2", "beta", "mb"),
            ("id3", "gamma", "mc"),
        ])
        assert results["id1"].link == "shares_usage"
        assert results["id2"] is None  # beta missing from response
        assert results["id3"].link == "contrasts_with"  # found via word fallback


class TestJudgeChunking:
    def test_large_batch_splits_into_chunks(self):
        """20 candidates should be split into 2 chunks (15 + 5)."""
        from unittest.mock import MagicMock, call
        from kg.tracked_llm import TrackedLLM
        from kg.judge import MAX_BATCH_SIZE

        call_count = 0
        chunk_sizes = []

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            # Count candidates from user message
            user_msg = kwargs["messages"][1]["content"]
            n = user_msg.count("\n") - 1  # candidate lines
            chunk_sizes.append(n)
            # Return array of correct size
            import json
            items = [{"link": "shares_usage", "confidence": 0.8, "reason": "r"} for _ in range(n)]
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = json.dumps(items)
            resp.usage = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = fake_create
        judge = Judge(llm=TrackedLLM(mock_client, "test_user"))

        candidates = [(f"id{i}", f"word{i}", f"meaning{i}") for i in range(20)]
        results = judge.evaluate_batch("target", "target_meaning", candidates)

        assert call_count == 2  # 15 + 5
        assert len(results) == 20
        # All should have results (shares_usage with conf 0.8)
        for cid in [f"id{i}" for i in range(20)]:
            assert cid in results

    def test_exact_max_batch_no_split(self):
        """Exactly MAX_BATCH_SIZE candidates → no split."""
        from unittest.mock import MagicMock
        from kg.tracked_llm import TrackedLLM
        from kg.judge import MAX_BATCH_SIZE
        import json

        items = [{"link": "shares_usage", "confidence": 0.8, "reason": "r"} for _ in range(MAX_BATCH_SIZE)]
        mock_client = MagicMock()
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = json.dumps(items)
        resp.usage = None
        mock_client.chat.completions.create.return_value = resp

        judge = Judge(llm=TrackedLLM(mock_client, "test_user"))
        candidates = [(f"id{i}", f"w{i}", f"m{i}") for i in range(MAX_BATCH_SIZE)]
        results = judge.evaluate_batch("t", "tm", candidates)

        assert mock_client.chat.completions.create.call_count == 1
        assert len(results) == MAX_BATCH_SIZE

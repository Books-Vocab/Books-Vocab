"""Tests for kg.enrich — LLM-powered card enrichment."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.cards import Card
from kg.enrich import _build_prompt, _parse_enrich_response, enrich_cards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_card(content: str = "hello", meaning: str = "你好",
               examples: list[str] | None = None) -> Card:
    return Card(content=content, meaning=meaning,
                examples=examples or [])


def _mock_response(content: str, prompt_tokens: int = 10,
                   completion_tokens: int = 20):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens)
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_single_card_with_example(self):
        card = _make_card("abandon", "放棄", ["He abandoned the project."])
        prompt = _build_prompt([card])
        assert "abandon" in prompt
        assert "放棄" in prompt
        assert "He abandoned the project." in prompt
        assert "context" in prompt

    def test_card_without_examples(self):
        card = _make_card("hello", "你好")
        prompt = _build_prompt([card])
        parsed = json.loads(prompt.split("分析以下單字（含現有翻譯和例句上下文）：\n")[1].split("\n\n回傳")[0])
        assert len(parsed) == 1
        assert "context" not in parsed[0]

    def test_multiple_cards(self):
        cards = [_make_card("a", "一"), _make_card("b", "二")]
        prompt = _build_prompt(cards)
        assert "a" in prompt
        assert "b" in prompt


# ---------------------------------------------------------------------------
# _parse_enrich_response
# ---------------------------------------------------------------------------

class TestParseEnrichResponse:
    def test_json_array_direct(self):
        data = [{"word": "hello", "pos": "n."}]
        result = _parse_enrich_response(json.dumps(data))
        assert result == data

    def test_results_key(self):
        data = {"results": [{"word": "hello"}]}
        result = _parse_enrich_response(json.dumps(data))
        assert result == [{"word": "hello"}]

    def test_fallback_to_first_list_value(self):
        data = {"enrichments": [{"word": "hello"}]}
        result = _parse_enrich_response(json.dumps(data))
        assert result == [{"word": "hello"}]

    def test_empty_string(self):
        """Empty/null content → empty dict parse → empty list."""
        # json.loads("") raises; the function does `raw_content or "{}"`
        result = _parse_enrich_response("")
        assert result == []

    def test_none_content(self):
        result = _parse_enrich_response(None)
        assert result == []

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_enrich_response("not json at all {{{")

    def test_dict_no_list_values(self):
        result = _parse_enrich_response('{"status": "ok"}')
        assert result == []


# ---------------------------------------------------------------------------
# enrich_cards
# ---------------------------------------------------------------------------

class TestEnrichCards:
    def test_empty_cards_returns_empty(self):
        client = MagicMock()
        result = enrich_cards(client, [])
        assert result == []
        client.chat.completions.create.assert_not_called()

    @patch("kg.enrich.sync_retry")
    def test_normal_batch(self, mock_retry):
        enriched = [{"word": "hello", "pos": "interj.", "note": "打招呼用語"}]
        mock_retry.return_value = _mock_response(json.dumps(enriched))

        client = MagicMock()
        cards = [_make_card("hello", "你好")]
        result = enrich_cards(client, cards)

        assert result == enriched
        mock_retry.assert_called_once()

    @patch("kg.token_tracker.record")
    @patch("kg.enrich.sync_retry")
    def test_usage_calls_token_tracker(self, mock_retry, mock_record):
        mock_retry.return_value = _mock_response(
            json.dumps([{"word": "x"}]), prompt_tokens=100, completion_tokens=50
        )
        client = MagicMock()
        enrich_cards(client, [_make_card()], user_id="u_test")

        mock_record.assert_called_once_with("u_test", "enrich", 100, 50)

    @patch("kg.token_tracker.record")
    @patch("kg.enrich.sync_retry")
    def test_no_usage_skips_tracker(self, mock_retry, mock_record):
        resp = _mock_response(json.dumps([]))
        resp.usage = None
        mock_retry.return_value = resp

        client = MagicMock()
        enrich_cards(client, [_make_card()], user_id="u_test")
        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# enrich_cards_stream
# ---------------------------------------------------------------------------

class TestEnrichCardsStream:
    @pytest.mark.asyncio
    async def test_empty_cards(self):
        from kg.enrich import enrich_cards_stream
        client = MagicMock()
        results = []
        async for msg in enrich_cards_stream(client, []):
            results.append(msg)
        assert len(results) == 1
        assert results[0]["status"] == "done"
        assert results[0]["total"] == 0

    @pytest.mark.asyncio
    async def test_multi_batch_yields_progress(self):
        from kg.enrich import enrich_cards_stream
        enriched = [{"word": "w", "pos": "n."}]
        resp = _mock_response(json.dumps(enriched))

        client = MagicMock()

        with patch("kg.enrich.sync_retry", return_value=resp):
            cards = [_make_card(f"word{i}", f"意思{i}") for i in range(5)]
            results = []
            async for msg in enrich_cards_stream(client, cards, batch_size=2):
                results.append(msg)

        # 5 cards / batch_size 2 = 3 batches → at least 3 progress messages
        running_msgs = [r for r in results if r["status"] == "running"]
        assert len(running_msgs) >= 3
        # Last running message should have current == total
        assert running_msgs[-1]["current"] == 5

    @pytest.mark.asyncio
    async def test_stream_with_token_tracking(self):
        from kg.enrich import enrich_cards_stream
        resp = _mock_response(json.dumps([{"word": "x"}]),
                              prompt_tokens=50, completion_tokens=25)
        client = MagicMock()

        with patch("kg.enrich.sync_retry", return_value=resp), \
             patch("kg.token_tracker.record") as mock_record:
            cards = [_make_card()]
            async for _ in enrich_cards_stream(client, cards, user_id="u_test"):
                pass
            mock_record.assert_called()

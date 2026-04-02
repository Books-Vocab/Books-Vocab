"""Tests for TrackedLLM — unified LLM wrapper with auto token tracking."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.tracked_llm import TrackedLLM


def _mock_client(prompt_tokens=10, completion_tokens=20):
    client = MagicMock()
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=30)
    choice = SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
    resp = SimpleNamespace(choices=[choice], usage=usage)
    client.chat.completions.create.return_value = resp
    return client, resp


def _mock_embed_client(prompt_tokens=5, total_tokens=5):
    client = MagicMock()
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=total_tokens)
    data = [SimpleNamespace(embedding=[0.1, 0.2], index=0)]
    resp = SimpleNamespace(data=data, usage=usage)
    client.embeddings.create.return_value = resp
    return client, resp


class TestTrackedLLMChat:
    @patch("kg.tracked_llm.record")
    def test_chat_records_token_usage(self, mock_record):
        client, _ = _mock_client(prompt_tokens=15, completion_tokens=25)
        llm = TrackedLLM(client, user_id="u1")
        resp = llm.chat("judge", model="m", messages=[])
        mock_record.assert_called_once_with("u1", "judge", 15, 25)
        assert resp.choices[0].message.content == '{"ok": true}'

    @patch("kg.tracked_llm.record")
    def test_chat_no_usage_skips_record(self, mock_record):
        client = MagicMock()
        resp = SimpleNamespace(choices=[], usage=None)
        client.chat.completions.create.return_value = resp
        llm = TrackedLLM(client, user_id="u1")
        llm.chat("judge", model="m", messages=[])
        mock_record.assert_not_called()

    @patch("kg.tracked_llm.record")
    def test_multiple_calls_each_recorded(self, mock_record):
        client, _ = _mock_client()
        llm = TrackedLLM(client, user_id="u1")
        llm.chat("judge", model="m", messages=[])
        llm.chat("judge", model="m", messages=[])
        assert mock_record.call_count == 2


class TestTrackedLLMEmbed:
    @patch("kg.tracked_llm.record")
    def test_embed_records_prompt_tokens(self, mock_record):
        client, _ = _mock_embed_client(prompt_tokens=5, total_tokens=5)
        llm = TrackedLLM(client, user_id="u1")
        llm.embed("embed", input=["hello"], model="m")
        mock_record.assert_called_once_with("u1", "embed", 5, 0)

    @patch("kg.tracked_llm.record")
    def test_embed_falls_back_to_total_tokens(self, mock_record):
        client = MagicMock()
        usage = SimpleNamespace(prompt_tokens=0, total_tokens=8)
        resp = SimpleNamespace(data=[], usage=usage)
        client.embeddings.create.return_value = resp
        llm = TrackedLLM(client, user_id="u1")
        llm.embed("embed", input=["hi"], model="m")
        mock_record.assert_called_once_with("u1", "embed", 8, 0)


class TestTrackedLLMChatAsync:
    @pytest.mark.asyncio
    @patch("kg.tracked_llm.record")
    async def test_chat_async_records_usage(self, mock_record):
        client = MagicMock()
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20)
        choice = SimpleNamespace(message=SimpleNamespace(content="{}"))
        resp = SimpleNamespace(choices=[choice], usage=usage)

        async def mock_create(**kwargs):
            return resp
        client.chat.completions.create = mock_create

        llm = TrackedLLM(client, user_id="u1")
        result = await llm.chat_async("translate_quick", model="m", messages=[])
        mock_record.assert_called_once_with("u1", "translate_quick", 10, 20)

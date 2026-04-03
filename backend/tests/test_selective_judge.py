"""Tests for selective judge prompt (max_links routing)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kg.judge import Judge, BATCH_SYSTEM_PROMPT


def _make_client_capture() -> tuple[MagicMock, list]:
    """Build a mock OpenAI client that captures the system message."""
    captured: list[dict] = []
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "[]"
    mock_resp.usage = None

    def _capture(**kwargs):
        captured.append(kwargs)
        return mock_resp

    mock_client.chat.completions.create.side_effect = _capture
    return mock_client, captured


def _make_judge(client: MagicMock) -> Judge:
    from kg.tracked_llm import TrackedLLM
    return Judge(llm=TrackedLLM(client, "test_user"))


def _candidates(n: int) -> list[tuple[str, str, str]]:
    """Generate n dummy candidates."""
    return [(f"id_{i}", f"word_{i}", f"meaning_{i}") for i in range(n)]


class TestSelectivePromptRouting:
    def test_selective_prompt_used_when_5_or_more(self):
        """When >=5 candidates and max_links provided, selective prompt is used."""
        client, captured = _make_client_capture()
        judge = _make_judge(client)
        judge.evaluate_batch("target", "meaning", _candidates(6), max_links=3)

        assert len(captured) == 1
        system_msg = captured[0]["messages"][0]["content"]
        # Selective prompt contains "at most" or "最多"
        assert "at most" in system_msg or "最多" in system_msg
        # Should NOT be the standard prompt
        assert system_msg != BATCH_SYSTEM_PROMPT

    def test_standard_prompt_when_less_than_5(self):
        """When <5 candidates, standard prompt used regardless of max_links."""
        client, captured = _make_client_capture()
        judge = _make_judge(client)
        judge.evaluate_batch("target", "meaning", _candidates(3), max_links=2)

        assert len(captured) == 1
        system_msg = captured[0]["messages"][0]["content"]
        assert system_msg == BATCH_SYSTEM_PROMPT

    def test_standard_prompt_when_no_max_links(self):
        """When max_links is None, standard prompt used even with many candidates."""
        client, captured = _make_client_capture()
        judge = _make_judge(client)
        judge.evaluate_batch("target", "meaning", _candidates(10))

        assert len(captured) == 1
        system_msg = captured[0]["messages"][0]["content"]
        assert system_msg == BATCH_SYSTEM_PROMPT

    def test_selective_prompt_forwarded_to_chunks(self):
        """When batch is split into chunks, max_links is forwarded."""
        client, captured = _make_client_capture()
        judge = _make_judge(client)
        # 20 candidates → split into 2 chunks (MAX_BATCH_SIZE=15)
        judge.evaluate_batch("target", "meaning", _candidates(20), max_links=4)

        assert len(captured) == 2
        for call in captured:
            system_msg = call["messages"][0]["content"]
            assert "at most" in system_msg or "最多" in system_msg

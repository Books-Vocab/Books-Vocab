"""Tests for async eval runner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_eval.config import EvalConfig
from llm_eval.registry import RenderedPrompt
from llm_eval.runner import EvalResult, _call_one, run_eval


@pytest.fixture
def mock_prompt():
    return RenderedPrompt(
        name="test",
        version="v1",
        system=None,
        user="Translate: {{ word }}",
        schema={},
    )


@pytest.fixture
def sample():
    return {"id": "test_001", "word": "hello"}


@pytest.mark.asyncio
async def test_call_one_success(mock_prompt, sample):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        result = await _call_one("gemini", "gemini-2.5-flash-lite", mock_prompt, sample, EvalConfig(prompt_name="test"))

    assert result.sample_id == "test_001"
    assert result.model == "gemini-2.5-flash-lite"
    assert result.provider == "gemini"
    assert result.error is None
    assert result.parsed_output == {"t": "你好"}
    assert result.input_tokens == 10
    assert result.output_tokens == 5


@pytest.mark.asyncio
async def test_call_one_timeout(mock_prompt, sample):
    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_client_factory.return_value = mock_client

        result = await _call_one("gemini", "gemini-2.5-flash-lite", mock_prompt, sample, EvalConfig(prompt_name="test", cloud_timeout_s=0.01))

    assert result.error == "timeout"
    assert result.parsed_output is None


@pytest.mark.asyncio
async def test_call_one_ollama_unreachable(mock_prompt, sample):
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        result = await _call_one("ollama", "gemma3:4b", mock_prompt, sample, EvalConfig(prompt_name="test"))

    assert result.error == "ollama_unavailable"


@pytest.mark.asyncio
async def test_run_eval_basic(mock_prompt):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        samples = [
            {"id": "s1", "word": "hello"},
            {"id": "s2", "word": "world"},
        ]
        results = await run_eval(mock_prompt, samples, ["gemini-2.5-flash-lite"])

    assert "gemini-2.5-flash-lite" in results
    summary = results["gemini-2.5-flash-lite"]
    assert summary.sample_count == 2
    assert summary.success_count == 2
    assert summary.error_count == 0
    assert len(summary.samples) == 2


@pytest.mark.asyncio
async def test_run_eval_with_limit(mock_prompt):
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"t":"你好"}'))]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    with patch("llm_eval.runner.create_eval_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_client_factory.return_value = mock_client

        samples = [
            {"id": "s1", "word": "hello"},
            {"id": "s2", "word": "world"},
            {"id": "s3", "word": "foo"},
        ]
        config = EvalConfig(prompt_name="test", limit=2)
        results = await run_eval(mock_prompt, samples, ["gemini-2.5-flash-lite"], config)

    assert results["gemini-2.5-flash-lite"].sample_count == 2

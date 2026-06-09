"""Tests for kg.llm.ab — deprecated A/B harness."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.llm import ab as ab_mod


# ---------------------------------------------------------------------------
# available_providers
# ---------------------------------------------------------------------------

class TestAvailableProviders:
    def test_returns_providers_with_api_key_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        result = ab_mod.available_providers()
        names = [p.name for p in result]
        assert "gemini" in names

    def test_returns_empty_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        result = ab_mod.available_providers()
        assert result == []


# ---------------------------------------------------------------------------
# run_one
# ---------------------------------------------------------------------------

class TestRunOne:
    def test_basic_call(self, monkeypatch):
        """run_one builds prompt, calls client, and returns latency + tokens."""
        mock_client = MagicMock()
        mock_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        mock_choice = SimpleNamespace(
            message=SimpleNamespace(content='{"translation": "你好"}')
        )
        mock_resp = SimpleNamespace(usage=mock_usage, choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_resp

        fake_provider = SimpleNamespace(
            name="gemini",
            chat_model="gemini-2.5-flash-lite",
            api_key_env="GEMINI_API_KEY",
            extra_body=None,
            max_tokens_default=None,
        )

        with patch("kg.service_factories.create_client", return_value=mock_client):
            result = ab_mod.run_one(fake_provider, "hello", "context here")

        assert result["provider"] == "gemini"
        assert result["model"] == "gemini-2.5-flash-lite"
        assert result["in_tokens"] == 10
        assert result["out_tokens"] == 5
        assert "latency_s" in result
        assert result["content"]
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.5-flash-lite"
        assert call_kwargs["temperature"] == 0.3

    def test_extra_body_and_max_tokens(self, monkeypatch):
        mock_client = MagicMock()
        mock_resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        )
        mock_client.chat.completions.create.return_value = mock_resp

        fake_provider = SimpleNamespace(
            name="deepseek",
            chat_model="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
            extra_body={"thinking": True},
            max_tokens_default=2048,
        )

        with patch("kg.service_factories.create_client", return_value=mock_client):
            ab_mod.run_one(fake_provider, "word", "ctx")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": True}
        assert call_kwargs["max_tokens"] == 2048

    def test_missing_usage_defaults_to_zero(self, monkeypatch):
        mock_client = MagicMock()
        mock_resp = SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        )
        mock_client.chat.completions.create.return_value = mock_resp

        fake_provider = SimpleNamespace(
            name="gemini",
            chat_model="gemini-2.5-flash-lite",
            api_key_env="GEMINI_API_KEY",
            extra_body=None,
            max_tokens_default=None,
        )

        with patch("kg.service_factories.create_client", return_value=mock_client):
            result = ab_mod.run_one(fake_provider, "word", "ctx")

        assert result["in_tokens"] == 0
        assert result["out_tokens"] == 0

    def test_no_choices_defaults_empty_content(self, monkeypatch):
        mock_client = MagicMock()
        mock_resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0),
            choices=[],
        )
        mock_client.chat.completions.create.return_value = mock_resp

        fake_provider = SimpleNamespace(
            name="gemini",
            chat_model="gemini-2.5-flash-lite",
            api_key_env="GEMINI_API_KEY",
            extra_body=None,
            max_tokens_default=None,
        )

        with patch("kg.service_factories.create_client", return_value=mock_client):
            result = ab_mod.run_one(fake_provider, "word", "ctx")

        assert result["content"] == ""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    def test_dry_run_returns_0(self, capsys):
        rc = ab_mod.main(["--dry-run"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out

    def test_no_providers_returns_1(self, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        rc = ab_mod.main([])
        assert rc == 1
        captured = capsys.readouterr()
        assert "No providers available" in captured.out

    def test_with_key_and_custom_words(self, monkeypatch, capsys):
        monkeypatch.setenv("GEMINI_API_KEY", "fake")

        mock_client = MagicMock()
        mock_resp = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        )
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("kg.service_factories.create_client", return_value=mock_client):
            rc = ab_mod.main(["serendipity"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "serendipity" in captured.out

    def test_provider_error_prints_and_continues(self, monkeypatch, capsys):
        monkeypatch.setenv("GEMINI_API_KEY", "fake")

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("network")

        with patch("kg.service_factories.create_client", return_value=mock_client):
            rc = ab_mod.main([])

        assert rc == 0
        captured = capsys.readouterr()
        assert "ERROR" in captured.out

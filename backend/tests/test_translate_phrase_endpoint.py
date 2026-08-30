"""Integration tests for the phrase translation HTTP contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _stub_phrase_llm() -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"t":"受審"}'))],
            # One million Gemini input tokens cost $0.10 for the Pro fixture.
            usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0),
        )
    )
    return client


def test_phrase_success_header_reports_post_use_quota_snapshot(isolated_api):
    """A successful phrase response reports quota after its LLM usage."""
    fake = _stub_phrase_llm()
    with patch("kg.translate_handlers.create_async_client", return_value=fake):
        response = isolated_api.client.post(
            "/api/translate/phrase",
            json={
                "word": "on trial quota snapshot",
                "context": "He was on trial for fraud.",
            },
            headers=isolated_api.headers,
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"t": "受審"}
    # The Pro test user has a $0.30 limit; $0.10 used leaves 2/3.
    assert response.headers["X-Quota-Fraction"] == "0.6667"
    assert response.headers["X-Quota-Reset"] == "86400"

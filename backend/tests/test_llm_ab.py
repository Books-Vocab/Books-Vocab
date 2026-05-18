"""Phase 6 — LLM provider A/B harness smoke tests (no live API calls)."""
from __future__ import annotations

import pytest


def test_sample_inputs_nonempty():
    from kg.llm.ab import SAMPLE_INPUTS
    assert len(SAMPLE_INPUTS) >= 3
    assert all(word and context for word, context in SAMPLE_INPUTS)


def test_available_providers_reflects_api_keys(monkeypatch):
    from kg.llm.ab import available_providers
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    names = {p.name for p in available_providers()}
    assert "gemini" in names
    assert "deepseek" not in names
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    assert "deepseek" in {p.name for p in available_providers()}


def test_dry_run_makes_no_api_call(monkeypatch, capsys):
    from kg.llm import ab
    monkeypatch.setattr(ab, "run_one", lambda *a, **k: pytest.fail("dry-run must not call the API"))
    rc = ab.main(["--dry-run"])
    assert rc == 0
    assert "dry-run" in capsys.readouterr().out.lower()


def test_explicit_words_become_samples(monkeypatch, capsys):
    from kg.llm import ab
    monkeypatch.setattr(ab, "run_one", lambda *a, **k: pytest.fail("dry-run must not call the API"))
    rc = ab.main(["--dry-run", "serendipity", "ephemeral"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Samples: 2" in out

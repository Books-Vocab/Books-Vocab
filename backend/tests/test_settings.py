"""Tests for KGSettings defaults."""
from pathlib import Path

from kg.settings import KGSettings, load_settings


def test_settings_has_llm_defaults():
    s = KGSettings(data_dir=Path("/tmp"), jwt_secret="x" * 16)
    assert s.gemini_temperature == 0.3
    assert s.judge_temperature == 0.1
    assert s.similarity_threshold == 0.70
    assert s.candidate_k == 20
    assert s.max_batch_size == 500
    assert s.max_word_length == 200


def test_cors_origins_trims_whitespace_and_drops_empty(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv("CORS_ORIGINS", "a, b ,c ,, ")
    s = load_settings()
    assert s.cors_origins == ("a", "b", "c")


def test_invalid_float_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv("PRO_DAILY_LIMIT_USD", "notanumber")
    # Must not raise; falls back to the dataclass default.
    s = load_settings()
    assert s.pro_daily_limit_usd == 0.30


def test_invalid_int_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv("EMBEDDING_DIM", "notanint")
    s = load_settings()
    assert s.embedding_dim == 3072

"""Tests for KGSettings defaults."""
from pathlib import Path

import pytest

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


def test_rate_limit_envs_are_captured_in_settings_snapshot(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv("API_RATE_LIMIT", "61")
    monkeypatch.setenv("TRANSLATE_RATE_LIMIT", "21")
    monkeypatch.setenv("ADMIN_LOGIN_RATE_LIMIT", "6")

    s = load_settings()

    assert s.api_rate_limit == 61
    assert s.translate_rate_limit == 21
    assert s.admin_login_rate_limit == 6


def test_rate_limit_envs_missing_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    for name in ("API_RATE_LIMIT", "TRANSLATE_RATE_LIMIT", "ADMIN_LOGIN_RATE_LIMIT"):
        monkeypatch.delenv(name, raising=False)

    s = load_settings()

    assert (s.api_rate_limit, s.translate_rate_limit, s.admin_login_rate_limit) == (60, 20, 5)


@pytest.mark.parametrize(
    ("env_name", "setting_name", "default", "raw"),
    [
        ("API_RATE_LIMIT", "api_rate_limit", 60, "not-an-int"),
        ("TRANSLATE_RATE_LIMIT", "translate_rate_limit", 20, "0"),
        ("ADMIN_LOGIN_RATE_LIMIT", "admin_login_rate_limit", 5, "10001"),
    ],
)
def test_rate_limit_envs_invalid_non_positive_or_too_large_fall_back(
    monkeypatch, env_name, setting_name, default, raw
):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv(env_name, raw)

    s = load_settings()

    assert getattr(s, setting_name) == default


@pytest.mark.parametrize(
    ("env_name", "setting_name"),
    [
        ("API_RATE_LIMIT", "api_rate_limit"),
        ("TRANSLATE_RATE_LIMIT", "translate_rate_limit"),
        ("ADMIN_LOGIN_RATE_LIMIT", "admin_login_rate_limit"),
    ],
)
def test_rate_limit_envs_accept_positive_boundary(monkeypatch, env_name, setting_name):
    monkeypatch.setenv("JWT_SECRET", "x" * 16)
    monkeypatch.setenv(env_name, "10000")

    s = load_settings()

    assert getattr(s, setting_name) == 10000

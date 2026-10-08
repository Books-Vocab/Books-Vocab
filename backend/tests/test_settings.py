"""Tests for KGSettings defaults."""

import logging
from pathlib import Path

import pytest

from kg.settings import KGSettings, load_settings


def test_settings_has_llm_defaults():
    s = KGSettings(data_dir=Path("/tmp"), jwt_secret="x" * 32)
    assert s.gemini_temperature == 0.3
    assert s.judge_temperature == 0.1
    assert s.similarity_threshold == 0.70
    assert s.candidate_k == 20
    assert s.max_batch_size == 500
    assert s.max_word_length == 200


def test_cors_origins_trims_whitespace_and_drops_empty(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("CORS_ORIGINS", "a, b ,c ,, ")
    s = load_settings()
    assert s.cors_origins == ("a", "b", "c")


def test_invalid_float_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("PRO_DAILY_LIMIT_USD", "notanumber")
    # Must not raise; falls back to the dataclass default.
    s = load_settings()
    assert s.pro_daily_limit_usd == 0.30


@pytest.mark.parametrize(
    ("env_name", "setting_name", "default", "raw"),
    [
        ("PRO_DAILY_LIMIT_USD", "pro_daily_limit_usd", 0.30, "nan"),
        ("PRO_DAILY_LIMIT_USD", "pro_daily_limit_usd", 0.30, "inf"),
        ("PRO_DAILY_LIMIT_USD", "pro_daily_limit_usd", 0.30, "-inf"),
        ("FREE_DAILY_LIMIT_USD", "free_daily_limit_usd", 0.03, "nan"),
        ("FREE_DAILY_LIMIT_USD", "free_daily_limit_usd", 0.03, "inf"),
        ("FREE_DAILY_LIMIT_USD", "free_daily_limit_usd", 0.03, "-inf"),
        ("JUDGE_CONFIDENCE_THRESHOLD", "judge_confidence_threshold", 0.7, "nan"),
        ("JUDGE_CONFIDENCE_THRESHOLD", "judge_confidence_threshold", 0.7, "inf"),
        ("JUDGE_CONFIDENCE_THRESHOLD", "judge_confidence_threshold", 0.7, "-inf"),
    ],
)
def test_non_finite_float_envs_fall_back_to_defaults(monkeypatch, env_name, setting_name, default, raw):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(env_name, raw)

    s = load_settings()

    assert getattr(s, setting_name) == default


@pytest.mark.parametrize(
    ("env_name", "setting_name", "raw", "expected"),
    [
        ("PRO_DAILY_LIMIT_USD", "pro_daily_limit_usd", "0.42", 0.42),
        ("FREE_DAILY_LIMIT_USD", "free_daily_limit_usd", "0.04", 0.04),
        ("JUDGE_CONFIDENCE_THRESHOLD", "judge_confidence_threshold", "0.85", 0.85),
    ],
)
def test_finite_float_envs_are_preserved(monkeypatch, env_name, setting_name, raw, expected):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(env_name, raw)

    s = load_settings()

    assert getattr(s, setting_name) == expected


def test_invalid_int_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("EMBEDDING_DIM", "notanint")
    s = load_settings()
    assert s.embedding_dim == 3072


def test_rate_limit_envs_are_captured_in_settings_snapshot(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("API_RATE_LIMIT", "61")
    monkeypatch.setenv("TRANSLATE_RATE_LIMIT", "21")
    monkeypatch.setenv("ADMIN_LOGIN_RATE_LIMIT", "6")

    s = load_settings()

    assert s.api_rate_limit == 61
    assert s.translate_rate_limit == 21
    assert s.admin_login_rate_limit == 6


def test_rate_limit_envs_missing_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
def test_rate_limit_envs_invalid_non_positive_or_too_large_fall_back(monkeypatch, env_name, setting_name, default, raw):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
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
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(env_name, "10000")

    s = load_settings()

    assert getattr(s, setting_name) == 10000


_REPO_BACKEND = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "value",
    [
        "your-secret-key-change-in-production",
        "  YOUR-Secret-Key-Change-In-Production \n",
        "changeme",
        "secret",
    ],
)
def test_placeholder_jwt_secret_is_rejected(monkeypatch, value):
    monkeypatch.setenv("JWT_SECRET", value)
    with pytest.raises(RuntimeError, match="placeholder"):
        load_settings()


def test_short_jwt_secret_is_rejected_without_echoing_value(monkeypatch):
    secret = "Ab1-" * 7 + "xyz"  # 31 chars
    assert len(secret) == 31
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError, match="32") as exc:
        load_settings()
    assert secret not in str(exc.value)


def test_missing_jwt_secret_is_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        load_settings()


@pytest.mark.parametrize("length", [32, 36, 48])
def test_strong_jwt_secret_is_accepted(monkeypatch, length):
    import secrets

    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    assert load_settings().jwt_secret == "k" * 32
    token = secrets.token_urlsafe(length)
    monkeypatch.setenv("JWT_SECRET", token)
    assert load_settings().jwt_secret == token


def test_env_example_and_readme_contract():
    env_lines = (_REPO_BACKEND / ".env.example").read_text().splitlines()
    keys = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env_lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert keys["JWT_SECRET"] == ""
    assert "GEMINI_API_KEY" in keys
    assert "ADMIN_PASSWORD" in keys
    for gone in ("OPENAI_API_KEY", "DEBUG_BYPASS_SUBSCRIPTION", "PRO_DEVELOPER_BYPASS_USER_IDS"):
        assert gone not in keys
    readme = (_REPO_BACKEND / "README.md").read_text()
    for banned in ("requirements.txt", "pip install", "python -m venv"):
        assert banned not in readme
    assert "uv sync" in readme
    assert "uv run uvicorn kg.api:app --reload --port 8000" in readme
    assert "JWT_SECRET" in readme


@pytest.mark.parametrize(
    "flag",
    ["APP_STORE_ALLOW_UNSIGNED_SYNC", "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS"],
)
def test_unsigned_app_store_flags_log_warning(monkeypatch, caplog, flag):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(flag, "True")
    with caplog.at_level(logging.WARNING, logger="kg.settings"):
        load_settings()
    assert any(flag in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)

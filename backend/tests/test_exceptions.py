"""Tests for custom exception hierarchy."""
from kg.exceptions import (
    KGError,
    QuotaExceededError,
    ExternalServiceError,
    LLMParseError,
    NotFoundError,
)


def test_hierarchy():
    assert issubclass(QuotaExceededError, KGError)
    assert issubclass(ExternalServiceError, KGError)
    assert issubclass(LLMParseError, ExternalServiceError)
    assert issubclass(NotFoundError, KGError)


def test_quota_exceeded_has_reset():
    err = QuotaExceededError(reset_seconds=3600)
    assert err.reset_seconds == 3600
    assert err.status_code == 429


def test_not_found_has_entity():
    err = NotFoundError("User", "abc123")
    assert "User" in str(err)
    assert err.status_code == 404

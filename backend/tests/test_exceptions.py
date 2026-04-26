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


def test_external_service_error_does_not_leak_inner_exc():
    """Public detail must not contain str(inner exception)."""
    inner = RuntimeError("OpenAI 401 Unauthorized: model=gemini-2.0-flash secret=sk-xxx")
    err = ExternalServiceError("translate/quick", exc=inner)
    detail = err.to_detail()
    assert detail == {"code": "EXTERNAL_SERVICE_ERROR", "label": "translate/quick"}
    # Inner exc string must not be reachable via to_detail
    serialized = str(detail)
    assert "OpenAI" not in serialized
    assert "sk-xxx" not in serialized
    assert "gemini-2.0-flash" not in serialized
    # But inner exc remains accessible for logging
    assert err.exc is inner
    assert err.label == "translate/quick"


def test_external_service_error_label_only():
    """Label-only construction still works."""
    err = ExternalServiceError("gemini/empty_response")
    detail = err.to_detail()
    assert detail == {"code": "EXTERNAL_SERVICE_ERROR", "label": "gemini/empty_response"}
    assert err.exc is None


def test_external_service_error_status_code():
    err = ExternalServiceError("translate/quick")
    assert err.status_code == 502

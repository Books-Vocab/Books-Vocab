"""Unified exception hierarchy for KG backend.

Service-layer code raises these; the FastAPI exception handler
in api.py converts them to HTTP responses.
"""
from __future__ import annotations


class KGError(Exception):
    """Base for all KG domain errors."""

    status_code: int = 500

    def __init__(self, *args, headers: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers = headers or {}

    def to_detail(self) -> dict:
        return {"code": type(self).__name__, "detail": str(self)}


class NotFoundError(KGError):
    status_code = 404

    def __init__(self, entity: str, identifier: str | None = None):
        self.entity = entity
        self.identifier = identifier
        msg = f"{entity} not found" if not identifier else f"{entity} '{identifier}' not found"
        super().__init__(msg)


class QuotaExceededError(KGError):
    status_code = 429

    def __init__(self, reset_seconds: int, *, headers: dict | None = None):
        self.reset_seconds = reset_seconds
        super().__init__(f"Quota exceeded, resets in {reset_seconds}s", headers=headers)

    def to_detail(self) -> dict:
        return {"code": "quota_exhausted", "reset_seconds": self.reset_seconds}


class ExternalServiceError(KGError):
    """Wraps failures from Gemini, App Store, etc.

    Public surface (`to_detail`) only exposes a stable `label`. The original
    exception (if any) is held on `self.exc` for logger consumption only —
    never serialized to the client, to avoid leaking provider error strings,
    model names, API keys, or stack hints.
    """
    status_code = 502

    def __init__(self, label: str, *, exc: BaseException | None = None, headers: dict | None = None):
        self.label = label
        self.exc = exc
        super().__init__(label, headers=headers)

    def to_detail(self) -> dict:
        return {"code": "EXTERNAL_SERVICE_ERROR", "label": self.label}


class LLMParseError(ExternalServiceError):
    """LLM returned unparseable output."""
    status_code = 502

    def to_detail(self) -> dict:
        return {"code": "LLM_PARSE_ERROR", "label": self.label}


class BadRequestError(KGError):
    """Malformed or unparseable input."""
    status_code = 400


class ValidationError(KGError):
    """Invalid input from client."""
    status_code = 422


class ConflictError(KGError):
    """Resource conflict (e.g. duplicate link)."""
    status_code = 409


class ForbiddenError(KGError):
    """Access denied."""
    status_code = 403

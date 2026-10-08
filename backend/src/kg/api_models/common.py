from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

_WS = re.compile(r"[\s\u200b]+")
_MULTISPACE = re.compile(r" {2,}")
MAX_SOURCE_URL_LENGTH = 2048


def _normalize_context(v: str) -> str:
    """Normalize EPUB-sourced context: collapse whitespace, strip NBSP, etc."""
    if not v:
        return ""
    v = unicodedata.normalize("NFC", v)
    v = _WS.sub(" ", v)
    v = _MULTISPACE.sub(" ", v)
    return v.strip()


def _validate_http_url(value: str) -> str:
    """Defense-in-depth: reject non-http(s) schemes on VocabSource.url.

    Blocks javascript:, data:, file:, ftp:, etc. to neutralize XSS payloads
    that could otherwise reach browser UI rendering url verbatim.
    Pure validator (no normalization) to preserve round-trip equality.
    """
    if not value:
        return value
    if len(value) > MAX_SOURCE_URL_LENGTH:
        raise ValueError(f"VocabSource.url must be at most {MAX_SOURCE_URL_LENGTH} characters")
    lower = value.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        raise ValueError("VocabSource.url must use http or https scheme")
    return value


class VocabSource(BaseModel):
    type: Literal["book", "web"]
    title: str | None = Field(default=None, max_length=500)
    url: Annotated[str, AfterValidator(_validate_http_url)] | None = None  # web only
    chapter: str | None = Field(default=None, max_length=500)  # book only

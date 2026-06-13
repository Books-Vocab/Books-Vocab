from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel

_WS = re.compile(r"[\u00a0\u2000-\u200b\t\r]+")
_NL = re.compile(r"\n+")
_MULTISPACE = re.compile(r" {2,}")


def _normalize_context(v: str) -> str:
    """Normalize EPUB-sourced context: collapse whitespace, strip NBSP, etc."""
    if not v:
        return ""
    v = unicodedata.normalize("NFC", v)
    v = _WS.sub(" ", v)
    v = _NL.sub(" ", v)
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
    lower = value.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        raise ValueError("VocabSource.url must use http or https scheme")
    return value


class VocabSource(BaseModel):
    type: Literal["book", "web"]
    title: str | None = None
    url: Annotated[str, AfterValidator(_validate_http_url)] | None = None  # web only
    chapter: str | None = None   # book only

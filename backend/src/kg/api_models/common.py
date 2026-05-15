from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel


def _normalize_context(v: str) -> str:
    """Normalize EPUB-sourced context: collapse whitespace, strip NBSP, etc."""
    if not v:
        return ""
    v = unicodedata.normalize("NFC", v)
    v = re.sub(r"[\u00a0\u2000-\u200b\t\r]+", " ", v)
    v = re.sub(r"\n+", " ", v)
    v = re.sub(r" {2,}", " ", v)
    return v.strip()


class VocabSource(BaseModel):
    type: Literal["book", "web"]
    title: str | None = None
    url: str | None = None       # web only
    chapter: str | None = None   # book only

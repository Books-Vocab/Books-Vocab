"""Defense-in-depth tests for VocabSource.url scheme validator.

Pairs with browser UI XSS hardening. Backend rejects any
non-http(s) scheme up front so malicious payloads never reach storage or
downstream renderers.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models import VocabSource


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost",
        "https://example.com/path?q=1#frag",
        "HTTP://Example.COM",  # case-insensitive scheme check
        "HTTPS://x",
        None,
        "",
    ],
)
def test_vocab_source_url_accepts_valid(url):
    src = VocabSource(type="web", title="t", url=url)
    assert src.url == url  # no normalization / trailing slash mutation


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "vbscript:msgbox(1)",
        "about:blank",
        "  https://example.com",  # leading whitespace not stripped → invalid
    ],
)
def test_vocab_source_url_rejects_invalid_scheme(url):
    with pytest.raises(ValidationError) as exc_info:
        VocabSource(type="web", title="t", url=url)
    assert "http or https scheme" in str(exc_info.value)


def test_vocab_source_url_no_trailing_slash_normalization():
    """Round-trip: input must equal output (pydantic HttpUrl would add '/')."""
    raw = "https://example.com"
    src = VocabSource(type="web", url=raw)
    assert src.url == raw
    assert src.model_dump()["url"] == raw

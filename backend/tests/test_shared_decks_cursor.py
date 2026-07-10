"""Phase 1b-i: opaque, HMAC-signed keyset cursor for /api/decks pagination.

The cursor is base64url(JSON) + HMAC-SHA256 tag (server secret). Signing makes
it tamper-evident: a client cannot forge a cursor to page past the discovery
WHERE filter, and a mutating sort counter (download/rating, Phase 3) cannot be
steered by hand-crafted cursors.
"""
from __future__ import annotations

import pytest

from kg.exceptions import BadRequestError
from kg.shared_decks.cursor import decode_cursor, encode_cursor

_SECRET = "test-secret-at-least-16-chars"


def test_roundtrip_preserves_payload():
    token = encode_cursor({"s": "recency", "v": "2026-07-09T00:00:00+00:00", "id": "d1"}, _SECRET)
    assert isinstance(token, str)
    payload = decode_cursor(token, _SECRET)
    assert payload == {"s": "recency", "v": "2026-07-09T00:00:00+00:00", "id": "d1"}


def test_none_encodes_to_none():
    assert encode_cursor(None, _SECRET) is None


def test_empty_decodes_to_none():
    assert decode_cursor(None, _SECRET) is None
    assert decode_cursor("", _SECRET) is None


def test_tampered_payload_is_rejected():
    token = encode_cursor({"s": "alpha", "v": "abc", "id": "d1"}, _SECRET)
    # Flip a character in the payload segment (before the '.').
    body, _, sig = token.partition(".")
    tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
    with pytest.raises(BadRequestError):
        decode_cursor(tampered, _SECRET)


def test_wrong_secret_is_rejected():
    token = encode_cursor({"s": "alpha", "v": "abc", "id": "d1"}, _SECRET)
    with pytest.raises(BadRequestError):
        decode_cursor(token, "a-different-secret-16chars")


def test_malformed_token_is_rejected():
    with pytest.raises(BadRequestError):
        decode_cursor("not-a-valid-cursor", _SECRET)

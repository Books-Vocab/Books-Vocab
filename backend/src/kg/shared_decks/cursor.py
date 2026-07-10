"""Opaque, HMAC-signed keyset cursor for shared-deck pagination.

Wire form: ``base64url(json_payload) + "." + base64url(hmac_sha256_tag)``.

The payload is a small JSON dict (sort key, last sort value, last deck/card id).
Signing with a server secret makes the cursor tamper-evident — a client cannot
forge one to page past the discovery WHERE filter, nor steer a mutating-counter
sort (Phase 3) with a hand-crafted boundary. A bad/forged token raises
``BadRequestError`` rather than silently restarting from page one (which would
loop the client forever on a corrupted cursor).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from ..exceptions import BadRequestError


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + ("=" * ((-len(text)) % 4)))


def _sign(body: str, secret: str) -> str:
    tag = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return _b64u_encode(tag)


def encode_cursor(payload: dict[str, Any] | None, secret: str) -> str | None:
    """Sign ``payload`` into an opaque cursor token. ``None`` → ``None`` (the
    last page has no next cursor)."""
    if payload is None:
        return None
    body = _b64u_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body, secret)}"


def decode_cursor(token: str | None, secret: str) -> dict[str, Any] | None:
    """Verify + decode a cursor token back to its payload dict. ``None``/empty →
    ``None``. Raises :class:`BadRequestError` on any malformed/forged token."""
    if not token:
        return None
    body, sep, sig = token.partition(".")
    if not sep or not body or not sig:
        raise BadRequestError("Invalid cursor")
    expected = _sign(body, secret)
    if not hmac.compare_digest(sig, expected):
        raise BadRequestError("Invalid cursor")
    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BadRequestError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise BadRequestError("Invalid cursor")
    return payload


__all__ = ["encode_cursor", "decode_cursor"]

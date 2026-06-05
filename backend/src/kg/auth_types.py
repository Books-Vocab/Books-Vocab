"""Shared types for OAuth/JWT token verification."""

from typing import NamedTuple


class VerifiedIdentity(NamedTuple):
    sub: str
    email: str | None
    email_verified: bool

"""Public shared-decks (Explore) router, mounted at ``/api/decks``.

Phase 1a-ii wires the router shell into app composition; the browse endpoints
(``GET /api/decks`` + detail + cards) land in Phase 1b-i. Guest browse uses
``OptionalCurrentUser`` (a public GET tolerating an absent/expired bearer);
write paths (copy/publish/rate/report) arrive in later phases.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["shared-decks"])

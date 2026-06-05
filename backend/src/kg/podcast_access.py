"""Podcast access tiers — the entitlement policy that replaced public-read.

Three tiers, derived purely from auth state + Pro entitlement (no per-series
flags, because there is currently no Pro-only *content* — the wall is uniform):

* ``guest`` — no authenticated user. May browse catalog metadata + covers, but
  may not stream any audio.
* ``free`` — authenticated, no active Pro entitlement. May stream only the
  *preview* asset of episode :data:`FREE_PREVIEW_EP_NUM` of each series.
* ``pro`` — active Pro entitlement. Full access.

The HTTP gate lives in ``routers/podcast.py``; this module is the pure policy
(tier resolution + the audio-asset decision) so it stays unit-testable without
FastAPI plumbing and the client can mirror the same predicate.
"""
from __future__ import annotations

from typing import Literal

from .types import UserRecord

PodcastTier = Literal["guest", "free", "pro"]

# Only episode 1 is previewable for the free tier. Kept as a named constant so
# the policy is one edit away from "first N episodes free" without touching the
# gate's control flow.
FREE_PREVIEW_EP_NUM = 1

# Asset stems under ``ep_NN/`` — the basename before the format extension.
# ``audio`` = full episode (pro); ``preview`` = the pre-generated free-tier clip.
FULL_AUDIO_STEM = "audio"
PREVIEW_AUDIO_STEM = "preview"

# Machine-readable error codes returned in the gate's ``{"detail": {...}}`` body
# so the client can route to the right surface (login sheet vs paywall) without
# string-matching a human message.
ERR_AUTH_REQUIRED = "auth_required"
ERR_UPGRADE_REQUIRED = "upgrade_required"


def resolve_podcast_tier(user: UserRecord | None) -> PodcastTier:
    """Map an (optional) authenticated user to their podcast access tier."""
    if user is None:
        return "guest"
    # Local import keeps this module free of the deps/billing import cycle.
    from .deps_quota import _is_pro

    return "pro" if _is_pro(user) else "free"


def is_free_previewable_episode(ep_num: int) -> bool:
    """True iff a free-tier caller may stream a preview of this episode."""
    return ep_num == FREE_PREVIEW_EP_NUM

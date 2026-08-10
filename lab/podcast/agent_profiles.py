"""Shared agent-profile registry for the podcast pipeline and monitor.

This module deliberately has no pipeline, FastAPI, filesystem, or environment
side effects.  Consumers may import the profile names without importing the
runner or starting the monitor.
"""

from __future__ import annotations

PROFILE_DEFAULT_MODEL: dict[str, str] = {"claude": "opus[1m]"}
AGENT_PROFILES: tuple[str, ...] = tuple(PROFILE_DEFAULT_MODEL)

__all__ = ["AGENT_PROFILES", "PROFILE_DEFAULT_MODEL"]

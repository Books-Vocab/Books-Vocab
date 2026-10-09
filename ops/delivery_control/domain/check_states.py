"""Terminal GitHub check states, shared by the control plane and ``deliver``."""

from __future__ import annotations

FAILURE_STATES = frozenset(
    {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
)
SUCCESS_STATES = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
TERMINAL_STATES = FAILURE_STATES | SUCCESS_STATES

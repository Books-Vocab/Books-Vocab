"""Typed refusal raised when an exact reanchor tuple is no longer valid."""

from __future__ import annotations

from typing import Any


class ReanchorRefused(RuntimeError):
    """The exact transaction tuple no longer permits local mutation."""

    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details

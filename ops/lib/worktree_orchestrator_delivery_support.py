"""Monotonic close-wave phase receipt support."""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import io
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted delivery functions."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


_DELIVERY_PHASES = (
    "cutover", "resolve-source", "anchor", "validate", "resolve-integration", "sync",
)
_DELIVERY_PHASE_STATUSES = {"started", "completed", "blocked"}


def _delivery_record_phase(
    manifest_path: Path | None,
    phase: str,
    *,
    status: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Persist one monotonic close-wave phase receipt.

    The manifest is the recovery ledger, not merely a final report.  A phase may
    be replayed after a process crash, but a completed phase must never regress to
    ``started`` or be overwritten with a different operation identity.  The
    atomic ``_integrate_save`` write means the phase receipt is durable before the
    next phase mutates primary/registry state.
    """
    if manifest_path is None:
        return None
    if phase not in _DELIVERY_PHASES:
        raise ValueError(f"unknown close-wave phase: {phase}")
    if status not in _DELIVERY_PHASE_STATUSES:
        raise ValueError(f"unknown close-wave phase status: {status}")
    payload = _delivery_load_json(manifest_path)
    if payload is None:
        raise OSError(f"integration manifest is unreadable: {manifest_path}")
    marker = _delivery_update_phase_marker(
        payload.get("close_wave"), phase, status=status, **fields,
    )
    payload["close_wave"] = marker
    _integrate_save(manifest_path, payload)
    return marker


def _delivery_update_phase_marker(
    raw_marker: Any,
    phase: str,
    *,
    status: str,
    **fields: Any,
) -> dict[str, Any]:
    """Pure marker update used to batch a phase receipt with another save."""
    if phase not in _DELIVERY_PHASES:
        raise ValueError(f"unknown close-wave phase: {phase}")
    if status not in _DELIVERY_PHASE_STATUSES:
        raise ValueError(f"unknown close-wave phase status: {status}")
    if raw_marker is not None and not isinstance(raw_marker, dict):
        raise ValueError("integration manifest has malformed close_wave marker")
    marker = dict(raw_marker or {})
    phases = marker.get("phases")
    if phases is not None and not isinstance(phases, dict):
        raise ValueError("integration manifest has malformed phase ledger")
    phases = dict(phases or {})
    previous = phases.get(phase)
    if previous is not None and not isinstance(previous, dict):
        raise ValueError(f"integration manifest has malformed {phase} phase")
    previous = dict(previous or {})
    if previous.get("status") == "completed":
        # A completed receipt is immutable.  In particular, a retry after a
        # crash must not replace its operation identity with the retry's base.
        marker["phases"] = phases
        if marker.get("last_successful_phase") is None:
            marker["last_successful_phase"] = phase
        return marker
    entry = {**previous, "status": status}
    for key, value in fields.items():
        if value is not None:
            entry[key] = value
    phases[phase] = entry
    marker["phases"] = phases
    marker.setdefault("last_successful_phase", None)
    if status == "completed":
        previous_success = marker.get("last_successful_phase")
        if (previous_success not in _DELIVERY_PHASES
                or _DELIVERY_PHASES.index(phase)
                >= _DELIVERY_PHASES.index(previous_success)):
            marker["last_successful_phase"] = phase
    for key in ("operation_base", "landed_sha"):
        if key in fields and fields[key] is not None:
            marker[key] = fields[key]
    return marker

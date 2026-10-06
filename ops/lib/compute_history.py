"""Bounded, append-only run history that feeds the ``auto`` cost model.

One NDJSON line per *verified successful* run, written by the Oscar-side CLI::

    {"profile", "mode": "local"|"felix", "duration_seconds",
     "transfer_seconds": float|null, "recorded_at": epoch seconds}

Reads never raise: a malformed line is ignored, never trusted.  Sparse or stale
history yields ``None`` so ``auto`` stays on local (fail closed).
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import statistics
import tempfile
from pathlib import Path
from typing import Any

HISTORY_NAME = "history.ndjson"
LOCK_NAME = "history.lock"
MODES = frozenset({"local", "felix"})
COMPACT_ABOVE_LINES = 2000
KEEP_PER_PROFILE = 50
WINDOW_SECONDS = 14 * 24 * 3600
MIN_LOCAL_SAMPLES = 3
MAX_LOCAL_SAMPLES = 20
MIN_TRANSFER_SAMPLES = 1


def _seconds(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _valid(entry: Any, now: float) -> bool:
    if not isinstance(entry, dict):
        return False
    profile = entry.get("profile")
    if not isinstance(profile, str) or not profile:
        return False
    if entry.get("mode") not in MODES:
        return False
    if not _seconds(entry.get("duration_seconds")):
        return False
    transfer = entry.get("transfer_seconds")
    if transfer is not None and not _seconds(transfer):
        return False
    recorded = entry.get("recorded_at")
    return _seconds(recorded) and recorded <= now


def _parse(raw: bytes, now: float) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):  # includes UnicodeDecodeError
            continue
        if _valid(entry, now):
            entries.append(entry)
    return entries


def _read_raw(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def read_entries(cache: Path, now: float) -> list[dict[str, Any]]:
    """All structurally valid entries, file order; never raises."""

    return _parse(_read_raw(cache / HISTORY_NAME), now)


def _compact(path: Path, now: float) -> None:
    kept: dict[str, list[dict[str, Any]]] = {}
    for entry in _parse(_read_raw(path), now):
        kept.setdefault(entry["profile"], []).append(entry)
    survivors = {
        id(e) for entries in kept.values() for e in entries[-KEEP_PER_PROFILE:]
    }
    ordered = [e for entries in kept.values() for e in entries if id(e) in survivors]
    ordered.sort(key=lambda e: e["recorded_at"])
    body = "".join(json.dumps(e, sort_keys=True) + "\n" for e in ordered)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".history-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body.encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(
    cache: Path,
    *,
    profile: str,
    mode: str,
    duration_seconds: float,
    transfer_seconds: float | None,
    now: float,
) -> None:
    """Append one entry (flock + single write + fsync); raises on I/O failure.

    The caller treats failure as non-fatal.  Invalid input is a programming
    error and raises ``ValueError`` rather than polluting the file.
    """

    entry = {
        "profile": profile,
        "mode": mode,
        "duration_seconds": duration_seconds,
        "transfer_seconds": transfer_seconds,
        "recorded_at": now,
    }
    if not _valid(entry, now):
        raise ValueError("invalid history entry")
    line = (json.dumps(entry, sort_keys=True) + "\n").encode()
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / HISTORY_NAME
    with open(cache / LOCK_NAME, "ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
                os.fsync(fd)
            finally:
                os.close(fd)
            if _read_raw(path).count(b"\n") > COMPACT_ABOVE_LINES:
                _compact(path, now)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _fresh(entries: list[dict[str, Any]], profile: str, mode: str, now: float):
    return [
        e
        for e in entries
        if e["profile"] == profile
        and e["mode"] == mode
        and now - e["recorded_at"] <= WINDOW_SECONDS
    ]


def local_durations(cache: Path, profile: str, now: float) -> list[float] | None:
    """Newest <=20 fresh local durations, or ``None`` when fewer than 3."""

    fresh = _fresh(read_entries(cache, now), profile, "local", now)
    fresh.sort(key=lambda e: e["recorded_at"])
    samples = [float(e["duration_seconds"]) for e in fresh[-MAX_LOCAL_SAMPLES:]]
    return samples if len(samples) >= MIN_LOCAL_SAMPLES else None


def felix_transfer_seconds(cache: Path, profile: str, now: float) -> float | None:
    """Median fresh felix transfer time, or ``None`` when no sample exists."""

    fresh = _fresh(read_entries(cache, now), profile, "felix", now)
    samples = [
        float(e["transfer_seconds"]) for e in fresh if e["transfer_seconds"] is not None
    ]
    if len(samples) < MIN_TRANSFER_SAMPLES:
        return None
    return float(statistics.median(samples))

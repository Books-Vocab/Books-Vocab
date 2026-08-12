"""Canonical JSON bytes shared by App Review evidence producers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable human-readable UTF-8 JSON with sorted keys and newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Hash canonical compact JSON bytes for provenance fingerprints."""
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

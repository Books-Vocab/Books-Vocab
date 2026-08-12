"""Canonical App Review serialization contract.

The three App Review producers must use one byte-level JSON policy.  These
tests intentionally exercise both the human-readable manifest bytes and the
compact digest bytes; changing either policy is a provenance change.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))

from lib.canonical_json import (  # noqa: E402
    canonical_json_bytes,
    canonical_json_sha256,
)


def test_canonical_json_bytes_are_key_order_and_unicode_stable() -> None:
    value = {"z": "繁體", "a": {"β": 2, "α": 1}}
    expected = '{\n  "a": {\n    "α": 1,\n    "β": 2\n  },\n  "z": "繁體"\n}\n'.encode(
        "utf-8"
    )
    assert canonical_json_bytes(value) == expected
    assert canonical_json_bytes({"a": value["a"], "z": value["z"]}) == expected


def test_canonical_json_sha256_is_compact_and_changes_with_content() -> None:
    value = {"b": 2, "a": ["x", "y"]}
    compact = b'{"a":["x","y"],"b":2}'
    assert canonical_json_sha256(value) == hashlib.sha256(compact).hexdigest()
    assert canonical_json_sha256({**value, "b": 3}) != canonical_json_sha256(value)
    # Pretty manifest bytes and digest bytes are deliberately different formats.
    assert canonical_json_bytes(value) != compact
    assert json.loads(canonical_json_bytes(value)) == value

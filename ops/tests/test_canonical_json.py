"""Canonical JSON finite-number boundary tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))

from lib.canonical_json import (  # noqa: E402
    canonical_json_bytes,
    canonical_json_sha256,
)


@pytest.mark.parametrize(
    "canonicalize",
    [canonical_json_bytes, canonical_json_sha256],
    ids=["bytes", "sha256"],
)
@pytest.mark.parametrize(
    "number",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_canonical_json_rejects_non_finite_numbers(canonicalize, number) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        canonicalize({"value": number})

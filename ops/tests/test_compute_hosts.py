from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib.compute_hosts import host_role  # noqa: E402


@pytest.mark.parametrize(
    ("node", "role"),
    [
        ("MacBook-Air-7", "oscar"),
        ("MacBook-Air-43", "oscar"),
        ("macbook-air-43.local", "oscar"),
        ("chenliangyusAir", "felix"),
        ("chenliangyus-MacBook-Air", "felix"),
        ("CHENLIANGYUS-MACBOOK-AIR.lan", "felix"),
    ],
)
def test_known_nodes_resolve_to_their_role(node: str, role: str) -> None:
    assert host_role(node) == role


@pytest.mark.parametrize(
    "node",
    [
        "",
        "MacBook-Air-8",
        "oscar",
        "felix",
        "macbook-air-43-evil",
        " MacBook-Air-43",
        None,
        7,
    ],
)
def test_unknown_or_malformed_nodes_fail_closed(node: object) -> None:
    assert host_role(node) is None  # type: ignore[arg-type]

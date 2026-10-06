"""Closed node-name to host-role table for the two-machine compute topology."""

from __future__ import annotations

_ROLES = {
    "macbook-air-7": "oscar",
    "chenliangyusair": "felix",
    "chenliangyus-macbook-air": "felix",
}


def host_role(node: str) -> str | None:
    """Return ``oscar``/``felix`` for a known node name, else ``None`` (fail closed)."""

    if not isinstance(node, str) or not node:
        return None
    return _ROLES.get(node.split(".", 1)[0].lower())

"""Closed node-name to host-role table for the two-machine compute topology."""

from __future__ import annotations

# macOS renames a machine (``MacBook-Air-7`` -> ``MacBook-Air-43``) when its name
# collides on the network, so every name the Oscar laptop has carried is listed.
# The Oscar laptop is the M4 Air at tailnet address 100.79.106.79.
_ROLES = {
    "macbook-air-7": "oscar",
    "macbook-air-43": "oscar",
    "chenliangyusair": "felix",
    "chenliangyus-macbook-air": "felix",
}


def host_role(node: str) -> str | None:
    """Return ``oscar``/``felix`` for a known node name, else ``None`` (fail closed)."""

    if not isinstance(node, str) or not node:
        return None
    return _ROLES.get(node.split(".", 1)[0].lower())

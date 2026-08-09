"""Tool identity — who produced a verdict.

A gate verdict is only as trustworthy as the knowledge of which build of which tool
produced it. `ops/worktree_orchestrate.py gate` routes changed files to gate tools that
run with the WORKTREE as their cwd, while the routing rules themselves come from
whichever copy of the orchestrator the shell resolved. Those two can be different
commits, and until this module existed nothing in the emitted verdict said which.

Content hash, not git commit: a commit id attributes an uncommitted edit to the
committed version, which is exactly the case where the difference matters most.

This module is the SoT for tool-identity hashing. `ops/ui_world_manifest.py` still
has a local `_sha256_hex`; migrating that copy belongs to its own bounded change.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["logical_tool_path", "sha256_file"]


def sha256_file(path: Path) -> str:
    """Streaming sha256 of a file's bytes. Raises OSError if it does not exist —
    a provenance helper must never degrade a missing tool into an empty digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def logical_tool_path(path: Path) -> str:
    """`/abs/…/<checkout>/ops/lib/x.py` -> `ops/lib/x.py`.

    The identity key must be checkout-independent: the same tool in a worktree and in
    the primary checkout has to yield the same string, or two provenance records could
    never be compared — which is the whole purpose. The RIGHTMOST `ops` segment wins,
    so a repo that happens to live under a directory called `ops` is not swallowed.

    Resolved throughout, fallback included: for a symlink at `<checkout>/ops/tool.py`
    whose target lives outside any `ops/`, answering with the LINK's name would claim an
    `ops/`-relative identity the real file does not have.
    """
    resolved = path.resolve()
    parts = resolved.parts
    try:
        index = len(parts) - 1 - list(reversed(parts)).index("ops")
    except ValueError:
        return resolved.name
    return "/".join(parts[index:])

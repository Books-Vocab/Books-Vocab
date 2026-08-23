"""Resolve control-plane executables without trusting an ambient PATH."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence

_FALLBACK_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "git": (
        "/usr/bin/git",
        "/opt/homebrew/bin/git",
        "/usr/local/bin/git",
    ),
    "gh": (
        "/opt/homebrew/bin/gh",
        "/usr/local/bin/gh",
        "/usr/bin/gh",
    ),
}


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_executable(
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return a command name or stable fallback executable.

    A command found in the supplied PATH remains a logical command name.  This
    preserves adapter evidence and fake-runner contracts.  When PATH cannot
    resolve a control-plane command, a known executable is selected explicitly
    instead of allowing a transient environment to create a false blocker.
    """

    if os.sep in name:
        return name
    env = environment if environment is not None else os.environ
    if shutil.which(name, path=env.get("PATH", "")):
        return name
    for candidate in _FALLBACK_EXECUTABLES.get(name, ()):
        if _is_executable(candidate):
            return candidate
    return name


def resolve_argv(
    argv: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Resolve only the executable position of an argv-only command."""

    if not argv:
        return ()
    return (
        resolve_executable(argv[0], environment=environment),
        *argv[1:],
    )


__all__ = ["resolve_argv", "resolve_executable"]

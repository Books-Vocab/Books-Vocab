"""Validate the checkout that supplies control-plane mutation code."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class SourceProvenanceError(RuntimeError):
    """The control-plane source cannot be proven compatible with its target."""


@dataclass(frozen=True)
class CheckoutProvenance:
    root: Path
    head_sha: str
    clean: bool


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise SourceProvenanceError(
            f"cannot inspect checkout {root}: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise SourceProvenanceError(f"cannot inspect checkout {root}: {detail}")
    return result.stdout.strip()


def inspect_checkout(root: Path) -> CheckoutProvenance:
    """Read exact HEAD and cleanliness without following the caller's cwd."""

    resolved = root.expanduser().resolve()
    top_level = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve()
    if top_level != resolved:
        raise SourceProvenanceError(
            f"checkout root is not canonical: expected {resolved}, found {top_level}"
        )
    head_sha = _git(resolved, "rev-parse", "HEAD")
    dirty = bool(_git(resolved, "status", "--porcelain", "--untracked-files=all"))
    return CheckoutProvenance(root=resolved, head_sha=head_sha, clean=not dirty)


def source_compatibility_problem(
    *, source_root: Path, target_repo: Path
) -> str | None:
    """Return one stable blocker before an in-process mutation is allowed.

    The loaded Python module is allowed to operate on another checkout only
    when it is the exact same committed, clean control-plane revision as the
    target.  This preserves the useful co-versioned module runner while
    preventing a stale detached checkout from applying old registry semantics.
    """

    try:
        source = inspect_checkout(source_root)
        target = inspect_checkout(target_repo)
    except SourceProvenanceError as error:
        return str(error)
    if not source.clean:
        return f"control-plane source checkout is dirty: {source.root}"
    if source.head_sha != target.head_sha:
        return (
            "control-plane source checkout HEAD differs from target repo HEAD: "
            f"source={source.head_sha} target={target.head_sha}"
        )
    return None


__all__ = [
    "CheckoutProvenance",
    "SourceProvenanceError",
    "inspect_checkout",
    "source_compatibility_problem",
]

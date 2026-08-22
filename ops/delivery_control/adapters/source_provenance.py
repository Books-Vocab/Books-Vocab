"""Validate the checkout that supplies control-plane mutation code."""

from __future__ import annotations

import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path


class SourceProvenanceError(RuntimeError):
    """The control-plane source cannot be proven compatible with its target."""


@dataclass(frozen=True)
class CheckoutProvenance:
    root: Path
    head_sha: str
    clean: bool
    control_plane_fingerprint: str


CONTROL_PLANE_PATHS = (
    "ops/lib/worktree_scope.py",
    "ops/worktree_registry.py",
    "ops/worktree_registry_core",
)


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
    """Read checkout state without following the caller's cwd."""

    resolved = root.expanduser().resolve()
    top_level = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve()
    if top_level != resolved:
        raise SourceProvenanceError(
            f"checkout root is not canonical: expected {resolved}, found {top_level}"
        )
    head_sha = _git(resolved, "rev-parse", "HEAD")
    dirty = bool(_git(resolved, "status", "--porcelain", "--untracked-files=all"))
    tracked_paths = _git(resolved, "ls-files", "-z", "--", *CONTROL_PLANE_PATHS)
    entries: list[tuple[str, str]] = []
    for relative in tracked_paths.split("\0"):
        if not relative:
            continue
        file_path = resolved / relative
        if not file_path.is_file():
            entries.append((relative, "missing"))
            continue
        entries.append((relative, hashlib.sha256(file_path.read_bytes()).hexdigest()))
    fingerprint = hashlib.sha256(
        "\0".join(f"{path}\0{digest}" for path, digest in entries).encode()
    ).hexdigest()
    return CheckoutProvenance(
        root=resolved,
        head_sha=head_sha,
        clean=not dirty,
        control_plane_fingerprint=fingerprint,
    )


def source_compatibility_problem(
    *,
    source_root: Path,
    target_repo: Path,
    expected_source_fingerprint: str | None = None,
) -> str | None:
    """Return one stable blocker before an in-process mutation is allowed.

    The loaded Python module is allowed to operate on another checkout only
    when both checkouts are clean and the registry mutation runtime has the
    exact same control-plane fingerprint.  Product commits may legitimately
    differ between canonical main and an owner worktree; comparing the whole
    repository HEAD would reject normal PI publication.  Fingerprinting the
    registry runtime preserves co-versioning without accepting stale registry
    semantics.
    """

    if not source_root.expanduser().resolve().exists():
        if expected_source_fingerprint is None:
            return (
                "control-plane source checkout disappeared before compatibility "
                "was established"
            )
        try:
            target = inspect_checkout(target_repo)
        except SourceProvenanceError as error:
            return str(error)
        if target.control_plane_fingerprint != expected_source_fingerprint:
            return (
                "canonical target fingerprint changed after source checkout "
                "release: "
                f"expected={expected_source_fingerprint} "
                f"target={target.control_plane_fingerprint}"
            )
        return None
    try:
        source = inspect_checkout(source_root)
        target = inspect_checkout(target_repo)
    except SourceProvenanceError as error:
        return str(error)
    if not source.clean:
        return f"control-plane source checkout is dirty: {source.root}"
    if source.control_plane_fingerprint != target.control_plane_fingerprint:
        return (
            "control-plane source fingerprint differs from target repo: "
            f"source={source.control_plane_fingerprint} "
            f"target={target.control_plane_fingerprint}"
        )
    return None


__all__ = [
    "CheckoutProvenance",
    "SourceProvenanceError",
    "inspect_checkout",
    "source_compatibility_problem",
]

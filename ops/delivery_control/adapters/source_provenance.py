"""Validate the checkout that supplies control-plane mutation code."""

from __future__ import annotations

import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path

from lib.executables import resolve_argv


class SourceProvenanceError(RuntimeError):
    """The control-plane source cannot be proven compatible with its target."""


@dataclass(frozen=True)
class CheckoutProvenance:
    root: Path
    head_sha: str
    clean: bool
    control_plane_fingerprint: str
    blocking_paths: tuple[str, ...] = ()
    untracked_warnings: tuple[str, ...] = ()


# Untracked files under these prefixes can change what the control plane runs;
# any other untracked file (root-level scratch, caches) is only a warning.
CONTROL_PLANE_UNTRACKED_PREFIXES = ("ops/", ".github/")

CONTROL_PLANE_PATHS = (
    "ops/lib/worktree_scope.py",
    "ops/worktree_registry.py",
    "ops/worktree_registry_core",
)


def _git(root: Path, *arguments: str, strip: bool = True) -> str:
    try:
        result = subprocess.run(
            resolve_argv(["git", "-C", str(root), *arguments]),
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
    return result.stdout.strip() if strip else result.stdout


def _classify_status(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split porcelain -z output into blocking paths and untracked warnings."""

    blocking: list[str] = []
    warnings: list[str] = []
    fields = raw.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            index += 1  # rename/copy source path follows as its own field
        if code == "??" and not path.startswith(CONTROL_PLANE_UNTRACKED_PREFIXES):
            warnings.append(path)
        else:
            blocking.append(path)
    return tuple(blocking), tuple(warnings)


def _dirty_message(source: CheckoutProvenance) -> str:
    shown = ", ".join(source.blocking_paths[:5])
    if len(source.blocking_paths) > 5:
        shown += f", ... (+{len(source.blocking_paths) - 5} more)"
    return (
        f"control-plane source checkout is dirty: {source.root}; "
        f"offending paths: {shown}; "
        f"fix: git -C {source.root} status, then commit, restore or remove them"
    )


def inspect_checkout(root: Path) -> CheckoutProvenance:
    """Read checkout state without following the caller's cwd."""

    resolved = root.expanduser().resolve()
    top_level = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve()
    if top_level != resolved:
        raise SourceProvenanceError(
            f"checkout root is not canonical: expected {resolved}, found {top_level}"
        )
    head_sha = _git(resolved, "rev-parse", "HEAD")
    blocking, warnings = _classify_status(
        _git(resolved, "status", "--porcelain=v1", "-z", "--untracked-files=all", strip=False)
    )
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
        clean=not blocking,
        control_plane_fingerprint=fingerprint,
        blocking_paths=blocking,
        untracked_warnings=warnings,
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
        return _dirty_message(source)
    if source.control_plane_fingerprint != target.control_plane_fingerprint:
        return (
            "control-plane source fingerprint differs from target repo: "
            "for a control-plane change, run the canonical target command "
            f"{target_repo / 'ops' / 'delivery.py'} or merge the change first; "
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

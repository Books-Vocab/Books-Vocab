"""Filesystem anchors and the private-output guard for the workbench.

Every default path resolves against the package root (``lab/llm_eval``),
never the caller's working directory: the docs say ``cd lab/llm_eval``, the
capability matrix runs from there, and agents run from the repo root.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PACKAGE_ROOT / "results"
PRIVATE_CORPUS_DIR = PACKAGE_ROOT / "private_corpus"


def add_allow_unignored_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-unignored",
        action="store_true",
        help="Write private user data even where git would let it be committed.",
    )


def refuse_committable_outputs(
    parser: argparse.ArgumentParser, outputs: Iterable[Path], *, allow: bool
) -> None:
    """Usage error (exit 2) before private user data lands where git could
    commit it, unless the caller passed ``--allow-unignored``."""
    if allow:
        return
    exposed = committable_paths(outputs)
    if exposed:
        parser.error(
            "refusing to write private user data to a path that is not "
            "git-ignored or that git could not confirm is outside a work tree "
            f"(could be committed): {', '.join(map(str, exposed))}. "
            "Use a git-ignored directory or pass --allow-unignored."
        )


def committable_paths(paths: Iterable[Path]) -> list[Path]:
    """Paths that some git work tree would let you ``git add``.

    A path is safe when no work tree contains it, or when git ignores it.
    Anything git cannot vouch for (tracked, not ignored, git unavailable,
    unexpected git error) counts as committable — private user data fails
    closed.
    """
    return [path for path in paths if _committable(Path(path).resolve())]


def _committable(path: Path) -> bool:
    anchor = path.parent
    while not anchor.is_dir():
        anchor = anchor.parent
    try:
        inside = _git(anchor, "rev-parse", "--is-inside-work-tree")
        if inside.returncode == 0:
            if inside.stdout.strip() != "true":
                # Inside a git dir / bare repo, which has no work tree to
                # ``git add`` from.  Trust that only when no ancestor carries
                # a ``.git`` marker: a repo that owns this directory but
                # that git declined to treat as a work tree (broken
                # discovery, odd config) must still fail closed.
                return _has_repo_marker(anchor)
            # Exit 0 = ignored, 1 = not ignored; a tracked path is never ignored.
            return _git(anchor, "check-ignore", "-q", "--", str(path)).returncode != 0
        # rev-parse also fails for a work tree git cannot read (dubious
        # ownership, permissions, corruption).  Only an explicit "not a git
        # repository" with no repo marker anywhere above is proof of safety.
        return not _provably_outside_any_repo(anchor, inside.stderr)
    except OSError:
        return True


def _provably_outside_any_repo(anchor: Path, stderr: str) -> bool:
    if "not a git repository" not in stderr:
        return False
    if os.environ.get("GIT_DIR") or os.environ.get("GIT_WORK_TREE"):
        return False
    return not _has_repo_marker(anchor)


def _has_repo_marker(anchor: Path) -> bool:
    return any(
        # lexists: a dangling ``.git`` symlink is a repo marker git trips on,
        # yet Path.exists() follows it and reports False.
        os.path.lexists(directory / ".git")
        for directory in (anchor, *anchor.parents)
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Every ambient GIT_* variable is dropped (GIT_DIR, GIT_WORK_TREE,
    # GIT_CEILING_DIRECTORIES, GIT_COMMON_DIR, GIT_CONFIG_*, ...): they
    # redirect repository discovery, so with one set git answers about the
    # override instead of the destination's real repo (GIT_DIR=<bare repo>
    # makes rev-parse print "false" inside an ordinary work tree).
    # LC_ALL=C pins git's message language: the "not a git repository" check
    # above matches on it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**env, "LC_ALL": "C"},
    )

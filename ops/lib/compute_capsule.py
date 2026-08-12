"""Deterministic read-only capsules from a clean, committed Git tree."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CapsuleError(ValueError):
    """The requested source cannot be pinned to a clean tracked tree."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False, text=True)
    if result.returncode:
        raise CapsuleError(f"git: {result.stderr.strip() or 'command failed'}")
    return result.stdout


def _digest(files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, data in files:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


@dataclass(frozen=True)
class Capsule:
    commit: str
    tree_sha256: str
    files: tuple[str, ...]
    materialized_root: Path


def materialize_tracked_capsule(repo: Path | str, commit: str, destination: Path | str) -> Capsule:
    root = Path(repo).resolve()
    dest = Path(destination).resolve()
    if not root.is_dir() or not commit or len(commit) != 40:
        raise CapsuleError("source-schema")
    git_dir = _git(root, "rev-parse", "--git-dir").strip()
    if not git_dir:
        raise CapsuleError("source-git")
    head = _git(root, "rev-parse", "HEAD").strip()
    if head != commit:
        raise CapsuleError("source-commit")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise CapsuleError("source-git-dirty")
    entries = _git(root, "ls-tree", "-r", "--full-tree", commit).splitlines()
    files: list[tuple[str, bytes]] = []
    for entry in entries:
        meta, relative = entry.split("\t", 1)
        mode, kind, _object = meta.split(" ", 2)
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise CapsuleError(f"special-file: {relative}")
        if relative.startswith(".git/") or relative == ".git":
            raise CapsuleError("git-metadata")
        data = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{relative}"],
            capture_output=True,
            check=False,
        )
        if data.returncode:
            raise CapsuleError(f"tracked-read: {relative}")
        files.append((relative, data.stdout))
    files.sort()
    if dest.exists():
        if any(dest.iterdir()):
            raise CapsuleError("destination-not-empty")
    else:
        dest.mkdir(parents=True)
    for relative, data in files:
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)
    for directory in sorted((path for path in dest.rglob("*") if path.is_dir()), key=lambda p: len(p.parts), reverse=True):
        os.chmod(directory, 0o555)
    os.chmod(dest, 0o555)
    materialized = [(path.relative_to(dest).as_posix(), path.read_bytes()) for path in dest.rglob("*") if path.is_file()]
    materialized.sort()
    digest = _digest(materialized)
    expected = _digest(files)
    if digest != expected:
        raise CapsuleError("materialized-tree-digest")
    return Capsule(commit, expected, tuple(relative for relative, _data in files), dest)

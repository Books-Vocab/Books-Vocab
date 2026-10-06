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
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False, text=True
    )
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


def _read_blobs(root: Path, pending: list[tuple[str, str]]) -> list[tuple[str, bytes]]:
    """Read every blob with one ``git cat-file --batch`` process.

    One ``git show`` per file cost ~80 s for this repository's 2400 files; a single
    batch process takes a few seconds.
    """

    request = b"".join(
        object_id.encode("ascii") + b"\n" for _relative, object_id in pending
    )
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=request,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise CapsuleError("tracked-read: cat-file")
    out = result.stdout
    position = 0
    files: list[tuple[str, bytes]] = []
    for relative, object_id in pending:
        newline = out.find(b"\n", position)
        if newline < 0:
            raise CapsuleError(f"tracked-read: {relative}")
        header = out[position:newline].split(b" ")
        if (
            len(header) != 3
            or header[0].decode("ascii", "replace") != object_id
            or header[1] != b"blob"
        ):
            raise CapsuleError(f"tracked-read: {relative}")
        try:
            size = int(header[2])
        except ValueError:
            raise CapsuleError(f"tracked-read: {relative}") from None
        start = newline + 1
        end = start + size
        if end >= len(out) + 1 or out[end : end + 1] != b"\n":
            raise CapsuleError(f"tracked-read: {relative}")
        files.append((relative, out[start:end]))
        position = end + 1
    return files


def _symlink_stays_in_tree(root: Path, commit: str, relative: str) -> bool:
    """True when a tracked symlink's target is a relative path inside the tree."""

    blob = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{relative}"],
        capture_output=True,
        check=False,
    )
    if blob.returncode:
        return False
    try:
        target = blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if (
        not target.strip()
        or target != target.strip()
        or "\0" in target
        or target.startswith("/")
    ):
        return False
    joined = os.path.normpath(os.path.join(os.path.dirname(relative), target))
    return (
        joined != "."
        and joined != ".."
        and not joined.startswith("../")
        and not os.path.isabs(joined)
    )


@dataclass(frozen=True)
class Capsule:
    commit: str
    tree_sha256: str
    files: tuple[str, ...]
    materialized_root: Path
    excluded_symlinks: tuple[str, ...] = ()


def materialize_tracked_capsule(
    repo: Path | str, commit: str, destination: Path | str
) -> Capsule:
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
    # -z keeps paths raw: without it git C-quotes non-ASCII names
    # ("docs/reference/\\346\\236..."), which `git show` then cannot resolve.
    entries = [
        entry
        for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", commit).split(
            "\0"
        )
        if entry
    ]
    pending: list[tuple[str, str]] = []
    excluded_symlinks: list[str] = []
    for entry in entries:
        meta, relative = entry.split("\t", 1)
        mode, kind, object_id = meta.split(" ", 2)
        if kind == "blob" and mode == "120000":
            # Tracked symlinks (e.g. AGENTS.md -> CLAUDE.md) are repository
            # conventions whose real targets are regular tracked files already in
            # the capsule.  Leave the link itself out, but only when it stays
            # inside the tree; anything else is refused.  Felix extracts regular
            # files only and hashes regular files only, so both sides agree.
            if not _symlink_stays_in_tree(root, commit, relative):
                raise CapsuleError(f"symlink-escape: {relative}")
            excluded_symlinks.append(relative)
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise CapsuleError(f"special-file: {relative}")
        if relative.startswith(".git/") or relative == ".git":
            raise CapsuleError("git-metadata")
        pending.append((relative, object_id))
    files = _read_blobs(root, pending)
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
    for directory in sorted(
        (path for path in dest.rglob("*") if path.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        os.chmod(directory, 0o555)
    os.chmod(dest, 0o555)
    materialized = [
        (path.relative_to(dest).as_posix(), path.read_bytes())
        for path in dest.rglob("*")
        if path.is_file()
    ]
    materialized.sort()
    digest = _digest(materialized)
    expected = _digest(files)
    if digest != expected:
        raise CapsuleError("materialized-tree-digest")
    return Capsule(
        commit,
        expected,
        tuple(relative for relative, _data in files),
        dest,
        tuple(sorted(excluded_symlinks)),
    )

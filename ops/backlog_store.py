"""Low-level file-store primitives for :mod:`backlog`.

This module deliberately knows nothing about backlog entry validation or CLI
semantics.  It owns only path calculation, readable JSON serialization,
atomic replacement, and the two locks needed by the file store.  Keeping this
seam dependency-free makes it safe to import from the sandboxed ops tests and
prevents storage concerns from spreading through command handlers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

from lib.lock_wait import LockUnavailable, exclusive_lock

# The ticket data plane may live outside the code repository.  Keep the resolver
# here, beside the low-level store primitives, so the CLI and the orchestrator
# cannot each invent a different interpretation of the same environment setting.
STORE_ENV = "KG_BACKLOG_STORE"
LEGACY_STORE_RELATIVE = Path("docs") / "runbook" / "backlog"
LEGACY_VIEW_RELATIVE = Path("docs") / "runbook" / "improvement_backlog.md"


def resolve_store(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the active ticket store without making it a code-tree default.

    The compatibility default deliberately remains the historical in-repository
    store until an operator selects an external path.  Once ``KG_BACKLOG_STORE``
    is set, both ``backlog.py`` and the worktree orchestrator use this exact
    absolute path; ticket mutations then cannot create a code-repository commit.
    Relative overrides are interpreted from the checkout root, matching the other
    KG path overrides, while ``~`` is expanded before resolution.
    """
    root = Path(root).expanduser().resolve()
    values = os.environ if environ is None else environ
    raw = str(values.get(STORE_ENV) or "").strip()
    candidate = Path(raw).expanduser() if raw else root / LEGACY_STORE_RELATIVE
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def is_external_store(store: Path, root: Path) -> bool:
    """Whether ``store`` is outside the code checkout containing ``root``."""
    try:
        Path(store).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
    except ValueError:
        return True
    return False


def store_descriptor(store: Path, root: Path) -> dict[str, object]:
    """Return stable provenance for the active backlog data plane."""
    store = Path(store).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if is_external_store(store, root):
        mode = "external"
    else:
        try:
            relative = store.relative_to(root)
        except ValueError:  # defensive: is_external_store already checked it
            mode = "external"
        else:
            mode = "repo-legacy" if relative == LEGACY_STORE_RELATIVE else "repo-custom"
    return {
        "schema": "kg.backlog.store.v1",
        "path": str(store),
        "mode": mode,
        "independent": mode == "external",
        "code_repo": str(root),
    }


def default_view(store: Path, root: Path) -> Path:
    """Place the generated convenience view beside, not inside, an external store."""
    store = Path(store).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if is_external_store(store, root):
        return store.parent / "improvement_backlog.md"
    return root / LEGACY_VIEW_RELATIVE


class EntryLockUnavailable(RuntimeError):
    """The per-entry lock could not be acquired."""

    def __init__(self, path: Path, cause: BaseException) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"entry lock unavailable for {path.name}: {cause}")


def entry_path(store: Path, entry_id: str) -> Path:
    """Return the one-file-per-entry path for ``entry_id``."""
    return Path(store) / f"{entry_id}.json"


def dumps(payload: dict) -> str:
    """Serialize an entry in the human-readable, git-friendly form."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextlib.contextmanager
def view_lock(root: Path) -> Iterator[bool]:
    """Serialize the shared generated-view refresh cycle.

    The lock is advisory and fail-open by design.  Mutations have already
    landed by the time a view refresh runs, so an unavailable refresh lock
    must not turn a successful mutation into a reported write failure.
    """
    lock_path = Path(root) / ".cache" / "backlog_view.lock"
    with exclusive_lock(lock_path, label="backlog-view", fail_closed=False) as acquired:
        yield acquired


def write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` atomically without changing its existing mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def entry_lock(root: Path, path: Path) -> Iterator[None]:
    """Serialize create-or-reuse for one entry path and fail closed."""
    path = Path(path)
    key = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    lock_path = Path(root) / ".cache" / "backlog_entry_locks" / f"{key}.lock"
    try:
        with exclusive_lock(lock_path, label=f"backlog-entry:{path.name}"):
            yield
    except LockUnavailable as exc:
        raise EntryLockUnavailable(path, exc) from exc

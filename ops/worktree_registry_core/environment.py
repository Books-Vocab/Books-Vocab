"""Filesystem, clock, Git, and ledger-location adapters."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path
from typing import Any

from .storage import load_state as _load_state


def git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.strip()


def repo_root() -> Path:
    rc, out = git(["rev-parse", "--show-toplevel"], Path.cwd())
    return Path(out).resolve() if rc == 0 and out else Path.cwd().resolve()


def common_anchor() -> Path:
    root = repo_root()
    rc, out = git(["rev-parse", "--git-common-dir"], root)
    if rc != 0 or not out:
        return root
    common = Path(out)
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent


def default_state_path() -> Path:
    return common_anchor() / ".cache" / "worktree_registry.json"


def parse_at(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def resolve_now(value: str | None = None) -> tuple[int, str]:
    now = parse_at(value)
    return int(now.timestamp()), now.strftime("%Y-%m-%dT%H:%M:%SZ")


def state_path(args: argparse.Namespace) -> Path:
    raw = getattr(args, "state", None)
    return Path(raw).expanduser().resolve() if raw else default_state_path()


def load_state(path: Path | None = None) -> dict[str, Any]:
    return _load_state(Path(path or default_state_path()))

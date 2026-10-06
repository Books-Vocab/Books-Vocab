"""Filesystem, clock, Git, and ledger-location adapters."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path
from typing import Any

from lib.executables import resolve_argv

from .storage import load_state as _load_state

REGISTRY_GIT_TIMEOUT_SECONDS = 120.0


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    command = resolve_argv(["git", *args])
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=REGISTRY_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = _text(exc.stdout or exc.output)
        detail = f"git command timed out after {REGISTRY_GIT_TIMEOUT_SECONDS:g}s"
        return 124, f"{output.rstrip()}\n{detail}" if output else detail
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.strip()


def repo_root(root: Path | None = None) -> Path:
    working = (root or Path.cwd()).resolve()
    rc, out = git(["rev-parse", "--show-toplevel"], working)
    return Path(out).resolve() if rc == 0 and out else working


def common_anchor(root: Path | None = None) -> Path:
    root = repo_root(root)
    rc, out = git(["rev-parse", "--git-common-dir"], root)
    if rc != 0 or not out:
        return root
    common = Path(out)
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent


def default_state_path(root: Path | None = None) -> Path:
    return common_anchor(root) / ".cache" / "worktree_registry.json"


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

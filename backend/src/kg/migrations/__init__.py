"""One-off data migrations."""

from __future__ import annotations

from pathlib import Path


def resolve_users_root(data_dir: Path) -> Path:
    """User dirs live under data_dir/users/ (production layout); else data_dir itself."""
    users = data_dir / "users"
    return users if users.is_dir() else data_dir

"""Best-effort cleanup limited to assets created by one reanchor attempt."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import git_ops
from .errors import ReanchorRefused


def _compensate(repo: Path, *, target: Path, branch: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    tracked = any(
        Path(row.get("worktree", "")).expanduser().resolve() == target
        for row in git_ops._worktree_rows(repo)
    )
    if tracked:
        abort_rc, abort_output = git_ops._git(["rebase", "--abort"], target)
        steps.append(
            {
                "action": "rebase-abort",
                "rc": abort_rc,
                "output": abort_output,
                "not_in_progress": abort_rc != 0,
            }
        )
        remove_rc, remove_output = git_ops._git(
            ["worktree", "remove", "--force", str(target)], repo
        )
        steps.append(
            {"action": "worktree-remove", "rc": remove_rc, "output": remove_output}
        )
    local_head = git_ops._local_branch_sha(repo, branch)
    if local_head is not None:
        rc, output = git_ops._git(
            ["update-ref", "-d", f"refs/heads/{branch}", local_head], repo
        )
        steps.append({"action": "local-branch-delete", "rc": rc, "output": output})
    path_tracked = any(
        Path(row.get("worktree", "")).expanduser().resolve() == target
        for row in git_ops._worktree_rows(repo)
    )
    branch_remaining = git_ops._local_branch_sha(repo, branch) is not None
    path_remaining = os.path.lexists(target)
    return {
        "complete": not path_tracked and not branch_remaining and not path_remaining,
        "path_remaining": path_remaining,
        "path_tracked": path_tracked,
        "branch_remaining": branch_remaining,
        "steps": steps,
    }


def safe_compensate(repo: Path, *, target: Path, branch: str) -> dict[str, Any]:
    try:
        return _compensate(repo, target=target, branch=branch)
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        return {
            "complete": False,
            "reason": f"compensation could not prove cleanup: {type(exc).__name__}: {exc}",
            "path_remaining": os.path.lexists(target),
            "branch_remaining": git_ops._local_branch_sha(repo, branch) is not None,
            "steps": [],
        }

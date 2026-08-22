"""Exact Git provisioning and owned-asset compensation for published resume."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import git_ops
from .domain import COMMIT_SHA_RE, DeclaredOperations
from .errors import ReanchorRefused


@dataclass
class ProvisioningAttempt:
    target_added: bool = False
    branch_created: bool = False


def verify_remote_head(repo: Path, *, branch: str, expected_head: str) -> None:
    observed = git_ops._remote_head(repo, branch)
    if observed != expected_head:
        raise ReanchorRefused(
            "remote branch changed during resume-published",
            expected_remote_head=expected_head,
            observed_remote_head=observed,
        )


def validate_released_assets(
    repo: Path, *, recorded_path: Path, target: Path, branch: str,
) -> None:
    git_ops.validate_new_target(repo, target=target, branch=branch)
    ref = f"refs/heads/{branch}"
    rc, local_refs = git_ops._git(
        ["for-each-ref", "--format=%(refname)", ref], repo
    )
    if rc != 0 or local_refs not in {"", ref}:
        raise ReanchorRefused("local branch inventory cannot be proven exact")
    if local_refs == ref:
        raise ReanchorRefused("local branch already exists; duplicate resume is forbidden")
    rows = git_ops._worktree_rows(repo)
    recorded_rows = [
        row
        for row in rows
        if Path(row.get("worktree", "")).expanduser().resolve() == recorded_path
    ]
    if os.path.lexists(recorded_path):
        dirty = ""
        if recorded_path.is_dir():
            rc, output = git_ops._git(["status", "--porcelain=v1"], recorded_path)
            dirty = output if rc == 0 else "unknown"
        reason = (
            "recorded published worktree is dirty and was not released"
            if dirty
            else "recorded published worktree was not released"
        )
        raise ReanchorRefused(reason, recorded_path=str(recorded_path))
    if recorded_rows:
        raise ReanchorRefused(
            "recorded published worktree release is unknown",
            recorded_path=str(recorded_path),
        )


def ensure_exact_source(
    repo: Path, *, branch: str, base_sha: str, remote_head: str,
    declared: DeclaredOperations,
) -> None:
    verify_remote_head(repo, branch=branch, expected_head=remote_head)
    rc, output = git_ops._git(
        ["fetch", "--quiet", "--no-tags", "origin", f"refs/heads/{branch}"],
        repo,
    )
    if rc != 0:
        raise ReanchorRefused("exact remote branch could not be fetched", git=output)
    verify_remote_head(repo, branch=branch, expected_head=remote_head)
    for label, sha in (("original base", base_sha), ("remote HEAD", remote_head)):
        rc, output = git_ops._git(["cat-file", "-e", f"{sha}^{{commit}}"], repo)
        if rc != 0:
            raise ReanchorRefused(f"{label} commit is unavailable", git=output)
    if git_ops._git(["merge-base", "--is-ancestor", base_sha, remote_head], repo)[0] != 0:
        raise ReanchorRefused("original base is not an ancestor of remote PR HEAD")
    if git_ops.scope_operations(repo, start=base_sha, end=remote_head) != declared:
        raise ReanchorRefused("remote PR branch differs from the exact original Scope")


def provision_exact(
    repo: Path, *, target: Path, branch: str, remote_head: str,
    base_sha: str, declared: DeclaredOperations, attempt: ProvisioningAttempt,
) -> str:
    rc, output = git_ops._git(
        ["worktree", "add", "--detach", str(target), remote_head], repo
    )
    if rc != 0:
        raise ReanchorRefused("local worktree recreation failed", git=output)
    attempt.target_added = True
    rc, output = git_ops._git(["switch", "-c", branch], target)
    branch_rc, current_branch = git_ops._git(["branch", "--show-current"], target)
    if branch_rc == 0 and current_branch == branch:
        attempt.branch_created = True
    if rc != 0:
        raise ReanchorRefused("local branch recreation failed", git=output)
    verify_remote_head(repo, branch=branch, expected_head=remote_head)
    status_rc, status = git_ops._git(["status", "--porcelain=v1"], target)
    head_rc, head = git_ops._git(["rev-parse", "--verify", "HEAD^{commit}"], target)
    if (
        branch_rc != 0 or current_branch != branch or status_rc != 0 or status
        or head_rc != 0 or COMMIT_SHA_RE.fullmatch(head) is None
        or head != remote_head
    ):
        raise ReanchorRefused("resumed worktree failed exact branch/clean/HEAD readback")
    if git_ops.scope_operations(target, start=base_sha, end=head) != declared:
        raise ReanchorRefused("resumed branch differs from the exact original Scope")
    return head


def compensate(
    repo: Path, *, target: Path, branch: str, expected_head: str,
    attempt: ProvisioningAttempt,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    if attempt.target_added:
        rows = git_ops._worktree_rows(repo)
        target_rows = [
            row for row in rows
            if Path(row.get("worktree", "")).expanduser().resolve() == target
        ]
        target_head = git_ops._git(["rev-parse", "HEAD^{commit}"], target)[1]
        if len(target_rows) == 1 and target_head == expected_head:
            rc, output = git_ops._git(
                ["worktree", "remove", "--force", str(target)], repo
            )
            steps.append({"action": "worktree-remove", "rc": rc, "output": output})
    if attempt.branch_created and git_ops._local_branch_sha(repo, branch) == expected_head:
        rc, output = git_ops._git(
            ["update-ref", "-d", f"refs/heads/{branch}", expected_head], repo
        )
        steps.append({"action": "local-branch-delete", "rc": rc, "output": output})
    path_remaining = os.path.lexists(target)
    branch_remaining = git_ops._local_branch_sha(repo, branch) is not None
    return {
        "complete": not path_remaining and not (
            attempt.branch_created and branch_remaining
        ),
        "path_remaining": path_remaining,
        "branch_remaining": branch_remaining,
        "steps": steps,
    }

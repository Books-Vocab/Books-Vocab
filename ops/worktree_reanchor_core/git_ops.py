"""Exact Git observations, local mutation, and compensation for reanchor."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .domain import COMMIT_SHA_RE, DeclaredOperations, commit_sha
from .errors import ReanchorRefused

REANCHOR_GIT_TIMEOUT_SECONDS = 120.0


@dataclass
class ReanchorAttempt:
    """Track local state so existing owner assets are never mistaken for ours."""

    existing_target: bool = False
    rebased_head: str | None = None


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        process = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=REANCHOR_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = _text(exc.stdout or exc.output)
        detail = f"git command timed out after {REANCHOR_GIT_TIMEOUT_SECONDS:g}s"
        return 124, f"{output.rstrip()}\n{detail}" if output else detail
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return process.returncode, process.stdout.strip()


def _remote_head(repo: Path, branch: str) -> str:
    ref = f"refs/heads/{branch}"
    rc, output = _git(["ls-remote", "--heads", "origin", ref], repo)
    if rc != 0:
        raise ReanchorRefused(f"remote ref cannot be read: {ref}", git=output, ref=ref)
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise ReanchorRefused(
            f"remote ref is missing or non-unique: {ref}", ref=ref, rows=rows
        )
    return commit_sha(rows[0][0], label=f"remote {ref}")


def verify_remote_cas(
    repo: Path,
    *,
    branch: str,
    expected_remote_head: str,
    expected_live_main: str,
) -> None:
    observed_head = _remote_head(repo, branch)
    if observed_head != expected_remote_head:
        raise ReanchorRefused(
            "remote branch changed during reanchor",
            expected_remote_head=expected_remote_head,
            observed_remote_head=observed_head,
        )
    observed_main = _remote_head(repo, "main")
    if observed_main != expected_live_main:
        raise ReanchorRefused(
            "live main changed during reanchor",
            expected_live_main=expected_live_main,
            observed_live_main=observed_main,
        )


def _worktree_rows(repo: Path) -> list[dict[str, str]]:
    rc, output = _git(["worktree", "list", "--porcelain"], repo)
    if rc != 0:
        raise ReanchorRefused("physical worktree inventory cannot be read", git=output)
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return rows


def _local_branch_sha(repo: Path, branch: str) -> str | None:
    rc, output = _git(
        ["rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"], repo
    )
    return output if rc == 0 and COMMIT_SHA_RE.fullmatch(output) else None


def scope_operations(repo: Path, *, start: str, end: str) -> DeclaredOperations:
    rc, output = _git(
        ["diff", "--name-status", "--no-renames", f"{start}..{end}"], repo
    )
    if rc != 0:
        raise ReanchorRefused(
            "exact branch Scope diff cannot be computed",
            start=start,
            end=end,
            git=output,
        )
    operation_for_status = {
        "A": "add",
        "M": "modify",
        "T": "modify",
        "D": "delete",
    }
    operations: list[tuple[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        status = fields[0][:1] if fields else ""
        if status not in operation_for_status or len(fields) != 2:
            raise ReanchorRefused(
                "exact branch Scope contains an unsupported Git operation", entry=line
            )
        operations.append((fields[1], operation_for_status[status]))
    return tuple(sorted(operations))


def validate_repository(repo: Path) -> None:
    if not repo.is_dir():
        raise ReanchorRefused("repository path is not a directory")
    if _git(["rev-parse", "--show-toplevel"], repo)[0] != 0:
        raise ReanchorRefused("repository path is not a Git worktree")


def validate_new_target(repo: Path, *, target: Path, branch: str) -> None:
    if target == repo or target.exists() or target.is_symlink():
        raise ReanchorRefused(
            "target path must be new and must not be the repository root"
        )
    if not target.parent.is_dir():
        raise ReanchorRefused("target path parent does not exist")
    rc, output = _git(["check-ref-format", f"refs/heads/{branch}"], repo)
    if rc != 0:
        raise ReanchorRefused("original branch is not a valid local ref", git=output)
    if _local_branch_sha(repo, branch) is not None:
        raise ReanchorRefused(
            "local branch already exists; duplicate adoption is forbidden"
        )
    for row in _worktree_rows(repo):
        path = Path(row.get("worktree", "")).expanduser().resolve()
        if path == target or row.get("branch") == f"refs/heads/{branch}":
            raise ReanchorRefused(
                "target path or branch already belongs to a physical worktree"
            )


def validate_authorized_existing_target(
    repo: Path,
    *,
    recorded_path: Path,
    target: Path,
    branch: str,
    expected_head: str,
) -> None:
    """Validate the one existing path authorized by the exact owner claim.

    ``validate_new_target`` intentionally remains strict for every new-target
    caller. This seam is only called after registry and lifecycle proof have
    selected the original owner claim; it still requires the physical path,
    branch, HEAD, and clean state to agree exactly.
    """

    requested_path = target.expanduser().resolve()
    exact_recorded_path = recorded_path.expanduser().resolve()
    if requested_path != exact_recorded_path:
        raise ReanchorRefused(
            "authorized existing target differs from the exact recorded path",
            recorded_path=str(exact_recorded_path),
            requested_path=str(requested_path),
        )
    repo_path = repo.expanduser().resolve()
    if requested_path == repo_path or target.is_symlink() or not target.is_dir():
        raise ReanchorRefused(
            "authorized existing target must be a real non-root worktree directory"
        )
    rc, output = _git(["check-ref-format", f"refs/heads/{branch}"], repo)
    if rc != 0:
        raise ReanchorRefused("original branch is not a valid local ref", git=output)

    local_head = _local_branch_sha(repo, branch)
    if local_head is None:
        raise ReanchorRefused(
            "authorized existing worktree branch is unavailable",
            branch=branch,
        )
    if local_head != expected_head:
        raise ReanchorRefused(
            "authorized existing worktree HEAD differs from the exact remote HEAD",
            expected_head=expected_head,
            observed_head=local_head,
        )

    rows = _worktree_rows(repo)
    path_rows = [
        row
        for row in rows
        if Path(row.get("worktree", "")).expanduser().resolve() == requested_path
    ]
    branch_rows = [row for row in rows if row.get("branch") == f"refs/heads/{branch}"]
    if (
        len(path_rows) != 1
        or len(branch_rows) != 1
        or path_rows[0] is not branch_rows[0]
    ):
        raise ReanchorRefused(
            "authorized existing worktree is not uniquely tracked by the exact branch",
            path_matches=len(path_rows),
            branch_matches=len(branch_rows),
        )

    branch_rc, current_branch = _git(["branch", "--show-current"], target)
    status_rc, status = _git(["status", "--porcelain=v1"], target)
    head_rc, current_head = _git(["rev-parse", "--verify", "HEAD^{commit}"], target)
    if branch_rc != 0 or current_branch != branch:
        raise ReanchorRefused(
            "authorized existing worktree is occupied by another branch",
            expected_branch=branch,
            observed_branch=current_branch,
        )
    if status_rc != 0:
        raise ReanchorRefused(
            "authorized existing worktree cleanliness cannot be proven",
            git=status,
        )
    if status:
        raise ReanchorRefused("authorized existing worktree is dirty", git=status)
    if head_rc != 0 or current_head != expected_head:
        raise ReanchorRefused(
            "authorized existing worktree HEAD readback differs from the exact remote HEAD",
            expected_head=expected_head,
            observed_head=current_head,
        )


def ensure_commits_and_scope(
    repo: Path,
    *,
    branch: str,
    base_sha: str,
    remote_head: str,
    live_main: str,
    declared: DeclaredOperations,
) -> None:
    rc, output = _git(
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "origin",
            "refs/heads/main",
            f"refs/heads/{branch}",
        ],
        repo,
    )
    if rc != 0:
        raise ReanchorRefused("exact remote commits could not be fetched", git=output)
    verify_remote_cas(
        repo,
        branch=branch,
        expected_remote_head=remote_head,
        expected_live_main=live_main,
    )
    for label, sha in (
        ("original base", base_sha),
        ("expected remote HEAD", remote_head),
        ("live main", live_main),
    ):
        rc, output = _git(["cat-file", "-e", f"{sha}^{{commit}}"], repo)
        if rc != 0:
            raise ReanchorRefused(f"{label} commit is unavailable", git=output)
    if _git(["merge-base", "--is-ancestor", base_sha, remote_head], repo)[0] != 0:
        raise ReanchorRefused("original base is not an ancestor of remote PR HEAD")
    if _git(["merge-base", "--is-ancestor", base_sha, live_main], repo)[0] != 0:
        raise ReanchorRefused("original base is not an ancestor of live main")
    if scope_operations(repo, start=base_sha, end=remote_head) != declared:
        raise ReanchorRefused("remote PR branch differs from the exact original Scope")


def recreate_and_rebase(
    repo: Path,
    *,
    target: Path,
    branch: str,
    base_sha: str,
    remote_head: str,
    live_main: str,
    declared: DeclaredOperations,
    preserve_conflict: bool = False,
    reuse_existing: bool = False,
    attempt: ReanchorAttempt | None = None,
) -> str:
    if attempt is None:
        attempt = ReanchorAttempt(existing_target=reuse_existing)
    else:
        attempt.existing_target = reuse_existing

    if reuse_existing:
        rc, output = _git(["rebase", "--onto", live_main, base_sha, branch], target)
    else:
        rc, output = _git(
            ["worktree", "add", "-b", branch, str(target), remote_head], repo
        )
        if rc != 0:
            raise ReanchorRefused("local worktree recreation failed", git=output)
        rc, output = _git(["rebase", "--onto", live_main, base_sha, branch], target)
    if rc != 0:
        if preserve_conflict:
            raise ReanchorRefused(
                "rebase conflict requires original-owner resolution",
                rebase_conflict=True,
                worktree=str(target),
                branch=branch,
                git=output,
            )
        if reuse_existing:
            abort_rc, abort_output = _git(["rebase", "--abort"], target)
            if abort_rc != 0:
                output = (
                    f"{output}\nexisting rebase abort failed: {abort_output}"
                ).strip()
        raise ReanchorRefused("rebase conflict blocked same-owner reanchor", git=output)
    if reuse_existing:
        head_rc, rebased_head = _git(["rev-parse", "--verify", "HEAD^{commit}"], target)
        if head_rc == 0 and COMMIT_SHA_RE.fullmatch(rebased_head):
            attempt.rebased_head = rebased_head
    verify_remote_cas(
        repo,
        branch=branch,
        expected_remote_head=remote_head,
        expected_live_main=live_main,
    )
    branch_rc, current_branch = _git(["branch", "--show-current"], target)
    status_rc, status = _git(["status", "--porcelain=v1"], target)
    head_rc, head = _git(["rev-parse", "--verify", "HEAD^{commit}"], target)
    if (
        branch_rc != 0
        or current_branch != branch
        or status_rc != 0
        or status
        or head_rc != 0
        or COMMIT_SHA_RE.fullmatch(head) is None
    ):
        raise ReanchorRefused(
            "reanchored worktree failed exact branch/clean/HEAD readback"
        )
    if _git(["merge-base", "--is-ancestor", live_main, head], target)[0] != 0:
        raise ReanchorRefused("reanchored HEAD is not based on exact live main")
    if scope_operations(target, start=live_main, end=head) != declared:
        raise ReanchorRefused("reanchored branch differs from the exact original Scope")
    if reuse_existing:
        attempt.rebased_head = head
    return head


def _compensate_existing(
    repo: Path,
    *,
    target: Path,
    branch: str,
    expected_head: str,
    attempt: ReanchorAttempt,
) -> dict[str, object]:
    """Rollback only an exact in-place rebase; never remove the owner asset."""

    steps: list[dict[str, object]] = []
    path_remaining = os.path.lexists(target)
    if not path_remaining:
        return {
            "complete": False,
            "preserved_existing": True,
            "reason": "authorized existing worktree disappeared during compensation",
            "path_remaining": False,
            "branch_remaining": _local_branch_sha(repo, branch) is not None,
            "steps": steps,
        }

    rows = _worktree_rows(repo)
    path_rows = [
        row
        for row in rows
        if Path(row.get("worktree", "")).expanduser().resolve()
        == target.expanduser().resolve()
    ]
    branch_rc, current_branch = _git(["branch", "--show-current"], target)
    status_rc, status = _git(["status", "--porcelain=v1"], target)
    head_rc, current_head = _git(["rev-parse", "--verify", "HEAD^{commit}"], target)
    if (
        len(path_rows) != 1
        or path_rows[0].get("branch") != f"refs/heads/{branch}"
        or branch_rc != 0
        or current_branch != branch
        or status_rc != 0
        or status
        or head_rc != 0
    ):
        return {
            "complete": False,
            "preserved_existing": True,
            "reason": "existing worktree changed before exact compensation",
            "path_remaining": path_remaining,
            "branch_remaining": _local_branch_sha(repo, branch) is not None,
            "steps": steps,
        }
    if current_head == expected_head:
        return {
            "complete": True,
            "preserved_existing": True,
            "path_remaining": True,
            "branch_remaining": True,
            "steps": steps,
        }
    if attempt.rebased_head is None or current_head != attempt.rebased_head:
        return {
            "complete": False,
            "preserved_existing": True,
            "reason": "existing worktree HEAD changed without an exact rebase attempt identity",
            "expected_rebased_head": attempt.rebased_head,
            "observed_head": current_head,
            "path_remaining": path_remaining,
            "branch_remaining": True,
            "steps": steps,
        }

    reset_rc, reset_output = _git(["reset", "--hard", expected_head], target)
    steps.append(
        {
            "action": "existing-worktree-reset",
            "rc": reset_rc,
            "output": reset_output,
        }
    )
    final_branch_rc, final_branch = _git(["branch", "--show-current"], target)
    final_status_rc, final_status = _git(["status", "--porcelain=v1"], target)
    final_head_rc, final_head = _git(["rev-parse", "--verify", "HEAD^{commit}"], target)
    complete = (
        reset_rc == 0
        and final_branch_rc == 0
        and final_branch == branch
        and final_status_rc == 0
        and not final_status
        and final_head_rc == 0
        and final_head == expected_head
    )
    return {
        "complete": complete,
        "preserved_existing": True,
        "path_remaining": os.path.lexists(target),
        "branch_remaining": _local_branch_sha(repo, branch) is not None,
        "steps": steps,
    }


def compensate_existing(
    repo: Path,
    *,
    target: Path,
    branch: str,
    expected_head: str,
    attempt: ReanchorAttempt,
) -> dict[str, object]:
    """Return structured compensation evidence even when reads fail."""

    try:
        return _compensate_existing(
            repo,
            target=target,
            branch=branch,
            expected_head=expected_head,
            attempt=attempt,
        )
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        try:
            branch_remaining = _local_branch_sha(repo, branch) is not None
        except (OSError, ReanchorRefused, TypeError, ValueError):
            branch_remaining = None
        return {
            "complete": False,
            "preserved_existing": True,
            "reason": f"existing worktree compensation could not prove cleanup: {type(exc).__name__}: {exc}",
            "path_remaining": os.path.lexists(target),
            "branch_remaining": branch_remaining,
            "steps": [],
        }

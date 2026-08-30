"""Recover one published claim whose remote branch disappeared after publication."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import worktree_registry as registry
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.domain.observations import (
    PullRequestInventory,
    PullRequestSnapshot,
)
from delivery_control.services.pr_contract import (
    parse_pull_request_body,
    pull_request_holds,
)

from . import git_ops
from .domain import COMMIT_SHA_RE, DeclaredOperations, commit_sha, declared_operations
from .errors import ReanchorRefused

SCHEMA = "kg.worktree.published-remote-recovery.v1"
EXIT_OK = 0
EXIT_BLOCK = 1
ELIGIBLE_STATUSES = frozenset({"published", "cleanup_pending"})


@dataclass(frozen=True)
class RecoveryRequest:
    repo: Path
    state_path: Path
    pull_request_number: int
    lane_id: str
    branch: str
    owner_thread_id: str
    claim_generation: int
    expected_base_sha: str
    expected_head_sha: str
    target: Path


@dataclass(frozen=True)
class RegistryProof:
    record: dict[str, Any]
    fingerprint: str
    recorded_path: Path
    base_sha: str
    declared: DeclaredOperations
    handback_digest: str
    origin_main_sha: str | None


@dataclass(frozen=True)
class PullRequestProof:
    snapshot: PullRequestSnapshot
    body_sha256: str


@dataclass
class RecoveryAttempt:
    target_created: bool = False
    branch_created: bool = False
    remote_created_by_attempt: bool = False


class RecoveryGitPort(Protocol):
    def validate_repository(self) -> None: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def live_main_sha(self) -> str: ...

    def validate_released_assets(
        self, *, recorded_path: Path, target: Path, branch: str
    ) -> None: ...

    def fetch_pr_head(self, *, pull_request_number: int, expected_head: str) -> str: ...

    def validate_source(
        self, *, base_sha: str, head_sha: str, declared: DeclaredOperations
    ) -> None: ...

    def provision_exact(
        self,
        *,
        target: Path,
        branch: str,
        head_sha: str,
        base_sha: str,
        declared: DeclaredOperations,
        attempt: RecoveryAttempt,
    ) -> None: ...

    def validate_local_exact(
        self, *, target: Path, branch: str, expected_head: str
    ) -> None: ...

    def push_empty_lease(
        self,
        *,
        target: Path,
        branch: str,
        expected_head: str,
        attempt: RecoveryAttempt,
    ) -> None: ...

    def remove_local_assets(
        self, *, target: Path, branch: str, expected_head: str
    ) -> None: ...

    def compensate_local_assets(
        self,
        *,
        target: Path,
        branch: str,
        expected_head: str,
        attempt: RecoveryAttempt,
    ) -> dict[str, object]: ...

    def delete_remote_exact(self, *, branch: str, expected_head: str) -> None: ...


class RecoveryGitHubPort(Protocol):
    def get_pull_request(self, number: int) -> PullRequestSnapshot: ...

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory: ...

    def changed_paths(self, number: int) -> tuple[str, ...]: ...

    def merge_queue_entry_snapshot(self, pull_request_id: str) -> object | None: ...


def build_request(
    *,
    repo: Path,
    state_path: Path,
    pull_request_number: int,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_base_sha: str,
    expected_head_sha: str,
    target: Path,
) -> RecoveryRequest:
    if pull_request_number <= 0:
        raise ReanchorRefused("one explicit positive PR number is required")
    if not lane_id.strip() or not branch.strip() or not owner_thread_id.strip():
        raise ReanchorRefused("lane, branch, and owner must identify one claim")
    if claim_generation < 0:
        raise ReanchorRefused("claim generation must be non-negative")
    base_sha = commit_sha(expected_base_sha, label="expected base")
    head_sha = commit_sha(expected_head_sha, label="expected PR HEAD")
    if target == repo.resolve() or target.exists() or target.is_symlink():
        raise ReanchorRefused("recovery target must be a new local path")
    if not target.parent.is_dir():
        raise ReanchorRefused("recovery target parent does not exist")
    return RecoveryRequest(
        repo=repo.resolve(),
        state_path=state_path.resolve(),
        pull_request_number=pull_request_number,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_base_sha=base_sha,
        expected_head_sha=head_sha,
        target=target.resolve(),
    )


def _record_fingerprint(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _registry_preflight(request: RecoveryRequest) -> RegistryProof:
    state = registry.load_state(request.state_path)
    records = state.get("records", [])
    if not isinstance(records, list):
        raise ReanchorRefused("registry records are malformed")

    live_records = [
        item
        for item in records
        if isinstance(item, dict) and item.get("status") in ELIGIBLE_STATUSES
    ]
    lane_matches: list[dict[str, Any]] = []
    branch_matches: list[dict[str, Any]] = []
    for item in live_records:
        if not isinstance(item, dict):
            continue
        try:
            external_ids = registry._legacy_external_ids(item)
        except (TypeError, ValueError):
            external_ids = []
        if request.lane_id in external_ids:
            lane_matches.append(item)
        if item.get("branch") == request.branch:
            branch_matches.append(item)
    if (
        len(lane_matches) != 1
        or len(branch_matches) != 1
        or lane_matches[0] is not branch_matches[0]
    ):
        raise ReanchorRefused(
            "published recovery requires one unambiguous registry claim",
            lane_matches=len(lane_matches),
            branch_matches=len(branch_matches),
        )
    record = lane_matches[0]
    if record.get("status") not in ELIGIBLE_STATUSES:
        raise ReanchorRefused("registry claim is not published or cleanup_pending")
    if record.get("external_ids") != [request.lane_id]:
        raise ReanchorRefused("registry external identity differs from the exact lane")
    if record.get("branch") != request.branch:
        raise ReanchorRefused("registry branch differs from the exact recovery claim")
    if record.get("codex_thread_id") != request.owner_thread_id:
        raise ReanchorRefused("registry owner differs from the exact recovery claim")
    if record.get("claim_generation") != request.claim_generation:
        raise ReanchorRefused(
            "registry claim generation differs from the exact recovery claim"
        )
    if record.get("base_sha") != request.expected_base_sha:
        raise ReanchorRefused("registry base differs from the exact recovery claim")
    if record.get("handed_back_sha") != request.expected_head_sha:
        raise ReanchorRefused("registry handback HEAD differs from the exact PR HEAD")
    if record.get("handback_claim_generation") != request.claim_generation:
        raise ReanchorRefused(
            "registry handback generation differs from the exact claim"
        )
    if not registry._has_valid_stored_handback(record):
        raise ReanchorRefused("registry claim lacks a valid immutable handback seal")
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        raise ReanchorRefused("registry handback seal is missing")
    expected_seal = {
        "schema": "kg.worktree.handback.v1",
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "external_ids": [request.lane_id],
        "base_sha": request.expected_base_sha,
        "tip_sha": request.expected_head_sha,
    }
    for key, expected in expected_seal.items():
        if seal.get(key) != expected:
            raise ReanchorRefused(
                f"registry handback seal {key} differs from the exact claim"
            )
    initial_holds = seal.get("initial_holds", [])
    if initial_holds:
        raise ReanchorRefused("published remote recovery refuses P0/P1/security holds")
    digest = seal.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ReanchorRefused("registry handback seal digest is missing")
    origin_main_sha = seal.get("origin_main_sha")
    if (
        origin_main_sha is not None
        and COMMIT_SHA_RE.fullmatch(str(origin_main_sha)) is None
    ):
        raise ReanchorRefused("registry handback origin/main evidence is malformed")
    recorded_path = Path(str(record.get("path") or "")).expanduser().resolve()
    if not str(record.get("path") or "").strip() or not recorded_path.is_absolute():
        raise ReanchorRefused("registry recorded worktree path is malformed")
    declared = declared_operations(record.get("scope"))
    return RegistryProof(
        record=record,
        fingerprint=_record_fingerprint(record),
        recorded_path=recorded_path,
        base_sha=request.expected_base_sha,
        declared=declared,
        handback_digest=digest,
        origin_main_sha=str(origin_main_sha) if origin_main_sha is not None else None,
    )


def _snapshot_key(snapshot: PullRequestSnapshot) -> tuple[object, ...]:
    return (
        snapshot.number,
        snapshot.branch,
        snapshot.base_sha,
        snapshot.head_sha,
        snapshot.state,
        snapshot.draft,
        snapshot.mergeable,
        snapshot.base_branch,
        snapshot.title,
        snapshot.body,
        snapshot.auto_merge_enabled,
        snapshot.node_id,
        snapshot.labels,
    )


def _read_exact_pr(
    github: RecoveryGitHubPort,
    *,
    request: RecoveryRequest,
    proof: RegistryProof,
) -> PullRequestProof:
    pull_request = github.get_pull_request(request.pull_request_number)
    if pull_request.number != request.pull_request_number:
        raise ReanchorRefused("explicit PR readback returned a different PR")
    if pull_request.state != "OPEN" or pull_request.draft:
        raise ReanchorRefused("recovery requires an OPEN non-draft PR")
    if pull_request.base_branch != "main":
        raise ReanchorRefused("recovery requires PR target main")
    if pull_request.branch != request.branch:
        raise ReanchorRefused("PR branch differs from the exact recovery claim")
    if pull_request.base_sha != request.expected_base_sha:
        raise ReanchorRefused("PR base differs from the exact recovery claim")
    if pull_request.head_sha != request.expected_head_sha:
        raise ReanchorRefused("PR HEAD differs from the exact recovery claim")
    if pull_request.auto_merge_enabled:
        raise ReanchorRefused("recovery refuses native queue or auto-merge ownership")

    history = github.list_pull_requests_for_branch(request.branch)
    if history.problems or len(history.records) != 1:
        raise ReanchorRefused(
            "PR branch history must map to exactly one unambiguous PR",
            matches=len(history.records),
        )
    history_pr = history.records[0]
    if history_pr.number != request.pull_request_number:
        raise ReanchorRefused("PR history does not match the explicit PR number")
    if _snapshot_key(history_pr) != _snapshot_key(pull_request):
        raise ReanchorRefused("PR history readback differs from the exact PR")

    queue_entry = github.merge_queue_entry_snapshot(pull_request.node_id)
    if queue_entry is not None:
        raise ReanchorRefused("recovery refuses native merge queue ownership")
    try:
        holds = pull_request_holds(pull_request)
    except Exception as exc:
        raise ReanchorRefused(f"PR hold evidence is malformed: {exc}") from exc
    if holds:
        raise ReanchorRefused("published remote recovery refuses P0/P1/security holds")
    try:
        receipt = parse_pull_request_body(pull_request.body)
    except Exception as exc:
        raise ReanchorRefused(f"PR body is not an exact typed handback: {exc}") from exc
    expected_scope = proof.declared
    actual_scope = tuple(
        sorted((item.path, item.operation.value) for item in receipt.scope.files)
    )
    if (
        receipt.lane_id != request.lane_id
        or receipt.owner_thread_id != request.owner_thread_id
        or receipt.claim_generation != request.claim_generation
        or receipt.branch != request.branch
        or Path(receipt.worktree_path).expanduser().resolve() != proof.recorded_path
        or receipt.base_sha != request.expected_base_sha
        or receipt.head_sha != request.expected_head_sha
        or receipt.content_digest != proof.handback_digest
        or actual_scope != expected_scope
    ):
        raise ReanchorRefused(
            "PR body typed receipt differs from the immutable registry claim"
        )
    if (
        proof.origin_main_sha is not None
        and receipt.origin_main_sha != proof.origin_main_sha
    ):
        raise ReanchorRefused(
            "PR receipt origin/main differs from the immutable handback seal"
        )
    changed_paths = tuple(sorted(github.changed_paths(request.pull_request_number)))
    if changed_paths != tuple(sorted(path for path, _ in expected_scope)):
        raise ReanchorRefused(
            "PR changed paths differ from the immutable registry Scope"
        )
    return PullRequestProof(
        snapshot=pull_request,
        body_sha256=hashlib.sha256(pull_request.body.encode("utf-8")).hexdigest(),
    )


class RecoveryGit:
    """Git-only implementation; GitHub is queried through a read-only port."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo.resolve()

    def validate_repository(self) -> None:
        git_ops.validate_repository(self.repo)

    def remote_branch_sha(self, branch: str) -> str | None:
        ref = f"refs/heads/{branch}"
        rc, output = git_ops._git(["ls-remote", "--heads", "origin", ref], self.repo)
        if rc != 0:
            raise ReanchorRefused(
                "remote branch ref cannot be read", ref=ref, git=output
            )
        rows = [line.split() for line in output.splitlines() if line.strip()]
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
            raise ReanchorRefused(
                "remote branch ref readback is malformed", ref=ref, rows=rows
            )
        return commit_sha(rows[0][0], label=f"remote {ref}")

    def live_main_sha(self) -> str:
        observed = self.remote_branch_sha("main")
        if observed is None:
            raise ReanchorRefused("live origin/main is absent")
        return observed

    def validate_released_assets(
        self, *, recorded_path: Path, target: Path, branch: str
    ) -> None:
        from . import resume_git_ops

        resume_git_ops.validate_released_assets(
            self.repo,
            recorded_path=recorded_path,
            target=target,
            branch=branch,
        )

    def fetch_pr_head(self, *, pull_request_number: int, expected_head: str) -> str:
        rc, output = git_ops._git(
            [
                "fetch",
                "--quiet",
                "--no-tags",
                "origin",
                f"refs/pull/{pull_request_number}/head",
            ],
            self.repo,
        )
        if rc != 0:
            raise ReanchorRefused(
                "immutable PR head ref could not be fetched", git=output
            )
        rc, fetched = git_ops._git(
            ["rev-parse", "--verify", "FETCH_HEAD^{commit}"], self.repo
        )
        if rc != 0 or fetched != expected_head:
            raise ReanchorRefused(
                "immutable PR head ref differs from the exact PR readback",
                fetched_head=fetched,
                expected_head=expected_head,
            )
        return fetched

    def validate_source(
        self, *, base_sha: str, head_sha: str, declared: DeclaredOperations
    ) -> None:
        for label, sha in (("original base", base_sha), ("PR HEAD", head_sha)):
            rc, output = git_ops._git(
                ["cat-file", "-e", f"{sha}^{{commit}}"], self.repo
            )
            if rc != 0:
                raise ReanchorRefused(f"{label} commit is unavailable", git=output)
        if (
            git_ops._git(
                ["merge-base", "--is-ancestor", base_sha, head_sha], self.repo
            )[0]
            != 0
        ):
            raise ReanchorRefused(
                "original base is not an ancestor of the exact PR HEAD"
            )
        if (
            git_ops.scope_operations(self.repo, start=base_sha, end=head_sha)
            != declared
        ):
            raise ReanchorRefused("PR head differs from the immutable registry Scope")

    def provision_exact(
        self,
        *,
        target: Path,
        branch: str,
        head_sha: str,
        base_sha: str,
        declared: DeclaredOperations,
        attempt: RecoveryAttempt,
    ) -> None:
        rc, output = git_ops._git(
            ["worktree", "add", "--detach", str(target), head_sha], self.repo
        )
        if rc != 0:
            raise ReanchorRefused(
                "temporary recovery worktree creation failed", git=output
            )
        attempt.target_created = True
        rc, output = git_ops._git(["switch", "-c", branch], target)
        if git_ops._local_branch_sha(self.repo, branch) == head_sha:
            attempt.branch_created = True
        if rc != 0:
            raise ReanchorRefused(
                "temporary recovery branch creation failed", git=output
            )
        self.validate_local_exact(target=target, branch=branch, expected_head=head_sha)
        if git_ops.scope_operations(target, start=base_sha, end=head_sha) != declared:
            raise ReanchorRefused(
                "temporary recovery branch differs from the immutable Scope"
            )

    def validate_local_exact(
        self, *, target: Path, branch: str, expected_head: str
    ) -> None:
        branch_rc, current_branch = git_ops._git(["branch", "--show-current"], target)
        head_rc, current_head = git_ops._git(
            ["rev-parse", "--verify", "HEAD^{commit}"], target
        )
        status_rc, status = git_ops._git(
            ["status", "--porcelain=v1", "--untracked-files=all"], target
        )
        if (
            branch_rc != 0
            or current_branch != branch
            or head_rc != 0
            or current_head != expected_head
            or status_rc != 0
            or status
        ):
            raise ReanchorRefused(
                "temporary recovery assets failed exact branch/clean/HEAD readback"
            )

    def push_empty_lease(
        self,
        *,
        target: Path,
        branch: str,
        expected_head: str,
        attempt: RecoveryAttempt,
    ) -> None:
        self.validate_local_exact(
            target=target, branch=branch, expected_head=expected_head
        )
        if self.remote_branch_sha(branch) is not None:
            raise ReanchorRefused(
                "remote branch appeared before the empty remote lease"
            )
        ref = f"refs/heads/{branch}"
        rc, output = git_ops._git(
            [
                "push",
                "origin",
                f"--force-with-lease={ref}:",
                f"{expected_head}:{ref}",
            ],
            target,
        )
        if rc != 0:
            raise ReanchorRefused("empty remote lease push failed", git=output)
        # The push command's success is the ownership boundary.  Any later
        # readback failure must retain this fact so compensation may use the
        # exact-head CAS delete, while still refusing a raced ref.
        attempt.remote_created_by_attempt = True
        observed = self.remote_branch_sha(branch)
        if observed != expected_head:
            raise ReanchorRefused(
                "remote branch readback differs after empty lease push",
                observed_remote_head=observed,
                expected_remote_head=expected_head,
            )

    def remove_local_assets(
        self, *, target: Path, branch: str, expected_head: str
    ) -> None:
        self.validate_local_exact(
            target=target, branch=branch, expected_head=expected_head
        )
        rc, output = git_ops._git(["worktree", "remove", "--", str(target)], self.repo)
        if rc != 0:
            raise ReanchorRefused(
                "temporary recovery worktree cleanup failed", git=output
            )
        if any(
            Path(row.get("worktree", "")).resolve() == target
            for row in self._worktree_rows()
        ):
            raise ReanchorRefused("temporary recovery worktree remained after cleanup")
        if git_ops._local_branch_sha(self.repo, branch) != expected_head:
            raise ReanchorRefused(
                "temporary recovery local branch changed before cleanup"
            )
        rc, output = git_ops._git(
            ["update-ref", "-d", f"refs/heads/{branch}", expected_head], self.repo
        )
        if rc != 0 or git_ops._local_branch_sha(self.repo, branch) is not None:
            raise ReanchorRefused(
                "temporary recovery local branch cleanup failed", git=output
            )

    def _worktree_rows(self) -> list[dict[str, str]]:
        return _worktree_rows(self.repo)

    def compensate_local_assets(
        self,
        *,
        target: Path,
        branch: str,
        expected_head: str,
        attempt: RecoveryAttempt,
    ) -> dict[str, object]:
        steps: list[dict[str, object]] = []
        if attempt.target_created:
            rows = [
                row
                for row in self._worktree_rows()
                if Path(row.get("worktree", "")).resolve() == target
            ]
            if len(rows) == 1 and rows[0].get("branch") == f"refs/heads/{branch}":
                head_rc, head = git_ops._git(
                    ["rev-parse", "--verify", "HEAD^{commit}"], target
                )
                status_rc, status = git_ops._git(
                    ["status", "--porcelain=v1", "--untracked-files=all"], target
                )
                if (
                    head_rc == 0
                    and head == expected_head
                    and status_rc == 0
                    and not status
                ):
                    rc, output = git_ops._git(
                        ["worktree", "remove", "--force", str(target)], self.repo
                    )
                    steps.append(
                        {"action": "worktree-remove", "rc": rc, "output": output}
                    )
        if (
            attempt.branch_created
            and git_ops._local_branch_sha(self.repo, branch) == expected_head
        ):
            rc, output = git_ops._git(
                ["update-ref", "-d", f"refs/heads/{branch}", expected_head], self.repo
            )
            steps.append({"action": "local-branch-delete", "rc": rc, "output": output})
        rows_remaining = any(
            Path(row.get("worktree", "")).resolve() == target
            for row in self._worktree_rows()
        )
        branch_remaining = git_ops._local_branch_sha(self.repo, branch) is not None
        return {
            "complete": not rows_remaining
            and not os.path.lexists(target)
            and not branch_remaining,
            "path_remaining": os.path.lexists(target),
            "branch_remaining": branch_remaining,
            "steps": steps,
        }

    def delete_remote_exact(self, *, branch: str, expected_head: str) -> None:
        observed = self.remote_branch_sha(branch)
        if observed is None:
            return
        if observed != expected_head:
            raise ReanchorRefused("remote branch drifted before exact compensation")
        ref = f"refs/heads/{branch}"
        rc, output = git_ops._git(
            ["push", "origin", f"--force-with-lease={ref}:{expected_head}", f":{ref}"],
            self.repo,
        )
        if rc != 0 or self.remote_branch_sha(branch) is not None:
            raise ReanchorRefused("remote compensation failed", git=output)


def _worktree_rows(repo: Path) -> list[dict[str, str]]:
    rc, output = git_ops._git(["worktree", "list", "--porcelain"], repo)
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


def _compensate(
    git: RecoveryGitPort,
    *,
    request: RecoveryRequest,
    attempt: RecoveryAttempt,
) -> dict[str, object]:
    try:
        local = git.compensate_local_assets(
            target=request.target,
            branch=request.branch,
            expected_head=request.expected_head_sha,
            attempt=attempt,
        )
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        local = {
            "complete": False,
            "reason": f"local compensation failed: {type(exc).__name__}: {exc}",
        }
    remote: dict[str, object] = {
        "complete": True,
        "created_by_attempt": attempt.remote_created_by_attempt,
    }
    if attempt.remote_created_by_attempt:
        try:
            git.delete_remote_exact(
                branch=request.branch,
                expected_head=request.expected_head_sha,
            )
        except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
            remote = {
                "complete": False,
                "created_by_attempt": True,
                "reason": f"remote compensation failed: {type(exc).__name__}: {exc}",
            }
    return {
        "complete": bool(local.get("complete")) and bool(remote.get("complete")),
        "local": local,
        "remote": remote,
    }


def _same_registry(before: RegistryProof, after: RegistryProof) -> None:
    if before.fingerprint != after.fingerprint:
        raise ReanchorRefused("registry claim changed during published remote recovery")


def perform_recovery(
    *,
    repo: Path,
    state_path: Path,
    pull_request_number: int,
    lane_id: str,
    branch: str,
    owner_thread_id: str,
    claim_generation: int,
    expected_base_sha: str,
    expected_head_sha: str,
    target: Path,
    git: RecoveryGitPort | None = None,
    github: RecoveryGitHubPort | None = None,
) -> dict[str, object]:
    request = build_request(
        repo=repo,
        state_path=state_path,
        pull_request_number=pull_request_number,
        lane_id=lane_id,
        branch=branch,
        owner_thread_id=owner_thread_id,
        claim_generation=claim_generation,
        expected_base_sha=expected_base_sha,
        expected_head_sha=expected_head_sha,
        target=target,
    )
    git_port = git or RecoveryGit(request.repo)
    github_port = github or GitHubCliAdapter(repo=request.repo)
    git_port.validate_repository()
    initial_registry = _registry_preflight(request)
    git_port.validate_released_assets(
        recorded_path=initial_registry.recorded_path,
        target=request.target,
        branch=request.branch,
    )
    if git_port.remote_branch_sha(request.branch) is not None:
        raise ReanchorRefused(
            "published remote recovery requires an explicitly absent remote branch"
        )
    initial_pr = _read_exact_pr(github_port, request=request, proof=initial_registry)
    initial_live_main = git_port.live_main_sha()
    fetched_head = git_port.fetch_pr_head(
        pull_request_number=request.pull_request_number,
        expected_head=request.expected_head_sha,
    )
    if fetched_head != request.expected_head_sha:
        raise ReanchorRefused("immutable PR head fetch differs from exact PR proof")
    git_port.validate_source(
        base_sha=initial_registry.base_sha,
        head_sha=request.expected_head_sha,
        declared=initial_registry.declared,
    )
    attempt = RecoveryAttempt()
    try:
        before_push_registry = _registry_preflight(request)
        _same_registry(initial_registry, before_push_registry)
        if git_port.live_main_sha() != initial_live_main:
            raise ReanchorRefused("live origin/main changed before empty remote lease")
        if git_port.remote_branch_sha(request.branch) is not None:
            raise ReanchorRefused("remote branch appeared before empty remote lease")
        before_push_pr = _read_exact_pr(
            github_port, request=request, proof=before_push_registry
        )
        if _snapshot_key(before_push_pr.snapshot) != _snapshot_key(initial_pr.snapshot):
            raise ReanchorRefused("PR readback changed before empty remote lease")
        git_port.validate_released_assets(
            recorded_path=before_push_registry.recorded_path,
            target=request.target,
            branch=request.branch,
        )
        git_port.provision_exact(
            target=request.target,
            branch=request.branch,
            head_sha=request.expected_head_sha,
            base_sha=before_push_registry.base_sha,
            declared=before_push_registry.declared,
            attempt=attempt,
        )
        git_port.validate_local_exact(
            target=request.target,
            branch=request.branch,
            expected_head=request.expected_head_sha,
        )
        # The lease is intentionally the last pre-push action after all exact facts.
        before_push_registry = _registry_preflight(request)
        _same_registry(initial_registry, before_push_registry)
        if git_port.live_main_sha() != initial_live_main:
            raise ReanchorRefused("live origin/main changed before empty remote lease")
        if git_port.remote_branch_sha(request.branch) is not None:
            raise ReanchorRefused("remote branch appeared before empty remote lease")
        before_push_pr = _read_exact_pr(
            github_port, request=request, proof=before_push_registry
        )
        if _snapshot_key(before_push_pr.snapshot) != _snapshot_key(initial_pr.snapshot):
            raise ReanchorRefused("PR readback changed before empty remote lease")
        git_port.push_empty_lease(
            target=request.target,
            branch=request.branch,
            expected_head=request.expected_head_sha,
            attempt=attempt,
        )
        if git_port.remote_branch_sha(request.branch) != request.expected_head_sha:
            raise ReanchorRefused("remote branch did not read back at exact PR HEAD")
        final_pr = _read_exact_pr(github_port, request=request, proof=initial_registry)
        if _snapshot_key(final_pr.snapshot) != _snapshot_key(initial_pr.snapshot):
            raise ReanchorRefused("PR readback changed after remote recovery")
        final_registry = _registry_preflight(request)
        _same_registry(initial_registry, final_registry)
        if git_port.live_main_sha() != initial_live_main:
            raise ReanchorRefused("live origin/main changed after remote recovery")
        git_port.remove_local_assets(
            target=request.target,
            branch=request.branch,
            expected_head=request.expected_head_sha,
        )
        if git_port.remote_branch_sha(request.branch) != request.expected_head_sha:
            raise ReanchorRefused("remote recovery branch changed after local cleanup")
    except (OSError, ReanchorRefused, TypeError, ValueError) as exc:
        compensation = _compensate(git_port, request=request, attempt=attempt)
        details = dict(exc.details) if isinstance(exc, ReanchorRefused) else {}
        details["compensation"] = compensation
        reason = (
            exc.reason
            if isinstance(exc, ReanchorRefused)
            else f"recovery source error: {type(exc).__name__}: {exc}"
        )
        raise ReanchorRefused(reason, **details) from exc
    return {
        "schema": SCHEMA,
        "action": "recover-published-remote",
        "status": "recovered",
        "pull_request": request.pull_request_number,
        "lane": request.lane_id,
        "branch": request.branch,
        "owner_thread_id": request.owner_thread_id,
        "claim_generation": request.claim_generation,
        "base_sha": request.expected_base_sha,
        "head": request.expected_head_sha,
        "live_main": initial_live_main,
        "remote_branch": request.branch,
        "remote_branch_sha": request.expected_head_sha,
        "worktree": str(request.target),
        "worktree_absent": True,
        "local_branch_absent": True,
        "registry_mutated": False,
        "pr_body_sha256": initial_pr.body_sha256,
        "handback_digest": initial_registry.handback_digest,
        "scope": [path for path, _ in initial_registry.declared],
        "next_action": "keep the recovered remote branch and exact PR in the durable queue",
    }


def _emit(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("status") == "recovered":
        print(
            f"✓ recovered PR #{payload['pull_request']} remote branch {payload['branch']}"
        )
    else:
        print(
            f"✗ recover-published-remote refused: {payload.get('reason', 'unknown reason')}"
        )


def cmd_recover(args: Any, *, freeze_reason: str | None = None) -> int:
    if freeze_reason:
        payload = {
            "schema": SCHEMA,
            "action": "recover-published-remote",
            "status": "blocked",
            "reason": freeze_reason,
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    state_path = (
        Path(args.state).expanduser().resolve()
        if args.state
        else registry.default_state_path()
    )
    try:
        payload = perform_recovery(
            repo=Path(args.repo).expanduser().resolve(),
            state_path=state_path,
            pull_request_number=args.pull_request_number,
            lane_id=args.lane,
            branch=args.branch,
            owner_thread_id=args.owner_thread_id,
            claim_generation=args.claim_generation,
            expected_base_sha=args.expected_base,
            expected_head_sha=args.expected_head,
            target=Path(args.path).expanduser().resolve(),
        )
    except ReanchorRefused as exc:
        payload = {
            "schema": SCHEMA,
            "action": "recover-published-remote",
            "status": "blocked",
            "reason": exc.reason,
            **exc.details,
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    except (OSError, TypeError, ValueError) as exc:
        payload = {
            "schema": SCHEMA,
            "action": "recover-published-remote",
            "status": "blocked",
            "reason": f"recovery source error: {type(exc).__name__}: {exc}",
        }
        _emit(payload, as_json=args.json)
        return EXIT_BLOCK
    _emit(payload, as_json=args.json)
    return EXIT_OK


def add_parser(
    subparsers: Any,
    *,
    common: Any,
    handler: Any,
    default_repo: Path,
) -> Any:
    parser = subparsers.add_parser(
        "recover-published-remote",
        help="recover one published claim whose remote branch is explicitly absent",
    )
    common(parser)
    parser.add_argument("--repo", default=str(default_repo))
    parser.add_argument("--pr", dest="pull_request_number", type=int, required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--owner-thread-id", required=True)
    parser.add_argument("--claim-generation", type=int, required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--path", required=True)
    parser.set_defaults(func=handler)
    return parser

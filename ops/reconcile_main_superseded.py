#!/usr/bin/env -S uv run --python 3.13
"""Fail-closed reconciliation for an equivalent merged change on local main."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from delivery_control.adapters.git_cli import GitCliAdapter
from delivery_control.adapters.git_client import GitCliClient
from delivery_control.adapters.git_parsing import parse_changed_files
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.github_client import GitHubCliClient
from delivery_control.adapters.registry import RegistryCliAdapter
from delivery_control.adapters.subprocess_runner import SubprocessCommandRunner
from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    PhysicalWorktree,
    RegistryInventory,
    RegistrySnapshot,
)
from delivery_control.ports.process import CommandRunnerPort

SCHEMA = "kg.delivery.main-reconcile.v1"
ACTION = "park-superseded-local-main"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ReconcileBlocked(Exception):
    """A deterministic fail-closed preflight or CAS refusal."""

    def __init__(self, reason: str, *, phase: str = "preflight") -> None:
        self.reason = reason
        self.phase = phase
        super().__init__(reason)


@dataclass(frozen=True)
class ReconcileRequest:
    repo: Path
    expected_local_main_head: str
    expected_origin_main_sha: str
    merged_pr_number: int
    merged_source_head_sha: str
    merged_source_parent_sha: str
    branch: str
    owner_thread: str
    external_id: str
    expected_fingerprint: str
    operator: str
    reason: str


@dataclass(frozen=True)
class CommitIdentity:
    sha: str
    parents: tuple[str, ...]
    changes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PullRequestEvidence:
    number: int
    branch: str
    base_branch: str
    base_sha: str
    head_sha: str
    state: str
    merge_commit_sha: str | None
    merged_at: str | None
    changed_paths: tuple[str, ...] = ()
    url: str = ""


class GitReadPort(Protocol):
    def canonical_checkout(self) -> CanonicalCheckoutSnapshot: ...

    def origin_main_sha(self) -> str: ...

    def commit_identity(self, sha: str) -> CommitIdentity: ...

    def normalized_patch_fingerprint(self, base_sha: str, head_sha: str) -> str: ...

    def patch_id(self, base_sha: str, head_sha: str) -> str: ...

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool: ...

    def remote_branch_sha(self, branch: str) -> str | None: ...

    def pr_ref_sha(self, number: int) -> str | None: ...

    def local_branch_sha(self, branch: str) -> str | None: ...

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]: ...


class GitParkPort(Protocol):
    def park_main_to_origin(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str: ...


class GitHubReadPort(Protocol):
    def get_pull_request(self, number: int) -> PullRequestEvidence: ...

    def list_pull_requests_for_branch(
        self, branch: str
    ) -> tuple[PullRequestEvidence, ...]: ...


class RegistryReadPort(Protocol):
    def list_records(self) -> RegistryInventory: ...


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ReconcileBlocked(f"{field} is required")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ReconcileBlocked(f"{field} contains control characters")
    return value.strip()


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise ReconcileBlocked(f"{field} must be a lowercase 40-character SHA")
    return value


def _fingerprint(value: object) -> str:
    if type(value) is not str or _FINGERPRINT_RE.fullmatch(value) is None:
        raise ReconcileBlocked(
            "expected fingerprint must be a lowercase 40- or 64-character digest"
        )
    return value


def _clean_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    return detail or error.__class__.__name__


def _changes(value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(value))


def _scope_changes(record: RegistrySnapshot) -> tuple[tuple[str, str], ...]:
    return _changes(
        tuple((item.path, item.operation.value) for item in record.scope.files)
    )


def _change_payload(changes: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    return [
        {"path": path, "operation": operation} for path, operation in _changes(changes)
    ]


def _before_payload(checkout: CanonicalCheckoutSnapshot) -> dict[str, object]:
    return {
        "path": str(checkout.path.resolve()),
        "branch": checkout.branch,
        "clean": checkout.clean,
        "local_main_head": checkout.head_sha,
    }


def _validate_request(request: ReconcileRequest) -> None:
    if not request.repo.is_absolute():
        raise ReconcileBlocked("repo must be an absolute canonical checkout path")
    local = _sha(request.expected_local_main_head, "expected local main HEAD")
    origin = _sha(request.expected_origin_main_sha, "expected origin/main SHA")
    if local == origin:
        raise ReconcileBlocked("local main and origin/main must be distinct")
    _sha(request.merged_source_head_sha, "merged source HEAD SHA")
    _sha(request.merged_source_parent_sha, "merged source parent SHA")
    if type(request.merged_pr_number) is not int or request.merged_pr_number <= 0:
        raise ReconcileBlocked("merged PR number must be positive")
    branch = _text(request.branch, "exact branch")
    if branch == "main" or branch.startswith("-"):
        raise ReconcileBlocked("exact branch must not be canonical main")
    _text(request.owner_thread, "owner thread")
    _text(request.external_id, "external-id")
    _fingerprint(request.expected_fingerprint)
    _text(request.operator, "operator")
    _text(request.reason, "reason")


class SupersededMainReconciler:
    """Validate immutable evidence, then invoke one exact main CAS park."""

    def __init__(
        self,
        git: GitReadPort,
        github: GitHubReadPort,
        registry: RegistryReadPort,
        command: GitParkPort,
    ) -> None:
        self.git = git
        self.github = github
        self.registry = registry
        self.command = command

    def _registry_record(
        self,
        request: ReconcileRequest,
        *,
        local: CommitIdentity,
        source: CommitIdentity,
    ) -> RegistrySnapshot:
        try:
            inventory = self.registry.list_records()
        except Exception as error:
            raise ReconcileBlocked(
                f"registry source problem: {_clean_error(error)}"
            ) from error
        if inventory.problems:
            reasons = "; ".join(problem.reason for problem in inventory.problems)
            raise ReconcileBlocked(f"registry source problem: {reasons}")

        branch_matches = [
            record for record in inventory.records if record.branch == request.branch
        ]
        external_matches = [
            record
            for record in inventory.records
            if request.external_id in record.external_ids
            or record.lane_id == request.external_id
        ]
        if len(branch_matches) != 1 or len(external_matches) != 1:
            raise ReconcileBlocked(
                "registry duplicate or missing exact branch/external-id evidence"
            )
        record = branch_matches[0]
        if external_matches[0] != record:
            raise ReconcileBlocked(
                "registry branch and external-id identify different lanes"
            )
        if record.lane_id != request.external_id:
            raise ReconcileBlocked("registry lane identity differs from external-id")
        if len(record.external_ids) != len(set(record.external_ids)):
            raise ReconcileBlocked("registry external-id evidence is duplicated")
        if record.owner_thread_id is None:
            raise ReconcileBlocked("registry owner is missing")
        if record.owner_thread_id != request.owner_thread:
            raise ReconcileBlocked("registry owner differs from owner thread")
        if record.status not in {"published", "merged", "abandoned"}:
            raise ReconcileBlocked(
                "registry lane is not published or terminal; active ownership is not parkable"
            )
        if not record.handback_valid or record.handed_back_sha is None:
            raise ReconcileBlocked("registry lane lacks a valid typed handback")
        if record.handed_back_sha != request.expected_local_main_head:
            raise ReconcileBlocked(
                "registry typed handback differs from expected local main HEAD"
            )
        if record.handback_claim_generation != record.claim_generation:
            raise ReconcileBlocked(
                "registry handback generation differs from claim generation"
            )
        if record.handback_digest is None:
            raise ReconcileBlocked("registry typed handback digest is missing")
        if record.published_base_sha is not None and (
            record.published_base_sha != request.merged_source_parent_sha
        ):
            raise ReconcileBlocked(
                "registry published base differs from merged source parent"
            )
        if record.status == "published" and record.published_base_sha is None:
            raise ReconcileBlocked(
                "published registry lane lacks published-base evidence"
            )
        expected_changes = _changes(source.changes)
        if _scope_changes(record) != expected_changes:
            raise ReconcileBlocked("registry Scope differs from merged source Scope")
        try:
            physical = self.git.list_worktrees()
        except Exception as error:
            raise ReconcileBlocked(
                f"physical worktree source problem: {_clean_error(error)}"
            ) from error
        if any(
            item.branch == record.branch or item.path.resolve() == record.path.resolve()
            for item in physical
        ):
            raise ReconcileBlocked(
                "published or terminal registry lane still has a physical worktree"
            )
        return record

    def _preflight(self, request: ReconcileRequest) -> dict[str, object]:
        try:
            checkout = self.git.canonical_checkout()
        except Exception as error:
            raise ReconcileBlocked(
                f"canonical checkout source problem: {_clean_error(error)}"
            ) from error
        before = _before_payload(checkout)
        if checkout.path.resolve() != request.repo.resolve():
            raise ReconcileBlocked("canonical checkout path differs from repo")
        if checkout.branch != "main" or not checkout.clean:
            raise ReconcileBlocked("canonical checkout must be clean and on main")
        if checkout.head_sha != request.expected_local_main_head:
            raise ReconcileBlocked(
                "canonical main HEAD differs from expected local main HEAD"
            )
        try:
            live_origin = self.git.origin_main_sha()
        except Exception as error:
            raise ReconcileBlocked(
                f"origin/main source problem: {_clean_error(error)}"
            ) from error
        if live_origin != request.expected_origin_main_sha:
            raise ReconcileBlocked("origin/main changed from expected SHA")

        try:
            local = self.git.commit_identity(request.expected_local_main_head)
        except Exception as error:
            raise ReconcileBlocked(
                f"local build-12 source problem: {_clean_error(error)}"
            ) from error
        if local.sha != request.expected_local_main_head:
            raise ReconcileBlocked("local build-12 commit identity differs from input")
        if len(local.parents) != 1:
            raise ReconcileBlocked("local build-12 commit must have exactly one parent")

        try:
            source = self.git.commit_identity(request.merged_source_head_sha)
        except Exception as error:
            raise ReconcileBlocked(
                f"merged source problem: {_clean_error(error)}"
            ) from error
        if source.sha != request.merged_source_head_sha:
            raise ReconcileBlocked("merged source commit identity differs from input")
        if len(source.parents) != 1:
            raise ReconcileBlocked("merged source commit must have exactly one parent")
        if source.parents[0] != request.merged_source_parent_sha:
            raise ReconcileBlocked("merged source immediate parent differs from input")

        local_changes = _changes(local.changes)
        source_changes = _changes(source.changes)
        if local_changes != source_changes:
            raise ReconcileBlocked("local and merged source changed Scope differs")

        try:
            local_normalized = self.git.normalized_patch_fingerprint(
                local.parents[0], local.sha
            )
            source_normalized = self.git.normalized_patch_fingerprint(
                source.parents[0], source.sha
            )
            local_patch_id = self.git.patch_id(local.parents[0], local.sha)
            source_patch_id = self.git.patch_id(source.parents[0], source.sha)
        except Exception as error:
            raise ReconcileBlocked(
                f"content fingerprint source problem: {_clean_error(error)}"
            ) from error
        if local_normalized != source_normalized or local_patch_id != source_patch_id:
            raise ReconcileBlocked(
                "local and merged source content fingerprint differs"
            )
        if request.expected_fingerprint not in {
            local_normalized,
            source_normalized,
            local_patch_id,
            source_patch_id,
        }:
            raise ReconcileBlocked(
                "expected content or patch fingerprint does not match"
            )

        try:
            history = self.github.list_pull_requests_for_branch(request.branch)
            pull_request = self.github.get_pull_request(request.merged_pr_number)
        except Exception as error:
            raise ReconcileBlocked(
                f"GitHub PR source problem: {_clean_error(error)}"
            ) from error
        if len(history) != 1 or history[0].number != request.merged_pr_number:
            raise ReconcileBlocked("GitHub PR history is duplicate or not exact")
        if history[0].branch != request.branch:
            raise ReconcileBlocked("GitHub PR history branch differs from exact branch")
        if pull_request.number != request.merged_pr_number:
            raise ReconcileBlocked("GitHub PR number differs from input")
        if pull_request.branch != request.branch:
            raise ReconcileBlocked("GitHub PR head branch differs from exact branch")
        if pull_request.state != "MERGED":
            raise ReconcileBlocked("GitHub PR is not MERGED")
        if pull_request.base_branch != "main":
            raise ReconcileBlocked("GitHub PR base branch is not main")
        if pull_request.base_sha != request.merged_source_parent_sha:
            raise ReconcileBlocked(
                "GitHub PR base SHA differs from merged source parent"
            )
        if pull_request.head_sha != request.merged_source_head_sha:
            raise ReconcileBlocked("GitHub PR head SHA differs from merged source HEAD")
        merge_commit_sha = _sha(pull_request.merge_commit_sha, "GitHub PR merge commit")
        if not _text(pull_request.merged_at, "GitHub PR mergedAt"):
            raise ReconcileBlocked("GitHub PR mergedAt evidence is missing")
        changed_paths = tuple(sorted(pull_request.changed_paths))
        if len(changed_paths) != len(set(changed_paths)):
            raise ReconcileBlocked("GitHub PR changed paths contain duplicates")
        if changed_paths != tuple(sorted(path for path, _ in source_changes)):
            raise ReconcileBlocked("GitHub PR changed Scope differs from source commit")

        try:
            remote_branch = self.git.remote_branch_sha(request.branch)
            pr_ref = self.git.pr_ref_sha(request.merged_pr_number)
            local_branch = self.git.local_branch_sha(request.branch)
        except Exception as error:
            raise ReconcileBlocked(
                f"remote ref source problem: {_clean_error(error)}"
            ) from error
        if (
            remote_branch is not None
            and remote_branch != request.merged_source_head_sha
        ):
            raise ReconcileBlocked("remote branch differs from merged source HEAD")
        if pr_ref != request.merged_source_head_sha:
            raise ReconcileBlocked("immutable PR ref differs from merged source HEAD")
        if (
            local_branch is not None
            and local_branch != request.expected_local_main_head
        ):
            raise ReconcileBlocked(
                "local owner branch differs from expected local main HEAD"
            )

        try:
            if not self.git.is_ancestor(
                request.merged_source_head_sha, request.expected_origin_main_sha
            ):
                raise ReconcileBlocked(
                    "merged source is not an ancestor of live origin/main"
                )
            if not self.git.is_ancestor(
                merge_commit_sha, request.expected_origin_main_sha
            ):
                raise ReconcileBlocked(
                    "PR merge commit is not an ancestor of live origin/main"
                )
        except ReconcileBlocked:
            raise
        except Exception as error:
            raise ReconcileBlocked(
                f"ancestry source problem: {_clean_error(error)}"
            ) from error

        record = self._registry_record(request, local=local, source=source)
        return {
            "before": before,
            "source": {
                "head_sha": source.sha,
                "parent_sha": source.parents[0],
                "changes": _change_payload(source_changes),
                "is_ancestor_of_live_origin": True,
                "merge_commit_is_ancestor_of_live_origin": True,
            },
            "pr": {
                "number": pull_request.number,
                "branch": pull_request.branch,
                "state": pull_request.state,
                "base_branch": pull_request.base_branch,
                "base_sha": pull_request.base_sha,
                "head_sha": pull_request.head_sha,
                "merge_commit_sha": merge_commit_sha,
                "merged_at": pull_request.merged_at,
                "history_count": len(history),
                "remote_branch_sha": remote_branch,
                "pr_ref_sha": pr_ref,
            },
            "owner": {
                "external_id": request.external_id,
                "owner_thread": request.owner_thread,
                "branch": record.branch,
                "path": str(record.path.resolve()),
                "status": record.status,
                "claim_generation": record.claim_generation,
                "handed_back_sha": record.handed_back_sha,
                "handback_digest": record.handback_digest,
                "handback_valid": record.handback_valid,
                "published_base_sha": record.published_base_sha,
                "scope": _change_payload(_scope_changes(record)),
            },
            "fingerprint": {
                "expected": request.expected_fingerprint,
                "local": {
                    "head_sha": local.sha,
                    "parent_sha": local.parents[0],
                    "normalized": local_normalized,
                    "patch_id": local_patch_id,
                },
                "source": {
                    "head_sha": source.sha,
                    "parent_sha": source.parents[0],
                    "normalized": source_normalized,
                    "patch_id": source_patch_id,
                },
            },
            "record": record,
        }

    @staticmethod
    def _blocked(
        request: ReconcileRequest,
        reason: str,
        *,
        phase: str,
        cas_conflict: bool = False,
        evidence: dict[str, object] | None = None,
        park_attempted: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "action": ACTION,
            "verdict": "blocked",
            "dispatchable": False,
            "registry_mutation": False,
            "cas_conflict": cas_conflict,
            "park_attempted": park_attempted,
            "phase": phase,
            "operator": request.operator,
            "reason": reason,
        }
        if evidence:
            payload.update(
                {key: value for key, value in evidence.items() if key != "record"}
            )
        return payload

    def reconcile(self, request: ReconcileRequest) -> dict[str, object]:
        try:
            _validate_request(request)
            evidence = self._preflight(request)
        except ReconcileBlocked as error:
            return self._blocked(
                request,
                error.reason,
                phase=error.phase,
            )
        except Exception as error:  # noqa: BLE001 — all preflight source failures block
            return self._blocked(
                request,
                f"preflight source problem: {_clean_error(error)}",
                phase="preflight",
            )

        try:
            after_sha = self.command.park_main_to_origin(
                expected_local_sha=request.expected_local_main_head,
                expected_origin_sha=request.expected_origin_main_sha,
            )
        except CompareAndSwapConflict as error:
            return self._blocked(
                request,
                f"CAS conflict: {_clean_error(error)}",
                phase="cas",
                cas_conflict=True,
                evidence=evidence,
                park_attempted=True,
            )
        except Exception as error:  # noqa: BLE001 — all CAS failures are terminal
            return self._blocked(
                request,
                f"CAS source problem: {_clean_error(error)}",
                phase="cas",
                evidence=evidence,
                park_attempted=True,
            )
        if after_sha != request.expected_origin_main_sha:
            return self._blocked(
                request,
                "CAS park returned a non-exact origin/main SHA",
                phase="cas-readback",
                cas_conflict=True,
                evidence=evidence,
                park_attempted=True,
            )
        try:
            after_checkout = self.git.canonical_checkout()
            after_origin = self.git.origin_main_sha()
        except Exception as error:  # noqa: BLE001 — post-park uncertainty blocks
            return self._blocked(
                request,
                f"post-park source problem: {_clean_error(error)}",
                phase="cas-readback",
                evidence=evidence,
                park_attempted=True,
            )
        if (
            after_checkout.path.resolve() != request.repo.resolve()
            or after_checkout.branch != "main"
            or not after_checkout.clean
            or after_checkout.head_sha != request.expected_origin_main_sha
            or after_origin != request.expected_origin_main_sha
        ):
            return self._blocked(
                request,
                "canonical main or origin/main drifted after CAS park",
                phase="cas-readback",
                cas_conflict=True,
                evidence=evidence,
                park_attempted=True,
            )
        return {
            "schema": SCHEMA,
            "action": ACTION,
            "verdict": "success",
            "dispatchable": False,
            "registry_mutation": False,
            "operator": request.operator,
            "reason": request.reason,
            "before": evidence["before"],
            "after": _before_payload(after_checkout),
            "source": evidence["source"],
            "pr": evidence["pr"],
            "owner": evidence["owner"],
            "fingerprint": evidence["fingerprint"],
        }


class GitReadAdapter:
    """Compose existing ops Git queries with exact commit/ref evidence."""

    def __init__(self, *, repo: Path, runner: CommandRunnerPort | None = None) -> None:
        self.repo = repo.resolve()
        self.runner = runner or SubprocessCommandRunner()
        self._client = GitCliClient(repo=self.repo, runner=self.runner)
        self._adapter = GitCliAdapter(repo=self.repo, runner=self.runner)

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return self._adapter.canonical_checkout()

    def origin_main_sha(self) -> str:
        return self._adapter.origin_main_sha()

    def commit_identity(self, sha: str) -> CommitIdentity:
        metadata = self._client.run("rev-list", "--parents", "-n", "1", sha)
        fields = metadata.split()
        if (
            not fields
            or fields[0] != sha
            or any(_SHA_RE.fullmatch(parent) is None for parent in fields[1:])
        ):
            raise ValueError("commit identity metadata is malformed")
        if len(fields) == 1:
            changes: tuple[tuple[str, str], ...] = ()
        else:
            payload = self._client.run(
                "diff",
                "--name-status",
                "-z",
                "--find-renames=100%",
                "--find-copies=100%",
                fields[1],
                sha,
            )
            parsed = parse_changed_files(payload)
            changes = _changes(
                tuple((item.path, item.operation.value) for item in parsed)
            )
        return CommitIdentity(sha=sha, parents=tuple(fields[1:]), changes=changes)

    def normalized_patch_fingerprint(self, base_sha: str, head_sha: str) -> str:
        return self._adapter.diff_fingerprint(base_sha, head_sha)

    def patch_id(self, base_sha: str, head_sha: str) -> str:
        diff = self._client.run(
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-color",
            "--unified=0",
            "--find-renames=100%",
            "--find-copies=100%",
            f"{base_sha}..{head_sha}",
        )
        try:
            completed = subprocess.run(
                ("git", "patch-id", "--stable"),
                input=diff,
                text=True,
                capture_output=True,
                check=False,
                cwd=self.repo,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"git patch-id failed: {error}") from error
        if completed.returncode != 0:
            raise RuntimeError(
                f"git patch-id failed: {completed.stderr.strip() or completed.returncode}"
            )
        fields = completed.stdout.split()
        if not fields or _SHA_RE.fullmatch(fields[0]) is None:
            raise ValueError("git patch-id output is malformed")
        return fields[0]

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        return self._adapter.is_ancestor(ancestor_sha, descendant_sha)

    def remote_branch_sha(self, branch: str) -> str | None:
        return self._adapter.remote_branch_sha(branch)

    def pr_ref_sha(self, number: int) -> str | None:
        ref = f"refs/pull/{number}/head"
        result = self._client.execute("ls-remote", "origin", ref)
        if result.exit_code != 0:
            raise RuntimeError(result.stderr.strip() or "PR ref lookup failed")
        lines = [line.split() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        if len(lines) != 1 or len(lines[0]) != 2 or lines[0][1] != ref:
            raise ValueError("PR ref lookup returned malformed evidence")
        return _sha(lines[0][0], "PR ref SHA")

    def local_branch_sha(self, branch: str) -> str | None:
        return self._adapter.local_branch_sha(branch)

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self._adapter.list_worktrees()

    def park_main_to_origin(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        return self._adapter.park_main_to_origin(
            expected_local_sha=expected_local_sha,
            expected_origin_sha=expected_origin_sha,
        )


class GitHubReadAdapter:
    """Read exact PR merge metadata while reusing existing PR query parsing."""

    _FIELDS = (
        "id,number,url,headRefName,baseRefName,baseRefOid,headRefOid,state,isDraft,"
        "mergeable,title,body,autoMergeRequest,labels,createdAt,mergedAt,mergeCommit"
    )

    def __init__(self, *, repo: Path, runner: CommandRunnerPort | None = None) -> None:
        self.repo = repo.resolve()
        self.runner = runner or SubprocessCommandRunner()
        self._client = GitHubCliClient(repo=self.repo, runner=self.runner)
        self._adapter = GitHubCliAdapter(repo=self.repo, runner=self.runner)

    def get_pull_request(self, number: int) -> PullRequestEvidence:
        snapshot = self._adapter.get_pull_request(number)
        payload = self._client.load_json(
            ("gh", "pr", "view", str(number), "--json", self._FIELDS)
        )
        if not isinstance(payload, Mapping):
            raise TypeError("GitHub PR merge payload is malformed")
        raw_merge = payload.get("mergeCommit")
        if raw_merge is None:
            merge_commit = None
        elif isinstance(raw_merge, Mapping) and type(raw_merge.get("oid")) is str:
            merge_commit = raw_merge["oid"]
        else:
            raise ValueError("GitHub PR mergeCommit payload is malformed")
        merged_at = payload.get("mergedAt")
        if merged_at is not None and type(merged_at) is not str:
            raise ValueError("GitHub PR mergedAt payload is malformed")
        changed_paths = tuple(sorted(self._adapter.changed_paths(number)))
        return PullRequestEvidence(
            number=snapshot.number,
            branch=snapshot.branch,
            base_branch=snapshot.base_branch,
            base_sha=snapshot.base_sha,
            head_sha=snapshot.head_sha,
            state=snapshot.state,
            merge_commit_sha=merge_commit,
            merged_at=merged_at,
            changed_paths=changed_paths,
            url=snapshot.url,
        )

    def list_pull_requests_for_branch(
        self, branch: str
    ) -> tuple[PullRequestEvidence, ...]:
        inventory = self._adapter.list_pull_requests_for_branch(branch)
        if inventory.problems:
            raise ValueError(
                "; ".join(problem.reason for problem in inventory.problems)
            )
        return tuple(
            PullRequestEvidence(
                number=item.number,
                branch=item.branch,
                base_branch=item.base_branch,
                base_sha=item.base_sha,
                head_sha=item.head_sha,
                state=item.state,
                merge_commit_sha=None,
                merged_at=(item.merged_at.isoformat() if item.merged_at else None),
                url=item.url,
            )
            for item in inventory.records
        )


def _build_runtime(
    repo: Path,
) -> tuple[GitReadAdapter, GitHubReadAdapter, RegistryCliAdapter, GitReadAdapter]:
    runner = SubprocessCommandRunner()
    git = GitReadAdapter(repo=repo, runner=runner)
    github = GitHubReadAdapter(repo=repo, runner=runner)
    registry = RegistryCliAdapter(
        script_path=repo / "ops" / "worktree_registry.py",
        state_path=repo / ".cache" / "worktree_registry.json",
        runner=runner,
    )
    return git, github, registry, git


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed CAS reconciliation of an equivalent merged local main commit"
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--expected-local-main-head",
        "--expected-local-head",
        dest="expected_local_main_head",
        required=True,
    )
    parser.add_argument(
        "--expected-origin-main-sha",
        "--expected-origin-head",
        dest="expected_origin_main_sha",
        required=True,
    )
    parser.add_argument(
        "--merged-pr-number", "--pr", dest="merged_pr_number", type=int, required=True
    )
    parser.add_argument(
        "--merged-source-head-sha",
        "--source-head-sha",
        dest="merged_source_head_sha",
        required=True,
    )
    parser.add_argument(
        "--merged-source-parent-sha",
        "--source-parent-sha",
        dest="merged_source_parent_sha",
        required=True,
    )
    parser.add_argument("--branch", required=True)
    parser.add_argument(
        "--owner-thread", "--owner-thread-id", dest="owner_thread", required=True
    )
    parser.add_argument("--external-id", required=True)
    parser.add_argument(
        "--expected-fingerprint",
        "--expected-patch-fingerprint",
        dest="expected_fingerprint",
        required=True,
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--json", action="store_true", help="emit the deterministic JSON result"
    )
    return parser


def _blocked_start(request: ReconcileRequest, reason: str) -> dict[str, object]:
    return SupersededMainReconciler._blocked(
        request, reason, phase="source", cas_conflict=False
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = ReconcileRequest(
        repo=Path(args.repo).expanduser().resolve(),
        expected_local_main_head=args.expected_local_main_head,
        expected_origin_main_sha=args.expected_origin_main_sha,
        merged_pr_number=args.merged_pr_number,
        merged_source_head_sha=args.merged_source_head_sha,
        merged_source_parent_sha=args.merged_source_parent_sha,
        branch=args.branch,
        owner_thread=args.owner_thread,
        external_id=args.external_id,
        expected_fingerprint=args.expected_fingerprint,
        operator=args.operator,
        reason=args.reason,
    )
    try:
        git, github, registry, command = _build_runtime(request.repo)
        result = SupersededMainReconciler(git, github, registry, command).reconcile(
            request
        )
    except Exception as error:  # noqa: BLE001 — runtime source failures block
        result = _blocked_start(
            request,
            f"runtime source problem: {_clean_error(error)}",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("verdict") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

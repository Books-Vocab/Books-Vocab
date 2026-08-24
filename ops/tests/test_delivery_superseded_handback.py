from __future__ import annotations

# The test imports the repository's ``ops`` modules after inserting the
# worktree-local module root, matching the existing ops test harness.
# ruff: noqa: E402

from pathlib import Path
import sys

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import PolicyViolation
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.domain.superseded_handback import (
    SUPERSEDED_PROOF_DISPOSITION,
    SUPERSEDED_PROOF_SCHEMA,
    superseded_proof_with_digest,
)
from delivery_control.services.superseded_handback import (
    SupersededHandbackService,
)
from worktree_registry_core.records import normalize_record, superseded_proof_problem


BASE = "a" * 40
HANDBACK = "b" * 40
MERGED_HEAD = "c" * 40
MERGED_BASE = "d" * 40
PATCH = "e" * 64
HAND_BACK_DIGEST = "f" * 64
BRANCH = "debug/redundant"
PATH = Path("/tmp/redundant")
SCOPE = Scope.from_paths(modify=("ops/example.py",))


def _proof() -> dict[str, object]:
    return superseded_proof_with_digest(
        {
            "schema": SUPERSEDED_PROOF_SCHEMA,
            "disposition": SUPERSEDED_PROOF_DISPOSITION,
            "lane_id": "DIRECT-REDUNDANT",
            "branch": BRANCH,
            "handback_sha": HANDBACK,
            "claim_generation": 2,
            "base_sha": BASE,
            "handback_digest": HAND_BACK_DIGEST,
            "merged_pr_number": 42,
            "merged_pr_state": "MERGED",
            "merged_pr_base_branch": "main",
            "merged_pr_branch": BRANCH,
            "merged_pr_head_sha": MERGED_HEAD,
            "merged_pr_base_sha": MERGED_BASE,
            "patch_fingerprint": PATCH,
            "scope_paths": ["ops/example.py"],
            "operator": "supervisor",
            "reason": "current handback is content-equivalent to merged PR",
        }
    )


def _raw_record() -> dict[str, object]:
    return {
        "branch": BRANCH,
        "path": str(PATH),
        "intent": "redundant",
        "base": BASE,
        "base_sha": BASE,
        "status": "abandoned",
        "external_ids": ["DIRECT-REDUNDANT"],
        "scope": {
            "schema": "kg.worktree.scope.v1",
            "files": [{"path": "ops/example.py", "operation": "modify"}],
        },
        "codex_thread_id": "owner",
        "claim_generation": 2,
        "handed_back_sha": HANDBACK,
        "handback_claim_generation": 2,
        "handback_seal": {
            "schema": "kg.worktree.handback.v1",
            "lane_id": "DIRECT-REDUNDANT",
            "owner_thread_id": "owner",
            "claim_generation": 2,
            "branch": BRANCH,
            "worktree_path": str(PATH),
            "base_sha": BASE,
            "parent_sha": BASE,
            "head_sha": HANDBACK,
            "origin_main_sha": BASE,
            "content_digest": HAND_BACK_DIGEST,
            "digest": HAND_BACK_DIGEST,
            "scope": {
                "schema": "kg.worktree.scope.v1",
                "files": [{"path": "ops/example.py", "operation": "modify"}],
            },
            "outcomes": [],
            "initial_holds": [],
        },
        "superseded_proof": _proof(),
    }


def test_superseded_proof_is_validated_and_preserved() -> None:
    record, problems = normalize_record(_raw_record(), index=0)

    assert record is not None
    assert problems == []
    assert superseded_proof_problem(record) is None
    assert record["superseded_proof"]["schema"] == SUPERSEDED_PROOF_SCHEMA


def _snapshot() -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id="DIRECT-REDUNDANT",
        branch=BRANCH,
        path=PATH,
        status="abandoned",
        scope=SCOPE,
        base_sha=BASE,
        claim_generation=2,
        owner_thread_id="owner",
        handed_back_sha=HANDBACK,
        handback_valid=True,
        handback_digest=HAND_BACK_DIGEST,
    )


class _Registry:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def find_terminal_claim(self, *, branch: str) -> RegistrySnapshot | None:
        return _snapshot() if branch == BRANCH else None

    def supersede(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class _Git:
    def __init__(self, *, patch_matches: bool = True) -> None:
        self.local = HANDBACK
        self.remote = MERGED_HEAD
        self.fingerprints = (PATCH, PATCH if patch_matches else "0" * 64)
        self.actions: list[tuple[str, str]] = []

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(Path("/repo"), "main", BASE, True)

    def origin_main_sha(self) -> str:
        return BASE

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return ()

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote

    def diff_fingerprint(self, base_sha: str, head_sha: str) -> str:
        return self.fingerprints[0] if base_sha == BASE else self.fingerprints[1]

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self.actions.append(("local", expected_head_sha))
        self.local = None

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self.actions.append(("remote", expected_head_sha))
        self.remote = None


class _GitHub:
    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory(
            records=(
                PullRequestSnapshot(
                    number=42,
                    url="https://example.test/pull/42",
                    branch=BRANCH,
                    base_sha=MERGED_BASE,
                    head_sha=MERGED_HEAD,
                    state="MERGED",
                    draft=False,
                    mergeable=True,
                ),
            )
        )

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/example.py",)

    def branch_is_protected(self, branch: str) -> bool:
        return False


def _service(git: _Git) -> tuple[SupersededHandbackService, _Registry]:
    registry = _Registry()
    return (
        SupersededHandbackService(
            registry_query=registry,
            registry_command=registry,
            git_query=git,
            git_command=git,
            github=_GitHub(),
        ),
        registry,
    )


def test_superseded_handback_records_proof_and_removes_exact_refs() -> None:
    git = _Git()
    service, registry = _service(git)

    result = service.supersede(
        branch=BRANCH,
        expected_head_sha=HANDBACK,
        operator="supervisor",
        reason="current handback is content-equivalent to merged PR",
    )

    assert result.disposition == SUPERSEDED_PROOF_DISPOSITION
    assert registry.calls[0]["expected_head_sha"] == HANDBACK
    assert git.actions == [("local", HANDBACK), ("remote", MERGED_HEAD)]
    assert git.local is None and git.remote is None


def test_superseded_handback_fails_closed_on_patch_mismatch() -> None:
    git = _Git(patch_matches=False)
    service, registry = _service(git)

    with pytest.raises(PolicyViolation, match="content fingerprint"):
        service.supersede(
            branch=BRANCH,
            expected_head_sha=HANDBACK,
            operator="supervisor",
            reason="discard attempt",
        )

    assert registry.calls == []
    assert git.actions == []

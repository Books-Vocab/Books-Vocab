from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    InventoryProblem,
    PhysicalWorktree,
    RegistryInventory,
    RegistrySnapshot,
)
from reconcile_main_superseded import (
    CommitIdentity,
    PullRequestEvidence,
    ReconcileRequest,
    SupersededMainReconciler,
)

LOCAL = "1" * 40
LOCAL_PARENT = "2" * 40
ORIGIN = "3" * 40
SOURCE = "4" * 40
SOURCE_PARENT = "5" * 40
MERGE = "6" * 40
LOCAL_PATCH = "7" * 40
SOURCE_PATCH = "7" * 40
FINGERPRINT = "8" * 64
HAND_BACK_DIGEST = "9" * 64
BRANCH = "release/ios-2.0.1-build-12"
OWNER = "worker-thread"
EXTERNAL = "DIRECT-DELIVERY-RECONCILE-SUPERSEDED-MAIN-20250825"
PATH = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
REPO = Path("/repo")
REGISTRY_PATH = Path("/tmp/released-build-12")
SCOPE = Scope.from_paths(modify=(PATH,))


def _request(**overrides: object) -> ReconcileRequest:
    values: dict[str, object] = {
        "repo": REPO,
        "expected_local_main_head": LOCAL,
        "expected_origin_main_sha": ORIGIN,
        "merged_pr_number": 1590,
        "merged_source_head_sha": SOURCE,
        "merged_source_parent_sha": SOURCE_PARENT,
        "branch": BRANCH,
        "owner_thread": OWNER,
        "external_id": EXTERNAL,
        "expected_fingerprint": LOCAL_PATCH,
        "operator": "Worker",
        "reason": "park local build-12 after equivalent merged source is proven",
    }
    values.update(overrides)
    return ReconcileRequest(**values)


class FakeGit:
    def __init__(self) -> None:
        self.local_main = LOCAL
        self.origin_main = ORIGIN
        self.checkout = CanonicalCheckoutSnapshot(REPO, "main", LOCAL, True)
        self.commits = {
            LOCAL: CommitIdentity(LOCAL, (LOCAL_PARENT,), ((PATH, "modify"),)),
            SOURCE: CommitIdentity(SOURCE, (SOURCE_PARENT,), ((PATH, "modify"),)),
        }
        self.normalized = {
            (LOCAL_PARENT, LOCAL): FINGERPRINT,
            (SOURCE_PARENT, SOURCE): FINGERPRINT,
        }
        self.patch_ids = {
            (LOCAL_PARENT, LOCAL): LOCAL_PATCH,
            (SOURCE_PARENT, SOURCE): SOURCE_PATCH,
        }
        self.ancestors = {(SOURCE, ORIGIN), (MERGE, ORIGIN)}
        self.remote_branch = SOURCE
        self.pr_ref = SOURCE
        self.local_branch = LOCAL
        self.worktrees: tuple[PhysicalWorktree, ...] = ()
        self.park_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
        self.park_error: Exception | None = None

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return self.checkout

    def origin_main_sha(self) -> str:
        return self.origin_main

    def commit_identity(self, sha: str) -> CommitIdentity:
        return self.commits[sha]

    def normalized_patch_fingerprint(self, base_sha: str, head_sha: str) -> str:
        return self.normalized[(base_sha, head_sha)]

    def patch_id(self, base_sha: str, head_sha: str) -> str:
        return self.patch_ids[(base_sha, head_sha)]

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        return (ancestor_sha, descendant_sha) in self.ancestors

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote_branch

    def pr_ref_sha(self, number: int) -> str | None:
        return self.pr_ref

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local_branch

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.worktrees

    def park_main_to_origin(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        self.park_calls.append((expected_local_sha, expected_origin_sha))
        if self.park_error is not None:
            raise self.park_error
        if (
            self.local_main != expected_local_sha
            or self.origin_main != expected_origin_sha
        ):
            raise CompareAndSwapConflict("fake CAS drift")
        self.local_main = expected_origin_sha
        self.checkout = CanonicalCheckoutSnapshot(
            REPO, "main", expected_origin_sha, True
        )
        return expected_origin_sha


class FakeRegistry:
    def __init__(self) -> None:
        self.record = RegistrySnapshot(
            lane_id=EXTERNAL,
            branch=BRANCH,
            path=REGISTRY_PATH,
            status="published",
            scope=SCOPE,
            base_sha=LOCAL_PARENT,
            published_base_sha=SOURCE_PARENT,
            claim_generation=3,
            external_ids=(EXTERNAL,),
            owner_thread_id=OWNER,
            handed_back_sha=LOCAL,
            handback_claim_generation=3,
            handback_valid=True,
            handback_digest=HAND_BACK_DIGEST,
        )
        self.extra_records: tuple[RegistrySnapshot, ...] = ()
        self.problems: tuple[InventoryProblem, ...] = ()
        self.mutation_calls = 0

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.record, *self.extra_records), self.problems)


class FakeGitHub:
    def __init__(self) -> None:
        self.pr = PullRequestEvidence(
            number=1590,
            branch=BRANCH,
            base_branch="main",
            base_sha=SOURCE_PARENT,
            head_sha=SOURCE,
            state="MERGED",
            merge_commit_sha=MERGE,
            merged_at="2026-08-25T00:00:00Z",
            changed_paths=(PATH,),
        )
        self.history: tuple[PullRequestEvidence, ...] = (self.pr,)

    def get_pull_request(self, number: int) -> PullRequestEvidence:
        return self.pr

    def list_pull_requests_for_branch(
        self, branch: str
    ) -> tuple[PullRequestEvidence, ...]:
        return self.history


def _service() -> tuple[SupersededMainReconciler, FakeGit, FakeRegistry, FakeGitHub]:
    git = FakeGit()
    registry = FakeRegistry()
    github = FakeGitHub()
    return SupersededMainReconciler(git, github, registry, git), git, registry, github


def test_exact_build12_success_only_parks_main_and_preserves_evidence() -> None:
    service, git, registry, _ = _service()

    result = service.reconcile(_request())

    assert result["schema"] == "kg.delivery.main-reconcile.v1"
    assert result["action"] == "park-superseded-local-main"
    assert result["verdict"] == "success"
    assert result["dispatchable"] is False
    assert result["registry_mutation"] is False
    assert result["before"]["local_main_head"] == LOCAL
    assert result["after"]["local_main_head"] == ORIGIN
    assert result["source"]["head_sha"] == SOURCE
    assert result["pr"]["merge_commit_sha"] == MERGE
    assert result["owner"]["claim_generation"] == 3
    assert result["fingerprint"]["expected"] == LOCAL_PATCH
    assert git.park_calls == [(LOCAL, ORIGIN)]
    assert git.delete_calls == []
    assert git.commits[LOCAL].parents == (LOCAL_PARENT,)
    assert registry.mutation_calls == 0


def test_local_patch_mismatch_fails_closed_before_cas() -> None:
    service, git, _, _ = _service()
    git.patch_ids[(LOCAL_PARENT, LOCAL)] = "a" * 40

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "fingerprint" in result["reason"]
    assert git.park_calls == []
    assert git.local_main == LOCAL


def test_open_or_not_merged_pr_fails_closed() -> None:
    service, git, _, github = _service()
    github.pr = PullRequestEvidence(
        **{
            **github.pr.__dict__,
            "state": "OPEN",
            "merge_commit_sha": None,
            "merged_at": None,
        }
    )

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "MERGED" in result["reason"]
    assert git.park_calls == []


def test_source_not_ancestor_fails_closed() -> None:
    service, git, _, _ = _service()
    git.ancestors.remove((SOURCE, ORIGIN))

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "ancestor" in result["reason"]
    assert git.park_calls == []


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    (
        ("owner_thread_id", "different-owner", "owner"),
        ("lane_id", "different-lane", "lane"),
        ("scope", Scope.from_paths(modify=("ops/other.py",)), "Scope"),
    ),
)
def test_registry_identity_lane_and_scope_mismatch_fail_closed(
    field: str, value: object, needle: str
) -> None:
    service, git, registry, _ = _service()
    registry.record = RegistrySnapshot(
        **{
            **registry.record.__dict__,
            field: value,
        }
    )

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert needle.lower() in result["reason"].lower()
    assert git.park_calls == []


def test_pr_base_and_head_mismatch_fail_closed() -> None:
    service, git, _, github = _service()
    github.pr = PullRequestEvidence(
        **{**github.pr.__dict__, "base_sha": "a" * 40, "head_sha": "b" * 40}
    )

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "base" in result["reason"] or "head" in result["reason"]
    assert git.park_calls == []


def test_malformed_or_ownerless_registry_fails_closed() -> None:
    service, git, registry, _ = _service()
    registry.problems = (
        InventoryProblem("registry", BRANCH, "registry record is malformed"),
    )

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "registry" in result["reason"]
    assert git.park_calls == []

    service, git, registry, _ = _service()
    registry.record = RegistrySnapshot(
        **{**registry.record.__dict__, "owner_thread_id": None}
    )
    result = service.reconcile(_request())
    assert result["verdict"] == "blocked"
    assert "owner" in result["reason"]
    assert git.park_calls == []


def test_duplicate_registry_lane_fails_closed() -> None:
    service, git, registry, _ = _service()
    registry.extra_records = (registry.record,)

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "duplicate" in result["reason"]
    assert git.park_calls == []


def test_local_or_origin_drift_fails_closed() -> None:
    service, git, _, _ = _service()
    git.origin_main = "a" * 40
    result = service.reconcile(_request())
    assert result["verdict"] == "blocked"
    assert "origin/main" in result["reason"]
    assert git.park_calls == []

    service, git, _, _ = _service()
    git.checkout = CanonicalCheckoutSnapshot(REPO, "main", "a" * 40, True)
    result = service.reconcile(_request())
    assert result["verdict"] == "blocked"
    assert "canonical" in result["reason"]
    assert git.park_calls == []


@pytest.mark.parametrize("field", ("remote_branch", "pr_ref"))
def test_remote_ref_drift_fails_closed(field: str) -> None:
    service, git, _, _ = _service()
    setattr(git, field, "a" * 40)

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "remote" in result["reason"] or "ref" in result["reason"]
    assert git.park_calls == []


def test_cas_conflict_is_not_retried_and_main_is_unchanged() -> None:
    service, git, _, _ = _service()
    git.park_error = CompareAndSwapConflict("origin/main changed during park")

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert result["cas_conflict"] is True
    assert git.park_calls == [(LOCAL, ORIGIN)]
    assert git.local_main == LOCAL


def test_missing_source_is_a_source_problem_and_never_parks() -> None:
    service, git, _, _ = _service()
    del git.commits[SOURCE]

    result = service.reconcile(_request())

    assert result["verdict"] == "blocked"
    assert "source" in result["reason"]
    assert git.park_calls == []


def test_malformed_source_sha_is_rejected_before_reads_or_cas() -> None:
    service, git, _, _ = _service()

    result = service.reconcile(_request(merged_source_head_sha=SOURCE[:-1]))

    assert result["verdict"] == "blocked"
    assert "SHA" in result["reason"]
    assert git.park_calls == []

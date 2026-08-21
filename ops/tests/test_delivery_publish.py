from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.errors import DeliverySourceError, PolicyViolation
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import (
    FileChange,
    FileOperation,
    InventoryProblem,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.services.publish import (
    PublicationOutcome,
    PublishService,
    parse_pull_request_body,
    render_pull_request_body,
)
from delivery_control.services.publish_preflight import PublishPreflightService

BASE = "a" * 40
HEAD = "b" * 40
OLD_HEAD = "c" * 40
BRANCH = "feat/delivery"
WORKTREE = Path("/tmp/delivery")


def _receipt(**changes: object) -> HandbackReceipt:
    values: dict[str, object] = {
        "lane_id": "DIRECT-1",
        "owner_thread_id": "thread-1",
        "claim_generation": 3,
        "branch": BRANCH,
        "worktree_path": str(WORKTREE),
        "base_sha": BASE,
        "parent_sha": BASE,
        "head_sha": HEAD,
        "origin_main_sha": "d" * 40,
        "content_digest": "e" * 64,
        "scope": Scope.from_paths(modify=("ops/a.py",)),
    }
    values.update(changes)
    return HandbackReceipt(**values)  # type: ignore[arg-type]


def _registry(receipt: HandbackReceipt, **changes: object) -> RegistrySnapshot:
    values: dict[str, object] = {
        "lane_id": receipt.lane_id,
        "branch": receipt.branch,
        "path": Path(receipt.worktree_path),
        "status": "active",
        "scope": receipt.scope,
        "base_sha": receipt.base_sha,
        "claim_generation": receipt.claim_generation,
        "owner_thread_id": receipt.owner_thread_id,
        "handed_back_sha": receipt.head_sha,
        "handback_claim_generation": receipt.claim_generation,
        "handback_valid": True,
    }
    values.update(changes)
    return RegistrySnapshot(**values)  # type: ignore[arg-type]


def _worktree(receipt: HandbackReceipt, **changes: object) -> WorktreeSnapshot:
    values: dict[str, object] = {
        "path": Path(receipt.worktree_path),
        "branch": receipt.branch,
        "base_sha": receipt.base_sha,
        "head_sha": receipt.head_sha,
        "parent_sha": receipt.parent_sha,
        "clean": True,
        "changes": (FileChange(FileOperation.MODIFY, "ops/a.py"),),
    }
    values.update(changes)
    return WorktreeSnapshot(**values)  # type: ignore[arg-type]


def _pull_request(
    receipt: HandbackReceipt,
    *,
    head_sha: str | None = None,
    title: str = "old title",
    body: str = "old body",
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=7,
        url="https://example.test/pull/7",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=head_sha or receipt.head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
        title=title,
        body=body,
    )


class FakeRegistry:
    def __init__(
        self,
        current: RegistrySnapshot | None,
        others: tuple[RegistrySnapshot, ...] = (),
        problems: tuple[InventoryProblem, ...] = (),
    ) -> None:
        self.current = current
        self.others = others
        self.problems = problems

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        if self.current is not None and self.current.lane_id == lane_id:
            return self.current
        return None

    def list_records(self) -> RegistryInventory:
        records = (() if self.current is None else (self.current,)) + self.others
        return RegistryInventory(records=records, problems=self.problems)


class FakeGit:
    def __init__(
        self,
        receipt: HandbackReceipt,
        *,
        snapshot: WorktreeSnapshot | None = None,
        remote_sha: str | None = None,
    ) -> None:
        self.snapshot = snapshot or _worktree(receipt)
        self.remote_sha = remote_sha
        self.push_calls: list[tuple[str | None, str]] = []
        self.on_push: object | None = None

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self.snapshot

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote_sha

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        assert self.remote_sha == expected_remote_sha
        assert expected_local_sha == self.snapshot.head_sha
        self.push_calls.append((expected_remote_sha, expected_local_sha))
        self.remote_sha = expected_local_sha
        if callable(self.on_push):
            self.on_push(expected_local_sha)
        return expected_local_sha


class FakeGitHub:
    def __init__(
        self,
        receipt: HandbackReceipt,
        *,
        pull_request: PullRequestSnapshot | None = None,
        protected: bool = False,
        fail_create_once: bool = False,
        changed_paths: tuple[str, ...] | None = None,
    ) -> None:
        self.receipt = receipt
        self.pull_request = pull_request
        self.protected = protected
        self.fail_create_once = fail_create_once
        self.paths = changed_paths or receipt.scope.paths
        self.create_calls = 0
        self.update_calls = 0

    def list_open_pull_requests(self) -> PullRequestInventory:
        records = () if self.pull_request is None else (self.pull_request,)
        return PullRequestInventory(records=records)

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        if self.pull_request is not None and self.pull_request.branch == branch:
            return self.pull_request
        return None

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert self.pull_request is not None and self.pull_request.number == number
        return self.pull_request

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return self.paths

    def branch_is_protected(self, branch: str) -> bool:
        return self.protected

    def create_pull_request(
        self, *, branch: str, title: str, body: str
    ) -> PullRequestSnapshot:
        self.create_calls += 1
        if self.fail_create_once and self.create_calls == 1:
            raise DeliverySourceError("injected create failure")
        self.pull_request = _pull_request(self.receipt, title=title, body=body)
        return self.pull_request

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        assert self.pull_request is not None and self.pull_request.number == number
        assert self.pull_request.head_sha == expected_head_sha
        self.update_calls += 1
        self.pull_request = replace(self.pull_request, title=title, body=body)
        return self.pull_request

    def observe_push(self, head_sha: str) -> None:
        if self.pull_request is not None:
            self.pull_request = replace(self.pull_request, head_sha=head_sha)


def _service(
    receipt: HandbackReceipt,
    *,
    registry: FakeRegistry | None = None,
    git: FakeGit | None = None,
    github: FakeGitHub | None = None,
) -> tuple[PublishService, FakeGit, FakeGitHub]:
    fake_registry = registry or FakeRegistry(_registry(receipt))
    fake_git = git or FakeGit(receipt)
    fake_github = github or FakeGitHub(receipt)
    fake_git.on_push = fake_github.observe_push
    preflight = PublishPreflightService(
        registry=fake_registry,
        git=fake_git,
        github=fake_github,
    )
    return (
        PublishService(
            preflight=preflight,
            git=fake_git,
            github_query=fake_github,
            github_command=fake_github,
        ),
        fake_git,
        fake_github,
    )


def test_body_is_deterministic_and_satisfies_readiness_labels() -> None:
    body = render_pull_request_body(_receipt())
    assert body.startswith("## Scope\n")
    assert "## Handback\n" in body
    assert "## Validation\n" in body
    assert "kg.worktree.handback.v1" in body
    assert "Base SHA:" in body and "Head SHA:" in body
    assert body.count("Digest:") == 1
    assert "GitHub required checks are authoritative" in body
    assert parse_pull_request_body(body) == _receipt()


def test_machine_receipt_parser_rejects_missing_or_duplicate_envelopes() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt)
    with pytest.raises(PolicyViolation, match="one typed"):
        parse_pull_request_body("## Scope\nnone")
    with pytest.raises(PolicyViolation, match="one typed"):
        parse_pull_request_body(body + body)


def test_machine_receipt_parser_normalizes_domain_validation_errors() -> None:
    body = render_pull_request_body(_receipt()).replace(
        '"content_digest":"' + "e" * 64 + '"',
        '"content_digest":"not-a-digest"',
    )

    with pytest.raises(PolicyViolation, match="receipt is invalid"):
        parse_pull_request_body(body)


def test_publish_create_then_retry_is_idempotent() -> None:
    receipt = _receipt()
    service, git, github = _service(receipt)

    created = service.publish(receipt=receipt, title="fix: delivery")
    retried = service.publish(receipt=receipt, title="fix: delivery")

    assert created.outcome is PublicationOutcome.CREATED
    assert retried.outcome is PublicationOutcome.ALREADY_PUBLISHED
    assert git.push_calls == [(None, receipt.head_sha)]
    assert github.create_calls == 1
    assert github.update_calls == 0


def test_retry_after_push_succeeds_when_first_pr_create_failed() -> None:
    receipt = _receipt()
    github = FakeGitHub(receipt, fail_create_once=True)
    service, git, github = _service(receipt, github=github)

    with pytest.raises(DeliverySourceError, match="injected"):
        service.publish(receipt=receipt, title="fix: delivery")
    result = service.publish(receipt=receipt, title="fix: delivery")

    assert result.outcome is PublicationOutcome.CREATED
    assert git.push_calls == [(None, receipt.head_sha)]
    assert github.create_calls == 2


def test_existing_unique_pr_allows_exact_force_with_lease_update() -> None:
    receipt = _receipt()
    pull_request = _pull_request(receipt, head_sha=OLD_HEAD)
    git = FakeGit(receipt, remote_sha=OLD_HEAD)
    github = FakeGitHub(receipt, pull_request=pull_request)
    service, git, github = _service(receipt, git=git, github=github)

    result = service.publish(receipt=receipt, title="fix: delivery")

    assert result.outcome is PublicationOutcome.UPDATED
    assert git.push_calls == [(OLD_HEAD, receipt.head_sha)]
    assert result.pull_request.head_sha == receipt.head_sha


@pytest.mark.parametrize(
    ("pull_request", "protected", "message"),
    [
        (None, False, "not owned"),
        (_pull_request(_receipt(), head_sha=OLD_HEAD), True, "protected"),
    ],
)
def test_publish_refuses_unknown_or_protected_remote_rewrite(
    pull_request: PullRequestSnapshot | None,
    protected: bool,
    message: str,
) -> None:
    receipt = _receipt()
    git = FakeGit(receipt, remote_sha=OLD_HEAD)
    github = FakeGitHub(
        receipt,
        pull_request=pull_request,
        protected=protected,
    )
    service, git, _ = _service(receipt, git=git, github=github)

    with pytest.raises(PolicyViolation, match=message):
        service.publish(receipt=receipt, title="fix: delivery")
    assert not git.push_calls


@pytest.mark.parametrize(
    ("registry_changes", "worktree_changes", "message"),
    [
        ({"claim_generation": 4}, {}, "generation"),
        ({}, {"clean": False}, "dirty"),
        (
            {},
            {"changes": (FileChange(FileOperation.ADD, "ops/a.py"),)},
            "operations or paths",
        ),
    ],
)
def test_preflight_rejects_non_exact_transport_facts(
    registry_changes: dict[str, object],
    worktree_changes: dict[str, object],
    message: str,
) -> None:
    receipt = _receipt()
    registry = FakeRegistry(_registry(receipt, **registry_changes))
    git = FakeGit(receipt, snapshot=_worktree(receipt, **worktree_changes))
    service, git, _ = _service(receipt, registry=registry, git=git)

    with pytest.raises(PolicyViolation, match=message):
        service.publish(receipt=receipt, title="fix: delivery")
    assert not git.push_calls


def test_preflight_rejects_scope_collision_and_existing_pr_scope_drift() -> None:
    receipt = _receipt()
    collision = _registry(
        receipt,
        lane_id="DIRECT-2",
        branch="feat/other",
        path=Path("/tmp/other"),
        owner_thread_id="thread-2",
    )
    collision_service, _, _ = _service(
        receipt,
        registry=FakeRegistry(_registry(receipt), (collision,)),
    )
    with pytest.raises(PolicyViolation, match="collision"):
        collision_service.publish(receipt=receipt, title="fix: delivery")

    pull_request = _pull_request(receipt)
    github = FakeGitHub(
        receipt,
        pull_request=pull_request,
        changed_paths=("ops/other.py",),
    )
    drift_service, _, _ = _service(receipt, github=github)
    with pytest.raises(PolicyViolation, match="paths differ"):
        drift_service.publish(receipt=receipt, title="fix: delivery")


def test_title_rejects_delete_control_character_before_any_mutation() -> None:
    receipt = _receipt()
    service, git, _ = _service(receipt)
    with pytest.raises(PolicyViolation, match="canonical"):
        service.publish(receipt=receipt, title="fix:\x7fdelivery")
    assert not git.push_calls


def test_preflight_blocks_incomplete_registry_collision_inventory() -> None:
    receipt = _receipt()
    registry = FakeRegistry(
        _registry(receipt),
        problems=(InventoryProblem("registry", "unknown", "malformed Scope"),),
    )
    service, git, _ = _service(receipt, registry=registry)

    with pytest.raises(PolicyViolation, match="collision inventory failed"):
        service.publish(receipt=receipt, title="fix: delivery")
    assert not git.push_calls


def test_final_readback_rejects_concurrently_closed_pr() -> None:
    receipt = _receipt()
    body = render_pull_request_body(receipt)
    closed = replace(
        _pull_request(receipt, title="fix: delivery", body=body),
        state="CLOSED",
    )
    github = FakeGitHub(receipt, pull_request=closed)
    service, _, _ = _service(
        receipt,
        git=FakeGit(receipt, remote_sha=receipt.head_sha),
        github=github,
    )

    with pytest.raises(PolicyViolation, match="readback"):
        service.publish(receipt=receipt, title="fix: delivery")

from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.application_services import DeliveryApplication
from delivery_control.domain.errors import (
    DeliverySourceError,
    InvalidReceipt,
    PolicyViolation,
)
from delivery_control.domain.unreachable_commits import (
    UNREACHABLE_COMMIT_PATH_LIMIT,
    UnreachableCommitEvidence,
    validate_unreachable_commit_path_limit,
)
from delivery_control.services.unreachable_commit import UnreachableCommitService

SHA = "a" * 40


def _evidence(**overrides: object) -> UnreachableCommitEvidence:
    payload: dict[str, object] = {
        "schema": "kg.delivery.unreachable-commit.v1",
        "commit_sha": SHA,
        "parent_shas": (),
        "subject": "preserved commit",
        "unreachable": True,
        "changed_paths": ("ops/a.py",),
        "changed_path_count": 1,
        "changed_paths_truncated": False,
        "change_fingerprint": "b" * 64,
        "disposition": "preserve_for_owner_correlation",
        "source_problem_scope": None,
        "next_step": "correlate with an owner, Issue, or PR before any lifecycle action",
        "complete": True,
        "error": None,
    }
    payload.update(overrides)
    return UnreachableCommitEvidence(**payload)


def test_unreachable_commit_evidence_requires_explicit_preservation_disposition() -> (
    None
):
    evidence = _evidence()

    assert evidence.complete
    assert evidence.unreachable is True
    assert evidence.disposition == "preserve_for_owner_correlation"
    assert evidence.changed_paths == ("ops/a.py",)

    with pytest.raises(ValueError, match="complete unreachable commit evidence"):
        _evidence(complete=True, unreachable=False)


def test_source_problem_keeps_observed_commit_content_non_actionable() -> None:
    evidence = _evidence(
        complete=False,
        error="git fsck exited with 8",
        disposition="preserve_with_source_problem",
        source_problem_scope="git_objects",
    )

    assert evidence.unreachable is True
    assert evidence.complete is False
    assert evidence.source_problem_scope == "git_objects"


def test_unreachable_commit_service_preserves_source_failures() -> None:
    class FailingGit:
        def inspect_unreachable_commit(
            self, *, commit_sha: str, max_paths: int
        ) -> UnreachableCommitEvidence:
            raise DeliverySourceError(
                f"fsck unavailable for {commit_sha} ({max_paths})"
            )

    evidence = UnreachableCommitService(git=FailingGit()).inspect(SHA)

    assert evidence.complete is False
    assert evidence.unreachable is None
    assert evidence.disposition == "source_problem"
    assert evidence.error == "fsck unavailable for " + SHA + " (200)"


@pytest.mark.parametrize("value", [1, UNREACHABLE_COMMIT_PATH_LIMIT])
def test_unreachable_commit_path_limit_accepts_bounded_values(value: int) -> None:
    assert validate_unreachable_commit_path_limit(value) == value


@pytest.mark.parametrize("value", [0, 201, "200", True, 1.5, None])
def test_unreachable_commit_path_limit_rejects_unbounded_values(
    value: object,
) -> None:
    with pytest.raises(InvalidReceipt, match="between 1 and 200"):
        validate_unreachable_commit_path_limit(value)


def test_application_rejects_unbounded_path_limit_before_git_query() -> None:
    class CountingGit:
        calls = 0

        def inspect_unreachable_commit(
            self, *, commit_sha: str, max_paths: int
        ) -> UnreachableCommitEvidence:
            self.calls += 1
            return _evidence(
                commit_sha=commit_sha, changed_paths=(), changed_path_count=0
            )

    git = CountingGit()
    application = DeliveryApplication(
        repo=Path("/tmp/unreachable-max-paths-test"),
        git=git,
        github=object(),
        registry=object(),
        runtime=object(),
        telemetry=object(),
    )

    with pytest.raises(PolicyViolation, match="between 1 and 200"):
        application.unreachable_commit_inspect(commit_sha=SHA, max_paths=201)

    assert git.calls == 0

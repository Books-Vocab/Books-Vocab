from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.git_cli import GitCliAdapter  # noqa: E402
from delivery_control.adapters.git_parsing import parse_commit_summaries  # noqa: E402
from delivery_control.adapters.errors import AdapterPayloadError  # noqa: E402
from delivery_control.domain.branch_content import (  # noqa: E402
    BRANCH_CONTENT_PATH_LIMIT,
    BranchContentEvidence,
    BranchContentReviewItem,
    BranchContentReviewPlan,
)
from delivery_control.domain.errors import InvalidReceipt  # noqa: E402
from delivery_control.ports.process import CommandResult  # noqa: E402
from delivery_control.services.branch_content import BranchContentService  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _remote_only_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo, base_sha = _repo(tmp_path)
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "switch", "-qc", "feat/remote-only")
    (repo / "remote.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add remote-only feature")
    remote_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/feat/remote-only")
    _git(repo, "switch", "main")
    _git(repo, "branch", "-D", "feat/remote-only")
    return repo, base_sha, remote_head


def test_parse_commit_summaries_preserves_bounded_truncation() -> None:
    first = "a" * 40
    second = "b" * 40
    summaries, truncated = parse_commit_summaries(
        f"{first}\tfirst\n{second}\tsecond\n",
        limit=1,
    )

    assert summaries == ((first, "first"),)
    assert truncated is True


def test_parse_commit_summaries_rejects_malformed_payload() -> None:
    with pytest.raises(AdapterPayloadError, match="malformed"):
        parse_commit_summaries("not-a-sha\tmessage\n", limit=20)


def test_git_adapter_returns_unlanded_branch_content_packet(tmp_path: Path) -> None:
    repo, base_sha = _repo(tmp_path)
    _git(repo, "switch", "-qc", "feat/unlanded")
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add feature")
    _git(repo, "switch", "main")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "advance main")
    main_sha = _git(repo, "rev-parse", "HEAD")

    evidence = GitCliAdapter(repo=repo).inspect_branch_content(
        branch="feat/unlanded",
        base_sha=main_sha,
    )

    assert evidence.complete
    assert evidence.base_is_ancestor is False
    assert evidence.ahead_commit_count == 1
    assert evidence.behind_commit_count == 1
    assert evidence.changed_paths == ("feature.py", "main.txt")
    assert evidence.changed_path_count == 2
    assert evidence.changed_paths_truncated is False
    assert evidence.commit_subjects == ("add feature",)
    assert len(evidence.change_fingerprint) == 64


def test_git_adapter_inspects_remote_only_branch_at_exact_remote_head(
    tmp_path: Path,
) -> None:
    repo, base_sha, remote_head = _remote_only_repo(tmp_path)

    evidence = GitCliAdapter(repo=repo).inspect_branch_content(
        branch="feat/remote-only",
        base_sha=base_sha,
    )

    assert evidence.complete
    assert evidence.head_sha == remote_head
    assert evidence.base_is_ancestor is True
    assert evidence.ahead_commit_count == 1
    assert evidence.behind_commit_count == 0
    assert evidence.changed_paths == ("remote.py",)
    assert evidence.changed_path_count == 1
    assert evidence.commit_subjects == ("add remote-only feature",)
    assert len(evidence.change_fingerprint) == 64
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/feat/remote-only",
            ],
            check=False,
        ).returncode
        == 1
    )


def test_git_adapter_missing_remote_branch_remains_structured_incomplete(
    tmp_path: Path,
) -> None:
    repo, base_sha = _repo(tmp_path)
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))

    evidence = BranchContentService(git=GitCliAdapter(repo=repo)).inspect(
        branch="feat/missing",
        base_sha=base_sha,
    )

    assert evidence.complete is False
    assert evidence.error is not None
    assert "not found in local or remote refs" in evidence.error


def test_git_adapter_missing_remote_object_remains_structured_incomplete(
    tmp_path: Path,
) -> None:
    base_sha = "a" * 40
    remote_head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 1, "", ""),
            CommandResult(
                ("git",),
                0,
                f"{remote_head}\trefs/heads/feat/remote-only\n",
                "",
            ),
            CommandResult(("git",), 128, "", "fatal: missing commit object"),
        ]
    )

    evidence = BranchContentService(
        git=GitCliAdapter(repo=tmp_path, runner=runner)
    ).inspect(
        branch="feat/remote-only",
        base_sha=base_sha,
    )

    assert evidence.complete is False
    assert evidence.error is not None
    assert "command failed" in evidence.error
    assert all("fetch" not in call for call in runner.calls)


def test_git_adapter_bounds_changed_paths_but_keeps_exact_fingerprint(
    tmp_path: Path,
) -> None:
    repo, base_sha = _repo(tmp_path)
    _git(repo, "switch", "-qc", "feat/many-files")
    for index in range(BRANCH_CONTENT_PATH_LIMIT + 1):
        (repo / f"file-{index:03d}.txt").write_text(
            f"{index}\n",
            encoding="utf-8",
        )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add many files")

    evidence = GitCliAdapter(repo=repo).inspect_branch_content(
        branch="feat/many-files",
        base_sha=base_sha,
    )

    assert evidence.complete
    assert evidence.changed_path_count == BRANCH_CONTENT_PATH_LIMIT + 1
    assert len(evidence.changed_paths) == BRANCH_CONTENT_PATH_LIMIT
    assert evidence.changed_paths_truncated is True
    assert evidence.changed_paths[0] == "file-000.txt"
    assert evidence.changed_paths[-1] == (
        f"file-{BRANCH_CONTENT_PATH_LIMIT - 1:03d}.txt"
    )
    assert len(evidence.change_fingerprint) == 64


def test_branch_review_plan_requires_audit_and_page_consistency() -> None:
    evidence = BranchContentEvidence(
        schema="kg.delivery.branch-content.v1",
        branch="feat/unlanded",
        base_sha="a" * 40,
        head_sha="b" * 40,
        base_is_ancestor=False,
        ahead_commit_count=1,
        behind_commit_count=0,
        changed_paths=("feature.py",),
        changed_path_count=1,
        changed_paths_truncated=False,
        change_fingerprint="c" * 64,
        commit_subjects=("feature",),
        commit_subjects_truncated=False,
        complete=True,
    )
    item = BranchContentReviewItem(
        schema="kg.delivery.branch-content-review-item.v1",
        branch="feat/unlanded",
        expected_head_sha="b" * 40,
        preflight_eligible=False,
        preflight_blockers=("not ancestor",),
        content=evidence,
        next_step="review content",
    )
    plan = BranchContentReviewPlan(
        schema="kg.delivery.branch-content-review-plan.v1",
        live_main_sha="a" * 40,
        audit_complete=False,
        complete=False,
        offset=0,
        limit=1,
        total_candidates=1,
        reviewed_count=1,
        remaining_count=0,
        source_problem_count=1,
        items=(item,),
        reviewable_complete=True,
    )

    assert plan.complete is False
    assert plan.items[0].content.change_fingerprint == "c" * 64

    with pytest.raises(InvalidReceipt, match="completeness"):
        BranchContentReviewPlan(
            schema=plan.schema,
            live_main_sha=plan.live_main_sha,
            audit_complete=False,
            complete=True,
            offset=plan.offset,
            limit=plan.limit,
            total_candidates=plan.total_candidates,
            reviewed_count=plan.reviewed_count,
            remaining_count=plan.remaining_count,
            source_problem_count=plan.source_problem_count,
            items=plan.items,
            reviewable_complete=True,
        )


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)

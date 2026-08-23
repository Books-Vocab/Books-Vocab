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
)


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

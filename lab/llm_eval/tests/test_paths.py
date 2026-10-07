"""The private-output guard fails closed when git cannot vouch for a path."""

from __future__ import annotations

import subprocess

import pytest

from llm_eval import paths
from llm_eval.paths import committable_paths


def test_path_outside_any_repo_is_safe(tmp_path, monkeypatch):
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert committable_paths([tmp_path / "out" / "x.jsonl"]) == []


def test_corrupt_repo_is_unsafe(tmp_path, monkeypatch):
    """A ``.git`` git cannot read still marks a work tree: fail closed."""
    monkeypatch.delenv("GIT_DIR", raising=False)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("garbage\n", encoding="utf-8")
    target = repo / "out.jsonl"
    assert committable_paths([target]) == [target.resolve()]


def test_broken_git_dir_env_is_unsafe(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "does-not-exist"))
    target = tmp_path / "out.jsonl"
    assert committable_paths([target]) == [target.resolve()]


def test_dangling_git_symlink_in_ancestor_is_unsafe(tmp_path, monkeypatch):
    """git reports "not a git repository" for a dangling ``.git`` symlink, but
    ``Path.exists()`` is False for it: the marker must still count."""
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    repo = tmp_path / "repo"
    (repo / "nested").mkdir(parents=True)
    (repo / ".git").symlink_to(tmp_path / "nowhere")
    target = repo / "nested" / "out.jsonl"
    assert committable_paths([target]) == [target.resolve()]


@pytest.mark.parametrize(
    "stderr",
    [
        "fatal: detected dubious ownership in repository at '/x'",
        "fatal: Permission denied",
        "error: object file is empty",
    ],
)
def test_unexplained_rev_parse_failure_is_unsafe(tmp_path, monkeypatch, stderr):
    def failing_git(cwd, *args):
        return subprocess.CompletedProcess(["git", *args], 128, "", stderr)

    monkeypatch.setattr(paths, "_git", failing_git)
    target = tmp_path / "out.jsonl"
    assert committable_paths([target]) == [target.resolve()]

"""The private-output guard fails closed when git cannot vouch for a path."""

from __future__ import annotations

import os
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


def _run_git(cwd, *args):
    """Run git with every ambient GIT_* override removed (hermetic setup)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def repo_with_decoy_git_dir(tmp_path):
    """A normal repo (ignores ``ignored/``) plus a valid bare repo elsewhere."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run_git(repo, "init", "-q").returncode == 0
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    bare = tmp_path / "decoy.git"
    assert _run_git(tmp_path, "init", "-q", "--bare", str(bare)).returncode == 0
    (tmp_path / "elsewhere").mkdir()
    return repo, bare, tmp_path / "elsewhere"


def _ambient_probe_says_false(repo):
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and probe.stdout.strip() == "false"


def test_git_dir_override_does_not_hide_the_real_repo(
    repo_with_decoy_git_dir, monkeypatch
):
    """GIT_DIR=<valid bare repo> makes ``rev-parse --is-inside-work-tree``
    exit 0 and print ``false`` inside a normal repo; that must not be read as
    "outside any work tree"."""
    repo, bare, _ = repo_with_decoy_git_dir
    monkeypatch.setenv("GIT_DIR", str(bare))
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    assert _ambient_probe_says_false(repo)  # the premise the old guard trusted
    target = repo / "out" / "x.jsonl"
    assert committable_paths([target]) == [target.resolve()]


def test_git_work_tree_override_does_not_hide_the_real_repo(
    repo_with_decoy_git_dir, monkeypatch
):
    repo, _, elsewhere = repo_with_decoy_git_dir
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))
    assert _ambient_probe_says_false(repo)
    target = repo / "out" / "x.jsonl"
    assert committable_paths([target]) == [target.resolve()]


def test_ignored_path_in_repo_stays_safe_under_git_dir_override(
    repo_with_decoy_git_dir, monkeypatch
):
    """Positive control: the real repo's ignore rules still vouch for a path."""
    repo, bare, _ = repo_with_decoy_git_dir
    monkeypatch.setenv("GIT_DIR", str(bare))
    assert committable_paths([repo / "ignored" / "x.jsonl"]) == []


def test_false_work_tree_claim_is_not_trusted_under_a_repo_marker(
    tmp_path, monkeypatch
):
    """Even if git claims "not inside a work tree", a ``.git`` marker in an
    ancestor means a repo owns this directory: fail closed."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)

    def lying_git(cwd, *args):
        return subprocess.CompletedProcess(["git", *args], 0, "false\n", "")

    monkeypatch.setattr(paths, "_git", lying_git)
    target = repo / "out.jsonl"
    assert committable_paths([target]) == [target.resolve()]


def test_false_work_tree_claim_is_trusted_without_a_marker(tmp_path, monkeypatch):
    """A bare repository directory has no ``.git`` marker and no work tree."""
    bare = tmp_path / "bare.git"
    assert _run_git(tmp_path, "init", "-q", "--bare", str(bare)).returncode == 0
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    assert committable_paths([bare / "out.jsonl"]) == []

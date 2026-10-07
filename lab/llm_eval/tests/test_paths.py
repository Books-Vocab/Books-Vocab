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


# --- config selection: the guard must not trust a verdict that depends on it ---


@pytest.fixture
def isolated_git_config(tmp_path, monkeypatch):
    """Temp HOME whose global config ignores ``secret.jsonl`` everywhere.

    The real ``~/.gitconfig`` is never read: HOME and XDG point at the temp
    dir and the system config is disabled.  Returns ``(repo, caller_empty)``
    where ``repo`` has no repo-local ignore rule and ``caller_empty`` is an
    empty config file a caller can select via ``GIT_CONFIG_GLOBAL``.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "global_ignore").write_text("secret.jsonl\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        f"[core]\n\texcludesFile = {home / 'global_ignore'}\n", encoding="utf-8"
    )
    caller_empty = tmp_path / "empty.gitconfig"
    caller_empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
        monkeypatch.delenv(name, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run_git(repo, "init", "-q").returncode == 0
    return repo, caller_empty


def _caller_check_ignore(repo, target):
    """What ``git check-ignore`` says in the caller's own environment."""
    return subprocess.run(
        ["git", "check-ignore", "-q", "--", str(target)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def test_caller_selected_global_config_cannot_make_a_global_ignore_trusted(
    isolated_git_config, monkeypatch
):
    """Reviewer P1: ``~/.gitconfig`` ignores the file, but the caller selects an
    empty ``GIT_CONFIG_GLOBAL``.  The caller's ``git add`` would stage it, so
    the guard must not call it safe on the strength of the default config."""
    repo, caller_empty = isolated_git_config
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(caller_empty))
    target = repo / "secret.jsonl"
    assert _caller_check_ignore(repo, target) == 1  # caller: not ignored
    assert committable_paths([target]) == [target.resolve()]


def test_config_count_override_cannot_make_a_global_ignore_trusted(
    isolated_git_config, monkeypatch
):
    """``GIT_CONFIG_COUNT``/``KEY_n``/``VALUE_n`` repoints ``core.excludesFile``
    away from the default global ignore; same hole as GIT_CONFIG_GLOBAL."""
    repo, caller_empty = isolated_git_config
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(caller_empty))
    target = repo / "secret.jsonl"
    assert _caller_check_ignore(repo, target) == 1
    assert committable_paths([target]) == [target.resolve()]


def test_config_parameters_override_cannot_make_a_global_ignore_trusted(
    isolated_git_config, monkeypatch
):
    repo, caller_empty = isolated_git_config
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.excludesfile={caller_empty}'")
    target = repo / "secret.jsonl"
    assert _caller_check_ignore(repo, target) == 1
    assert committable_paths([target]) == [target.resolve()]


def test_injected_excludes_do_not_vouch_for_a_path(isolated_git_config, monkeypatch):
    """The mirror image: the caller's config adds an ignore rule that no other
    environment shares.  Not durable, so not a reason to write private data."""
    repo, _ = isolated_git_config
    injected = repo.parent / "injected_ignore"
    injected.write_text("other.jsonl\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(injected))
    target = repo / "other.jsonl"
    assert _caller_check_ignore(repo, target) == 0  # caller view: ignored
    assert committable_paths([target]) == [target.resolve()]


def test_repo_local_ignore_is_trusted_regardless_of_config_env(
    isolated_git_config, monkeypatch
):
    """Positive control: ``.gitignore`` and ``.git/info/exclude`` outrank any
    config-provided excludes, so hostile config selection cannot un-ignore."""
    repo, caller_empty = isolated_git_config
    (repo / ".gitignore").write_text("tracked_rule.jsonl\n", encoding="utf-8")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "exclude").write_text(
        "info_rule.jsonl\n", encoding="utf-8"
    )
    negate = repo.parent / "negate_ignore"
    negate.write_text("!tracked_rule.jsonl\n!info_rule.jsonl\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(negate))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(caller_empty))
    targets = [repo / "tracked_rule.jsonl", repo / "info_rule.jsonl"]
    assert [_caller_check_ignore(repo, t) for t in targets] == [0, 0]
    assert committable_paths(targets) == []


def test_repo_local_config_excludes_file_does_not_vouch(isolated_git_config):
    """``core.excludesFile`` in ``.git/config`` is as private as the global one."""
    repo, _ = isolated_git_config
    local_ignore = repo.parent / "local_ignore"
    local_ignore.write_text("secret.jsonl\n", encoding="utf-8")
    assert (
        _run_git(repo, "config", "core.excludesFile", str(local_ignore)).returncode == 0
    )
    target = repo / "secret.jsonl"
    assert _caller_check_ignore(repo, target) == 0
    assert committable_paths([target]) == [target.resolve()]


def test_default_global_ignore_alone_no_longer_vouches(isolated_git_config):
    """Even with no env override, a global-only ignore is a per-machine fact."""
    repo, _ = isolated_git_config
    target = repo / "secret.jsonl"
    assert _caller_check_ignore(repo, target) == 0
    assert committable_paths([target]) == [target.resolve()]

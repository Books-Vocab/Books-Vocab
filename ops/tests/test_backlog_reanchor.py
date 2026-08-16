from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from backlog_reanchor import ReanchorDeps, patch_id


def test_patch_id_uses_injected_git_and_patch_id_runner(tmp_path):
    calls = []

    def git(*args, repo=None):
        calls.append((args, repo))
        return SimpleNamespace(returncode=0, stdout="commit patch\n")

    def patch_id_runner(text, cwd):
        assert text == "commit patch\n"
        assert cwd == tmp_path
        return "deadbeef stable\n"

    result = patch_id(
        "abc1234",
        repo=tmp_path,
        deps=ReanchorDeps(git=git, patch_id_runner=patch_id_runner),
    )

    assert result == "deadbeef"
    assert calls == [(("show", "abc1234"), tmp_path)]

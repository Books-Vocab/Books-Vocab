#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "boto3",
#     "pytest",
# ]
# ///
"""`--only-episode` / `--parallel` are validated before any stage runs (#2100).

Both were plain `type=int`, and the stages tested `if only_episode:` while the
planner tested `is not None`. So `--only-episode 0` skipped the series-wide stages
yet ran every per-episode stage over the WHOLE series, `--only-episode 99` started
a paid scriptwriter agent for a plan that doesn't exist, and `--parallel 0` only
blew up mid-stage inside ProcessPoolExecutor. Every case here runs `--dry-run`,
so the pre-fix code path can't reach a real agent.

Run:
    cd lab/podcast && uv run test_cli_episode_args.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import pipeline


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(pipeline, "_DASHBOARD_ENABLED", False)
    monkeypatch.delenv("PODCAST_JOB_ID", raising=False)
    ws = tmp_path / "book_0123abcd"
    (ws / "plan" / "episodes").mkdir(parents=True)
    (ws / "scripts").mkdir()
    (ws / "log.md").write_text("# Podcast Pipeline Log\n")
    for n in (1, 2, 3):
        (ws / "plan" / "episodes" / f"ep_{n:02d}.md").write_text(f"# Episode {n}\n")
    # An episode that only has a script (plan file removed) still exists.
    (ws / "scripts" / "ep_4_script.md").write_text("END_OF_SCRIPT\n")
    return ws


def _main(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
    pipeline.main()


def _state_files(ws: Path) -> set[str]:
    return {p.name for p in ws.iterdir()} - {"log.md", "plan", "scripts"}


@pytest.mark.parametrize(
    "argv",
    [
        ["--only-episode", "0"],
        ["--only-episode", "-1"],
        ["--only-episode", "x"],
        ["--parallel", "0"],
        ["--parallel", "11"],
        ["--parallel", "-3"],
    ],
    ids=[
        "episode-0",
        "episode-negative",
        "episode-nan",
        "parallel-0",
        "parallel-11",
        "parallel-negative",
    ],
)
def test_out_of_range_values_are_usage_errors(workspace, monkeypatch, argv):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, str(workspace), "--dry-run", *argv)
    assert exc.value.code == 2
    assert _state_files(workspace) == set(), (
        "a usage error must not touch the workspace"
    )


def test_missing_episode_is_a_usage_error_naming_the_known_ones(
    workspace, monkeypatch, capsys
):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, str(workspace), "--dry-run", "--only-episode", "99")

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--only-episode 99" in err
    assert "1, 2, 3, 4" in err, err
    assert _state_files(workspace) == {".pipeline.lock"}, (
        "rejected before any sidecar / manifest write"
    )


def test_only_episode_on_a_workspace_without_episodes_is_rejected(
    workspace, monkeypatch, capsys
):
    for f in [
        *(workspace / "plan" / "episodes").iterdir(),
        *(workspace / "scripts").iterdir(),
    ]:
        f.unlink()

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, str(workspace), "--dry-run", "--only-episode", "1")

    assert exc.value.code == 2
    assert "no episodes" in capsys.readouterr().err


@pytest.mark.parametrize("episode", ["1", "3", "4"])
def test_existing_episodes_are_accepted(workspace, monkeypatch, episode):
    _main(monkeypatch, str(workspace), "--dry-run", "--only-episode", episode)


@pytest.mark.parametrize("parallel", ["1", "10"])
def test_parallel_bounds_are_inclusive(workspace, monkeypatch, parallel):
    _main(monkeypatch, str(workspace), "--dry-run", "--parallel", parallel)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

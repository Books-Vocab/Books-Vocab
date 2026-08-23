from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib.test_execution_lock import TestExecutionLock  # noqa: E402
from run_serial_test_group import common_anchor, main  # noqa: E402


SCRIPT = OPS / "run_serial_test_group.py"


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def test_common_anchor_resolves_repository_git_common_dir(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    assert common_anchor(repo) == repo.resolve()


def test_common_anchor_resolves_linked_worktree_to_main_repository(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    (repo / "tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "tracked.txt"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--quiet", str(linked)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert common_anchor(linked) == repo.resolve()


def test_runner_waits_for_same_repository_lock_and_releases_after_child(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    marker = tmp_path / "child-ran.txt"
    child = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path(%r).write_text('ran', encoding='utf-8')"
        % str(marker),
    ]

    process = None
    try:
        with TestExecutionLock(repo, "nested"):
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(repo),
                    "--lock-name",
                    "nested",
                    "--",
                    *child,
                ],
                text=True,
            )
            time.sleep(0.2)
            assert process.poll() is None
            assert not marker.exists()
        assert process is not None
        process_rc = process.wait(timeout=5)
        assert process_rc == 0
        assert marker.read_text(encoding="utf-8") == "ran"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_runner_preserves_child_exit_code(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    assert (
        main(
            [
                "--repo-root",
                str(repo),
                "--lock-name",
                "unit",
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            ]
        )
        == 7
    )


def test_test_lock_does_not_reuse_delivery_mutation_lock(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    with TestExecutionLock(repo, "unit") as lock:
        assert lock.path.name == "test-execution.unit.lock"
        assert lock.path.name != "delivery-control.operation.lock"


def test_test_lock_rejects_path_traversal(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    try:
        TestExecutionLock(repo, "../worktree")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal lock name was accepted")

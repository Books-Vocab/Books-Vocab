from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from disk_usage import main


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Disk Test")
    (repo / "tracked.txt").write_text("main\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
    _run_git(repo, "commit", "-m", "initial")
    worktree = tmp_path / "lane-one"
    _run_git(repo, "worktree", "add", "-b", "lane-one", str(worktree), "main")
    (worktree / "lane.txt").write_bytes(b"lane\n" * 128)
    return repo, worktree


def _write_registry(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"schema": "kg.worktree.registry.v2", "records": records}),
        encoding="utf-8",
    )


def test_report_attributes_registered_lanes_and_canonical_main(tmp_path: Path) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-TEST"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "kg.disk.lane-usage.v1"
    by_path = {item["path"]: item for item in report["lanes"]}
    assert by_path[str(worktree)]["registry_status"] == "active"
    assert by_path[str(worktree)]["ownership"] == "registered"
    assert by_path[str(worktree)]["allocated_bytes"] > 0
    assert by_path[str(repo)]["lane_kind"] == "canonical-main"
    assert report["accounting"]["workspace_unassigned_allocated_bytes"] > 0
    assert (
        report["accounting"]["physical_lane_allocated_bytes"]
        >= by_path[str(worktree)]["allocated_bytes"]
    )
    assert report["policy"]["verdict"] == "pass"


def test_missing_active_registered_lane_is_visible_and_check_fails_closed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Disk Test")
    (repo / "tracked.txt").write_text("main\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
    _run_git(repo, "commit", "-m", "initial")
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    missing = tmp_path / "missing-lane"
    _write_registry(
        state,
        [
            {
                "branch": "missing-lane",
                "path": str(missing),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-MISSING"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(missing))
    assert entry["ownership"] == "registered"
    assert entry["exists"] is False
    assert entry["physical_state"] == "missing"
    assert report["policy"]["verdict"] == "block"
    assert "missing-registered-lane" in report["policy"]["reasons"]


@pytest.mark.parametrize("mode", ["logical_bytes", "allocated_bytes"])
def test_report_has_explicit_accounting_mode(mode: str, tmp_path: Path) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(state, [])

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["accounting"]["measurement"] in {"st_blocks", "st_size"}
    assert mode in report["accounting"]["fields"]
    assert report["accounting"]["physical_lane_allocated_bytes"] >= 0
    assert worktree.exists()


def test_terminal_registry_history_is_summarized_not_counted_as_live_lane(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": "merged",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-HISTORY"],
            },
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert all(item["registry_status"] != "merged" for item in report["lanes"])
    assert report["history"]["records"] == 1
    assert report["history"]["terminal_records"] == 1
    assert report["history"]["by_status"] == {"merged": 1}
    assert report["lane_count"] == 1
    assert len(json.dumps(report)) < 20_000


def test_measurement_time_budget_fails_closed_with_structured_evidence(
    tmp_path: Path,
) -> None:
    repo, _ = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(state, [])

    assert (
        main(
            [
                "--workspace",
                str(repo),
                "--state",
                str(state),
                "--output",
                str(output),
                "--time-budget-seconds",
                "0",
            ]
        )
        == 75
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["measurement"]["budget_seconds"] == 0.0
    assert report["measurement"]["budget_exhausted"] is True
    assert "measurement-time-budget-exceeded" in report["policy"]["reasons"]

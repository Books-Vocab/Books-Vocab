from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import disk_usage
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
    _run_git(worktree, "add", "lane.txt")
    _run_git(worktree, "commit", "-m", "lane fixture")
    return repo, worktree


def _write_registry(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"schema": "kg.worktree.registry.v2", "records": records}),
        encoding="utf-8",
    )


def test_measure_tree_does_not_resolve_each_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    for index in range(20):
        (root / f"file-{index}").write_bytes(b"x")

    original = disk_usage._path
    calls: list[str | Path] = []

    def tracking(value: str | Path) -> Path:
        calls.append(value)
        return original(value)

    monkeypatch.setattr(disk_usage, "_path", tracking)

    report = disk_usage.measure_tree(root)

    assert report["complete"] is True
    assert report["files"] == 20
    assert len(calls) <= 1


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


def test_missing_active_registered_lane_is_visible_and_warning_only(
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
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(missing))
    assert entry["ownership"] == "registered"
    assert entry["exists"] is False
    assert entry["physical_state"] == "missing"
    assert report["policy"]["verdict"] == "warning"
    assert "missing-registered-lane" in report["policy"]["reasons"]


def test_explicit_supervision_worktree_is_excluded_with_evidence(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    supervision = tmp_path / "supervision"
    _run_git(repo, "worktree", "add", "-b", "supervision", str(supervision), "main")
    (supervision / "supervision.txt").write_bytes(b"supervision\n" * 128)
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
        main(
            [
                "--workspace",
                str(repo),
                "--state",
                str(state),
                "--output",
                str(output),
                "--supervision-worktree",
                str(supervision),
            ]
        )
        == 0
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(supervision))
    assert entry["ownership"] == "excluded"
    assert entry["physical_state"] == "excluded"
    assert entry["allocated_bytes"] > 0
    assert report["exclusions"]["supervision_worktree_paths"] == [str(supervision)]
    assert report["policy"]["unregistered_physical_worktrees"] == []


def test_active_registered_dirty_worktree_is_attributed_without_blocking(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
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
                "external_ids": ["DIRECT-DELIVERY-DIRTY"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(worktree))
    assert entry["physical_state"] == "dirty"
    assert entry["worktree_state"] == "dirty"
    assert report["policy"]["verdict"] in {"pass", "warning"}
    assert str(worktree) in report["policy"]["active_dirty_implementation_worktrees"]
    assert str(worktree) not in report["policy"]["blocking_dirty_physical_worktrees"]
    assert entry["allocated_bytes"] > 0
    assert (
        report["accounting"]["physical_lane_allocated_bytes"]
        >= entry["allocated_bytes"]
    )


@pytest.mark.parametrize("status", ["published", "cleanup_pending", "abandoned"])
def test_non_active_registered_dirty_worktree_remains_a_hard_block(
    status: str, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": status,
                "claim_generation": 0,
                "external_ids": [f"DIRECT-DELIVERY-DIRTY-{status.upper()}"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["policy"]["verdict"] == "block"
    assert "dirty-physical-worktree" in report["policy"]["blocking_reasons"]
    assert str(worktree) in report["policy"]["blocking_dirty_physical_worktrees"]


def test_active_registered_dirty_worktree_still_enforces_lane_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    (worktree / "dirty.txt").write_bytes(b"dirty\n" * 128)
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
                "external_ids": ["DIRECT-DELIVERY-DIRTY-BUDGET"],
            }
        ],
    )
    monkeypatch.setenv("KG_DISK_GUARD_LANE_BUDGET_GIB", "0")
    monkeypatch.setenv("KG_DISK_GUARD_LANE_TOTAL_BUDGET_GIB", "0")

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(worktree))
    assert entry["allocated_bytes"] > 0
    assert (
        report["accounting"]["physical_lane_allocated_bytes"]
        >= entry["allocated_bytes"]
    )
    assert str(worktree) in report["policy"]["lane_budget_exceeded"]
    assert "dirty-physical-worktree" not in report["policy"]["blocking_reasons"]


def test_unknown_registry_status_is_a_hard_block(tmp_path: Path) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": "paused",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-UNKNOWN-STATUS"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(worktree))
    assert entry["registry_status"] == "paused"
    assert entry["ownership"] == "registered"
    assert report["policy"]["verdict"] == "block"
    assert "unknown-registry-status" in report["policy"]["blocking_reasons"]


def test_malformed_registry_record_is_a_hard_block(tmp_path: Path) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "path": str(worktree),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-MALFORMED"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["policy"]["verdict"] == "block"
    assert "registry-records-invalid" in report["policy"]["blocking_reasons"]


def test_registered_worktree_branch_identity_mismatch_is_a_hard_block(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "different-branch",
                "path": str(worktree),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-MISMATCH"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["policy"]["verdict"] == "block"
    assert str(worktree) in report["policy"]["physical_identity_mismatches"]


def test_unregistered_physical_worktree_is_a_hard_block(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    unregistered = tmp_path / "unregistered"
    _run_git(repo, "worktree", "add", "-b", "unregistered", str(unregistered), "main")
    (unregistered / "unregistered.txt").write_bytes(b"unregistered\n" * 128)
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
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(unregistered))
    assert entry["ownership"] == "unregistered"
    assert entry["physical_state"] == "present-unregistered"
    assert report["policy"]["verdict"] == "block"
    assert "unregistered-physical-worktree" in report["policy"]["reasons"]


def test_terminal_registered_residue_is_visible_but_not_active(
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
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    entry = next(item for item in report["lanes"] if item["path"] == str(worktree))
    assert entry["ownership"] == "registered"
    assert entry["registry_status"] == "merged"
    assert entry["physical_state"] == "terminal-residue"
    assert report["policy"]["unregistered_physical_worktrees"] == []
    assert (
        report["accounting"]["physical_lane_allocated_bytes"]
        >= entry["allocated_bytes"]
    )


@pytest.mark.parametrize("mode", ["logical_bytes", "allocated_bytes"])
def test_report_has_explicit_accounting_mode(mode: str, tmp_path: Path) -> None:
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
                "external_ids": ["DIRECT-DELIVERY-ACCOUNTING"],
            }
        ],
    )

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
    entry = next(item for item in report["lanes"] if item["path"] == str(worktree))
    assert entry["registry_status"] == "merged"
    assert entry["physical_state"] == "terminal-residue"
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

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import disk_usage
from disk_usage import main


@pytest.fixture(autouse=True)
def isolate_host_xctest_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never let unit tests inspect the operator's real XCTestDevices store."""

    monkeypatch.setenv("KG_XCTEST_DEVICES_ROOT", str(tmp_path / "XCTestDevices"))


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


def test_accounting_keeps_missing_active_lane_as_explicit_row(
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
    missing = tmp_path / "missing-lane"
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [
            {
                "branch": "missing-lane",
                "path": str(missing),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-MISSING-ACCOUNTING"],
            }
        ],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    row = next(
        item
        for item in report["accounting"]["lane_accounting"]
        if item["path"] == str(missing)
    )
    assert row["registry_status"] == "active"
    assert row["exists"] is False
    assert row["physical_state"] == "missing"
    assert row["measurement_error"] == "path-missing"
    assert row["accounted_in_aggregate"] is False


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
    assert report["policy"]["measurement_incomplete"] is False
    assert report["policy"]["quota_exceeded"] is True
    assert f"lane-budget-exceeded:{worktree}" in report["policy"]["quota_reasons"]
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
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
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


def test_git_status_timeout_is_structured_as_incomplete_not_quota_excess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": "active",
                "claim_generation": 0,
            }
        ],
    )
    original_run = disk_usage.subprocess.run

    def timeout_git_status(command: list[str], **kwargs: object) -> object:
        if command[:3] == ["git", "-C", str(worktree)] and "status" in command:
            timeout = kwargs.get("timeout")
            assert isinstance(timeout, (int, float)) and 0 < timeout <= 5
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
        return original_run(command, **kwargs)

    monkeypatch.setattr(disk_usage.subprocess, "run", timeout_git_status)

    report = disk_usage.build_report(repo, state, time_budget_seconds=5)

    assert report["measurement"]["status"] == "incomplete"
    assert report["measurement"]["incomplete_reasons"] == [
        "measurement-time-budget-exceeded"
    ]
    assert report["policy"]["verdict"] == "block"
    assert report["policy"]["measurement_incomplete"] is True
    assert report["policy"]["quota_exceeded"] is False


def test_historical_missing_lanes_keep_audit_identity_without_global_measurement_block(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    missing_records = [
        {
            "branch": f"history-{index}",
            "path": str(tmp_path / "history" / str(index)),
            "status": "merged",
            "claim_generation": 0,
            "external_ids": [f"MERGED-HISTORY-{index}"],
        }
        for index in range(1000)
    ]
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(worktree),
                "status": "active",
                "claim_generation": 0,
                "external_ids": ["DIRECT-DELIVERY-ACTIVE"],
            },
            *missing_records,
        ],
    )

    report = disk_usage.build_report(repo, state, time_budget_seconds=5)

    assert report["measurement"]["status"] == "complete"
    assert report["policy"]["verdict"] == "warning"
    assert report["policy"]["measurement_incomplete"] is False
    assert report["policy"]["quota_exceeded"] is False
    assert len(report["policy"]["missing_terminal_lanes"]) == 1000
    history_row = next(
        item
        for item in report["accounting"]["lane_accounting"]
        if item["path"] == str(tmp_path / "history" / "999")
    )
    history_lane = next(
        item
        for item in report["lanes"]
        if item["path"] == str(tmp_path / "history" / "999")
    )
    assert history_row["registry_status"] == "merged"
    assert history_row["measurement_error"] == "path-missing"
    assert history_lane["external_ids"] == ["MERGED-HISTORY-999"]
    assert history_lane["lane_key"]


def test_codex_topology_and_lane_classifications_are_separate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, active = _repo_with_worktree(tmp_path)
    terminal = repo / ".claude" / "worktrees" / "terminal"
    unknown = repo / ".claude" / "worktrees" / "unknown"
    codex_root = tmp_path / ".codex" / "worktrees"
    unregistered = codex_root / "unregistered"
    _run_git(repo, "worktree", "add", "-b", "terminal", str(terminal), "main")
    _run_git(repo, "worktree", "add", "-b", "unknown", str(unknown), "main")
    _run_git(repo, "worktree", "add", "-b", "unregistered", str(unregistered), "main")
    monkeypatch.setenv("KG_DISK_USAGE_CODEX_WORKTREE_ROOT", str(codex_root))

    missing = tmp_path / ".codex" / "worktrees" / "missing"
    state = tmp_path / "registry.json"
    _write_registry(
        state,
        [
            {
                "branch": "lane-one",
                "path": str(active),
                "status": "active",
                "claim_generation": 0,
            },
            {
                "branch": "missing",
                "path": str(missing),
                "status": "active",
                "claim_generation": 0,
            },
            {
                "branch": "terminal",
                "path": str(terminal),
                "status": "merged",
                "claim_generation": 0,
            },
            {
                "branch": "unknown",
                "path": str(unknown),
                "status": "paused",
                "claim_generation": 0,
            },
        ],
    )

    report = disk_usage.build_report(repo, state)
    classifications = report["lane_attribution"]["classifications"]

    assert report["topology"]["observed_roots"] == sorted(
        [str(repo / ".claude" / "worktrees"), str(codex_root)]
    )
    assert classifications["active"]["count"] == 1
    assert classifications["active_but_missing"]["count"] == 1
    assert classifications["physical_but_unregistered"]["count"] == 1
    assert classifications["terminal_residue"]["count"] == 1
    assert classifications["unknown"]["count"] == 1
    assert classifications["active_but_missing"]["allocated_bytes"] == 0
    assert classifications["active_but_missing"]["lane_keys"]
    assert classifications["physical_but_unregistered"]["allocated_bytes"] > 0
    assert classifications["terminal_residue"]["allocated_bytes"] > 0
    assert (
        len(report["lane_attribution"]["product_lane_keys"])
        == report["lane_attribution"]["product_lane_count"]
    )
    assert report["policy"]["missing_active_lanes"] == [str(missing)]
    assert report["policy"]["terminal_physical_residue"] == [str(terminal)]
    assert report["policy"]["unregistered_physical_worktrees"] == [str(unregistered)]


def test_codex_active_and_terminal_cache_residue_is_observed_not_evicted(
    tmp_path: Path,
) -> None:
    """The shell guard must never own worktree lifecycle cleanup."""

    script = Path(__file__).resolve().parents[1] / "kg_disk_guard.sh"
    root = tmp_path / "guard"
    registry = root / "registry.json"
    state = root / "state.json"
    cache = root / ".codex" / "worktrees" / "lane" / ".cache" / "ios-test-derived-data"
    for key in ("a", "b", "c", "d"):
        (cache / key / "Build").mkdir(parents=True)
        (cache / key / "Build" / "blob").write_text("x", encoding="utf-8")
    registry.parent.mkdir(parents=True, exist_ok=True)
    _write_registry(
        registry,
        [
            {
                "branch": "lane",
                "path": str(root / ".codex" / "worktrees" / "lane"),
                "status": "merged",
                "claim_generation": 0,
            }
        ],
    )
    env = {
        "KG_DISK_GUARD_WORKSPACE": str(root),
        "KG_DISK_GUARD_STATE": str(state),
        "KG_DISK_GUARD_REGISTRY_STATE": str(registry),
        "KG_DISK_GUARD_CODEX_WORKTREE_ROOT": str(root / ".codex" / "worktrees"),
        "KG_DISK_GUARD_LANE_USAGE_STATE": str(root / "lane.json"),
        "KG_DISK_GUARD_FREE_BYTES": str(30 * 1073741824),
        "KG_DISK_GUARD_ACTIVE_BUILD": "0",
        "KG_DISK_GUARD_GUARD_LOCK_HELD": "1",
        "KG_DISK_GUARD_BUILD_LOCK_HELD": "1",
        "KG_DISK_GUARD_WORKTREE_CACHE_KEEP": "0",
        "KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS": "0",
    }
    completed = subprocess.run(
        ["bash", str(script)], env={**dict(os.environ), **env}, check=False
    )
    assert completed.returncode == 0
    assert all((cache / key).is_dir() for key in ("a", "b", "c", "d"))


def _write_xctest_device(
    root: Path,
    udid: str,
    *,
    is_ephemeral: bool = False,
    is_deleted: bool = False,
    state: str = "Shutdown",
    plist_text: str | None = None,
) -> Path:
    device = root / udid
    (device / "data").mkdir(parents=True)
    plist = device / "device.plist"
    if plist_text is None:
        plist.write_bytes(
            __import__("plistlib").dumps(
                {
                    "UDID": udid,
                    "isEphemeral": is_ephemeral,
                    "isDeleted": is_deleted,
                    "state": state,
                }
            )
        )
    else:
        plist.write_text(plist_text, encoding="utf-8")
    (device / "data" / "payload").write_bytes(b"x" * 4096)
    return device


def test_xctest_devices_absent_root_is_explicit_and_non_blocking(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
    )
    absent = tmp_path / "missing-xctest-devices"

    assert (
        main(
            [
                "--workspace",
                str(repo),
                "--state",
                str(state),
                "--output",
                str(output),
                "--xctest-devices-root",
                str(absent),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    shared = report["accounting"]["shared_platform_storage"]["xctest_devices"]
    assert shared["exists"] is False
    assert shared["status"] == "absent"
    assert shared["attribution"] == "shared-host-platform"
    assert report["policy"]["verdict"] == "pass"


def test_xctest_devices_measured_root_is_shared_not_a_product_lane(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    xctest_root = tmp_path / "XCTestDevices"
    _write_xctest_device(
        xctest_root,
        "11111111-1111-4111-8111-111111111111",
        is_ephemeral=False,
    )
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
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
                "--xctest-devices-root",
                str(xctest_root),
                "--xctest-devices-budget-gib",
                "1",
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    shared = report["accounting"]["shared_platform_storage"]["xctest_devices"]
    assert shared["exists"] is True
    assert shared["status"] == "measured"
    assert shared["device_count"] == 1
    assert shared["allocated_bytes"] > 0
    assert shared["budget_exceeded"] is False
    assert shared["attribution"] == "shared-host-platform"
    assert all(
        str(xctest_root) not in item["path"]
        for item in report["accounting"]["lane_accounting"]
    )
    assert report["policy"]["verdict"] == "pass"


@pytest.mark.parametrize("kind", ["missing", "malformed"])
def test_xctest_devices_metadata_failure_blocks_without_reclaim(
    kind: str, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    xctest_root = tmp_path / "XCTestDevices"
    udid = "22222222-2222-4222-8222-222222222222"
    device = _write_xctest_device(xctest_root, udid)
    if kind == "missing":
        (device / "device.plist").unlink()
    else:
        (device / "device.plist").write_text("not a plist", encoding="utf-8")
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
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
                "--xctest-devices-root",
                str(xctest_root),
            ]
        )
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    shared = report["accounting"]["shared_platform_storage"]["xctest_devices"]
    assert shared["measurement_complete"] is True
    assert shared["metadata_complete"] is False
    assert report["policy"]["verdict"] == "block"
    assert "xctest-devices-metadata-unavailable" in report["policy"]["blocking_reasons"]


def test_xctest_devices_active_and_non_ephemeral_are_never_reclaim_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    xctest_root = tmp_path / "XCTestDevices"
    _write_xctest_device(
        xctest_root,
        "33333333-3333-4333-8333-333333333333",
        is_ephemeral=False,
        is_deleted=True,
        state="Booted",
    )
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
    )

    def should_not_run(_: dict[str, object]) -> dict[str, object]:
        raise AssertionError("unsafe XCTestDevices candidate was reclaimed")

    monkeypatch.setattr(disk_usage, "_reclaim_xctest_device", should_not_run)
    assert (
        main(
            [
                "--workspace",
                str(repo),
                "--state",
                str(state),
                "--output",
                str(output),
                "--xctest-devices-root",
                str(xctest_root),
                "--xctest-devices-budget-gib",
                "0",
                "--auto-reclaim-xctest-devices",
            ]
        )
        == 75
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    shared = report["accounting"]["shared_platform_storage"]["xctest_devices"]
    assert shared["reclaim"]["candidates"] == []
    assert shared["reclaim"]["status"] == "manual-review"
    assert (xctest_root / "33333333-3333-4333-8333-333333333333").exists()


def test_xctest_devices_supported_ephemeral_stale_reclaim_is_narrow_and_remeasured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    xctest_root = tmp_path / "XCTestDevices"
    udid = "44444444-4444-4444-8444-444444444444"
    device = _write_xctest_device(
        xctest_root,
        udid,
        is_ephemeral=True,
        is_deleted=True,
        state="Shutdown",
    )
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
    )
    calls: list[str] = []

    def supported_reclaim(candidate: dict[str, object]) -> dict[str, object]:
        calls.append(str(candidate["udid"]))
        assert candidate["is_ephemeral"] is True
        assert candidate["is_deleted"] is True
        assert candidate["active"] is False
        for child in sorted(device.iterdir(), reverse=True):
            if child.is_dir():
                for nested in sorted(child.rglob("*"), reverse=True):
                    if nested.is_file() or nested.is_symlink():
                        nested.unlink()
                child.rmdir()
            else:
                child.unlink()
        device.rmdir()
        return {"status": "reclaimed", "command": "supported-test-command"}

    monkeypatch.setattr(disk_usage, "_reclaim_xctest_device", supported_reclaim)
    assert (
        main(
            [
                "--workspace",
                str(repo),
                "--state",
                str(state),
                "--output",
                str(output),
                "--xctest-devices-root",
                str(xctest_root),
                "--xctest-devices-budget-gib",
                "0",
                "--auto-reclaim-xctest-devices",
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    shared = report["accounting"]["shared_platform_storage"]["xctest_devices"]
    assert calls == [udid]
    assert shared["reclaim"]["status"] == "reclaimed"
    assert shared["reclaim"]["succeeded"] == 1
    assert shared["allocated_bytes"] == 0
    assert shared["budget_exceeded"] is False


def test_xctest_devices_fields_are_additive_to_existing_report_schema(
    tmp_path: Path,
) -> None:
    repo, worktree = _repo_with_worktree(tmp_path)
    state = tmp_path / "registry.json"
    output = tmp_path / "lane-usage.json"
    _write_registry(
        state,
        [{"branch": "lane-one", "path": str(worktree), "status": "active"}],
    )

    assert (
        main(["--workspace", str(repo), "--state", str(state), "--output", str(output)])
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "kg.disk.lane-usage.v1"
    assert {"workspace", "registry", "lanes", "accounting", "policy"} <= report.keys()
    assert "shared_platform_storage" in report["accounting"]
    assert "xctest_devices" in report["accounting"]["shared_platform_storage"]


def test_xctest_devices_propagates_non_timeout_tree_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xctest_root = tmp_path / "XCTestDevices"
    udid = "66666666-6666-4666-8666-666666666666"
    _write_xctest_device(xctest_root, udid)

    def incomplete_tree(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "logical_bytes": 4096,
            "allocated_bytes": 4096,
            "files": 1,
            "complete": False,
            "errors": ["permission-denied"],
        }

    monkeypatch.setattr(disk_usage, "measure_tree", incomplete_tree)

    observed = disk_usage.inspect_xctest_devices(xctest_root)

    assert observed["measurement_complete"] is False
    assert observed["status"] == "measurement-incomplete"
    assert f"{udid}:permission-denied" in observed["measurement_errors"]


def test_xctest_devices_budget_uses_unique_physical_extents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xctest_root = tmp_path / "XCTestDevices"
    udid = "77777777-7777-4777-8777-777777777777"
    _write_xctest_device(xctest_root, udid)

    monkeypatch.setattr(disk_usage, "_supports_physical_extents", lambda: True)

    def shared_extent(
        *args: object, **kwargs: object
    ) -> tuple[list[tuple[int, int, int]], None]:
        return [(9, 4096, 8192)], None

    monkeypatch.setattr(disk_usage, "_physical_file_extents", shared_extent)

    observed = disk_usage.inspect_xctest_devices(xctest_root, budget_bytes=1024 * 1024)

    assert observed["allocation_method"] == "apfs-physical-extents"
    assert observed["physical_allocated_bytes"] == 4096
    assert observed["budget_allocated_bytes"] == 4096
    assert observed["allocated_bytes"] > observed["budget_allocated_bytes"]
    assert observed["measurement_complete"] is True


def test_xctest_devices_physical_open_fallback_is_explicit_and_conservative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xctest_root = tmp_path / "XCTestDevices"
    udid = "88888888-8888-4888-8888-888888888888"
    _write_xctest_device(xctest_root, udid)

    monkeypatch.setattr(disk_usage, "_supports_physical_extents", lambda: True)
    monkeypatch.setattr(
        disk_usage,
        "_physical_file_extents",
        lambda *args, **kwargs: ([], "physical-open:PermissionError"),
    )

    observed = disk_usage.inspect_xctest_devices(xctest_root, budget_bytes=1)

    assert observed["allocation_method"] == "apfs-physical-extents+st_blocks-fallback"
    assert observed["physical_measurement_complete"] is True
    assert observed["physical_fallback_files"] == 2
    assert (
        observed["budget_allocated_bytes"]
        == observed["physical_fallback_allocated_bytes"]
    )
    assert observed["budget_exceeded"] is True
    assert observed["physical_measurement_warnings"]

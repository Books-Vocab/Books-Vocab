from __future__ import annotations

import json
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from ops import ios_ui_run_many
from ops.ios_ui_run_many import RunManyError, classify_bundle, deduplicate_methods, load_methods


def test_canonical_device_requires_uuid_groups_and_normalizes_uppercase() -> None:
    assert ios_ui_run_many._canonical_device("01234567-89ab-cdef-0123-456789abcdef") == (
        "01234567-89AB-CDEF-0123-456789ABCDEF"
    )
    with pytest.raises(RunManyError, match="canonical UUID"):
        ios_ui_run_many._canonical_device("-" * 36)


def test_load_and_deduplicate_shared_selector(tmp_path: Path) -> None:
    methods = tmp_path / "methods.json"
    methods.write_text(
        json.dumps(
            {
                "runs": [
                    {"clusterID": "reader-runtime", "requirementID": "P4", "selector": "ReaderTests/testOne", "datasetID": "marketing_demo"},
                    {"clusterID": "reader-runtime", "requirementID": "P5", "selector": "ReaderTests/testOne", "datasetID": "marketing_demo"},
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = load_methods(methods)
    grouped = deduplicate_methods(loaded)
    assert grouped == [
        {
            "selector": "ReaderTests/testOne",
            "datasetID": "marketing_demo",
            "requirementIDs": ["P4", "P5"],
            "clusterIDs": ["reader-runtime"],
        }
    ]


def test_load_rejects_non_exact_selector(tmp_path: Path) -> None:
    methods = tmp_path / "methods.json"
    methods.write_text(
        json.dumps({"runs": [{"clusterID": "x", "requirementID": "P3", "selector": "--grep x", "datasetID": "marketing_demo"}]}),
        encoding="utf-8",
    )
    with pytest.raises(RunManyError, match="exact XCTest selector"):
        load_methods(methods)


@pytest.mark.parametrize("retired_requirement", ["P1", "P2"])
def test_load_rejects_retired_requirements(tmp_path: Path, retired_requirement: str) -> None:
    methods = tmp_path / "methods.json"
    methods.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "clusterID": "retired",
                        "requirementID": retired_requirement,
                        "selector": "RetiredTests/testRetired",
                        "datasetID": "marketing_demo",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunManyError, match="P3-P15"):
        load_methods(methods)


def test_classify_bundle_requires_contract(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "artifacts").mkdir(parents=True)
    (bundle / "verdict.json").write_text(json.dumps({"status": "ok", "exit": "0"}), encoding="utf-8")
    assert classify_bundle(bundle, 0) == "failed_contract"
    (bundle / "artifacts" / "ui-evidence-contract.json").write_text(json.dumps({"valid": True}), encoding="utf-8")
    assert classify_bundle(bundle, 0) == "passed_unattested"


def test_global_consumers_ignore_self_and_shell_command_text(monkeypatch: pytest.MonkeyPatch) -> None:
    process_table = """\
123 1 /bin/zsh -c ./ops/ios_ui_run_many.py cleanup
124 123 /usr/bin/python3 ./ops/ios_ui_run_many.py run
125 1 /usr/bin/xcodebuild test-without-building
126 1 /bin/sh -c echo ios_test.sh
"""

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == ["ps", "-axo", "pid=,ppid=,command="]
        return subprocess.CompletedProcess(args[0], 0, process_table, "")

    monkeypatch.setattr(ios_ui_run_many.subprocess, "run", fake_run)

    consumers = ios_ui_run_many._global_ios_consumers(exclude_pid=123)

    assert consumers == [
        "124 123 /usr/bin/python3 ./ops/ios_ui_run_many.py run",
        "125 1 /usr/bin/xcodebuild test-without-building",
    ]


def _expired_manifest(root: Path, *, status: str = "failure") -> Path:
    run_root = root / "ui-batch-old"
    (run_root / "raw").mkdir(parents=True)
    (run_root / "logs").mkdir()
    (run_root / "bundles" / "failed-helper").mkdir(parents=True)
    (run_root / "raw" / "selector.json").write_text("{}", encoding="utf-8")
    (run_root / "logs" / "selector.log").write_text("failed", encoding="utf-8")
    (run_root / "bundles" / "failed-helper" / "verdict.json").write_text("{}", encoding="utf-8")
    (run_root / "methods.json").write_text("[]", encoding="utf-8")
    (run_root / "summary.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    manifest = {
        "schema": "kg.ios.ui-run-manifest.v1",
        "runID": "ui-batch-old",
        "status": status,
        "verdict": status,
        "pid": None,
        "activePID": None,
        "expiresAt": "2000-01-01T00:00:00Z",
        "stagingRoot": str(run_root),
        "publishRoot": str(run_root / "bundles"),
    }
    path = run_root / "run-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_cleanup_commit_preserves_receipts_and_reclaims_only_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    _expired_manifest(staging)
    monkeypatch.setattr(ios_ui_run_many, "_global_ios_consumers", lambda **_: [])
    monkeypatch.setattr(ios_ui_run_many, "_active_lock_holders", lambda: [])

    payload, exit_code = ios_ui_run_many.cleanup_runs(
        argparse.Namespace(staging_root=staging, max_runs=10, commit=True)
    )

    assert exit_code == 0
    run_root = staging / "ui-batch-old"
    assert payload["reclaimed"][0]["action"] == "reclaimed"
    assert not (run_root / "raw").exists()
    assert not (run_root / "logs").exists()
    assert not (run_root / "bundles").exists()
    assert (run_root / "run-manifest.json").exists()
    assert (run_root / "summary.json").exists()
    assert (run_root / "methods.json").exists()
    assert (run_root / "cleanup-receipt.json").exists()


def test_cleanup_commit_blocks_on_active_consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    _expired_manifest(staging, status="abandoned")
    monkeypatch.setattr(ios_ui_run_many, "_global_ios_consumers", lambda **_: ["999 xcodebuild"])
    monkeypatch.setattr(ios_ui_run_many, "_active_lock_holders", lambda: [])

    payload, exit_code = ios_ui_run_many.cleanup_runs(
        argparse.Namespace(staging_root=staging, max_runs=10, commit=True)
    )

    assert exit_code == 75
    assert payload["candidates"][0]["action"] == "blocked"
    assert (staging / "ui-batch-old" / "raw").exists()

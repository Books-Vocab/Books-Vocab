from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("capture_profile", ROOT / "ops" / "capture_profile.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_ops_edit_commands = MODULE.build_ops_edit_commands
build_snapshot_command = MODULE.build_snapshot_command
load_profile = MODULE.load_profile


def test_load_profile_and_build_commands():
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")

    assert profile.profile_id == "marketing_demo"
    assert profile.materialize.uid == "marketing-demo"
    assert profile.snapshot.dataset_file.name == "marketing_demo.json"

    dry_run_commands = build_ops_edit_commands(profile, commit=False)
    assert dry_run_commands[0][:4] == [
        str(ROOT / "ops" / "devops_kg_safe.sh"),
        "ops-edit",
        "seed",
        "marketing-demo",
    ]
    assert "--commit" not in dry_run_commands[0]

    commit_commands = build_ops_edit_commands(profile, commit=True)
    assert "--commit" in commit_commands[0]
    assert commit_commands[1][2] == "user-config-set"
    assert commit_commands[2][2] == "notebook-update"

    snapshot_command = build_snapshot_command(profile, reuse_build=True)
    assert snapshot_command[:4] == [
        str(ROOT / "ops" / "ios_ops.sh"),
        "catalog",
        "snapshots",
        "--destination",
    ]
    assert "--dataset-file" in snapshot_command
    assert "--reuse-build" in snapshot_command


def test_plan_outputs_machine_readable_json():
    result = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "capture_profile.py"), "plan", str(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "kg.capture.run.v1"
    assert payload["action"] == "plan"
    assert payload["profile"] == "marketing_demo"
    assert payload["materialize"]["uid"] == "marketing-demo"
    assert payload["snapshot"]["datasetFile"].endswith("ops/fixtures/catalog/marketing_demo.json")

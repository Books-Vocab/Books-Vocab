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
build_render_command = MODULE.build_render_command
build_snapshot_command = MODULE.build_snapshot_command
load_profile = MODULE.load_profile


def test_load_profile_and_build_commands():
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")

    assert profile.profile_id == "marketing_demo"
    assert profile.materialize.uid == "marketing-demo"
    assert profile.snapshot.dataset_file.name == "marketing_demo.json"
    assert profile.render.variant == "app-store"
    assert profile.render.target == "promotion"
    assert profile.render.source_mode == "snapshot-derived"
    assert len(profile.shots) == 4
    assert profile.shots[0].appearance == "light"
    assert profile.shots[0].copy_title
    assert profile.shots[0].copy_subtitle

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

    render_command = build_render_command(
        profile,
        source_dir=ROOT / "tmp" / "framed",
        shots_json=ROOT / "tmp" / "shots.json",
    )
    assert render_command[:3] == [
        str(ROOT / "promotion" / "screenshots" / "scripts" / "render_screenshots.py"),
        "--variant",
        "app-store",
    ]
    assert "--target" in render_command
    assert "promotion" in render_command
    assert "--source-dir" in render_command
    assert "--shots-json" in render_command


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
    assert payload["render"]["variant"] == "app-store"
    assert payload["render"]["target"] == "promotion"
    assert payload["render"]["sourceMode"] == "snapshot-derived"
    assert payload["render"]["autoRunEligible"] is True
    assert len(payload["shots"]) == 4
    assert payload["shots"][0]["appearance"] == "light"
    assert payload["shots"][0]["copy"]["title"]
    assert payload["shots"][0]["copy"]["subtitle"]


def test_run_bridges_snapshot_outputs_into_render_inputs(monkeypatch, capsys, tmp_path: Path):
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")
    calls: list[list[str]] = []
    snapshot_root = tmp_path / "snapshots"
    raw_paths = [
        snapshot_root / "iPhone 17 Pro Max portrait" / "Bookshelf" / "With_Books.png",
        snapshot_root / "iPhone 17 Pro Max portrait" / "Today_Review" / "Front.png",
        snapshot_root / "iPhone 17 Pro Max portrait" / "Settings" / "Subscribed_Active.png",
        snapshot_root / "iPhone 17 Pro Max portrait" / "Welcome" / "Step_1___Capture.png",
    ]
    for path in raw_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")

    def fake_run(command: list[str]):
        calls.append(command)
        if command[1:3] == ["catalog", "snapshots"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "status": "ok",
                        "artifacts": {
                            "root": str(snapshot_root),
                            "pngCount": len(raw_paths),
                            "paths": [str(path) for path in raw_paths],
                        },
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(MODULE, "run_command", fake_run)
    monkeypatch.setattr(MODULE, "frame_snapshot_sources", lambda *args, **kwargs: {
        "shotsJson": str(tmp_path / "shots.json"),
        "framedSourceDir": str(tmp_path / "framed"),
        "shots": [{"id": "bookshelf"}],
    })

    rc = MODULE.cmd_run(profile, commit=False, reuse_build=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["bridge"]["shotsJson"].endswith("shots.json")
    assert payload["render"]["sourceMode"] == "snapshot-derived"
    assert "--source-dir" in calls[-1]
    assert "--shots-json" in calls[-1]
    assert len(calls) == 2  # snapshot + render; dry-run 不實際 materialize

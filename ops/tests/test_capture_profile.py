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
build_world_diff_command = MODULE.build_world_diff_command
build_render_command = MODULE.build_render_command
build_snapshot_command = MODULE.build_snapshot_command
load_profile = MODULE.load_profile
build_expectation = MODULE.build_expectation


def _assertion_is_subset(small, big, path=""):
    """big 的對應節點是否滿足 small 的每條斷言（用於 derived ⊇ handwritten）。"""
    if isinstance(small, dict):
        assert isinstance(big, dict), f"{path}: 型別不符"
        for k, v in small.items():
            assert k in big, f"{path}.{k}: derived 缺漏手寫斷言"
            _assertion_is_subset(v, big[k], f"{path}.{k}")
    elif isinstance(small, list):
        assert isinstance(big, list), f"{path}: 型別不符"
        # list 以「small 每個元素都能在 big 找到滿足者」比對（順序無關）。
        # 存在性比對非雙射,不證 cardinality;此處 card content / notebook name /
        # link (from,to,kind) 在手寫 spec 皆唯一鍵,不可能虛假雙重匹配,故足夠。
        for i, item in enumerate(small):
            assert any(
                _try_subset(item, cand) for cand in big
            ), f"{path}[{i}]: derived 找不到滿足手寫斷言的元素 {item}"
    else:
        assert small == big, f"{path}: {small!r} != {big!r}"


def _try_subset(small, big):
    try:
        _assertion_is_subset(small, big)
        return True
    except AssertionError:
        return False


def test_derive_expectation_covers_handwritten():
    """derived expectation 必須涵蓋手寫 marketing_demo_expectation.json 的每條斷言。

    證明手寫 spec 可被 derive 取代，drift 來源消失。
    """
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")
    derived = build_expectation(profile)
    handwritten = json.loads(
        (ROOT / "ops" / "capture_profiles" / "marketing_demo_expectation.json").read_text(
            encoding="utf-8"
        )
    )
    assert derived["schema"] == handwritten["schema"]
    _assertion_is_subset(handwritten, derived, path="root")


def test_derive_check_detects_drift(tmp_path):
    """--check 對 stale expectation 檔回非零（drift guard）。"""
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"schema": "kg.ops_world_expectation.v1"}), encoding="utf-8")
    rc = MODULE.cmd_derive_expectation(profile, out=stale, check=True)
    assert rc != 0


def test_load_profile_and_build_commands():
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")

    assert profile.profile_id == "marketing_demo"
    assert profile.materialize.uid == "marketing-demo"
    assert profile.snapshot.dataset_file.name == "marketing_demo.json"
    assert profile.materialize.expectation_file is not None
    assert profile.materialize.expectation_file.name == "marketing_demo_expectation.json"
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

    verify_command = build_world_diff_command(profile)
    assert verify_command is not None
    assert verify_command[:3] == [
        str(ROOT / "ops" / "devops_kg_safe.sh"),
        "ops-cli",
        "world-diff",
    ]
    assert verify_command[3] == "marketing-demo"
    assert verify_command[-1] == "--json"

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
    assert payload["materialize"]["expectationFile"].endswith("ops/capture_profiles/marketing_demo_expectation.json")
    assert payload["verify"]["enabled"] is True
    assert payload["verify"]["command"][1:3] == ["ops-cli", "world-diff"]
    assert payload["snapshot"]["datasetFile"].endswith("ops/fixtures/ui_worlds/marketing_demo.json")
    assert payload["render"]["variant"] == "app-store"
    assert payload["render"]["target"] == "promotion"
    assert payload["render"]["sourceMode"] == "snapshot-derived"
    assert payload["render"]["autoRunEligible"] is True
    assert len(payload["shots"]) == 4
    assert payload["shots"][0]["appearance"] == "light"
    assert payload["shots"][0]["copy"]["title"]
    assert payload["shots"][0]["copy"]["subtitle"]


def test_verify_requires_matching_world(monkeypatch, capsys):
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")

    def fake_run(command: list[str]):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"schema": "kg.ops_world_diff.v1", "ok": False, "mismatchCount": 1, "mismatches": [{"path": "cards[x]"}]}),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "run_command", fake_run)
    rc = MODULE.cmd_verify(profile)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["action"] == "verify"
    assert payload["status"] == "error"
    assert payload["verify"]["ok"] is False


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
    assert payload["verify"]["planned"] is True
    assert payload["bridge"]["shotsJson"].endswith("shots.json")
    assert payload["render"]["sourceMode"] == "snapshot-derived"
    assert "--source-dir" in calls[-1]
    assert "--shots-json" in calls[-1]
    assert len(calls) == 2  # snapshot + render; dry-run 不實際 materialize

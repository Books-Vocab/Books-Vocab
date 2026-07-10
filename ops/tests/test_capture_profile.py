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
build_emit_commands = MODULE.build_emit_commands
emit_spec_world = MODULE.emit_spec_world
load_profile = MODULE.load_profile
build_expectation = MODULE.build_expectation
CaptureProfileError = MODULE.CaptureProfileError

MARKETING_ACCOUNT = ROOT / "ops" / "capture_profiles" / "marketing_account.json"


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


def _write_profile_with_dataset(tmp_path: Path, dataset_path: Path) -> Path:
    source = json.loads((ROOT / "ops" / "capture_profiles" / "marketing_demo.json").read_text(
        encoding="utf-8"
    ))
    source["snapshot"]["datasetFile"] = str(dataset_path)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    return profile_path


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


def test_load_profile_rejects_non_ui_world_dataset(tmp_path: Path):
    dataset = tmp_path / "bad_dataset.json"
    dataset.write_text(json.dumps({"schema": "not-ui-world", "datasetID": "bad"}), encoding="utf-8")
    profile_path = _write_profile_with_dataset(tmp_path, dataset)

    try:
        load_profile(profile_path)
    except CaptureProfileError as exc:
        assert "schema 必須是 kg.fixture.dataset.v2" in str(exc)
    else:
        raise AssertionError("expected non-UI World dataset to fail")


def test_load_profile_rejects_asset_hash_drift(tmp_path: Path):
    source_dataset = json.loads((ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text(
        encoding="utf-8"
    ))
    source_dataset["assets"]["books"]["catalog_reader_epub"]["sha256"] = "0" * 64
    dataset = tmp_path / "bad_hash_dataset.json"
    dataset.write_text(json.dumps(source_dataset, ensure_ascii=False), encoding="utf-8")
    profile_path = _write_profile_with_dataset(tmp_path, dataset)

    try:
        load_profile(profile_path)
    except CaptureProfileError as exc:
        assert "assets.books.catalog_reader_epub.sha256 mismatch" in str(exc)
    else:
        raise AssertionError("expected asset hash drift to fail")


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


# ---------------------------------------------------------------------------
# spec-emit source mode（行銷帳號：spec→emit-ios on-demand，不 commit 生成 world）
# ---------------------------------------------------------------------------


def test_marketing_demo_stays_dataset_file_mode():
    """既有 marketing_demo profile 仍走 dataset-file 模式（回歸基準不破壞）。"""
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")
    assert profile.snapshot.source == "dataset-file"
    assert profile.snapshot.dataset_file is not None
    assert profile.snapshot.spec_file is None
    assert profile.snapshot.plan_file is None
    assert profile.materialize is not None
    # dataset-file 模式仍導出 ops-edit 造景指令 + world-diff 驗證
    assert build_ops_edit_commands(profile, commit=False)
    assert build_world_diff_command(profile) is not None


def test_load_spec_emit_profile_parses():
    profile = load_profile(MARKETING_ACCOUNT)
    assert profile.profile_id == "marketing_account"
    # spec-emit 模式：materialize 缺席 → None，不污染 DB 造景面
    assert profile.materialize is None
    assert profile.snapshot.source == "spec-emit"
    assert profile.snapshot.dataset_file is None
    assert profile.snapshot.spec_file is not None
    assert profile.snapshot.spec_file.name == "marketing_account_spec.json"
    assert profile.snapshot.plan_file is not None
    assert profile.snapshot.plan_file.name == "history_plan.json"
    assert profile.render.source_mode == "snapshot-derived"
    assert len(profile.shots) == 5
    assert profile.shots[0].source_scenario == "Knowledge Graph View/Populated graph"
    assert all(shot.copy_title and shot.copy_subtitle for shot in profile.shots)


def test_spec_emit_suppresses_materialize_and_verify():
    """materialize 缺席 → 不產 ops-edit 指令、不產 world-diff。"""
    profile = load_profile(MARKETING_ACCOUNT)
    assert build_ops_edit_commands(profile, commit=False) == []
    assert build_ops_edit_commands(profile, commit=True) == []
    assert build_world_diff_command(profile) is None


def test_build_emit_commands_sequence(tmp_path: Path):
    """導出 emit 指令序列：有 planFile → 先 shape_history 再 emit-ios，末命令寫 out。"""
    profile = load_profile(MARKETING_ACCOUNT)
    out = tmp_path / "ui_world.json"
    commands = build_emit_commands(profile, out)
    assert len(commands) == 2  # shape_history + emit-ios（planFile 存在）
    shape_cmd, emit_cmd = commands
    assert shape_cmd[1].endswith("shape_history.py")
    assert str(profile.snapshot.spec_file) in shape_cmd
    assert str(profile.snapshot.plan_file) in shape_cmd
    assert "--out" in shape_cmd
    assert emit_cmd[1].endswith("build_demo.py")
    assert emit_cmd[2:4] == ["emit-ios", "--spec"]
    assert "--out" in emit_cmd
    assert str(out) in emit_cmd
    assert "--commit" in emit_cmd
    assert "--json" in emit_cmd
    # 有 planFile → emit-ios 帶 --plan，把 review 時鐘凍結在 anchor
    assert "--plan" in emit_cmd
    assert emit_cmd[emit_cmd.index("--plan") + 1] == str(profile.snapshot.plan_file)


def test_emit_spec_world_produces_valid_deterministic_world():
    """實際 emit：world 過 manifest validate，datasetID 確定式（spec 內容 hash 派生）。"""
    profile = load_profile(MARKETING_ACCOUNT)
    world_path, results = emit_spec_world(profile)
    assert world_path.exists()
    # 每個 emit 子步驟 exit 0
    assert all(step["exitCode"] == 0 for step in results)
    doc = json.loads(world_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "kg.fixture.dataset.v2"
    assert doc["datasetID"].startswith("spec-")
    # 二次 emit → 同 datasetID（確定式）
    world_path2, _ = emit_spec_world(profile)
    doc2 = json.loads(world_path2.read_text(encoding="utf-8"))
    assert doc2["datasetID"] == doc["datasetID"]


def test_plan_spec_emit_outputs_emit_section():
    result = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "capture_profile.py"), "plan", str(MARKETING_ACCOUNT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["profile"] == "marketing_account"
    assert payload["materialize"] is None
    assert payload["verify"]["enabled"] is False
    assert payload["snapshot"]["source"] == "spec-emit"
    assert payload["snapshot"]["specFile"].endswith("marketing_account_spec.json")
    assert payload["snapshot"]["planFile"].endswith("history_plan.json")
    assert payload["emit"]["enabled"] is True
    assert isinstance(payload["emit"]["commands"], list) and payload["emit"]["commands"]
    assert len(payload["shots"]) == 5
    assert payload["render"]["autoRunEligible"] is True


# ---------------------------------------------------------------------------
# snapshot artifact 解析：slug 必須對齊 catalog 檔名規則（只空格→_，保留其他），
# 且 App Store iPhone 直式圖必須選 iPhone portrait（非 iPad landscape）。
# 迴歸來源：marketing_account pipeline 首次端到端跑，Vocab/Notebook 兩景 title
# 含 middle-dot `·` 時 snapshot_slug（全非 alnum→_）產出 `Populated___...` 與
# catalog 實際檔名 `Populated_·_...` 不符 → resolve missing。
# ---------------------------------------------------------------------------

snapshot_slug = MODULE.snapshot_slug
resolve_shot_artifacts = MODULE.resolve_shot_artifacts


def test_snapshot_slug_matches_catalog_filename_rule():
    # catalog slug 實測規則（build/snapshots/catalog-*）：只把空格轉 _，保留其他所有
    # 字元（middle-dot ·、括號、em-dash、加號、CJK 等）。
    assert snapshot_slug("Populated · mixed sync states") == "Populated_·_mixed_sync_states"
    assert snapshot_slug("Populated · multiple notebooks") == "Populated_·_multiple_notebooks"
    assert snapshot_slug("Vocabulary List View") == "Vocabulary_List_View"
    assert snapshot_slug("Badge stress (99+)") == "Badge_stress_(99+)"
    assert snapshot_slug("Default (複習優先)") == "Default_(複習優先)"
    assert snapshot_slug("Populated graph") == "Populated_graph"  # 無特殊字元不受影響
    # . : / 也是 catalog 分隔符（CatalogSnapshotTests.swift:331 CharacterSet(".:/")）——
    # 從真實 catalog 檔名反證：只 replace 空格會漏這三者。
    assert snapshot_slug("Step 1 / Capture") == "Step_1___Capture"  # / + 空格
    assert snapshot_slug("Half (0.5)") == "Half_(0_5)"  # . → _
    assert snapshot_slug("Two speakers (current: 1)") == "Two_speakers_(current__1)"  # : → _


def test_resolve_matches_special_char_scene_and_prefers_iphone_portrait():
    profile = load_profile(MARKETING_ACCOUNT)
    # 模擬真實 catalog 輸出：2 device × 2 appearance（iPad Pro 11 landscape 排序在
    # iPhone 15 Pro portrait 之前，正是舊 resolve 誤選 iPad 的成因）。
    devices = [
        "iPad Pro 11 landscape (dark)",
        "iPad Pro 11 landscape",
        "iPhone 15 Pro portrait (dark)",
        "iPhone 15 Pro portrait",
    ]
    scenes = {
        "Knowledge Graph View": "Populated_graph",
        "Vocabulary List View": "Populated_·_mixed_sync_states",
        "Notebook List View": "Populated_·_multiple_notebooks",
        "Stats View": "Populated",
        "Today Review": "Back",
    }
    paths = [
        f"/tmp/build/snapshots/{dev}/{cat.replace(' ', '_')}/{title}.png"
        for dev in devices
        for cat, title in scenes.items()
    ]
    resolved = resolve_shot_artifacts(profile, {"artifacts": {"paths": paths}})
    assert len(resolved) == 5  # 全 5 shots 匹配（含含 · 的 Vocab/Notebook 兩景）
    for r in resolved:
        assert "iPhone" in r["rawPath"], f"{r['id']} 應選 iPhone，實得 {r['rawPath']}"
        assert "landscape" not in r["rawPath"], f"{r['id']} 不應選 landscape"
        assert "(dark)" not in r["rawPath"], f"{r['id']} light shot 不應選 dark"


def test_resolve_marketing_demo_slash_and_middot_scenes():
    # 迴歸：marketing_demo 的 `Welcome/Step 1 / Capture`（title 含 /）與
    # `Bookshelf View/Populated · mixed formats`（含 ·）必須同時匹配 catalog 檔名。
    # split("/",1) 後 title="Step 1 / Capture" → catalog "Step_1___Capture"。
    profile = load_profile(ROOT / "ops" / "capture_profiles" / "marketing_demo.json")
    files = {
        "Bookshelf View": "Populated_·_mixed_formats",
        "Today Review": "Front",
        "Settings": "Subscribed_Active",
        "Welcome": "Step_1___Capture",
    }
    paths = [
        f"/tmp/build/snapshots/iPhone 15 Pro portrait/{cat.replace(' ', '_')}/{title}.png"
        for cat, title in files.items()
    ]
    resolved = resolve_shot_artifacts(profile, {"artifacts": {"paths": paths}})
    assert len(resolved) == 4  # 4 shots 全匹配（含 · 的 Bookshelf 與含 / 的 Welcome）

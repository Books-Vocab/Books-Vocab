#!/usr/bin/env -S uv run --python 3.13 python
"""Capture profile runner: combine ops-edit shaping and iOS catalog snapshots."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAFE_WRAPPER = ROOT / "ops" / "devops_kg_safe.sh"
IOS_OPS = ROOT / "ops" / "ios_ops.sh"
PROMO_RENDER = ROOT / "promotion" / "screenshots" / "scripts" / "render_screenshots.py"
FRAME_RENDER = ROOT / "promotion" / "screenshots" / "scripts" / "frame_catalog_screenshots.py"
BUILD_DEMO = ROOT / "ops" / "demo" / "build_demo.py"
SHAPE_HISTORY = ROOT / "ops" / "demo" / "marketing_account" / "shape_history.py"
REVIEWER_EVIDENCE = ROOT / "ops" / "reviewer_evidence.py"
# Repo-relative on purpose: this path is only ever resolved against a git
# commit now, and an absolute working-tree constant is what the old
# --project-file default was built out of.
IOS_PROJECT_FILE_REL = "ios/BooksAndVocab.xcodeproj/project.pbxproj"

# snapshot dataset 來源模式（tagged union on snapshot.source）
SOURCE_DATASET_FILE = "dataset-file"  # 既有：吃預先 committed 的 UI World fixture
SOURCE_SPEC_EMIT = "spec-emit"        # 新增：從 kg.seed_spec.v1 on-demand emit，不 commit 生成 world
SNAPSHOT_SOURCES = {SOURCE_DATASET_FILE, SOURCE_SPEC_EMIT}

# 純宣告轉換（不讀 DB），用來從 seed/steps 自動導出 world expectation。
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "ops"))
from kg.ops_world_expectation import derive_expectation  # noqa: E402
from reviewer_evidence import (  # noqa: E402
    EvidenceError,
    build_manifest as build_reviewer_evidence_manifest,
    materialize_tracked_file,
    write_bundle as write_reviewer_evidence_bundle,
)
from ui_world_manifest import UIWorldManifestError, validate_fixture_dataset_file as _validate_ui_world  # noqa: E402


logger = logging.getLogger(__name__)


class CaptureProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaterializeStep:
    subcommand: str
    args: list[str]


@dataclass(frozen=True)
class MaterializeConfig:
    uid: str
    seed_file: Path
    expectation_file: Path | None
    steps: list[MaterializeStep]


@dataclass(frozen=True)
class SnapshotConfig:
    source: str
    destination: str
    groups: list[str]
    scenarios: list[str]
    # dataset-file 模式：預先存在的 UI World fixture 路徑。
    dataset_file: Path | None = None
    # spec-emit 模式：kg.seed_spec.v1 輸入（emit-ios --spec）+ 選配 kg.history_plan.v1。
    spec_file: Path | None = None
    plan_file: Path | None = None


@dataclass(frozen=True)
class RenderConfig:
    variant: str
    target: str
    output_dir: Path | None
    source_mode: str


@dataclass(frozen=True)
class ShotConfig:
    shot_id: str
    source_scenario: str
    output_name: str
    appearance: str
    copy_title: str
    copy_subtitle: str


@dataclass(frozen=True)
class CaptureProfile:
    profile_id: str
    materialize: MaterializeConfig | None
    snapshot: SnapshotConfig
    render: RenderConfig
    shots: list[ShotConfig]


def _ensure_list(raw: Any, *, field: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CaptureProfileError(f"{field} 必須是 array")
    return raw


def _ensure_str(raw: Any, *, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CaptureProfileError(f"{field} 必須是非空字串")
    return raw


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def validate_fixture_dataset_file(path: Path) -> None:
    try:
        _validate_ui_world(path, label="snapshot.datasetFile")
    except UIWorldManifestError as exc:
        raise CaptureProfileError(str(exc)) from exc


def _load_materialize(materialize_raw: dict[str, Any]) -> MaterializeConfig:
    steps: list[MaterializeStep] = []
    for index, step_raw in enumerate(_ensure_list(materialize_raw.get("steps"), field="materialize.steps")):
        if not isinstance(step_raw, dict):
            raise CaptureProfileError(f"materialize.steps[{index}] 必須是 object")
        subcommand = _ensure_str(step_raw.get("subcommand"), field=f"materialize.steps[{index}].subcommand")
        args = [str(item) for item in _ensure_list(step_raw.get("args"), field=f"materialize.steps[{index}].args")]
        steps.append(MaterializeStep(subcommand=subcommand, args=args))

    materialize = MaterializeConfig(
        uid=_ensure_str(materialize_raw.get("uid"), field="materialize.uid"),
        seed_file=_resolve_path(_ensure_str(materialize_raw.get("seedFile"), field="materialize.seedFile")),
        expectation_file=(
            _resolve_path(_ensure_str(materialize_raw.get("expectationFile"), field="materialize.expectationFile"))
            if materialize_raw.get("expectationFile") is not None
            else None
        ),
        steps=steps,
    )
    if not materialize.seed_file.exists():
        raise CaptureProfileError(f"seed file 不存在: {materialize.seed_file}")
    if materialize.expectation_file is not None and not materialize.expectation_file.exists():
        raise CaptureProfileError(f"expectation file 不存在: {materialize.expectation_file}")
    return materialize


def _load_snapshot(source: str, snapshot_raw: dict[str, Any]) -> SnapshotConfig:
    common = dict(
        source=source,
        destination=_ensure_str(snapshot_raw.get("destination"), field="snapshot.destination"),
        groups=[str(item) for item in _ensure_list(snapshot_raw.get("groups"), field="snapshot.groups")],
        scenarios=[str(item) for item in _ensure_list(snapshot_raw.get("scenarios"), field="snapshot.scenarios")],
    )

    if source == SOURCE_DATASET_FILE:
        if snapshot_raw.get("specFile") is not None or snapshot_raw.get("planFile") is not None:
            raise CaptureProfileError(
                f"snapshot.source={SOURCE_DATASET_FILE} 不支援 specFile/planFile"
            )
        dataset_file = _resolve_path(_ensure_str(snapshot_raw.get("datasetFile"), field="snapshot.datasetFile"))
        if not dataset_file.exists():
            raise CaptureProfileError(f"dataset file 不存在: {dataset_file}")
        validate_fixture_dataset_file(dataset_file)
        return SnapshotConfig(**common, dataset_file=dataset_file)

    # SOURCE_SPEC_EMIT：datasetFile 由 emit 產生（不預先存在）。
    if snapshot_raw.get("datasetFile") is not None:
        raise CaptureProfileError(
            f"snapshot.source={SOURCE_SPEC_EMIT} 不接受 datasetFile（world 由 spec on-demand emit）"
        )
    spec_file = _resolve_path(_ensure_str(snapshot_raw.get("specFile"), field="snapshot.specFile"))
    if not spec_file.exists():
        raise CaptureProfileError(f"spec file 不存在: {spec_file}")
    plan_file: Path | None = None
    if snapshot_raw.get("planFile") is not None:
        plan_file = _resolve_path(_ensure_str(snapshot_raw.get("planFile"), field="snapshot.planFile"))
        if not plan_file.exists():
            raise CaptureProfileError(f"plan file 不存在: {plan_file}")
    if not BUILD_DEMO.exists():
        raise CaptureProfileError(f"build_demo 不存在: {BUILD_DEMO}")
    if plan_file is not None and not SHAPE_HISTORY.exists():
        raise CaptureProfileError(f"shape_history 不存在: {SHAPE_HISTORY}")
    return SnapshotConfig(**common, spec_file=spec_file, plan_file=plan_file)


def load_profile(path: str | Path) -> CaptureProfile:
    profile_path = _resolve_path(str(path))
    if not profile_path.exists():
        raise CaptureProfileError(f"profile 不存在: {profile_path}")
    data = json.loads(profile_path.read_text())
    if data.get("schema") != "kg.capture.profile.v1":
        raise CaptureProfileError("schema 必須是 kg.capture.profile.v1")

    snapshot_raw = data.get("snapshot")
    if not isinstance(snapshot_raw, dict):
        raise CaptureProfileError("snapshot 必須存在且為 object")

    source = snapshot_raw.get("source", SOURCE_DATASET_FILE)
    if source not in SNAPSHOT_SOURCES:
        raise CaptureProfileError(
            f"snapshot.source 必須是 {SOURCE_DATASET_FILE} 或 {SOURCE_SPEC_EMIT}"
        )

    # materialize：dataset-file 模式必填（DB 造景 + world-diff 交叉驗證）；
    # spec-emit 模式由 spec↔fixture roundtrip 保證，materialize 可略（None）。
    materialize_raw = data.get("materialize")
    materialize: MaterializeConfig | None = None
    if source == SOURCE_DATASET_FILE:
        if not isinstance(materialize_raw, dict):
            raise CaptureProfileError("materialize 必須存在且為 object")
        materialize = _load_materialize(materialize_raw)
    elif materialize_raw is not None:
        # spec-emit 模式若提供 materialize，只接受空殼（無 uid/seedFile/steps）；
        # 有實質 DB 造景欄位即為模式污染，fail-loud。
        if not isinstance(materialize_raw, dict):
            raise CaptureProfileError("materialize 必須是 object")
        polluting = [k for k in ("uid", "seedFile", "expectationFile") if materialize_raw.get(k)]
        if polluting or materialize_raw.get("steps"):
            raise CaptureProfileError(
                "spec-emit 模式不支援 materialize DB 造景（"
                f"發現 {', '.join(polluting + (['steps'] if materialize_raw.get('steps') else []))}）；"
                "spec-based 帳號的 roundtrip 由 spec↔fixture 保證"
            )

    snapshot = _load_snapshot(source, snapshot_raw)

    render_raw = data.get("render")
    if not isinstance(render_raw, dict):
        raise CaptureProfileError("render 必須存在且為 object")
    render = RenderConfig(
        variant=_ensure_str(render_raw.get("variant"), field="render.variant"),
        target=_ensure_str(render_raw.get("target"), field="render.target"),
        output_dir=(
            _resolve_path(_ensure_str(render_raw.get("outputDir"), field="render.outputDir"))
            if render_raw.get("outputDir") is not None
            else None
        ),
        source_mode=_ensure_str(render_raw.get("sourceMode"), field="render.sourceMode"),
    )
    if render.variant not in {"app-store", "web", "all"}:
        raise CaptureProfileError("render.variant 必須是 app-store、web 或 all")
    if render.target not in {"promotion", "legacy"}:
        raise CaptureProfileError("render.target 必須是 promotion 或 legacy")
    if render.source_mode not in {"legacy-framed-sources", "snapshot-derived"}:
        raise CaptureProfileError("render.sourceMode 必須是 legacy-framed-sources 或 snapshot-derived")
    if not PROMO_RENDER.exists():
        raise CaptureProfileError(f"render script 不存在: {PROMO_RENDER}")
    if not FRAME_RENDER.exists():
        raise CaptureProfileError(f"framing script 不存在: {FRAME_RENDER}")

    shots: list[ShotConfig] = []
    for index, shot_raw in enumerate(_ensure_list(data.get("shots"), field="shots")):
        if not isinstance(shot_raw, dict):
            raise CaptureProfileError(f"shots[{index}] 必須是 object")
        copy_raw = shot_raw.get("copy")
        if not isinstance(copy_raw, dict):
            raise CaptureProfileError(f"shots[{index}].copy 必須是 object")
        shots.append(
            ShotConfig(
                shot_id=_ensure_str(shot_raw.get("id"), field=f"shots[{index}].id"),
                source_scenario=_ensure_str(shot_raw.get("sourceScenario"), field=f"shots[{index}].sourceScenario"),
                output_name=_ensure_str(shot_raw.get("outputName"), field=f"shots[{index}].outputName"),
                appearance=str(shot_raw.get("appearance", "light")).strip() or "light",
                copy_title=_ensure_str(copy_raw.get("title"), field=f"shots[{index}].copy.title"),
                copy_subtitle=_ensure_str(copy_raw.get("subtitle"), field=f"shots[{index}].copy.subtitle"),
            )
        )
    if not shots:
        raise CaptureProfileError("shots 至少需要一筆")
    if any(shot.appearance not in {"light", "dark"} for shot in shots):
        raise CaptureProfileError("shots.appearance 只能是 light 或 dark")

    return CaptureProfile(
        profile_id=_ensure_str(data.get("id"), field="id"),
        materialize=materialize,
        snapshot=snapshot,
        render=render,
        shots=shots,
    )


def build_ops_edit_commands(profile: CaptureProfile, *, commit: bool) -> list[list[str]]:
    if profile.materialize is None:
        return []
    commands = [
        [
            str(SAFE_WRAPPER),
            "ops-edit",
            "seed",
            profile.materialize.uid,
            str(profile.materialize.seed_file),
            "--json",
        ]
    ]
    for step in profile.materialize.steps:
        commands.append([
            str(SAFE_WRAPPER),
            "ops-edit",
            step.subcommand,
            profile.materialize.uid,
            *step.args,
            "--json",
        ])
    if commit:
        return [cmd[:-1] + ["--commit", "--json"] for cmd in commands]
    return commands


def build_snapshot_command(
    profile: CaptureProfile, *, reuse_build: bool, dataset_file: Path | None = None
) -> list[str]:
    # dataset-file 模式用 profile 內的 committed fixture；spec-emit 模式由呼叫者
    # 傳入 on-demand emit 出的暫存 world 路徑。
    resolved_dataset = dataset_file if dataset_file is not None else profile.snapshot.dataset_file
    if resolved_dataset is None:
        raise CaptureProfileError(
            "snapshot 缺少 dataset 來源：spec-emit 模式需先 emit_spec_world 取得 world 路徑"
        )
    command = [
        str(IOS_OPS),
        "catalog",
        "snapshots",
        "--destination",
        profile.snapshot.destination,
        "--dataset-file",
        str(resolved_dataset),
    ]
    for group in profile.snapshot.groups:
        command.extend(["--group", group])
    for scenario in profile.snapshot.scenarios:
        command.extend(["--scenario", scenario])
    if reuse_build:
        command.append("--reuse-build")
    command.append("--json")
    return command


def build_world_diff_command(profile: CaptureProfile) -> list[str] | None:
    if profile.materialize is None or profile.materialize.expectation_file is None:
        return None
    return [
        str(SAFE_WRAPPER),
        "ops-cli",
        "world-diff",
        profile.materialize.uid,
        str(profile.materialize.expectation_file),
        "--json",
    ]


def build_emit_commands(profile: CaptureProfile, out_path: Path) -> list[list[str]]:
    """spec-emit 模式：導出「把 world emit 到 out_path」的確定式指令序列。

    有 planFile → 先 shape_history 把 spec 依 history_plan 重錨到暫存 spec（冪等），
    再 emit-ios 投影成 UI World；無 planFile → 直接 emit committed spec。全程走
    capture_profile 自身的 uv-3.13 直譯器（stdlib + sibling 模組，無 backend 依賴）。
    """
    if profile.snapshot.source != SOURCE_SPEC_EMIT:
        raise CaptureProfileError("build_emit_commands 僅適用 spec-emit 模式")
    if profile.snapshot.spec_file is None:
        raise CaptureProfileError("spec-emit 模式缺少 snapshot.specFile")

    commands: list[list[str]] = []
    spec_for_emit: Path = profile.snapshot.spec_file
    plan_args: list[str] = []
    if profile.snapshot.plan_file is not None:
        reshaped_spec = out_path.parent / f"{out_path.stem}.spec.json"
        commands.append([
            sys.executable,
            str(SHAPE_HISTORY),
            str(profile.snapshot.spec_file),
            str(profile.snapshot.plan_file),
            "--out",
            str(reshaped_spec),
        ])
        spec_for_emit = reshaped_spec
        # 有 plan → 同時把 review 時鐘凍結在 anchor（emit-ios --plan），
        # capture 出的世界不隨牆鐘漂移；freeze 為 plan 的確定式純函式。
        plan_args = ["--plan", str(profile.snapshot.plan_file)]
    commands.append([
        sys.executable,
        str(BUILD_DEMO),
        "emit-ios",
        "--spec",
        str(spec_for_emit),
        "--out",
        str(out_path),
        *plan_args,
        "--commit",
        "--json",
    ])
    return commands


def emit_spec_world(profile: CaptureProfile) -> tuple[Path, list[dict[str, Any]]]:
    """執行 spec-emit：產出暫存 UI World，過 manifest validate（fail-loud），回傳路徑。

    暫存於 build/capture_profiles/emit-<id>-*/ui_world.json，不 commit 生成物；
    world 由 spec（+plan）確定式派生（datasetID = spec 內容 hash），可復現。
    """
    if profile.snapshot.source != SOURCE_SPEC_EMIT:
        raise CaptureProfileError("emit_spec_world 僅適用 spec-emit 模式")
    capture_root = ROOT / "build" / "capture_profiles"
    capture_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"emit-{profile.profile_id}-", dir=str(capture_root)))
    world_path = workdir / "ui_world.json"

    results: list[dict[str, Any]] = []
    for command in build_emit_commands(profile, world_path):
        result = run_command(command)
        results.append(
            {
                "command": command,
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            raise CaptureProfileError(
                f"spec-emit 步驟失敗（exit {result.returncode}）: "
                f"{result.stderr.strip() or result.stdout.strip() or command}"
            )
    if not world_path.exists():
        raise CaptureProfileError(f"spec-emit 未產出 world: {world_path}")
    validate_fixture_dataset_file(world_path)
    return world_path, results


def build_prepare_command(profile: CaptureProfile) -> list[str]:
    return [
        str(IOS_OPS),
        "catalog",
        "prepare",
        "--destination",
        profile.snapshot.destination,
        "--json",
    ]


def build_render_command(
    profile: CaptureProfile,
    *,
    source_dir: Path | None = None,
    shots_json: Path | None = None,
) -> list[str]:
    command = [
        str(PROMO_RENDER),
        "--variant",
        profile.render.variant,
        "--target",
        profile.render.target,
    ]
    if source_dir is not None:
        command.extend(["--source-dir", str(source_dir)])
    if shots_json is not None:
        command.extend(["--shots-json", str(shots_json)])
    if profile.render.output_dir is not None:
        command.extend(["--output-dir", str(profile.render.output_dir)])
    return command


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def build_expectation(profile: CaptureProfile) -> dict[str, Any]:
    """從 profile 的 seedFile + materialize.steps 純宣告導出 world expectation。

    不讀 DB；產物即可取代手寫 expectationFile，消除 spec drift 來源。card↔notebook
    membership 不在斷言範圍（derive 不導 card.notebook），與 ops_world_diff 以 content
    為 card key 的 scope 一致。
    """
    if profile.materialize is None:
        raise CaptureProfileError("profile 無 materialize（spec-emit 模式），無法導出 expectation")
    seed = json.loads(profile.materialize.seed_file.read_text(encoding="utf-8"))
    steps = [{"subcommand": s.subcommand, "args": s.args} for s in profile.materialize.steps]
    return derive_expectation(seed, steps)


def cmd_derive_expectation(
    profile: CaptureProfile, *, out: Path | None = None, check: bool = False
) -> int:
    """從 seed/steps 導出 expectation 寫檔（或 --check 驗 stale）。"""
    spec = build_expectation(profile)
    target = out or profile.materialize.expectation_file
    if check:
        if target is None or not Path(target).exists():
            emit_json({"schema": "kg.capture.run.v1", "action": "derive-expectation",
                       "status": "error", "error": "無 expectation 檔可比對"})
            return 1
        current = json.loads(Path(target).read_text(encoding="utf-8"))
        drift = current != spec
        emit_json({"schema": "kg.capture.run.v1", "action": "derive-expectation",
                   "status": "drift" if drift else "ok", "path": str(target)})
        return 1 if drift else 0
    text = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
    if target is None:
        sys.stdout.write(text)
        return 0
    Path(target).write_text(text, encoding="utf-8")
    emit_json({"schema": "kg.capture.run.v1", "action": "derive-expectation",
               "status": "written", "path": str(target)})
    return 0


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError as exc:
        logger.debug("failed to parse capture subprocess stdout as json: %s", exc)
        return None


def should_prepare_cache(snapshot_result: subprocess.CompletedProcess[str], snapshot_payload: dict[str, Any] | None) -> bool:
    if snapshot_result.returncode == 87:
        return True
    if not snapshot_payload:
        return False
    test_exit = snapshot_payload.get("test", {}).get("exitCode")
    return test_exit == 87


def snapshot_slug(raw: str) -> str:
    # 鏡像 catalog 的 PlaybookSnapshot.Snapshot.normalize（權威 SoT：
    # ios/BooksAndVocabTests/CatalogSnapshotTests.swift:331-338）——把 `. : /` 與所有
    # whitespace 當分隔符轉 _，保留其他所有字元（middle-dot ·、括號、em-dash、加號、
    # hyphen、%、CJK 等）。舊版把所有非 alnum 轉 _，對含 ·／()等的 title 與 catalog
    # 檔名不符 → resolve missing（只 replace 空格則對含 . : / 的 title 又會漏）。
    return re.sub(r"[.:/\s]", "_", raw)


def resolve_shot_artifacts(profile: CaptureProfile, snapshot_payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_paths = [Path(path) for path in snapshot_payload.get("artifacts", {}).get("paths", [])]
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for index, shot in enumerate(profile.shots, start=1):
        try:
            category, title = shot.source_scenario.split("/", 1)
        except ValueError as exc:
            raise CaptureProfileError(f"shots.sourceScenario 格式必須是 Category/Title: {shot.source_scenario}") from exc
        suffix = f"/{snapshot_slug(category)}/{snapshot_slug(title)}.png"
        candidates = [path for path in artifact_paths if str(path).endswith(suffix)]
        if shot.appearance == "light":
            candidates = [path for path in candidates if "(dark)" not in str(path)]
        else:
            candidates = [path for path in candidates if "(dark)" in str(path)]
        # App Store iPhone 直式圖：偏好 iPhone portrait。catalog 固定渲染
        # iPhone 15 Pro portrait + iPad Pro 11 landscape 兩 device，且 iPad landscape
        # 排序在前——不加偏好會誤選橫向 iPad 圖套進直式框。退回任何符合外觀者。
        portrait = [path for path in candidates if "iPhone" in str(path) and "landscape" not in str(path)]
        match = next(iter(portrait or candidates), None)
        if match is None:
            missing.append(shot.source_scenario)
            continue
        resolved.append(
            {
                "id": shot.shot_id,
                "sourceScenario": shot.source_scenario,
                "appearance": shot.appearance,
                "rawPath": str(match),
                "sourceStem": f"{index:02d}_{shot.shot_id}",
                "outputName": shot.output_name,
                "copy": {
                    "title": shot.copy_title,
                    "subtitle": shot.copy_subtitle,
                },
            }
        )
    if missing:
        raise CaptureProfileError(f"snapshot artifacts 缺少 shots 對應場景: {', '.join(missing)}")
    return resolved


def frame_snapshot_sources(profile: CaptureProfile, snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    capture_root = ROOT / "build" / "capture_profiles"
    capture_root.mkdir(parents=True, exist_ok=True)
    workspace_root = Path(
        tempfile.mkdtemp(prefix=f"capture-{profile.profile_id}-", dir=str(capture_root))
    )
    raw_root = workspace_root / "raw"
    framed_root = workspace_root / "framed"
    shots_json = workspace_root / "shots.json"
    raw_root.mkdir(parents=True, exist_ok=True)
    framed_root.mkdir(parents=True, exist_ok=True)

    shots = resolve_shot_artifacts(profile, snapshot_payload)
    shots_json.write_text(json.dumps(shots, ensure_ascii=False, indent=2))

    command = [
        str(FRAME_RENDER),
        "--shots-json",
        str(shots_json),
        "--output-dir",
        str(framed_root),
    ]
    result = run_command(command)
    if result.returncode != 0:
        raise CaptureProfileError(
            f"frame catalog screenshots failed: {result.stderr.strip() or result.stdout.strip() or 'unknown error'}"
        )
    outputs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {
        "workspaceRoot": str(workspace_root),
        "shotsJson": str(shots_json),
        "framedSourceDir": str(framed_root),
        "rawRoot": str(raw_root),
        "shots": shots,
        "outputs": outputs,
        "command": command,
    }


def reviewer_render_spec(profile: CaptureProfile) -> dict[str, Any]:
    """Normalize the render contract embedded in reviewer evidence."""
    return {
        "variant": profile.render.variant,
        "target": profile.render.target,
        "sourceMode": profile.render.source_mode,
        "shots": [
            {
                "id": shot.shot_id,
                "sourceScenario": shot.source_scenario,
                "appearance": shot.appearance,
                "outputName": shot.output_name,
                "copy": {"title": shot.copy_title, "subtitle": shot.copy_subtitle},
            }
            for shot in profile.shots
        ],
    }


def resolve_source_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CaptureProfileError(
            f"source commit 無法解析為完整 git commit: {ref}"
        )
    return commit


def resolve_project_file(
    project_file: Path | None, resolved_commit: str, destination: Path
) -> Path:
    """The pbxproj this bundle will describe, defaulting to the pinned commit's blob.

    The old default was the working tree's copy, which belongs to no commit in
    particular: pairing it with ``--source-commit`` produced a bundle that named
    one commit and carried another's build identity.  An explicitly passed path
    is still honoured — callers stage files legitimately — but it is now a named
    act rather than what happens when you say nothing, and
    ``app_review_gate.py`` re-derives the blob independently either way.
    """
    if project_file is not None:
        return project_file
    return materialize_tracked_file(
        workspace_root=ROOT,
        commit=resolved_commit,
        rel_path=IOS_PROJECT_FILE_REL,
        destination=destination,
    )


def cmd_reviewer_evidence(
    profile: CaptureProfile,
    *,
    profile_file: Path,
    dataset_file: Path,
    promotion_manifest_file: Path,
    render_output_dir: Path,
    bundle_dir: Path,
    project_file: Path | None,
    source_commit: str,
    fixed_clock: str,
    locale: str,
    expect_marketing_version: str | None,
    expect_build_number: str | None,
    commit: bool,
) -> int:
    """Build or atomically write a deterministic App Review evidence bundle."""
    try:
        resolved_commit = resolve_source_commit(source_commit)
        # The materialized blob has to outlive both the manifest build and the
        # bundle write, which copies it into inputs/.
        with tempfile.TemporaryDirectory(prefix="kg-reviewer-evidence-source-") as pinned:
            project_file = resolve_project_file(
                project_file, resolved_commit, Path(pinned) / "project.pbxproj"
            )
            manifest = build_reviewer_evidence_manifest(
                profile_file=profile_file,
                profile_id=profile.profile_id,
                dataset_file=dataset_file,
                promotion_manifest_file=promotion_manifest_file,
                project_file=project_file,
                render_output_dir=render_output_dir,
                render_spec=reviewer_render_spec(profile),
                device_destination=profile.snapshot.destination,
                locale=locale,
                fixed_clock=fixed_clock,
                source_commit=resolved_commit,
                generator_files=[Path(__file__).resolve(), REVIEWER_EVIDENCE],
                profile_validator=load_profile,
                dataset_validator=validate_fixture_dataset_file,
                expected_marketing_version=expect_marketing_version,
                expected_build_number=expect_build_number,
            )
            if commit:
                write_reviewer_evidence_bundle(
                    manifest,
                    bundle_dir=bundle_dir,
                    profile_file=profile_file,
                    dataset_file=dataset_file,
                    project_file=project_file,
                    promotion_manifest_file=promotion_manifest_file,
                    render_output_dir=render_output_dir,
                    profile_validator=load_profile,
                    dataset_validator=validate_fixture_dataset_file,
                )
    except EvidenceError as exc:
        raise CaptureProfileError(str(exc)) from exc

    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "reviewer-evidence",
            "profile": profile.profile_id,
            "status": "written" if commit else "dry-run",
            "commit": commit,
            "bundle": str(bundle_dir),
            "manifest": manifest,
        }
    )
    return 0


def cmd_plan(profile: CaptureProfile) -> int:
    verify_command = build_world_diff_command(profile)
    materialize_plan: dict[str, Any] | None = None
    if profile.materialize is not None:
        materialize_plan = {
            "uid": profile.materialize.uid,
            "seedFile": str(profile.materialize.seed_file),
            "expectationFile": str(profile.materialize.expectation_file) if profile.materialize.expectation_file else None,
            "steps": [
                {"subcommand": "seed", "args": [profile.materialize.uid, str(profile.materialize.seed_file)]},
                *[
                    {"subcommand": step.subcommand, "args": [profile.materialize.uid, *step.args]}
                    for step in profile.materialize.steps
                ],
            ],
        }
    emit_section: dict[str, Any] = {"enabled": False, "commands": None}
    if profile.snapshot.source == SOURCE_SPEC_EMIT:
        # plan 用代表性 out 路徑呈現指令（實際 run 時落在 build/capture_profiles/emit-*）。
        placeholder = ROOT / "build" / "capture_profiles" / f"emit-{profile.profile_id}" / "ui_world.json"
        emit_section = {
            "enabled": True,
            "specFile": str(profile.snapshot.spec_file),
            "planFile": str(profile.snapshot.plan_file) if profile.snapshot.plan_file else None,
            "commands": build_emit_commands(profile, placeholder),
        }
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "plan",
            "profile": profile.profile_id,
            "materialize": materialize_plan,
            "verify": {
                "enabled": verify_command is not None,
                "command": verify_command,
            },
            "emit": emit_section,
            "snapshot": {
                "source": profile.snapshot.source,
                "datasetFile": str(profile.snapshot.dataset_file) if profile.snapshot.dataset_file else None,
                "specFile": str(profile.snapshot.spec_file) if profile.snapshot.spec_file else None,
                "planFile": str(profile.snapshot.plan_file) if profile.snapshot.plan_file else None,
                "destination": profile.snapshot.destination,
                "groups": profile.snapshot.groups,
                "scenarios": profile.snapshot.scenarios,
            },
            "render": {
                "script": str(PROMO_RENDER),
                "variant": profile.render.variant,
                "target": profile.render.target,
                "sourceMode": profile.render.source_mode,
                "autoRunEligible": profile.render.source_mode == "snapshot-derived",
                "outputDir": str(profile.render.output_dir) if profile.render.output_dir else None,
            },
            "shots": [
                {
                    "id": shot.shot_id,
                    "sourceScenario": shot.source_scenario,
                    "outputName": shot.output_name,
                    "appearance": shot.appearance,
                    "copy": {"title": shot.copy_title, "subtitle": shot.copy_subtitle},
                }
                for shot in profile.shots
            ],
        }
    )
    return 0


def cmd_materialize(profile: CaptureProfile, *, commit: bool) -> int:
    commands = build_ops_edit_commands(profile, commit=commit)
    if not commit:
        emit_json(
            {
                "schema": "kg.capture.run.v1",
                "action": "materialize",
                "profile": profile.profile_id,
                "commit": False,
                "status": "dry-run",
                "results": [{"command": command, "planned": True} for command in commands],
            }
        )
        return 0
    results = []
    failed = False
    for command in commands:
        result = run_command(command)
        results.append(
            {
                "command": command,
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            failed = True
            break
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "materialize",
            "profile": profile.profile_id,
            "commit": commit,
            "status": "error" if failed else "ok",
            "results": results,
        }
    )
    return 1 if failed else 0


def cmd_snapshot(profile: CaptureProfile, *, reuse_build: bool) -> int:
    dataset_file: Path | None = None
    emit_step: dict[str, Any] | None = None
    if profile.snapshot.source == SOURCE_SPEC_EMIT:
        world_path, emit_results = emit_spec_world(profile)
        dataset_file = world_path
        emit_step = {"world": str(world_path), "steps": emit_results}
    command = build_snapshot_command(profile, reuse_build=reuse_build, dataset_file=dataset_file)
    result = run_command(command)
    payload = parse_json_stdout(result)
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "snapshot",
            "profile": profile.profile_id,
            "reuseBuild": reuse_build,
            "status": "ok" if result.returncode == 0 else "error",
            "emit": emit_step,
            "command": command,
            "snapshot": payload,
            "stderr": result.stderr,
        }
    )
    return result.returncode


def cmd_render(profile: CaptureProfile) -> int:
    raise CaptureProfileError("snapshot-derived render 需透過 run 先產生 framed source；目前不支援單獨 render")


def cmd_verify(profile: CaptureProfile) -> int:
    command = build_world_diff_command(profile)
    if command is None:
        raise CaptureProfileError("profile 未設定 materialize.expectationFile，無法 verify")
    result = run_command(command)
    payload = parse_json_stdout(result)
    ok = result.returncode == 0 and bool(payload and payload.get("ok") is True)
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "verify",
            "profile": profile.profile_id,
            "status": "ok" if ok else "error",
            "command": command,
            "verify": payload,
            "stderr": result.stderr,
        }
    )
    return 0 if ok else 2


def cmd_run(profile: CaptureProfile, *, commit: bool, reuse_build: bool) -> int:
    materialize_commands = build_ops_edit_commands(profile, commit=commit)
    materialize_results = []
    verify_step: dict[str, Any] | None = None
    if commit:
        for command in materialize_commands:
            result = run_command(command)
            materialize_results.append(
                {
                    "command": command,
                    "exitCode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode != 0:
                emit_json(
                    {
                        "schema": "kg.capture.run.v1",
                        "action": "run",
                        "profile": profile.profile_id,
                        "commit": commit,
                        "reuseBuild": reuse_build,
                        "status": "error",
                        "materialize": materialize_results,
                        "verify": None,
                        "snapshot": None,
                        "render": None,
                    }
                )
                return 1
        verify_command = build_world_diff_command(profile)
        if verify_command is not None:
            verify_result = run_command(verify_command)
            verify_payload = parse_json_stdout(verify_result)
            verify_ok = verify_result.returncode == 0 and bool(verify_payload and verify_payload.get("ok") is True)
            verify_step = {
                "command": verify_command,
                "exitCode": verify_result.returncode,
                "payload": verify_payload,
                "stderr": verify_result.stderr,
            }
            if not verify_ok:
                emit_json(
                    {
                        "schema": "kg.capture.run.v1",
                        "action": "run",
                        "profile": profile.profile_id,
                        "commit": commit,
                        "reuseBuild": reuse_build,
                        "status": "error",
                        "materialize": materialize_results,
                        "verify": verify_step,
                        "snapshot": None,
                        "render": None,
                    }
                )
                return 2
    else:
        materialize_results = [{"command": command, "planned": True} for command in materialize_commands]
        verify_command = build_world_diff_command(profile)
        if verify_command is not None:
            verify_step = {"command": verify_command, "planned": True}

    dataset_file: Path | None = None
    emit_step: dict[str, Any] | None = None
    if profile.snapshot.source == SOURCE_SPEC_EMIT:
        try:
            world_path, emit_results = emit_spec_world(profile)
        except CaptureProfileError as exc:
            emit_json(
                {
                    "schema": "kg.capture.run.v1",
                    "action": "run",
                    "profile": profile.profile_id,
                    "commit": commit,
                    "reuseBuild": reuse_build,
                    "status": "error",
                    "materialize": materialize_results,
                    "verify": verify_step,
                    "emit": {"status": "error", "error": str(exc)},
                    "snapshot": None,
                    "render": None,
                }
            )
            return 1
        dataset_file = world_path
        emit_step = {"world": str(world_path), "steps": emit_results}

    snapshot_command = build_snapshot_command(profile, reuse_build=reuse_build, dataset_file=dataset_file)
    snapshot_result = run_command(snapshot_command)
    snapshot_payload = parse_json_stdout(snapshot_result)
    prepare_step: dict[str, Any] | None = None
    if reuse_build and should_prepare_cache(snapshot_result, snapshot_payload):
        prepare_command = build_prepare_command(profile)
        prepare_result = run_command(prepare_command)
        prepare_payload = parse_json_stdout(prepare_result)
        prepare_step = {
            "command": prepare_command,
            "exitCode": prepare_result.returncode,
            "payload": prepare_payload,
            "stderr": prepare_result.stderr,
        }
        if prepare_result.returncode == 0:
            snapshot_result = run_command(snapshot_command)
            snapshot_payload = parse_json_stdout(snapshot_result)
    if snapshot_result.returncode != 0:
        emit_json(
            {
                "schema": "kg.capture.run.v1",
                "action": "run",
                "profile": profile.profile_id,
                "commit": commit,
                "reuseBuild": reuse_build,
                "status": "error",
                "materialize": materialize_results,
                "verify": verify_step,
                "emit": emit_step,
                "snapshot": {
                    "command": snapshot_command,
                    "exitCode": snapshot_result.returncode,
                    "payload": snapshot_payload,
                    "stderr": snapshot_result.stderr,
                    "prepare": prepare_step,
                },
                "render": None,
            }
        )
        return snapshot_result.returncode

    bridge = frame_snapshot_sources(profile, snapshot_payload or {})
    render_command = build_render_command(
        profile,
        source_dir=Path(bridge["framedSourceDir"]),
        shots_json=Path(bridge["shotsJson"]),
    )
    render_result = run_command(render_command)
    render_outputs = [line.strip() for line in render_result.stdout.splitlines() if line.strip()]
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "run",
            "profile": profile.profile_id,
            "commit": commit,
            "reuseBuild": reuse_build,
            "status": "ok" if render_result.returncode == 0 else "error",
            "materialize": materialize_results,
            "verify": verify_step,
            "emit": emit_step,
            "snapshot": {
                "command": snapshot_command,
                "exitCode": snapshot_result.returncode,
                "payload": snapshot_payload,
                "stderr": snapshot_result.stderr,
                "prepare": prepare_step,
            },
            "bridge": bridge,
            "render": {
                "command": render_command,
                "exitCode": render_result.returncode,
                "variant": profile.render.variant,
                "target": profile.render.target,
                "sourceMode": profile.render.source_mode,
                "outputDir": str(profile.render.output_dir) if profile.render.output_dir else None,
                "outputs": render_outputs,
                "stderr": render_result.stderr,
            },
        }
    )
    return render_result.returncode


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="run capture profiles that combine ops-edit, ios_ops, and promo rendering")
    sub = parser.add_subparsers(dest="action", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("profile")

    materialize = sub.add_parser("materialize")
    materialize.add_argument("profile")
    materialize.add_argument("--commit", action="store_true")

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("profile")
    snapshot.add_argument("--reuse-build", action="store_true")

    verify = sub.add_parser("verify")
    verify.add_argument("profile")

    render = sub.add_parser("render")
    render.add_argument("profile")

    derive = sub.add_parser("derive-expectation")
    derive.add_argument("profile")
    derive.add_argument("--out", help="輸出路徑（預設 profile 的 expectationFile；未設則印 stdout）")
    derive.add_argument("--check", action="store_true", help="只驗現有 expectation 檔是否 stale，drift 回非零")

    evidence = sub.add_parser(
        "reviewer-evidence",
        help="build a deterministic App Review reviewer-evidence manifest/bundle (dry-run by default)",
        description=(
            "Pin capture profile, validated UI World, actual Xcode build tuple, source commit, "
            "fixed clock, device/locale, render spec, and output checksums. Dry-run by default; "
            "add --commit to atomically write the bundle."
        ),
    )
    evidence.add_argument("profile", help="kg.capture.profile.v1 file")
    evidence.add_argument(
        "--dataset-file", required=True,
        help="exact kg.fixture.dataset.v2 UI World used for reviewer capture",
    )
    evidence.add_argument(
        "--render-output-dir", required=True,
        help="directory containing every profile shots[].outputName PNG",
    )
    evidence.add_argument(
        "--promotion-manifest", required=True,
        help=(
            "generated kg.app_review.promotion_manifest.v1 JSON; legacy YAML and "
            "unknown/skipped/stale evidence fail closed"
        ),
    )
    evidence.add_argument(
        "--bundle-dir", required=True,
        help="destination bundle directory (not created without --commit)",
    )
    evidence.add_argument(
        "--project-file",
        help=(
            "Xcode project.pbxproj used to read the actual marketing/build tuple; "
            "defaults to that file as recorded at --source-commit, never the working tree"
        ),
    )
    evidence.add_argument(
        "--source-commit", required=True,
        help="git commit/ref to resolve and pin in provenance; which commit the bundle claims is the caller's assertion",
    )
    evidence.add_argument(
        "--fixed-clock", required=True,
        help="timezone-aware ISO8601 capture clock; required to prevent wall-clock drift",
    )
    evidence.add_argument(
        "--locale", required=True,
        help="pinned capture locale, for example zh-Hant",
    )
    evidence.add_argument(
        "--expect-marketing-version",
        help="fail closed unless the actual project MARKETING_VERSION matches",
    )
    evidence.add_argument(
        "--expect-build-number",
        help="fail closed unless the actual project CURRENT_PROJECT_VERSION matches",
    )
    evidence.add_argument(
        "--commit", action="store_true",
        help="atomically write inputs, outputs, and manifest.json (default is dry-run)",
    )

    run = sub.add_parser("run")
    run.add_argument("profile")
    run.add_argument("--commit", action="store_true")
    run.add_argument("--reuse-build", action="store_true")

    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
        if args.action == "plan":
            return cmd_plan(profile)
        if args.action == "materialize":
            return cmd_materialize(profile, commit=args.commit)
        if args.action == "snapshot":
            return cmd_snapshot(profile, reuse_build=args.reuse_build)
        if args.action == "verify":
            return cmd_verify(profile)
        if args.action == "render":
            return cmd_render(profile)
        if args.action == "derive-expectation":
            return cmd_derive_expectation(
                profile, out=Path(args.out) if args.out else None, check=args.check
            )
        if args.action == "reviewer-evidence":
            return cmd_reviewer_evidence(
                profile,
                profile_file=_resolve_path(args.profile),
                dataset_file=_resolve_path(args.dataset_file),
                promotion_manifest_file=_resolve_path(args.promotion_manifest),
                render_output_dir=_resolve_path(args.render_output_dir),
                bundle_dir=_resolve_path(args.bundle_dir),
                project_file=_resolve_path(args.project_file) if args.project_file else None,
                source_commit=args.source_commit,
                fixed_clock=args.fixed_clock,
                locale=args.locale,
                expect_marketing_version=args.expect_marketing_version,
                expect_build_number=args.expect_build_number,
                commit=args.commit,
            )
        if args.action == "run":
            return cmd_run(profile, commit=args.commit, reuse_build=args.reuse_build)
    except CaptureProfileError as exc:
        emit_json({"schema": "kg.capture.run.v1", "action": "error", "status": "error", "error": str(exc)})
        logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

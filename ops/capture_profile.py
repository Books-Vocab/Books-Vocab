#!/usr/bin/env -S uv run --python 3.13 python
"""Capture profile runner: combine ops-edit shaping and iOS catalog snapshots."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAFE_WRAPPER = ROOT / "ops" / "devops_kg_safe.sh"
IOS_OPS = ROOT / "ops" / "ios_ops.sh"
PROMO_RENDER = ROOT / "promotion" / "screenshots" / "scripts" / "render_screenshots.py"
FRAME_RENDER = ROOT / "promotion" / "screenshots" / "scripts" / "frame_catalog_screenshots.py"

# 純宣告轉換（不讀 DB），用來從 seed/steps 自動導出 world expectation。
sys.path.insert(0, str(ROOT / "backend" / "src"))
from kg.ops_world_expectation import derive_expectation  # noqa: E402


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
    dataset_file: Path
    destination: str
    groups: list[str]
    scenarios: list[str]


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
    materialize: MaterializeConfig
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


def load_profile(path: str | Path) -> CaptureProfile:
    profile_path = _resolve_path(str(path))
    if not profile_path.exists():
        raise CaptureProfileError(f"profile 不存在: {profile_path}")
    data = json.loads(profile_path.read_text())
    if data.get("schema") != "kg.capture.profile.v1":
        raise CaptureProfileError("schema 必須是 kg.capture.profile.v1")

    materialize_raw = data.get("materialize")
    if not isinstance(materialize_raw, dict):
        raise CaptureProfileError("materialize 必須存在且為 object")
    snapshot_raw = data.get("snapshot")
    if not isinstance(snapshot_raw, dict):
        raise CaptureProfileError("snapshot 必須存在且為 object")

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

    snapshot = SnapshotConfig(
        dataset_file=_resolve_path(_ensure_str(snapshot_raw.get("datasetFile"), field="snapshot.datasetFile")),
        destination=_ensure_str(snapshot_raw.get("destination"), field="snapshot.destination"),
        groups=[str(item) for item in _ensure_list(snapshot_raw.get("groups"), field="snapshot.groups")],
        scenarios=[str(item) for item in _ensure_list(snapshot_raw.get("scenarios"), field="snapshot.scenarios")],
    )
    if not snapshot.dataset_file.exists():
        raise CaptureProfileError(f"dataset file 不存在: {snapshot.dataset_file}")

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


def build_snapshot_command(profile: CaptureProfile, *, reuse_build: bool) -> list[str]:
    command = [
        str(IOS_OPS),
        "catalog",
        "snapshots",
        "--destination",
        profile.snapshot.destination,
        "--dataset-file",
        str(profile.snapshot.dataset_file),
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
    if profile.materialize.expectation_file is None:
        return None
    return [
        str(SAFE_WRAPPER),
        "ops-cli",
        "world-diff",
        profile.materialize.uid,
        str(profile.materialize.expectation_file),
        "--json",
    ]


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
    return "".join(char if char.isalnum() else "_" for char in raw)


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
        match = next((path for path in artifact_paths if str(path).endswith(suffix)), None)
        if shot.appearance == "light":
            match = next((path for path in artifact_paths if str(path).endswith(suffix) and "(dark)" not in str(path)), match)
        else:
            match = next((path for path in artifact_paths if str(path).endswith(suffix) and "(dark)" in str(path)), match)
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


def cmd_plan(profile: CaptureProfile) -> int:
    verify_command = build_world_diff_command(profile)
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "plan",
            "profile": profile.profile_id,
            "materialize": {
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
            },
            "verify": {
                "enabled": verify_command is not None,
                "command": verify_command,
            },
            "snapshot": {
                "datasetFile": str(profile.snapshot.dataset_file),
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
    command = build_snapshot_command(profile, reuse_build=reuse_build)
    result = run_command(command)
    payload = parse_json_stdout(result)
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "snapshot",
            "profile": profile.profile_id,
            "reuseBuild": reuse_build,
            "status": "ok" if result.returncode == 0 else "error",
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

    snapshot_command = build_snapshot_command(profile, reuse_build=reuse_build)
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
        if args.action == "run":
            return cmd_run(profile, commit=args.commit, reuse_build=args.reuse_build)
    except CaptureProfileError as exc:
        emit_json({"schema": "kg.capture.run.v1", "action": "error", "status": "error", "error": str(exc)})
        logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

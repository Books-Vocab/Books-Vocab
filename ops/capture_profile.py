#!/usr/bin/env -S uv run python
"""Capture profile runner: combine ops-edit shaping and iOS catalog snapshots."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAFE_WRAPPER = ROOT / "ops" / "devops_kg_safe.sh"
IOS_OPS = ROOT / "ops" / "ios_ops.sh"
PROMO_RENDER = ROOT / "promotion" / "screenshots" / "scripts" / "render_screenshots.py"


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
class CaptureProfile:
    profile_id: str
    materialize: MaterializeConfig
    snapshot: SnapshotConfig
    render: RenderConfig


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
        steps=steps,
    )
    if not materialize.seed_file.exists():
        raise CaptureProfileError(f"seed file 不存在: {materialize.seed_file}")

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

    return CaptureProfile(
        profile_id=_ensure_str(data.get("id"), field="id"),
        materialize=materialize,
        snapshot=snapshot,
        render=render,
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


def build_render_command(profile: CaptureProfile) -> list[str]:
    command = [
        str(PROMO_RENDER),
        "--variant",
        profile.render.variant,
        "--target",
        profile.render.target,
    ]
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


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_plan(profile: CaptureProfile) -> int:
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "plan",
            "profile": profile.profile_id,
            "materialize": {
                "uid": profile.materialize.uid,
                "seedFile": str(profile.materialize.seed_file),
                "steps": [
                    {"subcommand": "seed", "args": [profile.materialize.uid, str(profile.materialize.seed_file)]},
                    *[
                        {"subcommand": step.subcommand, "args": [profile.materialize.uid, *step.args]}
                        for step in profile.materialize.steps
                    ],
                ],
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
        }
    )
    return 0


def cmd_materialize(profile: CaptureProfile, *, commit: bool) -> int:
    commands = build_ops_edit_commands(profile, commit=commit)
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
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else None
    except json.JSONDecodeError:
        payload = None
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
    command = build_render_command(profile)
    result = run_command(command)
    outputs = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    emit_json(
        {
            "schema": "kg.capture.run.v1",
            "action": "render",
            "profile": profile.profile_id,
            "status": "ok" if result.returncode == 0 else "error",
            "command": command,
            "render": {
                "variant": profile.render.variant,
                "target": profile.render.target,
                "sourceMode": profile.render.source_mode,
                "outputDir": str(profile.render.output_dir) if profile.render.output_dir else None,
                "outputs": outputs,
            },
            "stderr": result.stderr,
        }
    )
    return result.returncode


def cmd_run(profile: CaptureProfile, *, commit: bool, reuse_build: bool) -> int:
    materialize_commands = build_ops_edit_commands(profile, commit=commit)
    materialize_results = []
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
                    "snapshot": None,
                    "render": None,
                }
            )
            return 1

    snapshot_command = build_snapshot_command(profile, reuse_build=reuse_build)
    snapshot_result = run_command(snapshot_command)
    try:
        snapshot_payload = json.loads(snapshot_result.stdout) if snapshot_result.stdout.strip() else None
    except json.JSONDecodeError:
        snapshot_payload = None
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
                "snapshot": {
                    "command": snapshot_command,
                    "exitCode": snapshot_result.returncode,
                    "payload": snapshot_payload,
                    "stderr": snapshot_result.stderr,
                },
                "render": None,
            }
        )
        return snapshot_result.returncode

    if profile.render.source_mode != "snapshot-derived":
        emit_json(
            {
                "schema": "kg.capture.run.v1",
                "action": "run",
                "profile": profile.profile_id,
                "commit": commit,
                "reuseBuild": reuse_build,
                "status": "manual",
                "materialize": materialize_results,
                "snapshot": {
                    "command": snapshot_command,
                    "exitCode": snapshot_result.returncode,
                    "payload": snapshot_payload,
                    "stderr": snapshot_result.stderr,
                },
                "render": {
                    "command": build_render_command(profile),
                    "status": "manual",
                    "variant": profile.render.variant,
                    "target": profile.render.target,
                    "sourceMode": profile.render.source_mode,
                    "reason": "current render pipeline consumes checked-in framed sources, not the freshly exported catalog snapshots",
                    "outputDir": str(profile.render.output_dir) if profile.render.output_dir else None,
                },
            }
        )
        return 0

    render_command = build_render_command(profile)
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
            "snapshot": {
                "command": snapshot_command,
                "exitCode": snapshot_result.returncode,
                "payload": snapshot_payload,
                "stderr": snapshot_result.stderr,
            },
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

    render = sub.add_parser("render")
    render.add_argument("profile")

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
        if args.action == "render":
            return cmd_render(profile)
        if args.action == "run":
            return cmd_run(profile, commit=args.commit, reuse_build=args.reuse_build)
    except CaptureProfileError as exc:
        emit_json({"schema": "kg.capture.run.v1", "action": "error", "status": "error", "error": str(exc)})
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

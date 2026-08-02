#!/usr/bin/env -S uv run --python 3.13
"""Deterministic App Review reviewer-evidence manifest and bundle primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA = "kg.app_review.submission.v1"
PROMOTION_MANIFEST_SCHEMA = "kg.app_review.promotion_manifest.v1"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_MARKETING_RE = re.compile(r"MARKETING_VERSION\s*=\s*([^;\s]+)\s*;")
_BUILD_RE = re.compile(r"CURRENT_PROJECT_VERSION\s*=\s*([0-9]+)\s*;")


class EvidenceError(RuntimeError):
    """Reviewer-evidence inputs cannot produce an assertable bundle."""


SemanticValidator = Callable[[Path], Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Stable serialization: no wall clock, destination path, or insertion ordering."""
    return (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _require_file(path: Path, *, label: str) -> None:
    if not path.is_file():
        raise EvidenceError(f"{label} 不存在或不是檔案: {path}")


def _run_semantic_validator(
    path: Path, validator: SemanticValidator, *, label: str
) -> None:
    try:
        validator(path)
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError(f"{label} 完整語意驗證失敗: {exc}") from exc


def _validate_fixed_clock(value: str) -> None:
    if "T" not in value:
        raise EvidenceError("fixed clock 必須是含時區的 ISO8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("fixed clock 必須是含時區的 ISO8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceError("fixed clock 必須明示時區")


def _logical_tool_path(path: Path) -> str:
    parts = path.resolve().parts
    try:
        index = len(parts) - 1 - list(reversed(parts)).index("ops")
    except ValueError:
        return path.name
    return "/".join(parts[index:])


def _read_build_identity(project_file: Path) -> tuple[str, str, str]:
    """Read tuple and digest from one immutable byte snapshot."""
    _require_file(project_file, label="Xcode project file")
    try:
        payload = project_file.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"Xcode project 無法讀取: {project_file}") from exc
    marketing = _MARKETING_RE.search(text)
    build = _BUILD_RE.search(text)
    if marketing is None or build is None:
        raise EvidenceError("Xcode project 讀不到完整 build tuple")
    return (
        marketing.group(1),
        build.group(1),
        hashlib.sha256(payload).hexdigest(),
    )


def read_build_tuple(project_file: Path) -> tuple[str, str]:
    """Read the app tuple using the same first-value convention as release_bump.sh."""
    marketing, build, _digest = _read_build_identity(project_file)
    return marketing, build


def _load_dataset_identity(dataset_file: Path) -> tuple[str, str]:
    try:
        document = json.loads(dataset_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"UI World JSON 無法讀取: {dataset_file}") from exc
    if not isinstance(document, dict) or document.get("schema") != "kg.fixture.dataset.v2":
        raise EvidenceError("reviewer dataset schema 必須是 kg.fixture.dataset.v2")
    dataset_id = document.get("datasetID")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise EvidenceError("reviewer dataset 必須有非空 datasetID")
    return document["schema"], dataset_id


def _load_profile_identity(profile_file: Path) -> tuple[str, str]:
    try:
        document = json.loads(profile_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"capture profile JSON 無法讀取: {profile_file}") from exc
    if not isinstance(document, dict) or document.get("schema") != "kg.capture.profile.v1":
        raise EvidenceError("capture profile schema 必須是 kg.capture.profile.v1")
    profile_id = document.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise EvidenceError("capture profile 必須有非空 id")
    return document["schema"], profile_id


def _validated_outputs(
    render_spec: dict[str, Any], render_output_dir: Path
) -> list[dict[str, Any]]:
    shots = render_spec.get("shots")
    if not isinstance(shots, list) or not shots:
        raise EvidenceError("render spec 至少需要一筆 shots")
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            raise EvidenceError(f"render shots[{index}] 必須是 object")
        output_name = shot.get("outputName")
        shot_id = shot.get("id")
        if not isinstance(output_name, str) or not output_name:
            raise EvidenceError(f"render shots[{index}].outputName 必須是非空字串")
        if Path(output_name).name != output_name or not output_name.lower().endswith(".png"):
            raise EvidenceError(f"reviewer outputName 必須是安全檔名且為 PNG: {output_name}")
        if output_name in seen:
            raise EvidenceError(f"reviewer outputName 重複: {output_name}")
        seen.add(output_name)
        if not isinstance(shot_id, str) or not shot_id:
            raise EvidenceError(f"render shots[{index}].id 必須是非空字串")
        output_path = render_output_dir / output_name
        if not output_path.is_file():
            raise EvidenceError(f"缺少 reviewer output: {output_path}")
        size = output_path.stat().st_size
        if size <= 0:
            raise EvidenceError(f"reviewer output 是空檔: {output_path}")
        outputs.append(
            {
                "shotID": shot_id,
                "sourceScenario": shot.get("sourceScenario"),
                "appearance": shot.get("appearance"),
                "file": f"outputs/{output_name}",
                "byteSize": size,
                "sha256": sha256_file(output_path),
            }
        )
    expected_names = {Path(item["file"]).name for item in outputs}
    actual_names = {
        path.name
        for path in render_output_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    }
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise EvidenceError(
            f"reviewer output closure 不完整: missing={missing} extra={extra}"
        )
    return outputs


def validate_promotion_manifest(
    promotion_manifest_file: Path,
    *,
    profile_id: str,
    profile_digest: str,
    dataset_digest: str,
    render_spec: dict[str, Any],
    render_output_dir: Path,
) -> tuple[str, list[dict[str, Any]]]:
    """Require exact profile↔generated-manifest↔output closure; no legacy fallback."""
    _require_file(promotion_manifest_file, label="promotion manifest")
    try:
        document = json.loads(promotion_manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceError(
            "legacy/unknown promotion manifest 不可作 reviewer evidence；"
            f"必須是 {PROMOTION_MANIFEST_SCHEMA} JSON"
        ) from exc
    if not isinstance(document, dict) or document.get("schema") != PROMOTION_MANIFEST_SCHEMA:
        raise EvidenceError(f"promotion manifest schema 必須是 {PROMOTION_MANIFEST_SCHEMA}")
    required_keys = {
        "schema", "profileID", "profileSHA256", "datasetSHA256", "renderSpecSHA256", "shots"
    }
    if set(document) != required_keys:
        raise EvidenceError(
            "promotion manifest 必須是 closed-world exact keys: "
            f"missing={sorted(required_keys - set(document))} "
            f"unknown={sorted(set(document) - required_keys)}"
        )
    # Validate filesystem closure/path safety before comparing the generated
    # manifest header so an unsafe output cannot be masked as generic staleness.
    outputs = _validated_outputs(render_spec, render_output_dir)
    render_digest = _sha256_json(render_spec)
    expected_header = {
        "profileID": profile_id,
        "profileSHA256": profile_digest,
        "datasetSHA256": dataset_digest,
        "renderSpecSHA256": render_digest,
    }
    for key, expected in expected_header.items():
        if document.get(key) != expected:
            raise EvidenceError(
                f"promotion manifest stale: {key} expected={expected} actual={document.get(key)}"
            )

    manifest_shots = document.get("shots")
    if not isinstance(manifest_shots, list):
        raise EvidenceError("promotion manifest shots 必須是 array")
    expected_shots: list[dict[str, Any]] = []
    render_shots = render_spec["shots"]
    for index, (shot, output) in enumerate(zip(render_shots, outputs, strict=True)):
        expected_shots.append(
            {
                "id": shot["id"],
                "outputName": Path(output["file"]).name,
                "appearance": shot.get("appearance"),
                "status": "verified",
                "byteSize": output["byteSize"],
                "sha256": output["sha256"],
            }
        )
        if index < len(manifest_shots) and isinstance(manifest_shots[index], dict):
            status = manifest_shots[index].get("status")
            if status != "verified":
                raise EvidenceError(
                    f"required promotion evidence status={status!r} 不得 PASS: shots[{index}]"
                )
    if manifest_shots != expected_shots:
        raise EvidenceError(
            "profile↔promotion manifest↔outputs closure mismatch; "
            f"expectedShots={len(expected_shots)} actualShots={len(manifest_shots)}"
        )
    return sha256_file(promotion_manifest_file), outputs


def build_manifest(
    *,
    profile_file: Path,
    profile_id: str,
    dataset_file: Path,
    promotion_manifest_file: Path,
    project_file: Path,
    render_output_dir: Path,
    render_spec: dict[str, Any],
    device_destination: str,
    locale: str,
    fixed_clock: str,
    source_commit: str,
    generator_files: Iterable[Path],
    profile_validator: SemanticValidator,
    dataset_validator: SemanticValidator,
    expected_marketing_version: str | None = None,
    expected_build_number: str | None = None,
) -> dict[str, Any]:
    """Build the v1 contract entirely from pinned inputs; performs no writes."""
    for path, label in (
        (profile_file, "capture profile"),
        (dataset_file, "UI World"),
        (promotion_manifest_file, "promotion manifest"),
        (project_file, "Xcode project file"),
    ):
        _require_file(path, label=label)
    if not render_output_dir.is_dir():
        raise EvidenceError(f"render output directory 不存在: {render_output_dir}")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise EvidenceError("profile id 必須是非空字串")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise EvidenceError("source commit 必須是 40 位小寫 git SHA")
    _validate_fixed_clock(fixed_clock)
    if not _LOCALE_RE.fullmatch(locale):
        raise EvidenceError(f"locale 格式錯誤: {locale}")
    if not isinstance(device_destination, str) or not device_destination.strip():
        raise EvidenceError("device destination 必須是非空字串")

    _run_semantic_validator(
        profile_file, profile_validator, label="capture profile"
    )
    _run_semantic_validator(
        dataset_file, dataset_validator, label="UI World"
    )
    marketing_version, build_number, project_digest = _read_build_identity(project_file)
    if (
        expected_marketing_version is not None
        and marketing_version != expected_marketing_version
    ):
        raise EvidenceError(
            "marketing version 與期待不符: "
            f"expected={expected_marketing_version} actual={marketing_version}"
        )
    if expected_build_number is not None and build_number != expected_build_number:
        raise EvidenceError(
            "build number 與期待不符: "
            f"expected={expected_build_number} actual={build_number}"
        )
    dataset_schema, dataset_id = _load_dataset_identity(dataset_file)
    profile_schema, parsed_profile_id = _load_profile_identity(profile_file)
    if parsed_profile_id != profile_id:
        raise EvidenceError(
            f"profile id 漂移: parsed={parsed_profile_id} expected={profile_id}"
        )
    tools: list[dict[str, Any]] = []
    for path in generator_files:
        _require_file(path, label="generator")
        tools.append({"path": _logical_tool_path(path), "sha256": sha256_file(path)})
    tools.sort(key=lambda item: item["path"])
    if not tools:
        raise EvidenceError("provenance 至少需要一個 generator")

    profile_digest = sha256_file(profile_file)
    dataset_digest = sha256_file(dataset_file)
    render_digest = _sha256_json(render_spec)
    promotion_manifest_digest, outputs = validate_promotion_manifest(
        promotion_manifest_file,
        profile_id=profile_id,
        profile_digest=profile_digest,
        dataset_digest=dataset_digest,
        render_spec=render_spec,
        render_output_dir=render_output_dir,
    )
    required_evidence = [
        {"id": evidence_id, "status": "verified"}
        for evidence_id in (
            "build-tuple",
            "source-commit",
            "capture-profile",
            "ui-world",
            "fixed-clock",
            "device-locale",
            "render-spec",
            "promotion-closure",
            "output-checksums",
            "provenance",
        )
    ]
    return {
        "schema": SCHEMA,
        "verdict": {"status": "pass", "requiredEvidence": required_evidence},
        "build": {
            "marketingVersion": marketing_version,
            "buildNumber": build_number,
            "project": {"path": "inputs/project.pbxproj", "sha256": project_digest},
        },
        "source": {"commit": source_commit},
        "capture": {
            "profile": {
                "schema": profile_schema,
                "id": profile_id,
                "path": "inputs/capture_profile.json",
                "sha256": profile_digest,
            },
            "dataset": {
                "schema": dataset_schema,
                "id": dataset_id,
                "path": "inputs/ui_world.json",
                "sha256": dataset_digest,
            },
            "fixedClock": fixed_clock,
            "device": {"destination": device_destination},
            "locale": locale,
            "renderSpec": {"sha256": render_digest, "value": render_spec},
            "promotionManifest": {
                "schema": PROMOTION_MANIFEST_SCHEMA,
                "path": "inputs/promotion_manifest.json",
                "sha256": promotion_manifest_digest,
            },
        },
        "outputs": outputs,
        "provenance": {
            "sourceCommit": source_commit,
            "generators": tools,
            "inputDigests": {
                "profile": profile_digest,
                "dataset": dataset_digest,
                "project": project_digest,
                "renderSpec": render_digest,
                "promotionManifest": promotion_manifest_digest,
            },
            "rebuild": {
                "entrypoint": "ops/capture_profile.py",
                "profile": "inputs/capture_profile.json",
                "dataset": "inputs/ui_world.json",
                "fixedClock": fixed_clock,
                "locale": locale,
                "deviceDestination": device_destination,
            },
        },
    }


def _assert_manifest_matches_source(
    manifest: dict[str, Any], source: Path, expected_digest: str, *, label: str
) -> None:
    _require_file(source, label=label)
    actual = sha256_file(source)
    if actual != expected_digest:
        raise EvidenceError(
            f"{label} 在 manifest 建立後漂移: expected={expected_digest} actual={actual}"
        )


def write_bundle(
    manifest: dict[str, Any],
    *,
    bundle_dir: Path,
    profile_file: Path,
    dataset_file: Path,
    project_file: Path,
    promotion_manifest_file: Path,
    render_output_dir: Path,
    profile_validator: SemanticValidator,
    dataset_validator: SemanticValidator,
) -> None:
    """Write a complete bundle via same-parent staging + atomic rename."""
    if bundle_dir.exists():
        raise EvidenceError(f"reviewer evidence bundle 已存在: {bundle_dir}")
    try:
        profile_digest = manifest["capture"]["profile"]["sha256"]
        dataset_digest = manifest["capture"]["dataset"]["sha256"]
        project_digest = manifest["build"]["project"]["sha256"]
        promotion_digest = manifest["capture"]["promotionManifest"]["sha256"]
        profile_id = manifest["capture"]["profile"]["id"]
        dataset_schema = manifest["capture"]["dataset"]["schema"]
        dataset_id = manifest["capture"]["dataset"]["id"]
        render_spec = manifest["capture"]["renderSpec"]["value"]
        marketing_version = manifest["build"]["marketingVersion"]
        build_number = manifest["build"]["buildNumber"]
        outputs = manifest["outputs"]
    except (KeyError, TypeError) as exc:
        raise EvidenceError("reviewer evidence manifest 結構不完整") from exc
    for output in outputs:
        rel = Path(output["file"])
        if len(rel.parts) != 2 or rel.parts[0] != "outputs":
            raise EvidenceError(f"manifest output path 不安全: {rel}")

    bundle_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{bundle_dir.name}.tmp-", dir=str(bundle_dir.parent))
    )
    try:
        inputs_dir = staging / "inputs"
        outputs_dir = staging / "outputs"
        inputs_dir.mkdir()
        outputs_dir.mkdir()
        shutil.copyfile(profile_file, inputs_dir / "capture_profile.json")
        shutil.copyfile(dataset_file, inputs_dir / "ui_world.json")
        shutil.copyfile(project_file, inputs_dir / "project.pbxproj")
        shutil.copyfile(promotion_manifest_file, inputs_dir / "promotion_manifest.json")
        for output in outputs:
            name = Path(output["file"]).name
            shutil.copyfile(render_output_dir / name, outputs_dir / name)

        # Staged bytes, not mutable sources, are the publication authority. This closes
        # the validate→copy TOCTOU window: every copied input/output is re-hashed and its
        # semantic identity is revalidated before the atomic directory rename.
        staged_profile = inputs_dir / "capture_profile.json"
        staged_dataset = inputs_dir / "ui_world.json"
        staged_project = inputs_dir / "project.pbxproj"
        staged_promotion = inputs_dir / "promotion_manifest.json"
        _assert_manifest_matches_source(
            manifest, staged_profile, profile_digest, label="staged capture profile"
        )
        _assert_manifest_matches_source(
            manifest, staged_dataset, dataset_digest, label="staged UI World"
        )
        _assert_manifest_matches_source(
            manifest, staged_project, project_digest, label="staged Xcode project file"
        )
        _run_semantic_validator(
            staged_profile, profile_validator, label="staged capture profile"
        )
        _run_semantic_validator(
            staged_dataset, dataset_validator, label="staged UI World"
        )
        staged_profile_schema, staged_profile_id = _load_profile_identity(staged_profile)
        if staged_profile_schema != "kg.capture.profile.v1" or staged_profile_id != profile_id:
            raise EvidenceError("staged capture profile identity 漂移")
        staged_dataset_identity = _load_dataset_identity(staged_dataset)
        if staged_dataset_identity != (dataset_schema, dataset_id):
            raise EvidenceError("staged UI World identity 漂移")
        if read_build_tuple(staged_project) != (marketing_version, build_number):
            raise EvidenceError("staged Xcode build tuple 漂移")
        staged_promotion_digest, staged_outputs = validate_promotion_manifest(
            staged_promotion,
            profile_id=profile_id,
            profile_digest=profile_digest,
            dataset_digest=dataset_digest,
            render_spec=render_spec,
            render_output_dir=outputs_dir,
        )
        if staged_promotion_digest != promotion_digest or staged_outputs != outputs:
            raise EvidenceError("staged promotion evidence 漂移")
        (staging / "manifest.json").write_bytes(canonical_manifest_bytes(manifest))
        os.replace(staging, bundle_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

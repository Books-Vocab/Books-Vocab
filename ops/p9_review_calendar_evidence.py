"""Fail-closed contract for P9 review-calendar screenshot evidence v2.

The screenshot bytes and the installed UI World fixture are the portable
identity of an evidence record.  Filesystem inode numbers are deliberately not
part of this contract: they change across checkouts, copies, and device pulls.
This module validates local evidence only; it never captures screenshots or
starts an iOS runner.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EVIDENCE_SCHEMA = "kg.p9.review_calendar.review_manifest.v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_KEYS = frozenset({"schema", "records"})
RECORD_KEYS = frozenset(
    {
        "fixtureID",
        "stepLabel",
        "manifestAssetID",
        "manifestPath",
        "assetID",
        "artifactPath",
        "bytes",
        "sha256",
        "selector",
        "source",
        "datasetID",
        "device",
        "group",
        "installedFixture",
    }
)
INSTALLED_FIXTURE_KEYS = frozenset({"datasetID", "path", "bytes", "sha256"})
EVIDENCE_GROUPS = frozenset({"required", "counterexamples"})


class EvidenceContractError(ValueError):
    """Raised when P9 evidence cannot be independently re-verified."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceContractError(message)


def _relative_path(
    value: object,
    *,
    workspace_root: Path,
    field: str,
    allow_absolute_source: bool = False,
) -> tuple[str, Path]:
    if isinstance(value, Path):
        raw = value
    else:
        _require(isinstance(value, str) and value.strip(), f"{field} must be a non-empty path")
        raw = Path(value)
    if raw.is_absolute() and not allow_absolute_source:
        raise EvidenceContractError(f"{field} must be relative to the evidence workspace")
    resolved = raw.resolve() if raw.is_absolute() else (workspace_root / raw).resolve()
    root = workspace_root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise EvidenceContractError(f"{field} escapes the evidence workspace") from exc
    return relative, resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_attestation(path: Path, *, field: str) -> tuple[int, str]:
    _require(path.is_file(), f"{field} must resolve to a regular file")
    size = path.stat().st_size
    digest = _sha256(path)
    return size, digest


def make_record(
    *,
    fixture_id: str,
    step_label: str,
    manifest_asset_id: str,
    manifest_path: str,
    asset_id: str,
    artifact_path: Path,
    selector: str,
    source: str,
    dataset_id: str,
    device: str,
    group: str,
    installed_fixture_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Build one v2 record from actual files, without inode identity."""
    artifact_rel, artifact = _relative_path(
        artifact_path,
        workspace_root=workspace_root,
        field="artifactPath",
        allow_absolute_source=True,
    )
    fixture_rel, fixture = _relative_path(
        installed_fixture_path,
        workspace_root=workspace_root,
        field="installedFixture.path",
        allow_absolute_source=True,
    )
    artifact_bytes, artifact_sha = _file_attestation(artifact, field="artifactPath")
    fixture_bytes, fixture_sha = _file_attestation(fixture, field="installedFixture.path")
    _require(group in EVIDENCE_GROUPS, f"group must be one of {sorted(EVIDENCE_GROUPS)}")
    for field, value in (
        ("fixtureID", fixture_id),
        ("stepLabel", step_label),
        ("manifestAssetID", manifest_asset_id),
        ("manifestPath", manifest_path),
        ("assetID", asset_id),
        ("selector", selector),
        ("source", source),
        ("datasetID", dataset_id),
        ("device", device),
    ):
        _require(isinstance(value, str) and value.strip(), f"{field} must be non-empty")
    return {
        "fixtureID": fixture_id,
        "stepLabel": step_label,
        "manifestAssetID": manifest_asset_id,
        "manifestPath": manifest_path,
        "assetID": asset_id,
        "artifactPath": artifact_rel,
        "bytes": artifact_bytes,
        "sha256": artifact_sha,
        "selector": selector,
        "source": source,
        "datasetID": dataset_id,
        "device": device,
        "group": group,
        "installedFixture": {
            "datasetID": dataset_id,
            "path": fixture_rel,
            "bytes": fixture_bytes,
            "sha256": fixture_sha,
        },
    }


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    workspace_root: Path,
    expected_dataset_id: str | None = None,
    expected_device: str | None = None,
) -> dict[str, Any]:
    """Validate records and re-hash every screenshot and installed fixture."""
    _require(set(manifest) == MANIFEST_KEYS, "manifest keys must be exactly schema and records")
    _require(manifest.get("schema") == EVIDENCE_SCHEMA, f"schema must be {EVIDENCE_SCHEMA!r}")
    records = manifest.get("records")
    _require(isinstance(records, Sequence) and not isinstance(records, (str, bytes)), "records must be a non-empty list")
    _require(bool(records), "records must not be empty")
    seen_asset_ids: set[str] = set()
    seen_steps: set[str] = set()
    attested: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        _require(isinstance(raw, Mapping), f"records[{index}] must be an object")
        record = dict(raw)
        _require(set(record) == RECORD_KEYS, f"records[{index}] keys must equal the v2 contract")
        for field in ("fixtureID", "stepLabel", "manifestAssetID", "manifestPath", "assetID", "selector", "source", "datasetID", "device", "group"):
            _require(isinstance(record[field], str) and record[field].strip(), f"records[{index}].{field} must be non-empty")
        _require(record["group"] in EVIDENCE_GROUPS, f"records[{index}].group is invalid")
        _require(record["assetID"] not in seen_asset_ids, f"assetID is not unique: {record['assetID']!r}")
        _require(record["stepLabel"] not in seen_steps, f"stepLabel is not unique: {record['stepLabel']!r}")
        seen_asset_ids.add(record["assetID"])
        seen_steps.add(record["stepLabel"])
        if expected_dataset_id is not None:
            _require(record["datasetID"] == expected_dataset_id, f"records[{index}].datasetID drifted")
        if expected_device is not None:
            _require(record["device"] == expected_device, f"records[{index}].device drifted")

        _require(isinstance(record["bytes"], int) and not isinstance(record["bytes"], bool) and record["bytes"] > 0, f"records[{index}].bytes must be a positive integer")
        _require(isinstance(record["sha256"], str) and SHA256_RE.fullmatch(record["sha256"]) is not None, f"records[{index}].sha256 must be lowercase SHA-256")
        artifact_rel, artifact = _relative_path(record["artifactPath"], workspace_root=workspace_root, field=f"records[{index}].artifactPath")
        actual_bytes, actual_sha = _file_attestation(artifact, field=f"records[{index}].artifactPath")
        _require(actual_bytes == record["bytes"], f"records[{index}] screenshot byte size drifted")
        _require(actual_sha == record["sha256"], f"records[{index}] screenshot SHA-256 drifted")
        _require(record["artifactPath"] == artifact_rel, f"records[{index}].artifactPath must be canonical relative path")

        fixture = record["installedFixture"]
        _require(isinstance(fixture, Mapping), f"records[{index}].installedFixture must be an object")
        _require(set(fixture) == INSTALLED_FIXTURE_KEYS, f"records[{index}].installedFixture keys must equal the v2 contract")
        _require(fixture["datasetID"] == record["datasetID"], f"records[{index}] installed fixture dataset identity drifted")
        _require(isinstance(fixture["bytes"], int) and not isinstance(fixture["bytes"], bool) and fixture["bytes"] > 0, f"records[{index}].installedFixture.bytes must be a positive integer")
        _require(isinstance(fixture["sha256"], str) and SHA256_RE.fullmatch(fixture["sha256"]) is not None, f"records[{index}].installedFixture.sha256 must be lowercase SHA-256")
        fixture_rel, fixture_path = _relative_path(fixture["path"], workspace_root=workspace_root, field=f"records[{index}].installedFixture.path")
        actual_fixture_bytes, actual_fixture_sha = _file_attestation(fixture_path, field=f"records[{index}].installedFixture.path")
        _require(actual_fixture_bytes == fixture["bytes"], f"records[{index}] installed fixture byte size drifted")
        _require(actual_fixture_sha == fixture["sha256"], f"records[{index}] installed fixture SHA-256 drifted")
        _require(fixture["path"] == fixture_rel, f"records[{index}].installedFixture.path must be canonical relative path")
        attested.append({"assetID": record["assetID"], "artifactPath": artifact_rel, "bytes": actual_bytes, "sha256": actual_sha})
    return {"schema": EVIDENCE_SCHEMA, "records": attested, "count": len(attested)}


def validate_manifest_file(
    path: Path,
    *,
    workspace_root: Path,
    expected_dataset_id: str | None = None,
    expected_device: str | None = None,
) -> dict[str, Any]:
    """Load and validate a JSON v2 sidecar."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"manifest is not readable JSON: {path}") from exc
    _require(isinstance(manifest, Mapping), "manifest must be a JSON object")
    return validate_manifest(
        manifest,
        workspace_root=workspace_root,
        expected_dataset_id=expected_dataset_id,
        expected_device=expected_device,
    )

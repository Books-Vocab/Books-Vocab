"""Fail-closed contract for P9 review-calendar screenshot evidence v2.

The screenshot bytes and the installed UI World fixture are the portable
identity of an evidence record.  Filesystem allocation identity is deliberately
not part of this contract: it changes across checkouts, copies, and device pulls.
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
FIXTURE_DATASET_SCHEMA = "kg.fixture.dataset.v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
MANIFEST_KEYS = frozenset(
    {
        "schema",
        "sourceCommit",
        "datasetID",
        "datasetSHA256",
        "device",
        "selector",
        "records",
    }
)
OUTER_ARTIFACT_KEYS = frozenset(
    {
        "schema",
        "path",
        "sourceCommit",
        "datasetID",
        "datasetSHA256",
        "device",
        "selector",
        "recordCount",
    }
)
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
        "type",
        "selector",
        "source",
        "datasetID",
        "device",
        "group",
        "installedFixture",
    }
)
INSTALLED_FIXTURE_KEYS = frozenset(
    {"datasetID", "path", "bytes", "sha256", "type", "sourceCommit", "datasetSHA256"}
)
EVIDENCE_GROUPS = frozenset({"required", "counterexamples"})
ARTIFACT_TYPES = {".png": "image/png"}
INSTALLED_FIXTURE_TYPE = "application/json"


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


def _require_non_empty_string(value: object, *, field: str) -> str:
    _require(isinstance(value, str) and value.strip(), f"{field} must be non-empty")
    return value


def _validate_provenance(manifest: Mapping[str, Any]) -> None:
    source_commit = _require_non_empty_string(manifest["sourceCommit"], field="sourceCommit")
    _require(COMMIT_RE.fullmatch(source_commit) is not None, "sourceCommit must be a git commit SHA")
    _require_non_empty_string(manifest["datasetID"], field="datasetID")
    dataset_sha = _require_non_empty_string(manifest["datasetSHA256"], field="datasetSHA256")
    _require(SHA256_RE.fullmatch(dataset_sha) is not None, "datasetSHA256 must be lowercase SHA-256")
    _require_non_empty_string(manifest["device"], field="device")
    _require_non_empty_string(manifest["selector"], field="selector")


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
    source_commit: str,
    dataset_sha256: str,
    artifact_type: str = "image/png",
    installed_fixture_type: str = INSTALLED_FIXTURE_TYPE,
) -> dict[str, Any]:
    """Build one v2 record from actual files and portable metadata."""
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
    _require(artifact_type == ARTIFACT_TYPES.get(artifact.suffix), "artifact type does not match artifactPath")
    _require(installed_fixture_type == INSTALLED_FIXTURE_TYPE, "installed fixture type must be application/json")
    _require(COMMIT_RE.fullmatch(source_commit) is not None, "source_commit must be a git commit SHA")
    _require(SHA256_RE.fullmatch(dataset_sha256) is not None, "dataset_sha256 must be lowercase SHA-256")
    _require(fixture.suffix.lower() == ".json", "installed fixture path must be a JSON file")
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
        "type": artifact_type,
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
            "type": installed_fixture_type,
            "sourceCommit": source_commit,
            "datasetSHA256": dataset_sha256,
        },
    }


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    workspace_root: Path,
    expected_dataset_id: str | None = None,
    expected_device: str | None = None,
    expected_source_commit: str | None = None,
    expected_dataset_sha256: str | None = None,
    expected_selector: str | None = None,
    manifest_path: Path | None = None,
    outer_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate records and re-hash every screenshot and installed fixture."""
    _require(set(manifest) == MANIFEST_KEYS, "manifest keys must equal the v2 envelope contract")
    _require(manifest.get("schema") == EVIDENCE_SCHEMA, f"schema must be {EVIDENCE_SCHEMA!r}")
    _validate_provenance(manifest)
    if expected_dataset_id is not None:
        _require(manifest["datasetID"] == expected_dataset_id, "manifest datasetID drifted")
    if expected_device is not None:
        _require(manifest["device"] == expected_device, "manifest device drifted")
    if expected_source_commit is not None:
        _require(manifest["sourceCommit"] == expected_source_commit, "manifest sourceCommit drifted")
    if expected_dataset_sha256 is not None:
        _require(manifest["datasetSHA256"] == expected_dataset_sha256, "manifest datasetSHA256 drifted")
    if expected_selector is not None:
        _require(manifest["selector"] == expected_selector, "manifest selector drifted")

    if outer_verdict is not None:
        artifacts = outer_verdict.get("artifacts")
        _require(isinstance(artifacts, Mapping), "outer verdict artifacts must be an object")
        formal = artifacts.get("p9ReviewCalendarEvidence")
        _require(isinstance(formal, Mapping), "outer verdict must contain p9ReviewCalendarEvidence")
        _require(set(formal) == OUTER_ARTIFACT_KEYS, "outer verdict P9 artifact keys must equal the formal contract")
        _require(formal["schema"] == manifest["schema"], "outer verdict P9 artifact schema drifted")
        _require(_require_non_empty_string(formal["path"], field="outer verdict P9 artifact path"), "outer verdict P9 artifact path missing")
        if manifest_path is not None:
            _require(
                formal["path"] == str(manifest_path.resolve()),
                "outer verdict P9 artifact path drifted",
            )
        for field in ("sourceCommit", "datasetID", "datasetSHA256", "device", "selector"):
            _require(
                formal[field] == manifest[field],
                f"outer verdict P9 artifact {field} drifted",
            )
        _require(
            isinstance(formal["recordCount"], int)
            and not isinstance(formal["recordCount"], bool),
            "outer verdict P9 artifact recordCount must be an integer",
        )
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
        for field in ("fixtureID", "stepLabel", "manifestAssetID", "manifestPath", "assetID", "type", "selector", "source", "datasetID", "device", "group"):
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
        _require(record["datasetID"] == manifest["datasetID"], f"records[{index}].datasetID does not match envelope")
        _require(record["device"] == manifest["device"], f"records[{index}].device does not match envelope")
        _require(record["selector"] == manifest["selector"], f"records[{index}].selector does not match envelope")

        _require(isinstance(record["bytes"], int) and not isinstance(record["bytes"], bool) and record["bytes"] > 0, f"records[{index}].bytes must be a positive integer")
        _require(isinstance(record["sha256"], str) and SHA256_RE.fullmatch(record["sha256"]) is not None, f"records[{index}].sha256 must be lowercase SHA-256")
        artifact_rel, artifact = _relative_path(record["artifactPath"], workspace_root=workspace_root, field=f"records[{index}].artifactPath")
        actual_bytes, actual_sha = _file_attestation(artifact, field=f"records[{index}].artifactPath")
        _require(record["type"] == ARTIFACT_TYPES.get(artifact.suffix), f"records[{index}].type does not match artifactPath")
        _require(actual_bytes == record["bytes"], f"records[{index}] screenshot byte size drifted")
        _require(actual_sha == record["sha256"], f"records[{index}] screenshot SHA-256 drifted")
        _require(record["artifactPath"] == artifact_rel, f"records[{index}].artifactPath must be canonical relative path")

        fixture = record["installedFixture"]
        _require(isinstance(fixture, Mapping), f"records[{index}].installedFixture must be an object")
        _require(set(fixture) == INSTALLED_FIXTURE_KEYS, f"records[{index}].installedFixture keys must equal the v2 contract")
        _require(fixture["datasetID"] == record["datasetID"], f"records[{index}] installed fixture dataset identity drifted")
        _require(fixture["sourceCommit"] == manifest["sourceCommit"], f"records[{index}] installed fixture sourceCommit drifted")
        _require(fixture["datasetSHA256"] == manifest["datasetSHA256"], f"records[{index}] installed fixture datasetSHA256 drifted")
        _require(isinstance(fixture["bytes"], int) and not isinstance(fixture["bytes"], bool) and fixture["bytes"] > 0, f"records[{index}].installedFixture.bytes must be a positive integer")
        _require(isinstance(fixture["sha256"], str) and SHA256_RE.fullmatch(fixture["sha256"]) is not None, f"records[{index}].installedFixture.sha256 must be lowercase SHA-256")
        fixture_rel, fixture_path = _relative_path(fixture["path"], workspace_root=workspace_root, field=f"records[{index}].installedFixture.path")
        _require(fixture["type"] == INSTALLED_FIXTURE_TYPE, f"records[{index}].installedFixture.type must be application/json")
        _require(fixture_path.suffix.lower() == ".json", f"records[{index}].installedFixture.path must be a JSON file")
        actual_fixture_bytes, actual_fixture_sha = _file_attestation(fixture_path, field=f"records[{index}].installedFixture.path")
        _require(actual_fixture_bytes == fixture["bytes"], f"records[{index}] installed fixture byte size drifted")
        _require(actual_fixture_sha == fixture["sha256"], f"records[{index}] installed fixture SHA-256 drifted")
        _require(fixture["path"] == fixture_rel, f"records[{index}].installedFixture.path must be canonical relative path")
        try:
            installed_document = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceContractError(
                f"records[{index}].installedFixture.path must be readable JSON"
            ) from exc
        _require(isinstance(installed_document, Mapping), f"records[{index}].installedFixture must contain a JSON object")
        _require(
            installed_document.get("schema") == FIXTURE_DATASET_SCHEMA,
            f"records[{index}].installedFixture schema drifted",
        )
        _require(
            installed_document.get("datasetID") == fixture["datasetID"],
            f"records[{index}].installedFixture datasetID does not match materialized bytes",
        )
        attested.append({"assetID": record["assetID"], "artifactPath": artifact_rel, "bytes": actual_bytes, "sha256": actual_sha, "type": record["type"]})
    _require(
        outer_verdict is None or outer_verdict["artifacts"]["p9ReviewCalendarEvidence"]["recordCount"] == len(attested),
        "outer verdict P9 artifact recordCount drifted",
    )
    return {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": manifest["sourceCommit"],
        "datasetID": manifest["datasetID"],
        "datasetSHA256": manifest["datasetSHA256"],
        "device": manifest["device"],
        "selector": manifest["selector"],
        "records": attested,
        "count": len(attested),
    }


def validate_manifest_file(
    path: Path,
    *,
    workspace_root: Path,
    expected_dataset_id: str | None = None,
    expected_device: str | None = None,
    expected_source_commit: str | None = None,
    expected_dataset_sha256: str | None = None,
    expected_selector: str | None = None,
    outer_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and validate a JSON v2 sidecar."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"manifest is not readable JSON: {path}") from exc
    _require(isinstance(manifest, Mapping), "manifest must be a JSON object")
    _require(outer_verdict is not None, "P9 sidecar validation requires the formal outer verdict")
    return validate_manifest(
        manifest,
        workspace_root=workspace_root,
        expected_dataset_id=expected_dataset_id,
        expected_device=expected_device,
        expected_source_commit=expected_source_commit,
        expected_dataset_sha256=expected_dataset_sha256,
        expected_selector=expected_selector,
        manifest_path=path,
        outer_verdict=outer_verdict,
    )


def _main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--workspace-root", type=Path, required=True)
    validate_parser.add_argument("--outer-verdict", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outer = json.loads(args.outer_verdict.read_text(encoding="utf-8"))
        _require(isinstance(outer, Mapping), "outer verdict must be a JSON object")
        result = validate_manifest_file(
            args.manifest,
            workspace_root=args.workspace_root,
            outer_verdict=outer,
        )
    except (EvidenceContractError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    else:
        print(json.dumps(result, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())

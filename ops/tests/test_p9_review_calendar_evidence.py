from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.p9_review_calendar_evidence import (
    EVIDENCE_SCHEMA,
    EvidenceContractError,
    make_record,
    validate_manifest,
)

SOURCE_COMMIT = "c4f0f1774236fa219ab164709c5b7d6c844644d9"
SELECTOR = "FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors"
DATASET_SHA256 = hashlib.sha256(b"marketing-demo-source").hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    screenshot = tmp_path / "shots" / "calendar.png"
    screenshot.parent.mkdir(exist_ok=True)
    screenshot.write_bytes(b"png-fixture")
    fixture = tmp_path / "installed" / "ios_fixture_dataset.json"
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(
        '{"schema":"kg.fixture.dataset.v2","datasetID":"marketing_demo"}\n',
        encoding="utf-8",
    )
    return screenshot, fixture


def _record(tmp_path: Path) -> dict:
    screenshot, fixture = _fixture(tmp_path)
    return make_record(
        fixture_id="review-calendar.calendar",
        step_label="calendar",
        manifest_asset_id="review-calendar.calendar",
        manifest_path="p9_review_calendar_review_manifest.json",
        asset_id="calendar-shot",
        artifact_path=screenshot,
        selector=SELECTOR,
        source="ios/BooksAndVocabUITests/FixtureDatasetUITests.swift",
        dataset_id="marketing_demo",
        device="device-1",
        group="required",
        installed_fixture_path=fixture,
        workspace_root=tmp_path,
        source_commit=SOURCE_COMMIT,
        dataset_sha256=DATASET_SHA256,
    )


def _manifest(record: dict) -> dict:
    return {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": SOURCE_COMMIT,
        "datasetID": "marketing_demo",
        "datasetSHA256": DATASET_SHA256,
        "device": "device-1",
        "selector": SELECTOR,
        "records": [record],
    }


def _outer_verdict(tmp_path: Path, record: dict) -> dict:
    sidecar = tmp_path / "p9_review_calendar_review_manifest.json"
    return {
        "artifacts": {
            "p9ReviewCalendarEvidence": {
                "schema": EVIDENCE_SCHEMA,
                "path": str(sidecar),
                "sourceCommit": SOURCE_COMMIT,
                "datasetID": "marketing_demo",
                "datasetSHA256": DATASET_SHA256,
                "device": "device-1",
                "selector": SELECTOR,
                "recordCount": 1,
            }
        }
    }


def test_v2_record_attests_portable_bytes_type_and_installed_fixture(tmp_path: Path):
    record = _record(tmp_path)
    assert set(record) == {
        "fixtureID", "stepLabel", "manifestAssetID", "manifestPath", "assetID",
        "artifactPath", "bytes", "sha256", "type", "selector", "source",
        "datasetID", "device", "group", "installedFixture",
    }
    assert record["type"] == "image/png"
    assert set(record["installedFixture"]) == {
        "datasetID", "path", "bytes", "sha256", "type", "sourceCommit", "datasetSHA256",
    }
    assert record["installedFixture"]["type"] == "application/json"
    assert record["installedFixture"]["sourceCommit"] == SOURCE_COMMIT
    assert record["installedFixture"]["datasetSHA256"] == DATASET_SHA256
    manifest = _manifest(record)
    result = validate_manifest(
        manifest,
        workspace_root=tmp_path,
        expected_dataset_id="marketing_demo",
        expected_device="device-1",
        expected_source_commit=SOURCE_COMMIT,
        expected_dataset_sha256=DATASET_SHA256,
        expected_selector=SELECTOR,
    )
    assert result["count"] == 1
    assert result["records"][0]["bytes"] == len(b"png-fixture")


def test_v2_rejects_unknown_wire_fields_and_hash_or_size_drift(tmp_path: Path):
    record = _record(tmp_path)
    record["legacyWireField"] = 123
    with pytest.raises(EvidenceContractError, match="keys must equal"):
        validate_manifest(
            _manifest(record),
            workspace_root=tmp_path,
        )

    record = _record(tmp_path)
    record["bytes"] += 1
    with pytest.raises(EvidenceContractError, match="byte size drifted"):
        validate_manifest(
            _manifest(record),
            workspace_root=tmp_path,
        )


def test_v2_requires_formal_outer_verdict_to_match_sidecar(tmp_path: Path):
    record = _record(tmp_path)
    manifest = _manifest(record)
    sidecar = tmp_path / "p9_review_calendar_review_manifest.json"
    sidecar.write_text(json.dumps(manifest), encoding="utf-8")

    from ops.p9_review_calendar_evidence import validate_manifest_file

    result = validate_manifest_file(
        sidecar,
        workspace_root=tmp_path,
        expected_source_commit=SOURCE_COMMIT,
        expected_dataset_sha256=DATASET_SHA256,
        expected_selector=SELECTOR,
        outer_verdict=_outer_verdict(tmp_path, record),
    )
    assert result["count"] == 1

    outer = _outer_verdict(tmp_path, record)
    outer["artifacts"]["p9ReviewCalendarEvidence"]["datasetSHA256"] = "0" * 64
    with pytest.raises(EvidenceContractError, match="outer verdict.*datasetSHA256"):
        validate_manifest_file(
            sidecar,
            workspace_root=tmp_path,
            outer_verdict=outer,
        )

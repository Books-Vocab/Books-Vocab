from __future__ import annotations

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


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    screenshot = tmp_path / "shots" / "calendar.png"
    screenshot.parent.mkdir(exist_ok=True)
    screenshot.write_bytes(b"png-fixture")
    fixture = tmp_path / "installed" / "ios_fixture_dataset.json"
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text('{"datasetID":"marketing_demo"}\n', encoding="utf-8")
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
        selector="FixtureDatasetUITests/testReviewCalendarRequiredEvidenceUsesStableSelectors",
        source="ios/BooksAndVocabUITests/FixtureDatasetUITests.swift",
        dataset_id="marketing_demo",
        device="device-1",
        group="required",
        installed_fixture_path=fixture,
        workspace_root=tmp_path,
    )


def test_v2_record_attests_portable_bytes_and_installed_fixture(tmp_path: Path):
    record = _record(tmp_path)
    assert set(record) == {
        "fixtureID", "stepLabel", "manifestAssetID", "manifestPath", "assetID",
        "artifactPath", "bytes", "sha256", "selector", "source", "datasetID",
        "device", "group", "installedFixture",
    }
    assert "inode" not in json.dumps(record)
    result = validate_manifest(
        {"schema": EVIDENCE_SCHEMA, "records": [record]},
        workspace_root=tmp_path,
        expected_dataset_id="marketing_demo",
        expected_device="device-1",
    )
    assert result["count"] == 1
    assert result["records"][0]["bytes"] == len(b"png-fixture")


def test_v2_rejects_inode_identity_and_hash_or_size_drift(tmp_path: Path):
    record = _record(tmp_path)
    record["inode"] = 123  # v2 must not regress to checkout-local identity.
    with pytest.raises(EvidenceContractError, match="keys must equal"):
        validate_manifest(
            {"schema": EVIDENCE_SCHEMA, "records": [record]},
            workspace_root=tmp_path,
        )

    record = _record(tmp_path)
    record["bytes"] += 1
    with pytest.raises(EvidenceContractError, match="byte size drifted"):
        validate_manifest(
            {"schema": EVIDENCE_SCHEMA, "records": [record]},
            workspace_root=tmp_path,
        )

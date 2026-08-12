from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "ops" / "ui_world_manifest.py"
SPEC = importlib.util.spec_from_file_location("ui_world_manifest", MANIFEST_PATH)
assert SPEC and SPEC.loader
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)

BASELINE = ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"
GENERATED = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
CANONICAL_SETTINGS_ID = "sync_terminal_error_retry_success"
SYNC_SUMMARY_KEYS = {
    "isConnected",
    "isSyncing",
    "summaryText",
    "lastSyncedText",
    "lifecycle",
    "message",
    "attempt",
    "dataOutcome",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_settings_sync_fixture_is_materialized_with_provenance():
    data = _load(BASELINE)
    seed = data["settings"][CANONICAL_SETTINGS_ID]
    summary = seed["syncSummary"]

    assert set(summary) == SYNC_SUMMARY_KEYS
    assert summary["lifecycle"] == "terminalError"
    assert summary["message"]
    assert summary["attempt"] == 1
    assert summary["dataOutcome"] == "partial"


@pytest.mark.parametrize(
    ("lifecycle", "message", "attempt", "data_outcome"),
    [
        ("terminalSuccess", None, 1, "complete"),
        ("terminalError", "sync failed", 1, "partial"),
        ("retry", None, 2, "partial"),
    ],
)
def test_sync_lifecycle_payload_shapes_are_explicit(
    tmp_path: Path,
    lifecycle: str,
    message: str | None,
    attempt: int,
    data_outcome: str,
):
    data = _load(BASELINE)
    summary = data["settings"][CANONICAL_SETTINGS_ID]["syncSummary"]
    summary.update(
        lifecycle=lifecycle,
        message=message,
        attempt=attempt,
        dataOutcome=data_outcome,
    )
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert manifest.validate_fixture_dataset_file(path) == "marketing_demo"


def test_validator_rejects_stale_canonical_sync_shape(tmp_path: Path):
    data = _load(BASELINE)
    del data["settings"][CANONICAL_SETTINGS_ID]["syncSummary"]["attempt"]
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match="attempt"):
        manifest.validate_fixture_dataset_file(path)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("lifecycle", "terminal-error", "lifecycle is invalid"),
        ("dataOutcome", "none", "dataOutcome must be partial"),
        ("attempt", 0, "attempt must be >= 1"),
    ],
)
def test_validator_rejects_invalid_terminal_payload(
    tmp_path: Path, field: str, value: object, error: str
):
    data = _load(BASELINE)
    data["settings"][CANONICAL_SETTINGS_ID]["syncSummary"][field] = value
    path = tmp_path / f"invalid-{field}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match=error):
        manifest.validate_fixture_dataset_file(path)


def test_emitted_world_keeps_canonical_settings_and_asset_provenance_in_parity():
    source = _load(BASELINE)
    generated = _load(GENERATED)
    assert generated["settings"][CANONICAL_SETTINGS_ID] == source["settings"][CANONICAL_SETTINGS_ID]
    assert generated["assets"] == source["assets"]

    for document in (source, generated):
        for bucket in document["assets"].values():
            for asset in bucket.values():
                source_path = manifest._resolve_path(asset["sourcePath"])
                assert source_path.is_file()
                assert asset["byteSize"] == source_path.stat().st_size
                digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
                assert asset["sha256"] == digest

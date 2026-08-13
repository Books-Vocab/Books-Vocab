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


def test_fixture_asset_source_paths_are_repo_relative_and_inside_current_root():
    data = _load(BASELINE)
    for bucket in data["assets"].values():
        for asset in bucket.values():
            source_path = Path(asset["sourcePath"])
            assert not source_path.is_absolute()
            resolved = manifest._resolve_path(asset["sourcePath"])
            assert resolved.is_relative_to(manifest.ROOT)


def test_audio_assets_declare_their_actual_mpeg_container():
    data = _load(BASELINE)

    for asset in data["assets"]["audio"].values():
        assert asset["installAs"].endswith(".mp3")
        assert asset["contentType"] == "audio/mpeg"
        source_path = manifest._resolve_path(asset["sourcePath"])
        assert manifest._audio_container_type(source_path) == "audio/mpeg"


def test_validator_rejects_mp3_bytes_declared_as_m4a(tmp_path: Path):
    data = _load(BASELINE)
    asset = data["assets"]["audio"]["atomic_habits_ep1_flash_playable"]
    asset["installAs"] = "podcast-downloads/ui-playable-series/ui-playable-series_ep_01.m4a"
    asset["contentType"] = "audio/mp4"
    path = tmp_path / "mp3-as-m4a.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match="audio format mismatch.*audio/mpeg"):
        manifest.validate_fixture_dataset_file(path)


@pytest.mark.parametrize("source_path", ["/tmp/outside-fixture.md", "../../outside-fixture.md"])
def test_validator_rejects_absolute_or_escaping_asset_source_paths(tmp_path: Path, source_path: str):
    data = _load(BASELINE)
    data["assets"]["books"]["catalog_reader_epub"]["sourcePath"] = source_path
    path = tmp_path / "unsafe-source-path.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match="sourcePath.*相對|sourcePath.*outside"):
        manifest.validate_fixture_dataset_file(path)


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
        ("retry", None, 2, "none"),
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
        isSyncing=lifecycle in {"syncing", "retry"},
        message=message,
        attempt=attempt,
        dataOutcome=data_outcome,
    )
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert manifest.validate_fixture_dataset_file(path) == "marketing_demo"


@pytest.mark.parametrize(
    ("lifecycle", "is_syncing", "message", "attempt", "data_outcome", "error"),
    [
        ("idle", True, None, 0, "none", "isSyncing must be false"),
        ("syncing", False, None, 1, "none", "isSyncing must be true"),
        ("syncing", True, None, 0, "none", "attempt must be >= 1"),
        ("syncing", True, None, 1, "partial", "dataOutcome must be none"),
        ("terminalSuccess", False, "stale error", 1, "complete", "message must be null"),
        ("terminalSuccess", False, None, 0, "complete", "attempt must be >= 1"),
        ("retry", True, "stale error", 2, "none", "message must be null"),
        ("retry", True, None, 2, "partial", "dataOutcome must be none"),
        ("dismissed", False, None, 1, "partial", "message is required"),
        ("dismissed", False, None, 1, "none", "preserve a terminal outcome"),
    ],
)
def test_validator_rejects_lifecycle_cross_field_contradictions(
    tmp_path: Path,
    lifecycle: str,
    is_syncing: bool,
    message: str | None,
    attempt: int,
    data_outcome: str,
    error: str,
):
    data = _load(BASELINE)
    summary = data["settings"][CANONICAL_SETTINGS_ID]["syncSummary"]
    summary.update(
        lifecycle=lifecycle,
        isSyncing=is_syncing,
        message=message,
        attempt=attempt,
        dataOutcome=data_outcome,
    )
    path = tmp_path / f"contradiction-{lifecycle}-{attempt}-{data_outcome}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match=error):
        manifest.validate_fixture_dataset_file(path)


def test_validator_rejects_stale_canonical_sync_shape(tmp_path: Path):
    data = _load(BASELINE)
    del data["settings"][CANONICAL_SETTINGS_ID]["syncSummary"]["attempt"]
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(manifest.UIWorldManifestError, match="attempt"):
        manifest.validate_fixture_dataset_file(path)


def test_validator_rejects_legacy_settings_sync_shape_without_metadata(tmp_path: Path):
    data = _load(BASELINE)
    summary = data["settings"]["subscribed_active"]["syncSummary"]
    for key in ("lifecycle", "message", "attempt", "dataOutcome"):
        del summary[key]
    path = tmp_path / "legacy-missing-metadata.json"
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

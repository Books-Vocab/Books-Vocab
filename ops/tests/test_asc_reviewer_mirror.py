from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "asc_reviewer_mirror.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("asc_reviewer_mirror", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _png(width: int, height: int, marker: str) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + marker.encode("utf-8")
    )


def _desired_bundle(tmp_path: Path, names: list[str]) -> Path:
    bundle = tmp_path / "desired"
    inputs_dir = bundle / "inputs"
    outputs_dir = bundle / "outputs"
    inputs_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)
    project = b"MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 6;"
    dataset = b'{"schema":"kg.fixture.dataset.v2","datasetID":"dataset-1"}'
    (inputs_dir / "project.pbxproj").write_bytes(project)
    (inputs_dir / "ui_world.json").write_bytes(dataset)
    outputs = []
    for index, name in enumerate(names, start=1):
        payload = _png(1284, 2778, name)
        (outputs_dir / name).write_bytes(payload)
        shot_id = f"shot-{index}"
        outputs.append(
            {
                "id": shot_id,
                "appearance": "light",
                "file": f"outputs/{name}",
                "byteSize": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema": "kg.app_review.manual_asc_bundle.v1",
        "verdict": {"status": "pass"},
        "build": {
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
            "project": {
                "path": "inputs/project.pbxproj",
                "sha256": hashlib.sha256(project).hexdigest(),
            },
        },
        "source": {"commit": "a" * 40},
        "dataset": {
            "schema": "kg.fixture.dataset.v2",
            "id": "dataset-1",
            "path": "inputs/ui_world.json",
            "sha256": hashlib.sha256(dataset).hexdigest(),
        },
        "fixedClock": "2026-07-13T08:00:00Z",
        "locale": "zh-Hant",
        "displayType": "APP_IPHONE_65",
        "outputs": outputs,
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return bundle


class FakeASCClient:
    def __init__(
        self,
        desired_bundle: Path,
        *,
        live_names: list[str] | None = None,
        processing_state: str | None = "VALID",
        compliance: bool | None = False,
        build_number: str = "6",
        screenshot_state: str | None = "COMPLETE",
        wrong_source_checksum: bool = False,
        mutate_cdn_bytes: bool = False,
        api_error: bool = False,
    ) -> None:
        manifest = json.loads((desired_bundle / "manifest.json").read_text(encoding="utf-8"))
        desired_names = [Path(item["file"]).name for item in manifest["outputs"]]
        self.live_names = live_names if live_names is not None else desired_names
        self.processing_state = processing_state
        self.compliance = compliance
        self.build_number = build_number
        self.screenshot_state = screenshot_state
        self.wrong_source_checksum = wrong_source_checksum
        self.mutate_cdn_bytes = mutate_cdn_bytes
        self.api_error = api_error
        self.desired_bundle = desired_bundle
        self.secret_password = "do-not-leak-password"
        self.secret_notes = "do-not-leak-notes"

    def get_json(self, path: str) -> dict[str, Any]:
        if self.api_error:
            return {
                "_httpError": 503,
                "_detail": {"secret": self.secret_password},
            }
        if path.startswith("/v1/appStoreVersions/version-1"):
            return {
                "data": {
                    "type": "appStoreVersions",
                    "id": "version-1",
                    "attributes": {
                        "platform": "IOS",
                        "versionString": "2.0.0",
                        "appStoreState": "WAITING_FOR_REVIEW",
                    },
                    "relationships": {
                        "build": {"data": {"type": "builds", "id": "build-6"}},
                        "appStoreVersionLocalizations": {
                            "data": [
                                {
                                    "type": "appStoreVersionLocalizations",
                                    "id": "loc-zh-Hant",
                                }
                            ]
                        },
                        "appStoreReviewDetail": {
                            "data": {
                                "type": "appStoreReviewDetails",
                                "id": "review-detail-1",
                            }
                        },
                    },
                },
                "included": [
                    {
                        "type": "builds",
                        "id": "build-6",
                        "attributes": {
                            "version": self.build_number,
                            "processingState": self.processing_state,
                            "buildAudienceType": "APP_STORE_ELIGIBLE",
                            "usesNonExemptEncryption": self.compliance,
                        },
                    },
                    {
                        "type": "appStoreVersionLocalizations",
                        "id": "loc-zh-Hant",
                        "attributes": {
                            "locale": "zh-Hant",
                            "description": "Reviewer-facing description",
                            "keywords": "books,vocab",
                            "marketingUrl": "https://wordnexus.lol/",
                            "promotionalText": "Reviewer-facing promo",
                            "supportUrl": "https://wordnexus.lol/support.html",
                            "whatsNew": None,
                        },
                    },
                    {
                        "type": "appStoreReviewDetails",
                        "id": "review-detail-1",
                        "attributes": {
                            "contactFirstName": "Max",
                            "contactLastName": "Chen",
                            "contactPhone": "+886000000000",
                            "contactEmail": "review@example.com",
                            "demoAccountName": "demo@example.com",
                            "demoAccountPassword": self.secret_password,
                            "demoAccountRequired": True,
                            "notes": self.secret_notes,
                        },
                    },
                ],
            }
        if path.startswith("/v1/apps/app-1/reviewSubmissions"):
            return {
                "data": [
                    {
                        "type": "reviewSubmissions",
                        "id": "submission-1",
                        "attributes": {
                            "state": "WAITING_FOR_REVIEW",
                            "platform": "IOS",
                            "submittedDate": "2026-07-13T07:47:47Z",
                        },
                    },
                    {
                        "type": "reviewSubmissions",
                        "id": "historical-complete",
                        "attributes": {
                            "state": "COMPLETE",
                            "platform": "IOS",
                            "submittedDate": "2026-04-06T09:20:20Z",
                        },
                    },
                ]
            }
        if path.startswith("/v1/reviewSubmissions/submission-1/items"):
            return {
                "data": [
                    {
                        "type": "reviewSubmissionItems",
                        "id": "item-1",
                        "attributes": {"state": "READY_FOR_REVIEW"},
                        "relationships": {
                            "appStoreVersion": {
                                "data": {"type": "appStoreVersions", "id": "version-1"}
                            }
                        },
                    }
                ],
                "included": [
                    {
                        "type": "appStoreVersions",
                        "id": "version-1",
                        "attributes": {"versionString": "2.0.0", "platform": "IOS"},
                    }
                ],
            }
        if path.startswith("/v1/appStoreVersionLocalizations/loc-zh-Hant/appScreenshotSets"):
            shots = []
            relationships = []
            for index, name in enumerate(self.live_names, start=1):
                shot_id = f"live-shot-{index}"
                relationships.append({"type": "appScreenshots", "id": shot_id})
                source = (
                    (self.desired_bundle / "outputs" / name).read_bytes()
                    if (self.desired_bundle / "outputs" / name).is_file()
                    else _png(1284, 2778, name)
                )
                shots.append(
                    {
                        "type": "appScreenshots",
                        "id": shot_id,
                        "attributes": {
                            "fileName": name,
                            "fileSize": len(source),
                            "sourceFileChecksum": (
                                "0" * 32 if self.wrong_source_checksum else hashlib.md5(source).hexdigest()
                            ),
                            "assetDeliveryState": {"state": self.screenshot_state, "errors": []},
                            "imageAsset": {
                                "width": 1284,
                                "height": 2778,
                                "templateUrl": (
                                    f"https://is1-ssl.mzstatic.com/image/thumb/{shot_id}/"
                                    "{w}x{h}bb.{f}"
                                ),
                            },
                        },
                    }
                )
            return {
                "data": [
                    {
                        "type": "appScreenshotSets",
                        "id": "set-iphone",
                        "attributes": {"screenshotDisplayType": "APP_IPHONE_65"},
                        "relationships": {
                            "appScreenshots": {
                                "meta": {"paging": {"total": len(relationships), "limit": 50}},
                                "data": relationships,
                            }
                        },
                    }
                ],
                "included": shots,
            }
        raise AssertionError(f"unexpected ASC path: {path}")

    def get_asset_bytes(self, url: str) -> bytes:
        shot_id = url.split("/thumb/", 1)[1].split("/", 1)[0]
        index = int(shot_id.rsplit("-", 1)[1]) - 1
        name = self.live_names[index]
        source = self.desired_bundle / "outputs" / name
        if self.mutate_cdn_bytes:
            return _png(1284, 2778, f"cdn-mutated:{name}")
        return source.read_bytes() if source.is_file() else _png(1284, 2778, f"cdn:{name}")

    def fingerprint_secret(self, context: str, value: str) -> str:
        return hmac.new(b"test-only-fingerprint-key", f"{context}\0{value}".encode(), hashlib.sha256).hexdigest()


def test_live_mirror_pins_reviewer_surface_and_redacts_review_secrets(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png", "two.png"])
    client = FakeASCClient(desired_bundle)

    result = mod.run_audit(
        client,
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )

    document = result.document
    assert document["schema"] == "kg.app_review.asc_audit.v1"
    assert document["verdict"] == {"status": "pass", "mismatchCount": 0}
    assert document["live"]["version"]["selectedBuildRelationshipID"] == "build-6"
    assert document["live"]["build"] == {
        "id": "build-6",
        "number": "6",
        "processingState": "VALID",
        "audienceType": "APP_STORE_ELIGIBLE",
        "usesNonExemptEncryption": False,
    }
    assert document["live"]["submission"]["item"]["versionID"] == "version-1"
    assert [shot["fileName"] for shot in document["live"]["screenshots"]["items"]] == [
        "one.png",
        "two.png",
    ]
    assert all(shot["liveBytes"]["sha256"] for shot in document["live"]["screenshots"]["items"])
    review = document["live"]["reviewDetail"]
    assert review["fields"]["demoAccountName"]["identitySHA256"] == hashlib.sha256(
        b"demo@example.com"
    ).hexdigest()
    assert review["fields"]["demoAccountPassword"]["present"] is True
    assert review["fields"]["notes"]["present"] is True
    assert review["fields"]["demoAccountPassword"]["fingerprint"] != hashlib.sha256(
        client.secret_password.encode()
    ).hexdigest()
    assert "length" not in review["fields"]["demoAccountPassword"]
    serialized = mod.canonical_json_bytes(document).decode("utf-8")
    assert client.secret_password not in serialized
    assert client.secret_notes not in serialized
    assert "demo@example.com" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Demo@Example.COM\n", "demo@example.com"),
        ("\u00a0DE\u0301MO@example.com\u3000", "démo@example.com"),
        ("Straße@EXAMPLE.COM", "straße@example.com"),
        (" İTEST@EXAMPLE.COM ", "i\u0307test@example.com"),
    ],
)
def test_reviewer_username_identity_normalization_matches_ios_contract(raw: str, normalized: str):
    mod = _load_module()

    assert mod.normalized_reviewer_identity_sha256(raw) == hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_coherence_diff_reports_current_old4_vs_desired_new5_exactly(tmp_path: Path):
    mod = _load_module()
    desired_names = [
        "final_01_knowledge_graph.png",
        "final_02_vocab_list.png",
        "final_03_notebook.png",
        "final_04_stats.png",
        "final_05_today_review.png",
    ]
    live_names = [
        "final_04_reader.png",
        "final_01_vocab_list.png",
        "final_02_review_card.png",
        "final_03_other.png",
    ]
    desired_bundle = _desired_bundle(tmp_path, desired_names)

    result = mod.run_audit(
        FakeASCClient(desired_bundle, live_names=live_names),
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )

    mismatches = {item["code"]: item for item in result.document["mismatches"]}
    assert result.document["verdict"] == {
        "status": "fail",
        "mismatchCount": len(result.document["mismatches"]),
    }
    assert mismatches["screenshots.count"]["expected"] == 5
    assert mismatches["screenshots.count"]["actual"] == 4
    assert mismatches["screenshots.order"]["expected"] == desired_names
    assert mismatches["screenshots.order"]["actual"] == live_names
    assert mismatches["screenshots.missing"]["actual"] == desired_names
    assert mismatches["screenshots.extra"]["actual"] == live_names


@pytest.mark.parametrize(
    ("processing", "compliance", "expected_code"),
    [(None, False, "build.processing.unknown"), ("PROCESSING", False, "build.processing"), ("VALID", None, "build.compliance.unknown")],
)
def test_unknown_or_unready_required_live_evidence_never_passes(
    tmp_path: Path,
    processing: str | None,
    compliance: bool | None,
    expected_code: str,
):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png"])
    result = mod.run_audit(
        FakeASCClient(
            desired_bundle,
            processing_state=processing,
            compliance=compliance,
        ),
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )
    assert result.document["verdict"]["status"] == "fail"
    assert expected_code in {item["code"] for item in result.document["mismatches"]}


def test_api_error_fails_closed_without_leaking_detail(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png"])
    client = FakeASCClient(desired_bundle, api_error=True)
    with pytest.raises(mod.MirrorError) as caught:
        mod.run_audit(
            client,
            desired_bundle=desired_bundle,
            app_id="app-1",
            version_id="version-1",
            locale="zh-Hant",
            display_type="APP_IPHONE_65",
            observed_at="2026-07-13T16:00:00+08:00",
        )
    assert "503" in str(caught.value)
    assert client.secret_password not in str(caught.value)


def test_desired_unknown_manifest_field_never_reaches_live_api(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png"])
    manifest_path = desired_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capture"] = {"renderSpec": {"target": "promotion"}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(mod.MirrorError, match="exact keys"):
        mod.run_audit(
            FakeASCClient(desired_bundle),
            desired_bundle=desired_bundle,
            app_id="app-1",
            version_id="version-1",
            locale="zh-Hant",
            display_type="APP_IPHONE_65",
            observed_at="2026-07-13T16:00:00+08:00",
        )


def test_cdn_bytes_must_equal_desired_sha256_even_when_source_md5_matches(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png"])
    result = mod.run_audit(
        FakeASCClient(desired_bundle, mutate_cdn_bytes=True),
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )

    mismatch = next(
        item for item in result.document["mismatches"]
        if item["code"] == "screenshots.live-sha256:one.png"
    )
    assert result.document["verdict"]["status"] == "fail"
    assert mismatch["expected"] != mismatch["actual"]


def test_stale_build_and_wrong_screenshot_bytes_never_pass(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png"])
    result = mod.run_audit(
        FakeASCClient(
            desired_bundle,
            build_number="5",
            wrong_source_checksum=True,
            screenshot_state="PROCESSING",
        ),
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )
    mismatches = {item["code"]: item for item in result.document["mismatches"]}
    assert result.document["verdict"]["status"] == "fail"
    assert mismatches["build.number"]["classification"] == "stale"
    assert mismatches["screenshots.source-checksum:one.png"]["classification"] == "stale"
    assert mismatches["screenshots.state:one.png"]["actual"] == "PROCESSING"


def test_live_bundle_is_hash_closed_and_atomic(tmp_path: Path):
    mod = _load_module()
    desired_bundle = _desired_bundle(tmp_path, ["one.png", "two.png"])
    result = mod.run_audit(
        FakeASCClient(desired_bundle),
        desired_bundle=desired_bundle,
        app_id="app-1",
        version_id="version-1",
        locale="zh-Hant",
        display_type="APP_IPHONE_65",
        observed_at="2026-07-13T16:00:00+08:00",
    )
    output = tmp_path / "live-bundle"

    mod.write_bundle(result, desired_bundle=desired_bundle, bundle_dir=output)

    closure = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert closure["schema"] == "kg.app_review.asc_mirror_bundle.v1"
    for item in closure["files"]:
        path = output / item["path"]
        assert path.stat().st_size == item["byteSize"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    with pytest.raises(mod.MirrorError, match="已存在"):
        mod.write_bundle(result, desired_bundle=desired_bundle, bundle_dir=output)


def test_cli_help_is_read_only_and_self_describing():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "audit", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--desired-bundle" in result.stdout
    assert "--display-type" in result.stdout
    assert "--commit" in result.stdout
    assert "read-only" in result.stdout.lower()
    assert "--yes" not in result.stdout

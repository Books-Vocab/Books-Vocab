from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "app_review_gate.py"
CHECKED_SPEC = ROOT / "ops" / "app_review" / "2.0.0.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("app_review_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _png(marker: str) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + (1284).to_bytes(4, "big")
        + (2778).to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + marker.encode()
    )


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _target() -> dict:
    return {
        "appID": "app-1",
        "bundleID": "com.example.kg",
        "platform": "IOS",
        "versionID": "version-1",
        "marketingVersion": "2.0.0",
        "buildID": "build-6",
        "buildNumber": "6",
        "sourceCommit": "a" * 40,
        "datasetID": "dataset-1",
        "datasetSHA256": "b" * 64,
        "demoAccountIdentitySHA256": "e" * 64,
        "screenshotDisplayType": "APP_IPHONE_65",
    }


def _write_fixture_world(tmp_path: Path) -> Path:
    target = _target()
    desired = tmp_path / "desired"
    image = _png("desired")
    dataset = b'{"schema":"kg.fixture.dataset.v2","datasetID":"dataset-1"}'
    (desired / "inputs").mkdir(parents=True)
    (desired / "inputs" / "ui_world.json").write_bytes(dataset)
    target["datasetSHA256"] = _sha(dataset)
    project = b"MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 6;"
    profile = b'{"schema":"kg.capture.profile.v1","id":"profile-1"}'
    promotion = b'{"schema":"kg.app_review.promotion_manifest.v1"}'
    (desired / "inputs" / "project.pbxproj").write_bytes(project)
    (desired / "inputs" / "capture_profile.json").write_bytes(profile)
    (desired / "inputs" / "promotion_manifest.json").write_bytes(promotion)
    (desired / "outputs").mkdir(parents=True)
    (desired / "outputs" / "live.png").write_bytes(image)
    render_value = {
        "target": "promotion",
        "shots": [
            {
                "id": "desired",
                "outputName": "live.png",
                "copy": {"title": "Desired title", "subtitle": "Desired subtitle"},
            }
        ],
    }
    render_hash = _sha(
        json.dumps(render_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    desired_manifest = {
        "schema": "kg.app_review.submission.v1",
        "verdict": {
            "status": "pass",
            "requiredEvidence": [
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
            ],
        },
        "build": {
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
            "project": {"path": "inputs/project.pbxproj", "sha256": _sha(project)},
        },
        "source": {"commit": target["sourceCommit"]},
        "capture": {
            "profile": {
                "schema": "kg.capture.profile.v1",
                "id": "profile-1",
                "path": "inputs/capture_profile.json",
                "sha256": _sha(profile),
            },
            "dataset": {
                "schema": "kg.fixture.dataset.v2",
                "id": target["datasetID"],
                "sha256": target["datasetSHA256"],
                "path": "inputs/ui_world.json",
            },
            "device": {"destination": "platform=iOS Simulator,name=iPhone 17 Pro Max"},
            "fixedClock": "2026-07-13T08:00:00Z",
            "locale": "zh-Hant",
            "promotionManifest": {
                "schema": "kg.app_review.promotion_manifest.v1",
                "path": "inputs/promotion_manifest.json",
                "sha256": _sha(promotion),
            },
            "renderSpec": {
                "sha256": render_hash,
                "value": render_value,
            },
        },
        "outputs": [
            {
                "shotID": "desired",
                "sourceScenario": "Reader/Live",
                "appearance": "light",
                "file": "outputs/live.png",
                "byteSize": len(image),
                "sha256": _sha(image),
            }
        ],
        "provenance": {
            "generators": [{"path": "ops/reviewer_evidence.py", "sha256": "9" * 64}],
            "inputDigests": {
                "dataset": target["datasetSHA256"],
                "profile": _sha(profile),
                "project": _sha(project),
                "promotionManifest": _sha(promotion),
                "renderSpec": render_hash,
            },
            "rebuild": {
                "dataset": "inputs/ui_world.json",
                "deviceDestination": "platform=iOS Simulator,name=iPhone 17 Pro Max",
                "entrypoint": "ops/capture_profile.py",
                "fixedClock": "2026-07-13T08:00:00Z",
                "locale": "zh-Hant",
                "profile": "inputs/capture_profile.json",
            },
            "sourceCommit": target["sourceCommit"],
        },
    }
    _json(desired / "manifest.json", desired_manifest)
    desired_hash = _sha((desired / "manifest.json").read_bytes())

    live = tmp_path / "live"
    live_image = image
    live_rel = "live/images/01_live.png"
    (live / "live" / "images").mkdir(parents=True)
    (live / live_rel).write_bytes(live_image)
    (live / "desired" / "outputs").mkdir(parents=True)
    (live / "desired" / "manifest.json").write_bytes((desired / "manifest.json").read_bytes())
    (live / "desired" / "outputs" / "live.png").write_bytes(image)
    audit = {
        "schema": "kg.app_review.asc_audit.v1",
        "mode": "read-only",
        "verdict": {"status": "pass", "mismatchCount": 0},
        "desired": {
            "schema": "kg.app_review.submission.v1",
            "manifestSHA256": desired_hash,
            "build": {"marketingVersion": "2.0.0", "buildNumber": "6"},
            "locale": "zh-Hant",
            "target": "promotion",
            "outputs": [
                {
                    "order": 1,
                    "shotID": "desired",
                    "fileName": "live.png",
                    "sha256": _sha(image),
                    "sourceMD5": hashlib.md5(image).hexdigest(),
                    "byteSize": len(image),
                    "width": 1284,
                    "height": 2778,
                }
            ],
        },
        "live": {
            "observedAt": "2026-07-13T09:00:00Z",
            "appID": target["appID"],
            "version": {
                "id": target["versionID"],
                "versionString": target["marketingVersion"],
                "platform": "IOS",
                "state": "WAITING_FOR_REVIEW",
                "selectedBuildRelationshipID": target["buildID"],
                "includedBuildMatchCount": 1,
            },
            "build": {
                "id": target["buildID"],
                "number": target["buildNumber"],
                "processingState": "VALID",
                "audienceType": "APP_STORE_ELIGIBLE",
                "usesNonExemptEncryption": False,
            },
            "submission": {
                "id": "submission-1",
                "state": "WAITING_FOR_REVIEW",
                "platform": "IOS",
                "submittedDate": "2026-07-13T09:00:00Z",
                "item": {"id": "item-1", "state": "READY_FOR_REVIEW", "versionID": "version-1"},
            },
            "metadata": {
                "id": "loc-1",
                "locale": "zh-Hant",
                "fields": {
                    "description": "Live reviewer description",
                    "keywords": "live,keywords",
                    "promotionalText": "Live promo",
                    "supportUrl": "https://example.com/support",
                    "marketingUrl": "https://example.com",
                    "whatsNew": None,
                },
            },
            "reviewDetail": {
                "id": "review-1",
                "demoAccountRequired": True,
                "fields": {
                    "contactFirstName": {"present": True, "fingerprint": "1" * 64, "ref": "asc://review#first"},
                    "contactLastName": {"present": True, "fingerprint": "2" * 64, "ref": "asc://review#last"},
                    "contactPhone": {"present": True, "fingerprint": "3" * 64, "ref": "asc://review#phone"},
                    "contactEmail": {"present": True, "fingerprint": "4" * 64, "ref": "asc://review#email"},
                    "notes": {"present": True, "fingerprint": "d" * 64, "ref": "asc://review#notes"},
                    "demoAccountName": {
                        "present": True,
                        "fingerprint": "e" * 64,
                        "identitySHA256": target["demoAccountIdentitySHA256"],
                        "ref": "asc://review#name",
                    },
                    "demoAccountPassword": {"present": True, "fingerprint": "f" * 64, "ref": "asc://review#password"},
                },
            },
            "screenshots": {
                "locale": "zh-Hant",
                "displayType": "APP_IPHONE_65",
                "setID": "set-1",
                "matchingSetCount": 1,
                "relationshipCount": 1,
                "relationshipTotal": 1,
                "items": [
                    {
                        "order": 1,
                        "id": "live-shot-1",
                        "fileName": "live.png",
                        "state": "COMPLETE",
                        "width": 1284,
                        "height": 2778,
                        "sourceFileChecksum": hashlib.md5(live_image).hexdigest(),
                        "ref": "asc://shot/live-shot-1",
                        "bundlePath": live_rel,
                        "liveBytes": {
                            "status": "verified",
                            "sha256": _sha(live_image),
                            "byteSize": len(live_image),
                            "width": 1284,
                            "height": 2778,
                        },
                    }
                ],
            },
        },
        "mismatches": [],
    }
    _json(live / "audit.json", audit)
    files = []
    for rel in (
        "audit.json",
        "desired/manifest.json",
        "desired/outputs/live.png",
        live_rel,
    ):
        payload = (live / rel).read_bytes()
        files.append({"path": rel, "byteSize": len(payload), "sha256": _sha(payload)})
    _json(live / "manifest.json", {"schema": "kg.app_review.asc_mirror_bundle.v1", "files": files})

    journey_artifact = tmp_path / "evidence" / "journey.png"
    journey_artifact.parent.mkdir(parents=True)
    journey_artifact.write_bytes(_png("journey"))
    journey = {
        "schema": "kg.app_review.journey.v1",
        "id": "core",
        "claimIDs": ["metadata.core", "screenshot.live"],
        "target": {
            "bundleId": target["bundleID"],
            "marketingVersion": target["marketingVersion"],
            "buildNumber": target["buildNumber"],
            "sourceCommit": target["sourceCommit"],
        },
        "execution": {
            "evidenceKind": "exact-device",
            "configuration": "Release",
            "device": "iPhone 17 Pro Max",
            "os": "iOS 26.0",
            "locale": "zh-Hant",
            "timezone": "Asia/Taipei",
            "appearance": "light",
            "networkMode": "live",
        },
        "world": {
            "datasetID": target["datasetID"],
            "sha256": target["datasetSHA256"],
            "fixedClock": "2026-07-13T08:00:00Z",
        },
        "result": {
            "status": "pass",
            "testsExecuted": 2,
            "startedAt": "2026-07-13T09:05:00Z",
            "finishedAt": "2026-07-13T09:10:00Z",
        },
        "artifacts": [
            {"path": "evidence/journey.png", "sha256": _sha(journey_artifact.read_bytes()), "kind": "screenshot"}
        ],
    }
    _json(tmp_path / "journeys" / "core.json", journey)

    demo_artifact = tmp_path / "evidence" / "demo.png"
    demo_artifact.write_bytes(_png("demo"))
    demo = {
        "schema": "kg.app_review.demo_access.v1",
        "evidenceKind": "exact-device",
        "target": {
            "bundleId": target["bundleID"],
            "marketingVersion": target["marketingVersion"],
            "buildNumber": target["buildNumber"],
            "sourceCommit": target["sourceCommit"],
        },
        "execution": {
            "configuration": "Release",
            "device": "iPhone 17 Pro Max",
            "os": "iOS 26.0",
            "locale": "zh-Hant",
            "timezone": "Asia/Taipei",
            "networkMode": "live",
            "fixtureDataUsed": False,
        },
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": target["demoAccountIdentitySHA256"],
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:15:00Z",
        "result": {
            "status": "pass",
            "login": "pass",
            "entitlements": ["pro"],
            "testsExecuted": 2,
        },
        "artifacts": [
            {"path": "evidence/demo.png", "sha256": _sha(demo_artifact.read_bytes()), "kind": "screenshot"}
        ],
    }
    _json(tmp_path / "demo.json", demo)

    urls = {
        "schema": "kg.app_review.url_checks.v1",
        "observedAt": "2026-07-13T09:20:00Z",
        "results": [
            {
                "id": "support",
                "url": "https://example.com/support",
                "status": "pass",
                "httpStatus": 200,
                "finalUrl": "https://example.com/support",
                "contentSHA256": "1" * 64,
            }
        ],
    }
    _json(tmp_path / "urls.json", urls)

    appearance = {
        "schema": "kg.catalog.appearance.v1",
        "verdict": {"status": "pass", "proofCount": 1},
        "sourceCommit": target["sourceCommit"],
        "datasetID": target["datasetID"],
        "datasetSHA256": target["datasetSHA256"],
        "fixedClock": "2026-07-13T08:00:00Z",
        "observedAt": "2026-07-13T09:25:00Z",
        "captures": [
            {
                "id": "reader-light",
                "requestedAppearance": "light",
                "actualAppearance": "light",
                "pixelSHA256": "8" * 64,
            }
        ],
    }
    _json(tmp_path / "appearance.json", appearance)

    target["desiredManifestSHA256"] = desired_hash
    spec = {
        "schema": "kg.app_review.gate.v1",
        "target": target,
        "artifacts": {
            "desiredBundle": "desired",
            "liveMirrorBundle": "live",
            "journeys": [{"id": "core", "path": "journeys/core.json", "maxAgeHours": 24}],
            "demoAccess": {"path": "demo.json", "maxAgeHours": 24},
            "urlChecks": {"path": "urls.json", "maxAgeHours": 24},
            "appearanceProof": {
                "path": "appearance.json",
                "maxAgeHours": 24,
                "sha256": _sha((tmp_path / "appearance.json").read_bytes()),
            },
            "attestations": {
                "human": "attestations/human.json",
                "agent": "attestations/agent.json",
            },
        },
        "claims": [
            {
                "id": "metadata.core",
                "surface": {"kind": "metadata", "ref": "description"},
                "statement": "Core app workflow is available",
                "feature": "reader",
                "journeyIDs": ["core"],
                "entitlement": "free",
                "acceptedEvidenceKinds": ["exact-device", "release-equivalent-simulator"],
            },
            {
                "id": "screenshot.live",
                "surface": {"kind": "screenshot-copy", "ref": "live.png"},
                "statement": "Screenshot reflects the live reviewer build",
                "feature": "reader",
                "journeyIDs": ["core"],
                "entitlement": "pro",
                "acceptedEvidenceKinds": ["exact-device"],
            },
            {
                "id": "review.demo",
                "surface": {"kind": "review-notes", "ref": "notes"},
                "statement": "Reviewer demo login and Pro access work",
                "feature": "authentication",
                "journeyIDs": [],
                "entitlement": "pro",
                "acceptedEvidenceKinds": ["exact-device", "live-demo"],
            },
            {
                "id": "website.support",
                "surface": {"kind": "website", "ref": "support"},
                "statement": "Support URL is live",
                "feature": "support",
                "journeyIDs": [],
                "entitlement": "none",
                "acceptedEvidenceKinds": ["live-url"],
            },
        ],
        "requiredLiveURLs": [
            {"id": "support", "url": "https://example.com/support", "claimIDs": ["website.support"]}
        ],
        "producers": {
            "desiredBundle": {"type": "desired-bundle", "authority": "repo", "command": "produce desired"},
            "liveMirrorBundle": {"type": "asc-live-mirror", "authority": "asc-get", "command": "produce live"},
            "journey.core": {"type": "ios-ui-journey", "authority": "ios-release-test", "command": "produce journey"},
            "demoAccess": {"type": "demo-access", "authority": "live-demo", "command": "produce demo"},
            "urlChecks": {"type": "url-checks", "authority": "https-get", "command": "produce urls"},
            "appearanceProof": {"type": "catalog-appearance", "authority": "catalog-run", "command": "produce appearance"},
            "attestation.human": {"type": "human-attestation", "authority": "release-owner", "command": "attest human"},
            "attestation.agent": {"type": "agent-attestation", "authority": "gate-agent", "command": "attest agent"},
        },
        "freshness": {"liveMirrorMaxAgeHours": 24, "attestationMaxAgeHours": 24},
    }
    _json(tmp_path / "spec.json", spec)
    return tmp_path / "spec.json"


def test_gate_rejects_missing_typed_producer(tmp_path: Path):
    mod = _load_module()
    spec_path = _write_fixture_world(tmp_path)
    spec = json.loads(spec_path.read_text())
    spec["producers"].pop("journey.core")
    _json(spec_path, spec)

    with pytest.raises(mod.GateError, match="exactly cover"):
        mod.load_spec(spec_path)


def _attest(tmp_path: Path, root: str, actor_type: str) -> None:
    spec = json.loads((tmp_path / "spec.json").read_text())
    _json(
        tmp_path / "attestations" / f"{actor_type}.json",
        {
            "schema": "kg.app_review.attestation.v1",
            "actorType": actor_type,
            "subject": f"{actor_type}-reviewer",
            "attestationKind": "semantic",
            "claimIDs": [claim["id"] for claim in spec["claims"]],
            "status": "attested",
            "preAttestationRootSHA256": root,
            "observedAt": "2026-07-13T09:30:00Z",
            "expiresAt": "2026-07-14T09:30:00Z",
        },
    )


def test_gate_fails_closed_offline_and_requires_attestations(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="offline",
    )

    codes = {item["code"] for item in result.document["blocks"]}
    assert result.document["verdict"]["status"] == "block"
    assert "observation.offline" in codes
    assert "attestation.human.missing" in codes
    assert "attestation.agent.missing" in codes
    assert len(result.document["preAttestationRootSHA256"]) == 64


def test_online_gate_passes_only_with_fresh_root_bound_evidence(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    first = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "human")
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "agent")

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    assert result.document["verdict"] == {"status": "pass", "blockCount": 0}
    assert [item["fileName"] for item in result.document["reviewerView"]["screenshots"]] == ["live.png"]
    assert result.document["reviewerView"]["metadata"]["description"] == "Live reviewer description"
    assert "Desired title" not in result.html
    assert "Live reviewer description" in result.html
    assert "live/images/01_live.png" in result.html
    assert "metadata.core" in result.html


def test_material_change_invalidates_both_attestations(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    first = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "human")
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "agent")
    urls_path = tmp_path / "urls.json"
    urls = json.loads(urls_path.read_text())
    urls["results"][0]["contentSHA256"] = "2" * 64
    _json(urls_path, urls)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    codes = {item["code"] for item in result.document["blocks"]}
    assert "attestation.human.root" in codes
    assert "attestation.agent.root" in codes


def test_unknown_journey_and_fixture_demo_cannot_pass(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    journey_path = tmp_path / "journeys" / "core.json"
    journey = json.loads(journey_path.read_text())
    journey["result"]["status"] = "unknown"
    _json(journey_path, journey)
    demo_path = tmp_path / "demo.json"
    demo = json.loads(demo_path.read_text())
    demo["evidenceKind"] = "release-equivalent-simulator"
    _json(demo_path, demo)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    codes = {item["code"] for item in result.document["blocks"]}
    assert "journey.core.status" in codes
    assert "demo.evidence-kind" in codes


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("target", "journey.core.target.buildNumber"),
        ("artifact-hash", "journey.core.artifact.0.sha256"),
        ("stale", "journey.core.freshness"),
        ("missing", "journey.core.missing"),
    ],
)
def test_journey_path_hash_target_and_freshness_mismatches_block(
    tmp_path: Path, mutation: str, expected_code: str
):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    journey_path = tmp_path / "journeys" / "core.json"
    journey = json.loads(journey_path.read_text())
    if mutation == "target":
        journey["target"]["buildNumber"] = "5"
    elif mutation == "artifact-hash":
        journey["artifacts"][0]["sha256"] = "0" * 64
    elif mutation == "stale":
        journey["result"]["startedAt"] = "2026-07-10T09:00:00Z"
        journey["result"]["finishedAt"] = "2026-07-10T09:10:00Z"
    elif mutation == "missing":
        journey_path.unlink()
    if mutation != "missing":
        _json(journey_path, journey)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    assert expected_code in {item["code"] for item in result.document["blocks"]}


def test_malformed_live_review_secret_is_never_copied_or_serialized(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    audit_path = tmp_path / "live" / "audit.json"
    audit = json.loads(audit_path.read_text())
    secret = "must-never-enter-reviewer-bundle"
    audit["live"]["reviewDetail"]["fields"]["demoAccountPassword"]["plaintext"] = secret
    _json(audit_path, audit)
    closure_path = tmp_path / "live" / "manifest.json"
    closure = json.loads(closure_path.read_text())
    audit_bytes = audit_path.read_bytes()
    audit_entry = next(item for item in closure["files"] if item["path"] == "audit.json")
    audit_entry["byteSize"] = len(audit_bytes)
    audit_entry["sha256"] = _sha(audit_bytes)
    _json(closure_path, closure)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    assert "live-mirror.invalid" in {item["code"] for item in result.document["blocks"]}
    assert secret not in json.dumps(result.document)
    assert secret not in result.html
    assert all(secret.encode() not in payload for payload in result.files.values())


def test_unknown_live_audit_top_level_secret_is_never_copied(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    audit_path = tmp_path / "live" / "audit.json"
    audit = json.loads(audit_path.read_text())
    secret = "unknown-top-level-secret"
    audit["unexpectedSecret"] = secret
    _json(audit_path, audit)
    closure_path = tmp_path / "live" / "manifest.json"
    closure = json.loads(closure_path.read_text())
    audit_bytes = audit_path.read_bytes()
    audit_entry = next(item for item in closure["files"] if item["path"] == "audit.json")
    audit_entry.update(byteSize=len(audit_bytes), sha256=_sha(audit_bytes))
    _json(closure_path, closure)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    assert "live-mirror.invalid" in {item["code"] for item in result.document["blocks"]}
    assert all(secret.encode() not in payload for payload in result.files.values())


def test_live_outer_closure_cannot_smuggle_unreferenced_secret(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    secret = b"unreferenced-secret-file"
    secret_path = tmp_path / "live" / "unreferenced-secret.txt"
    secret_path.write_bytes(secret)
    closure_path = tmp_path / "live" / "manifest.json"
    closure = json.loads(closure_path.read_text())
    closure["files"].append(
        {"path": "unreferenced-secret.txt", "byteSize": len(secret), "sha256": _sha(secret)}
    )
    _json(closure_path, closure)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    invalid = next(item for item in result.document["blocks"] if item["code"] == "live-mirror.invalid")
    assert "semantic closure" in invalid["actual"]
    assert all(secret not in payload for payload in result.files.values())


def test_phase2_unknown_required_build_state_cannot_hide_behind_pass_verdict(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    audit_path = tmp_path / "live" / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["live"]["build"]["processingState"] = None
    _json(audit_path, audit)
    closure_path = tmp_path / "live" / "manifest.json"
    closure = json.loads(closure_path.read_text())
    audit_bytes = audit_path.read_bytes()
    audit_entry = next(item for item in closure["files"] if item["path"] == "audit.json")
    audit_entry.update(byteSize=len(audit_bytes), sha256=_sha(audit_bytes))
    _json(closure_path, closure)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    invalid = next(item for item in result.document["blocks"] if item["code"] == "live-mirror.invalid")
    assert "processing/audience/compliance" in invalid["actual"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("order", 99, "required evidence"),
        ("sourceFileChecksum", "0" * 32, "source checksum/order"),
    ],
)
def test_phase2_screenshot_order_and_source_checksum_are_reasserted(
    tmp_path: Path, field: str, value: object, message: str
):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    audit_path = tmp_path / "live" / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["live"]["screenshots"]["items"][0][field] = value
    _json(audit_path, audit)
    closure_path = tmp_path / "live" / "manifest.json"
    closure = json.loads(closure_path.read_text())
    audit_bytes = audit_path.read_bytes()
    audit_entry = next(item for item in closure["files"] if item["path"] == "audit.json")
    audit_entry.update(byteSize=len(audit_bytes), sha256=_sha(audit_bytes))
    _json(closure_path, closure)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    invalid = next(item for item in result.document["blocks"] if item["code"] == "live-mirror.invalid")
    assert message in invalid["actual"]


def test_phase1_required_objects_are_not_optional(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    manifest_path = tmp_path / "desired" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["capture"]["profile"]
    _json(manifest_path, manifest)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    invalid = next(item for item in result.document["blocks"] if item["code"] == "desired.invalid")
    assert "closed contract" in invalid["actual"]


def test_demo_claim_cannot_self_label_fixture_as_exact_device(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    demo_path = tmp_path / "demo.json"
    demo = json.loads(demo_path.read_text())
    demo["execution"]["fixtureDataUsed"] = True
    demo["account"]["provenance"] = "fixture-account"
    _json(demo_path, demo)

    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    codes = {item["code"] for item in result.document["blocks"]}
    assert "demo.fixture-data" in codes
    assert "demo.account.live-binding" in codes


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing", "appearance.missing"),
        ("hash", "appearance.sha256"),
        ("verdict", "appearance.verdict"),
        ("pixel", "appearance.capture.0.appearance"),
    ],
)
def test_appearance_proof_is_required_hash_pinned_and_fail_closed(
    tmp_path: Path, mutation: str, expected_code: str
):
    mod = _load_module()
    spec_path = _write_fixture_world(tmp_path)
    appearance_path = tmp_path / "appearance.json"
    appearance = json.loads(appearance_path.read_text())
    if mutation == "missing":
        appearance_path.unlink()
    elif mutation == "hash":
        appearance["captures"][0]["pixelSHA256"] = "7" * 64
        _json(appearance_path, appearance)
    elif mutation == "verdict":
        appearance["verdict"]["status"] = "fail"
        _json(appearance_path, appearance)
    elif mutation == "pixel":
        appearance["captures"][0]["actualAppearance"] = "dark"
        _json(appearance_path, appearance)
    if mutation in {"verdict", "pixel"}:
        spec = json.loads(spec_path.read_text())
        spec["artifacts"]["appearanceProof"]["sha256"] = _sha(appearance_path.read_bytes())
        _json(spec_path, spec)

    result = mod.evaluate_gate(
        spec_path=spec_path,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )

    assert expected_code in {item["code"] for item in result.document["blocks"]}


def test_bundle_is_exactly_hash_closed_and_verify_detects_extra(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    first = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "human")
    _attest(tmp_path, first.document["preAttestationRootSHA256"], "agent")
    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="online",
    )
    output = tmp_path / "reviewer-bundle"
    mod.write_bundle(result, output)

    verification = mod.verify_bundle(output)
    assert verification["status"] == "pass"
    assert verification["gateVerdict"] == "pass"
    assert verification["submitReady"] is True
    assert (output / "report.json").is_file()
    assert (output / "report.html").is_file()
    (output / "extra.txt").write_text("not closed")
    with pytest.raises(mod.GateError, match="closure"):
        mod.verify_bundle(output)


def test_cli_verify_never_false_greens_a_hash_valid_blocked_bundle(tmp_path: Path):
    mod = _load_module()
    spec = _write_fixture_world(tmp_path)
    result = mod.evaluate_gate(
        spec_path=spec,
        workspace_root=tmp_path,
        observed_at="2026-07-13T10:00:00Z",
        observation_mode="offline",
    )
    output = tmp_path / "blocked-bundle"
    mod.write_bundle(result, output)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "verify", "--bundle", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert payload["status"] == "pass"
    assert payload["gateVerdict"] == "block"
    assert payload["submitReady"] is False


def test_checked_in_2_0_0_spec_is_closed_and_self_describing():
    mod = _load_module()
    spec = mod.load_spec(CHECKED_SPEC)

    assert spec["schema"] == "kg.app_review.gate.v1"
    assert spec["target"]["marketingVersion"] == "2.0.0"
    assert spec["target"]["buildNumber"] == "6"
    assert {claim["surface"]["kind"] for claim in spec["claims"]} >= {
        "metadata",
        "review-notes",
        "screenshot-copy",
        "website",
    }
    assert all(claim["acceptedEvidenceKinds"] for claim in spec["claims"])


@pytest.mark.parametrize("command", ["dry-run", "verify"])
def test_cli_help_is_read_only_schema_driven_and_self_describing(command: str):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), command, "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--spec" in result.stdout
    assert "--observation-mode" in result.stdout
    assert "offline always BLOCK" in result.stdout
    assert "--yes" not in result.stdout
    assert "submit" not in result.stdout.lower()

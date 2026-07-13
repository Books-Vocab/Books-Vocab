from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "app_review_evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("app_review_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evidence = load_module()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_spec(tmp_path: Path) -> dict:
    dataset = tmp_path / "world.json"
    dataset.write_text(json.dumps({"datasetID": "world-1"}), encoding="utf-8")
    return {
        "schema": "kg.app_review.gate.v1",
        "target": {
            "bundleID": "com.example.app",
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
            "sourceCommit": "a" * 40,
            "datasetID": "world-1",
            "datasetSHA256": sha(dataset.read_bytes()),
        },
        "artifacts": {
            "urlChecks": {"path": "url.json", "maxAgeHours": 12},
            "journeys": [{"id": "core", "path": "core.json", "maxAgeHours": 24}],
            "attestations": {"human": "human.json", "agent": "agent.json"},
        },
        "requiredLiveURLs": [
            {"id": "site", "url": "https://example.com/", "claimIDs": ["web"]}
        ],
        "claims": [{"id": "web", "journeyIDs": []}, {"id": "core-claim", "journeyIDs": ["core"]}],
        "producers": {
            "urlChecks": {"type": "url-checks", "authority": "live-https-get", "command": "url command"},
            "journey.core": {"type": "ios-ui-journey", "authority": "ios-release-test", "command": "journey command"},
            "attestation.human": {"type": "human-attestation", "authority": "release-owner", "command": "human command"},
            "attestation.agent": {"type": "agent-attestation", "authority": "gate-agent", "command": "agent command"},
        },
    }


def test_url_checks_get_hashes_exact_body_and_rejects_redirect_or_error(tmp_path: Path):
    spec = base_spec(tmp_path)

    passed = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda url: (200, url, b"body"),
    )
    redirected = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda _url: (302, "https://example.com/new", b"redirect"),
    )
    failed = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda _url: (_ for _ in ()).throw(OSError("offline")),
    )

    assert passed["schema"] == "kg.app_review.url_checks.v1"
    assert passed["results"][0] == {
        "id": "site",
        "url": "https://example.com/",
        "status": "pass",
        "httpStatus": 200,
        "finalUrl": "https://example.com/",
        "contentSHA256": sha(b"body"),
    }
    assert redirected["results"][0]["status"] == "error"
    assert failed["results"][0]["status"] == "error"


def valid_run(tmp_path: Path, spec: dict) -> dict:
    artifact = tmp_path / "journey.png"
    artifact.write_bytes(b"png")
    target = spec["target"]
    return {
        "schema": "kg.ios.run.v1",
        "status": "ok",
        "result": "ok",
        "executed": "2",
        "options": {
            "evidenceProducer": "ops/ios_test.sh",
            "configuration": "Release",
            "bundleID": target["bundleID"],
            "marketingVersion": target["marketingVersion"],
            "buildNumber": target["buildNumber"],
            "sourceCommit": target["sourceCommit"],
            "datasetID": target["datasetID"],
            "datasetSHA256": target["datasetSHA256"],
            "fixedClock": "2026-07-13T08:00:00Z",
            "startedAt": "2026-07-13T09:00:00Z",
            "finishedAt": "2026-07-13T09:05:00Z",
            "evidenceKind": "release-equivalent-simulator",
            "device": "iPhone 17 Pro Max",
            "os": "iOS 26.0",
            "locale": "zh-Hant",
            "timezone": "Asia/Taipei",
            "appearance": "light",
            "networkMode": "fixture",
            "fixtureDataUsed": True,
        },
        "artifacts": {"uiContactSheet": str(artifact)},
    }


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda run: run.update(executed="0"), "journey.tests"),
        (lambda run: run["options"].update(configuration="Debug"), "journey.configuration"),
        (lambda run: run["options"].update(sourceCommit="b" * 40), "journey.sourceCommit"),
        (lambda run: run["options"].update(datasetSHA256="b" * 64), "journey.datasetSHA256"),
        (lambda run: run["options"].update(buildNumber="7"), "journey.buildNumber"),
        (lambda run: run["options"].update(evidenceKind="live-demo"), "journey.evidenceKind"),
        (lambda run: run["options"].update(evidenceProducer="caller"), "journey.producer"),
    ],
)
def test_journey_consumer_blocks_false_green_debug_and_provenance_drift(tmp_path: Path, mutation, code: str):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    mutation(run)

    with pytest.raises(evidence.EvidenceError, match=code):
        evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)


def test_journey_producer_hashes_artifacts_and_emits_exact_contract(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)

    result = evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)

    assert result["schema"] == "kg.app_review.journey.v1"
    assert result["result"]["testsExecuted"] == 2
    assert result["execution"]["configuration"] == "Release"
    assert result["artifacts"][0]["path"] == "journey.png"
    assert result["artifacts"][0]["sha256"] == sha(b"png")


def test_demo_producer_rejects_fixture_masquerading_as_live_demo(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    release = run["options"]
    run["demoEvidence"] = {
        **release,
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "live-demo",
        "networkMode": "live",
        "fixtureDataUsed": True,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "credentialFingerprint": "c" * 64,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.fixtureDataUsed"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_consumer_rejects_caller_magic_string_without_ios_owner(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["demoEvidence"] = {"evidenceProducer": "ops/app_review_evidence.py:live-demo"}

    with pytest.raises(evidence.EvidenceError, match="demo.producer"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_journey_rejects_artifact_outside_workspace(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    outside = tmp_path.parent / "outside-review-proof.png"
    outside.write_bytes(b"png")
    run["artifacts"]["uiContactSheet"] = str(outside)

    with pytest.raises(evidence.EvidenceError, match="journey.artifact.outside-workspace"):
        evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)


def test_plan_hard_blocks_missing_producer_and_lists_authority(tmp_path: Path):
    spec = base_spec(tmp_path)
    spec["producers"].pop("journey.core")

    plan = evidence.build_plan(spec, tmp_path)

    missing = next(item for item in plan["evidence"] if item["id"] == "journey.core")
    human = next(item for item in plan["evidence"] if item["id"] == "attestation.human")
    assert missing["status"] == "block"
    assert missing["reason"] == "producer-missing"
    assert human["authority"] == "release-owner"
    assert human["command"] == "human command"


def test_status_does_not_mark_existing_but_invalid_artifact_ready(tmp_path: Path):
    spec = base_spec(tmp_path)
    (tmp_path / "url.json").write_text("{}", encoding="utf-8")
    plan = evidence.build_plan(spec, tmp_path)

    status = evidence.apply_gate_blocks(
        plan,
        {"verdict": {"status": "block"}, "blocks": [{"code": "urls.schema"}]},
    )

    url_item = next(item for item in status["evidence"] if item["id"] == "urlChecks")
    assert url_item["status"] == "block"
    assert url_item["reason"] == "gate:urls.schema"


def test_appearance_producer_requires_receipt_and_target_bindings(tmp_path: Path):
    spec = base_spec(tmp_path)
    spec["target"]["sourceCommit"] = "a" * 40
    root = tmp_path / "catalog"
    root.mkdir()
    shared = {
        "sourceCommit": "a" * 40,
        "datasetID": spec["target"]["datasetID"],
        "datasetSHA256": spec["target"]["datasetSHA256"],
        "fixedClock": "2026-07-13T08:00:00Z",
    }
    (root / "catalog_appearance.json").write_text(json.dumps({"schema": "kg.catalog.appearance.v1", **shared, "verdict": {"status": "pass"}}), encoding="utf-8")
    (root / "catalog_run_receipt.json").write_text(json.dumps({"schema": "kg.ios.catalog.run_receipt.v1", **shared, "status": "pass"}), encoding="utf-8")

    assert evidence.produce_appearance(spec, root)["verdict"]["status"] == "pass"
    drift = json.loads((root / "catalog_run_receipt.json").read_text(encoding="utf-8"))
    drift["sourceCommit"] = "b" * 40
    (root / "catalog_run_receipt.json").write_text(json.dumps(drift), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="appearance.receipt.sourceCommit"):
        evidence.produce_appearance(spec, root)


@pytest.mark.skipif(sys.platform != "darwin", reason="renameatx_np is the macOS atomic directory exchange")
def test_desired_publication_atomically_exchanges_complete_directories(tmp_path: Path):
    destination = tmp_path / "bundle"
    staged = tmp_path / "stage"
    destination.mkdir()
    staged.mkdir()
    (destination / "old").write_text("old", encoding="utf-8")
    (staged / "new").write_text("new", encoding="utf-8")

    evidence._publish_directory_atomically(staged, destination)

    assert (destination / "new").read_text(encoding="utf-8") == "new"
    assert not (destination / "old").exists()
    assert (staged / "old").read_text(encoding="utf-8") == "old"

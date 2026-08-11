from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))

from lib.app_review_evaluators import (
    ATTESTATION_SCHEMA,
    DEMO_SCHEMA,
    JOURNEY_SCHEMA,
    EvidenceResult,
    evaluate_attestation,
    evaluate_claims,
    evaluate_demo,
    evaluate_journey,
    evaluate_urls,
    thaw,
)

OBSERVED = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
TARGET = {
    "bundleID": "com.example.kg",
    "marketingVersion": "2.0.0",
    "buildNumber": "6",
    "sourceCommit": "a" * 40,
    "datasetID": "dataset-1",
    "datasetSHA256": "b" * 64,
    "demoAccountIdentitySHA256": "e" * 64,
    "desiredManifestSHA256": "d" * 64,
    "appID": "app-1",
    "versionID": "version-1",
    "buildID": "build-6",
    "platform": "IOS",
    "screenshotDisplayType": "APP_IPHONE_65",
}


def _journey() -> dict:
    return {
        "schema": JOURNEY_SCHEMA,
        "id": "core",
        "claimIDs": ["metadata.core"],
        "target": {
            "bundleId": TARGET["bundleID"],
            "marketingVersion": TARGET["marketingVersion"],
            "buildNumber": TARGET["buildNumber"],
            "sourceCommit": TARGET["sourceCommit"],
        },
        "execution": {
            "evidenceKind": "exact-device",
            "configuration": "Release",
            "device": "iPhone",
            "os": "18.5",
            "locale": "zh-Hant",
            "timezone": "Asia/Taipei",
            "appearance": "light",
            "networkMode": "fixture",
        },
        "world": {"datasetID": TARGET["datasetID"], "sha256": TARGET["datasetSHA256"], "fixedClock": "2026-08-10T23:00:00Z"},
        "result": {
            "status": "pass",
            "testsExecuted": 1,
            "startedAt": "2026-08-10T23:10:00Z",
            "finishedAt": "2026-08-10T23:20:00Z",
        },
        "artifacts": [{"path": "evidence.png", "sha256": "f" * 64, "kind": "screenshot"}],
    }


def test_evidence_result_is_frozen_and_claim_tokens_are_immutable():
    result = EvidenceResult(
        blocks=({"code": "x", "expected": {"nested": 1}, "actual": []},),
        evidence_by_claim={"c": ["journey:core:exact-device"]},
        summary={"claims": [{"id": "c"}]},
        state={"live_body": {"nested": {"value": 1}}},
    )
    assert result.evidence_by_claim["c"] == ("journey:core:exact-device",)
    for mutation in (
        lambda: result.blocks[0]["expected"].__setitem__("nested", 2),
        lambda: result.summary["claims"][0].__setitem__("id", "mutated"),
        lambda: result.state["live_body"].__setitem__("x", 2),
    ):
        try:
            mutation()
        except (TypeError, AttributeError):
            pass
        else:
            raise AssertionError("nested EvidenceResult values must be read-only")
    try:
        result.state["mutate"] = True  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("state must be read-only")


def test_journey_evaluator_returns_only_its_claim_tokens():
    result = evaluate_journey(
        _journey(),
        ref={"id": "core", "maxAgeHours": 24},
        claims=[{"id": "metadata.core", "journeyIDs": ["core"], "acceptedEvidenceKinds": ["exact-device"]}],
        target=TARGET,
        desired={"fixedClock": "2026-08-10T23:00:00Z"},
        observed_at=OBSERVED,
        artifacts_ok=True,
    )
    assert result.blocks == ()
    assert result.evidence_by_claim["metadata.core"] == ("journey:core:exact-device",)
    assert result.state["valid"] is True


def test_journey_evaluator_rejects_stale_or_bad_artifacts_without_shared_state():
    journey = _journey()
    journey["result"]["finishedAt"] = "2026-08-09T00:00:00Z"
    result = evaluate_journey(
        journey,
        ref={"id": "core", "maxAgeHours": 1},
        claims=[{"id": "metadata.core", "journeyIDs": ["core"], "acceptedEvidenceKinds": ["exact-device"]}],
        target=TARGET,
        desired={"fixedClock": "2026-08-10T23:00:00Z"},
        observed_at=OBSERVED,
        artifacts_ok=False,
    )
    codes = {item["code"] for item in result.blocks}
    assert "journey.core.freshness" in codes
    assert result.evidence_by_claim == {}


def test_demo_evaluator_fail_closes_fixture_and_account_binding():
    demo = {
        "schema": DEMO_SCHEMA,
        "evidenceKind": "exact-device",
        "target": {"bundleId": TARGET["bundleID"], "marketingVersion": TARGET["marketingVersion"], "buildNumber": TARGET["buildNumber"], "sourceCommit": TARGET["sourceCommit"]},
        "execution": {"configuration": "Release", "device": "iPhone", "os": "18.5", "locale": "zh-Hant", "timezone": "Asia/Taipei", "networkMode": "live", "fixtureDataUsed": True},
        "account": {"provenance": "fixture-account", "accountRef": "fixture", "accountIdentitySHA256": "e" * 64, "entitlementSource": "fixture"},
        "observedAt": "2026-08-10T23:00:00Z",
        "result": {"status": "pass", "login": "pass", "entitlements": ["pro"], "testsExecuted": 1},
        "artifacts": [{"path": "evidence.png", "sha256": "f" * 64, "kind": "screenshot"}],
    }
    result = evaluate_demo(
        demo,
        ref={"maxAgeHours": 24},
        claims=[{"id": "review.demo", "acceptedEvidenceKinds": ["exact-device"]}],
        target=TARGET,
        live_body={"reviewDetail": {"fields": {"demoAccountName": {"ref": "live", "identitySHA256": "e" * 64}}}},
        observed_at=OBSERVED,
        artifacts_ok=True,
    )
    codes = {item["code"] for item in result.blocks}
    assert {"demo.fixture-data", "demo.account.live-binding"} <= codes
    assert result.evidence_by_claim == {}


def test_urls_and_attestation_are_independent_result_types():
    urls = evaluate_urls(
        {"schema": "kg.app_review.url_checks.v1", "observedAt": "2026-08-10T23:00:00Z", "results": [{"id": "support", "url": "https://example.com/support", "status": "pass", "httpStatus": 200, "finalUrl": "https://example.com/support", "contentSHA256": "f" * 64}]},
        required_urls=[{"id": "support", "url": "https://example.com/support", "claimIDs": ["website.support"]}],
        target=TARGET,
        live_body={"metadata": {"fields": {"supportUrl": "https://example.com/support"}}},
        observed_at=OBSERVED,
    )
    attestation = evaluate_attestation(
        {"schema": ATTESTATION_SCHEMA, "actorType": "agent", "subject": "agent", "attestationKind": "semantic", "claimIDs": ["website.support"], "status": "attested", "preAttestationRootSHA256": "a" * 64, "observedAt": "2026-08-10T23:00:00Z", "expiresAt": "2026-08-12T00:00:00Z"},
        actor="agent",
        claim_ids=["website.support"],
        pre_root="a" * 64,
        observed_at=OBSERVED,
        max_age_hours=24,
    )
    assert urls.blocks == ()
    assert urls.evidence_by_claim["website.support"] == ("url:support:live-url",)
    assert attestation.blocks == ()


def test_url_evaluator_rejects_non_hex_digest():
    result = evaluate_urls(
        {"schema": "kg.app_review.url_checks.v1", "observedAt": "2026-08-10T23:00:00Z", "results": [{"id": "support", "url": "https://example.com/support", "status": "pass", "httpStatus": 200, "finalUrl": "https://example.com/support", "contentSHA256": "g" * 64}]},
        required_urls=[{"id": "support", "url": "https://example.com/support", "claimIDs": ["website.support"]}],
        target=TARGET,
        live_body={"metadata": {"fields": {"supportUrl": "https://example.com/support"}}},
        observed_at=OBSERVED,
    )
    assert "url.support.status" in {item["code"] for item in result.blocks}
    assert result.evidence_by_claim == {}


def test_claim_reducer_preserves_report_shape_and_flags_missing_surface():
    result = evaluate_claims(
        [{"id": "metadata.core", "surface": {"kind": "metadata", "ref": "description"}, "statement": "description exists", "feature": "review", "entitlement": "none", "acceptedEvidenceKinds": ["exact-device"], "journeyIDs": ["core"]}],
        evidence_by_claim={"metadata.core": ["journey:core:exact-device"]},
        journey_evidence_by_id={"core": "exact-device"},
        live_names=set(),
        desired_names=set(),
        required_url_ids=set(),
        live_body={"metadata": {"fields": {"description": "present"}}},
    )
    assert result.blocks == ()
    assert thaw(result.summary)["claims"][0]["evidence"] == ["journey:core:exact-device"]

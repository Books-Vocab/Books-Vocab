from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/app_review_evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("app_review_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_spec() -> dict:
    return json.loads((ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8"))


def test_public_cli_has_no_catalog_or_image_generation_producers() -> None:
    module = load_module()
    choices = module.parser()._subparsers._group_actions[0].choices
    assert set(choices) == {"plan", "status", "urls", "journey", "journey-run", "demo-run", "attest"}
    assert not {"desired", "refresh-anchor", "appearance"} & set(choices)


def test_checked_spec_requires_manual_final_bundle_not_catalog_output() -> None:
    spec = checked_spec()
    producer = spec["producers"]["desiredBundle"]
    assert producer == {
        "authority": "release owner supplied final ASC bundle",
        "command": "test -f build/app-review/desired-2.0.0/bundle/manifest.json",
        "type": "desired-bundle",
    }
    encoded = json.dumps(spec, ensure_ascii=False)
    for retired in ("appearanceProof", "catalog-appearance", "capture_profile", "catalog snapshots"):
        assert retired not in encoded


def test_required_evidence_excludes_catalog_artifacts() -> None:
    module = load_module()
    ids = {item[0] for item in module.required_evidence(checked_spec())}
    assert "appearanceProof" not in ids
    assert {"desiredBundle", "liveMirrorBundle", "demoAccess", "urlChecks"} <= ids


def test_plan_preserves_typed_manual_bundle_authority(tmp_path: Path) -> None:
    module = load_module()
    spec = checked_spec()
    plan = module.build_plan(spec, tmp_path)
    desired = next(item for item in plan["evidence"] if item["id"] == "desiredBundle")
    assert desired["status"] == "block"
    assert desired["reason"] == "artifact-missing"
    assert desired["authority"] == "release owner supplied final ASC bundle"


def test_url_checks_hash_exact_body_and_reject_redirect() -> None:
    module = load_module()
    spec = {
        "requiredLiveURLs": [
            {"id": "support", "url": "https://example.com/support", "claimIDs": ["website.support"]},
            {"id": "privacy", "url": "https://example.com/privacy", "claimIDs": ["website.privacy"]},
        ]
    }

    def fetch(url: str):
        if url.endswith("support"):
            return 200, url, b"support"
        return 200, "https://redirected.example/privacy", b"privacy"

    report = module.produce_url_checks(spec, observed_at="2026-08-09T00:00:00Z", fetch=fetch)
    assert report["results"][0]["status"] == "pass"
    assert report["results"][0]["contentSHA256"] == module._sha(b"support")
    assert report["results"][1]["status"] == "error"


def test_attestation_is_bound_to_the_pre_attestation_root() -> None:
    module = load_module()
    document = module.produce_attestation(
        checked_spec(),
        actor="agent",
        subject="independent-reviewer",
        root_sha256="a" * 64,
        observed_at="2026-08-09T00:00:00Z",
        expires_at="2026-08-10T00:00:00Z",
    )
    assert document["schema"] == "kg.app_review.attestation.v1"
    assert document["preAttestationRootSHA256"] == "a" * 64
    assert document["status"] == "attested"

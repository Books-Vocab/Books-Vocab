from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
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


def test_producer_runner_reports_progress_on_stderr_and_preserves_json_stdout(tmp_path: Path):
    stdout = io.StringIO()
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import json,time; time.sleep(.08); print(json.dumps({'status':'pass'}))",
    ]

    with redirect_stdout(stdout), redirect_stderr(stderr):
        completed = evidence._run_producer_command(
            command,
            cwd=tmp_path,
            producer_name="desired-test",
            heartbeat_interval=0.02,
        )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"status": "pass"}
    assert stdout.getvalue() == ""
    progress = stderr.getvalue()
    assert "producer=desired-test phase=start" in progress
    assert "phase=heartbeat" in progress
    assert "alive=true" in progress
    assert "phase=done" in progress


def test_journey_demo_and_gate_use_named_streaming_runner(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def fake_runner(command, *, cwd, producer_name, heartbeat_interval=20.0):
        calls.append(producer_name)
        payload = {"verdict": {}, "blocks": []} if producer_name == "gate-evaluation" else {"status": "pass"}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(evidence, "_run_producer_command", fake_runner)
    evidence.execute_journey_run(
        workspace_root=tmp_path,
        dataset_file=tmp_path / "world.json",
        fixed_clock="2026-07-13T08:00:00Z",
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
        appearance="light",
        tests=["testCore"],
    )
    evidence.execute_demo_run(
        workspace_root=tmp_path,
        destination="platform=iOS,id=device",
        account_identity_sha256="d" * 64,
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
    )
    evidence.evaluate_gate(tmp_path / "spec.json", tmp_path)

    assert calls == ["journey-run", "demo-run", "gate-evaluation"]


def test_desired_pipeline_streams_every_subprocess_phase(tmp_path: Path, monkeypatch):
    import capture_profile

    profile_file = tmp_path / "profile.yml"
    profile_file.write_text("profile", encoding="utf-8")
    dataset_bytes = b'{"schema":"world"}\n'
    spec = {
        "target": {
            "datasetSHA256": sha(dataset_bytes),
            "sourceCommit": "a" * 40,
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
        }
    }
    profile = type("Profile", (), {"profile_id": "review"})()
    monkeypatch.setattr(capture_profile, "load_profile", lambda _path: profile)
    monkeypatch.setattr(capture_profile, "reviewer_render_spec", lambda _profile: {"shots": []})
    calls: list[str] = []

    def fake_runner(command, *, cwd, producer_name, heartbeat_interval=20.0):
        calls.append(producer_name)
        if producer_name == "desired-build":
            Path(command[command.index("--out") + 1]).write_bytes(dataset_bytes)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(evidence, "_run_producer_command", fake_runner)
    evidence.produce_desired_bundle(
        spec,
        workspace_root=tmp_path,
        profile_file=profile_file,
        render_output_dir=tmp_path / "renders",
        bundle_dir=tmp_path / "bundle",
        fixed_clock="2026-07-13T08:00:00Z",
        locale="zh-Hant",
        commit=False,
    )

    assert calls == ["desired-shape", "desired-build", "desired-bundle"]


def base_spec(tmp_path: Path) -> dict:
    dataset = tmp_path / "world.json"
    dataset.write_text(json.dumps({"datasetID": "world-1"}), encoding="utf-8")
    return {
        "schema": "kg.app_review.gate.v1",
        "target": {
            "appID": "app-1",
            "versionID": "version-1",
            "bundleID": "com.example.app",
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
            "sourceCommit": "a" * 40,
            "datasetID": "world-1",
            "datasetSHA256": sha(dataset.read_bytes()),
            "demoAccountIdentitySHA256": "d" * 64,
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
            "accountIdentitySHA256": "d" * 64,
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


def test_public_cli_does_not_accept_caller_supplied_demo_receipts():
    subparsers = next(
        action for action in evidence.parser()._actions
        if isinstance(action, evidence.argparse._SubParsersAction)
    )

    assert "demo" not in subparsers.choices


def test_demo_identity_resolver_hash_closes_live_mirror_and_rejects_wrong_fingerprint(tmp_path: Path):
    spec = base_spec(tmp_path)
    bundle = tmp_path / "live"
    bundle.mkdir()
    audit = {
        "schema": "kg.app_review.asc_audit.v1",
        "live": {"appID": spec["target"].get("appID"), "version": {"id": spec["target"].get("versionID")}, "reviewDetail": {"fields": {
            "demoAccountName": {"present": True, "identitySHA256": "d" * 64, "ref": "asc://review#name"}
        }}},
    }
    audit_bytes = json.dumps(audit, sort_keys=True).encode()
    (bundle / "audit.json").write_bytes(audit_bytes)
    (bundle / "manifest.json").write_text(json.dumps({
        "schema": "kg.app_review.asc_mirror_bundle.v1",
        "files": [{"path": "audit.json", "byteSize": len(audit_bytes), "sha256": sha(audit_bytes)}],
    }), encoding="utf-8")

    identity = evidence.resolve_demo_identity(spec, bundle)
    assert identity == {"accountRef": "asc://review#name", "identitySHA256": "d" * 64}
    spec["target"]["demoAccountIdentitySHA256"] = "e" * 64
    with pytest.raises(evidence.EvidenceError, match="demo.identity.spec-live"):
        evidence.resolve_demo_identity(spec, bundle)


@pytest.mark.parametrize("identity", [None, "not-a-sha", "A" * 64])
def test_demo_producer_rejects_missing_or_malformed_identity(tmp_path: Path, identity: str | None):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["options"]["liveDemoAccountIdentitySHA256"] = identity
    run["demoEvidence"] = {
        **run["options"],
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "exact-device",
        "networkMode": "live",
        "fixtureDataUsed": False,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": identity,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.account.identitySHA256"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_producer_rejects_spoofed_receipt_identity(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["options"]["liveDemoAccountIdentitySHA256"] = "e" * 64
    run["demoEvidence"] = {
        **run["options"],
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "exact-device",
        "networkMode": "live",
        "fixtureDataUsed": False,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": "d" * 64,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.account.identity-receipt"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_run_command_contains_only_fingerprint_not_raw_identity(tmp_path: Path):
    command = evidence.build_demo_run_command(
        workspace_root=tmp_path,
        destination="platform=iOS,id=device-1",
        account_identity_sha256="d" * 64,
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
    )

    rendered = " ".join(command)
    assert "--live-demo-account-identity-sha256 " + "d" * 64 in rendered
    assert "demo@example.com" not in rendered


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

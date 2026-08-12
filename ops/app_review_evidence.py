#!/usr/bin/env -S uv run --python 3.13
"""Typed, fail-closed producers and plan for App Review evidence.

Network scope is HTTPS GET only. The tool never writes App Store Connect and
writes local evidence only when ``--commit`` is explicit. Final ASC images and
their desired bundle are release-owner inputs; this tool does not generate them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.exit_codes import EXIT_BLOCK, EXIT_TOOL_ERROR, EXIT_USAGE
from lib.canonical_json import canonical_json_bytes
from lib.streaming_command import run_streamed_command

URL_SCHEMA = "kg.app_review.url_checks.v1"
JOURNEY_SCHEMA = "kg.app_review.journey.v1"
PLAN_SCHEMA = "kg.app_review.evidence_plan.v1"
PROJECT_FILE_REL = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PRODUCER_TYPES = {
    "desired-bundle",
    "asc-live-mirror",
    "ios-ui-journey",
    "demo-access",
    "url-checks",
    "agent-attestation",
    "human-attestation",
}


class EvidenceError(RuntimeError):
    pass


class ContractArgumentParser(argparse.ArgumentParser):
    """Map argparse's generic usage status (2) to KG's usage status (64)."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _evidence_error_exit_code(error: EvidenceError) -> int:
    """Separate invalid evidence (block) from producer/tool failures."""
    message = str(error)
    if message.startswith("--"):
        return EXIT_USAGE
    if message.startswith((
        "invalid JSON",
        "expected JSON object",
        "journey.runner.",
        "demo.runner.",
        "gate.execution:",
        "gate.report.invalid",
    )):
        return EXIT_TOOL_ERROR
    return EXIT_BLOCK


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_producer_command(
    command: list[str],
    *,
    cwd: Path | str,
    producer_name: str,
    heartbeat_interval: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    return run_streamed_command(
        command,
        cwd=cwd,
        label_key="producer",
        label=producer_name,
        progress_prefix="[app-review][evidence]",
        heartbeat_interval=heartbeat_interval,
        merge_stderr=False,
    )


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_get(url: str) -> tuple[int, str, bytes]:
    if not url.startswith("https://"):
        raise EvidenceError("URL must use HTTPS")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "KG-AppReview-Evidence/1"})
    with opener.open(request, timeout=20) as response:
        return int(response.status), response.geturl(), response.read()


def produce_url_checks(
    spec: dict[str, Any],
    *,
    observed_at: str,
    fetch: Callable[[str], tuple[int, str, bytes]] = https_get,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for required in spec.get("requiredLiveURLs") or []:
        url = required.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise EvidenceError(f"url.{required.get('id')}.https")
        status: int | None = None
        final_url: str | None = None
        body = b""
        verdict = "error"
        try:
            status, final_url, body = fetch(url)
            if 200 <= status < 300 and final_url == url:
                verdict = "pass"
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            final_url = exc.headers.get("Location") or exc.geturl()
            body = exc.read()
        except Exception:  # provider/network details are intentionally not persisted
            pass
        results.append(
            {
                "id": required.get("id"),
                "url": url,
                "status": verdict,
                "httpStatus": status,
                "finalUrl": final_url,
                "contentSHA256": _sha(body) if status is not None else None,
            }
        )
    return {"schema": URL_SCHEMA, "observedAt": observed_at, "results": results}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


def _workspace_artifact(path_value: object, workspace_root: Path, code: str) -> tuple[str, Path]:
    path = Path(str(path_value or ""))
    resolved = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
    root = workspace_root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise EvidenceError(f"{code}.outside-workspace") from exc
    _require(resolved.is_file(), f"{code}.missing")
    return relative, resolved


def produce_journey(
    spec: dict[str, Any],
    journey_id: str,
    run: dict[str, Any],
    *,
    workspace_root: Path = Path("."),
) -> dict[str, Any]:
    target = spec.get("target") or {}
    release = run.get("options")
    _require(run.get("schema") == "kg.ios.run.v1", "journey.run.schema")
    _require(run.get("status") in {"ok", "pass"} and run.get("result") in {"ok", "pass"}, "journey.status")
    try:
        executed = int(run.get("executed"))
    except (TypeError, ValueError):
        executed = 0
    _require(executed > 0, "journey.tests")
    _require(isinstance(release, dict), "journey.options")
    _require(release.get("evidenceProducer") == "ops/ios_test.sh", "journey.producer")
    _require(release.get("configuration") == "Release", "journey.configuration")
    _require(release.get("evidenceKind") in {"exact-device", "release-equivalent-simulator"}, "journey.evidenceKind")
    _require(release.get("fixtureDataUsed") is True, "journey.fixtureDataUsed")
    _require(release.get("networkMode") == "fixture", "journey.networkMode")
    for field in ("device", "os", "locale", "timezone", "appearance", "fixedClock", "startedAt", "finishedAt"):
        _require(isinstance(release.get(field), str) and bool(release[field]), f"journey.{field}")
    for field, target_key in (
        ("bundleID", "bundleID"),
        ("marketingVersion", "marketingVersion"),
        ("buildNumber", "buildNumber"),
        ("sourceCommit", "sourceCommit"),
        ("datasetID", "datasetID"),
        ("datasetSHA256", "datasetSHA256"),
    ):
        _require(release.get(field) == target.get(target_key), f"journey.{field}")
    # The verdict reads `sourceCommit` from git but the build tuple from the
    # checkout; when they disagree the run belongs to no commit, so it cannot be
    # handed to this spec's clean one.  `is False` rather than falsy: a verdict
    # produced before ios_test.sh recorded the field must not be read as clean.
    _require(release.get("sourceTreeDirty") is False, "journey.sourceTreeDirty")
    _require(bool(_COMMIT_RE.fullmatch(str(release.get("sourceCommit") or ""))), "journey.sourceCommit")
    _require(bool(_SHA_RE.fullmatch(str(release.get("datasetSHA256") or ""))), "journey.datasetSHA256")

    artifacts: list[dict[str, str]] = []
    file_artifact_keys = {"log", "uiContactSheet", "uiQuick4Sheet", "uiVisualReviewManifest", "uiVideo", "uiReviewHtml"}
    for kind, value in (run.get("artifacts") or {}).items():
        if kind not in file_artifact_keys:
            continue
        if not isinstance(value, str) or not value:
            continue
        relative, path = _workspace_artifact(value, workspace_root, "journey.artifact")
        artifacts.append({"path": relative, "sha256": _sha(path.read_bytes()), "kind": kind})
    _require(bool(artifacts), "journey.artifacts")
    claim_ids = sorted(
        claim["id"]
        for claim in spec.get("claims") or []
        if journey_id in (claim.get("journeyIDs") or [])
    )
    return {
        "schema": JOURNEY_SCHEMA,
        "id": journey_id,
        "claimIDs": claim_ids,
        "target": {
            "bundleId": release["bundleID"],
            "marketingVersion": release["marketingVersion"],
            "buildNumber": release["buildNumber"],
            "sourceCommit": release["sourceCommit"],
        },
        "execution": {
            "evidenceKind": release["evidenceKind"],
            "configuration": release["configuration"],
            "device": release["device"],
            "os": release["os"],
            "locale": release["locale"],
            "timezone": release["timezone"],
            "appearance": release["appearance"],
            "networkMode": release["networkMode"],
        },
        "world": {
            "datasetID": release["datasetID"],
            "sha256": release["datasetSHA256"],
            "fixedClock": release["fixedClock"],
        },
        "result": {
            "status": "pass",
            "testsExecuted": executed,
            "startedAt": release["startedAt"],
            "finishedAt": release["finishedAt"],
        },
        "artifacts": artifacts,
    }


def produce_demo_access(spec: dict[str, Any], run: dict[str, Any], *, workspace_root: Path = Path(".")) -> dict[str, Any]:
    target = spec.get("target") or {}
    demo = run.get("demoEvidence")
    _require(run.get("schema") == "kg.ios.run.v1", "demo.run.schema")
    _require(run.get("status") in {"ok", "pass"} and run.get("result") in {"ok", "pass"}, "demo.status")
    try:
        executed = int(run.get("executed"))
    except (TypeError, ValueError):
        executed = 0
    _require(executed > 0, "demo.tests")
    _require(isinstance(demo, dict), "demo.evidence")
    _require(demo.get("evidenceProducer") == "ops/ios_test.sh:live-demo", "demo.producer")
    _require(demo.get("configuration") == "Release", "demo.configuration")
    _require(demo.get("networkMode") == "live", "demo.networkMode")
    _require(demo.get("fixtureDataUsed") is False, "demo.fixtureDataUsed")
    _require(demo.get("evidenceKind") in {"exact-device", "live-demo"}, "demo.evidenceKind")
    _require(demo.get("sourceTreeDirty") is False, "demo.sourceTreeDirty")
    for field, target_key in (("bundleID", "bundleID"), ("marketingVersion", "marketingVersion"), ("buildNumber", "buildNumber"), ("sourceCommit", "sourceCommit")):
        _require(demo.get(field) == target.get(target_key), f"demo.{field}")
    artifacts: list[dict[str, str]] = []
    file_artifact_keys = {"log", "uiContactSheet", "uiQuick4Sheet", "uiVisualReviewManifest", "uiVideo", "uiReviewHtml"}
    for kind, value in (run.get("artifacts") or {}).items():
        if kind not in file_artifact_keys or not isinstance(value, str) or not value:
            continue
        relative, path = _workspace_artifact(value, workspace_root, "demo.artifact")
        artifacts.append({"path": relative, "sha256": _sha(path.read_bytes()), "kind": kind})
    _require(bool(artifacts), "demo.artifacts")
    account = demo.get("account") or {}
    _require(account.get("provenance") == "live-account", "demo.account.provenance")
    _require(account.get("entitlementSource") == "live-backend", "demo.account.entitlement")
    _require(demo.get("login") == "pass" and "pro" in (demo.get("entitlements") or []), "demo.result")
    identity_sha = str(account.get("accountIdentitySHA256") or "")
    _require(bool(_SHA_RE.fullmatch(identity_sha)), "demo.account.identitySHA256")
    _require(identity_sha == target.get("demoAccountIdentitySHA256"), "demo.account.identity-target")
    _require(identity_sha == (run.get("options") or {}).get("liveDemoAccountIdentitySHA256"), "demo.account.identity-receipt")
    return {
        "schema": "kg.app_review.demo_access.v1",
        "evidenceKind": demo["evidenceKind"],
        "target": {"bundleId": demo["bundleID"], "marketingVersion": demo["marketingVersion"], "buildNumber": demo["buildNumber"], "sourceCommit": demo["sourceCommit"]},
        "execution": {key: demo[key] for key in ("configuration", "device", "os", "locale", "timezone", "networkMode", "fixtureDataUsed")},
        "account": {key: account[key] for key in ("provenance", "accountRef", "accountIdentitySHA256", "entitlementSource")},
        "observedAt": demo["observedAt"],
        "result": {"status": "pass", "login": "pass", "entitlements": demo["entitlements"], "testsExecuted": executed},
        "artifacts": artifacts,
    }


def execute_journey_run(
    *,
    workspace_root: Path,
    dataset_file: Path,
    fixed_clock: str,
    locale: str,
    timezone_name: str,
    appearance: str,
    tests: list[str],
    evidence_kind: str = "release-equivalent-simulator",
    destination: str | None = None,
) -> dict[str, Any]:
    """Run the owning iOS producer; callers cannot inject provenance fields."""
    command = [
        str(workspace_root / "ops" / "ios_ops.sh"),
        "test", "--ui", "--configuration", "Release", "--dataset-file", str(dataset_file),
        "--fixed-clock", fixed_clock, "--evidence-locale", locale,
        "--evidence-timezone", timezone_name, "--evidence-appearance", appearance,
        "--evidence-kind", evidence_kind,
    ]
    if destination:
        command.extend(["--destination", destination])
    else:
        command.append("--lease")
    command.extend(["--json", *tests])
    completed = _run_producer_command(
        command, cwd=workspace_root, producer_name="journey-run",
    )
    if completed.returncode != 0:
        raise EvidenceError(f"journey.runner.exit:{completed.returncode}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("journey.runner.invalid-json") from exc
    _require(isinstance(result, dict), "journey.runner.invalid-json")
    return result


def resolve_demo_identity(spec: dict[str, Any], live_mirror_bundle: Path) -> dict[str, str]:
    manifest = _load(live_mirror_bundle / "manifest.json")
    _require(manifest.get("schema") == "kg.app_review.asc_mirror_bundle.v1", "demo.live-mirror.schema")
    audit_entry = next((item for item in manifest.get("files") or [] if item.get("path") == "audit.json"), None)
    _require(isinstance(audit_entry, dict), "demo.live-mirror.audit-entry")
    audit_path = live_mirror_bundle / "audit.json"
    _require(audit_path.is_file(), "demo.live-mirror.audit-missing")
    audit_bytes = audit_path.read_bytes()
    _require(audit_entry.get("byteSize") == len(audit_bytes) and audit_entry.get("sha256") == _sha(audit_bytes), "demo.live-mirror.audit-hash")
    try:
        audit = json.loads(audit_bytes)
    except json.JSONDecodeError as exc:
        raise EvidenceError("demo.live-mirror.audit-json") from exc
    _require(isinstance(audit, dict) and audit.get("schema") == "kg.app_review.asc_audit.v1", "demo.live-mirror.audit-schema")
    target = spec.get("target") or {}
    live = audit.get("live") or {}
    _require(live.get("appID") == target.get("appID"), "demo.live-mirror.app")
    _require((live.get("version") or {}).get("id") == target.get("versionID"), "demo.live-mirror.version")
    account = (((live.get("reviewDetail") or {}).get("fields") or {}).get("demoAccountName") or {})
    identity_sha = str(account.get("identitySHA256") or "")
    _require(bool(_SHA_RE.fullmatch(identity_sha)), "demo.identity.live")
    _require(identity_sha == target.get("demoAccountIdentitySHA256"), "demo.identity.spec-live")
    account_ref = account.get("ref")
    _require(isinstance(account_ref, str) and bool(account_ref), "demo.identity.ref")
    return {"accountRef": account_ref, "identitySHA256": identity_sha}


def build_demo_run_command(
    *, workspace_root: Path, destination: str, account_identity_sha256: str,
    locale: str, timezone_name: str,
) -> list[str]:
    _require(bool(_SHA_RE.fullmatch(account_identity_sha256)), "demo.identity.sha256")
    return [
        str(workspace_root / "ops" / "ios_ops.sh"), "test", "--ui",
        "--configuration", "Release", "--evidence-kind", "exact-device",
        "--destination", destination, "--live-demo",
        "--live-demo-account-identity-sha256", account_identity_sha256,
        "--evidence-locale", locale, "--evidence-timezone", timezone_name,
        "--json", "testLiveDemoAccountHasProEntitlement",
    ]


def execute_demo_run(
    *, workspace_root: Path, destination: str, account_identity_sha256: str,
    locale: str, timezone_name: str,
) -> dict[str, Any]:
    command = build_demo_run_command(
        workspace_root=workspace_root, destination=destination,
        account_identity_sha256=account_identity_sha256,
        locale=locale, timezone_name=timezone_name,
    )
    completed = _run_producer_command(
        command, cwd=workspace_root, producer_name="demo-run",
    )
    if completed.returncode != 0:
        raise EvidenceError(f"demo.runner.exit:{completed.returncode}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("demo.runner.invalid-json") from exc
    _require(isinstance(result, dict), "demo.runner.invalid-json")
    return result


def produce_attestation(spec: dict[str, Any], *, actor: str, subject: str, root_sha256: str, observed_at: str, expires_at: str) -> dict[str, Any]:
    _require(actor in {"human", "agent"}, "attestation.actor")
    _require(bool(_SHA_RE.fullmatch(root_sha256)), "attestation.root")
    return {
        "schema": "kg.app_review.attestation.v1",
        "actorType": actor,
        "subject": subject,
        "attestationKind": "semantic",
        "claimIDs": [claim["id"] for claim in spec.get("claims") or []],
        "status": "attested",
        "preAttestationRootSHA256": root_sha256,
        "observedAt": observed_at,
        "expiresAt": expires_at,
    }


def required_evidence(spec: dict[str, Any]) -> list[tuple[str, str]]:
    artifacts = spec.get("artifacts") or {}
    required: list[tuple[str, str]] = []
    for key in ("desiredBundle", "liveMirrorBundle", "demoAccess", "urlChecks"):
        if key in artifacts:
            value = artifacts[key]
            required.append((key, value if isinstance(value, str) else value.get("path")))
    for item in artifacts.get("journeys") or []:
        required.append((f"journey.{item.get('id')}", item.get("path")))
    for actor, path in (artifacts.get("attestations") or {}).items():
        required.append((f"attestation.{actor}", path))
    return required


def build_plan(spec: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    producers = spec.get("producers") or {}
    evidence: list[dict[str, Any]] = []
    for evidence_id, rel in required_evidence(spec):
        producer = producers.get(evidence_id)
        exists = isinstance(rel, str) and (workspace_root / rel).exists()
        if not isinstance(producer, dict):
            evidence.append({"id": evidence_id, "path": rel, "status": "block", "reason": "producer-missing", "producerType": None, "authority": None, "command": None})
            continue
        keys_ok = set(producer) == {"type", "authority", "command"}
        producer_type = producer.get("type")
        valid = keys_ok and producer_type in _PRODUCER_TYPES and all(isinstance(producer.get(key), str) and producer[key] for key in ("authority", "command"))
        evidence.append(
            {
                "id": evidence_id,
                "path": rel,
                "status": "ready" if valid and exists else "block",
                "reason": None if valid and exists else ("artifact-missing" if valid else "producer-invalid"),
                "producerType": producer_type,
                "authority": producer.get("authority"),
                "command": producer.get("command"),
            }
        )
    return {
        "schema": PLAN_SCHEMA,
        "status": "pass" if evidence and all(item["status"] == "ready" for item in evidence) else "block",
        "evidence": evidence,
    }


def apply_gate_blocks(plan: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    codes = [item.get("code") for item in gate.get("blocks") or [] if isinstance(item, dict)]
    prefixes = {
        "desiredBundle": ("desired.",),
        "liveMirrorBundle": ("live-mirror.",),
        "demoAccess": ("demo.",),
        "urlChecks": ("urls.", "url."),
        "attestation.human": ("attestation.human",),
        "attestation.agent": ("attestation.agent",),
    }
    for item in plan["evidence"]:
        item_prefixes = prefixes.get(item["id"], (f"{item['id']}.",))
        matching = next((code for code in codes if isinstance(code, str) and code.startswith(item_prefixes)), None)
        if matching:
            item["status"] = "block"
            item["reason"] = f"gate:{matching}"
    plan["gate"] = {
        "status": (gate.get("verdict") or {}).get("status", "block"),
        "blockCount": len(codes),
    }
    plan["status"] = "pass" if plan["evidence"] and all(item["status"] == "ready" for item in plan["evidence"]) and plan["gate"]["status"] == "pass" else "block"
    return plan


def evaluate_gate(spec_path: Path, workspace_root: Path) -> dict[str, Any]:
    command = [sys.executable, str(Path(__file__).with_name("app_review_gate.py")), "dry-run", "--spec", str(spec_path), "--workspace-root", str(workspace_root), "--observation-mode", "online"]
    completed = _run_producer_command(
        command, cwd=workspace_root, producer_name="gate-evaluation",
    )
    if completed.returncode not in {0, 2}:
        raise EvidenceError(f"gate.execution:{completed.returncode}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("gate.report.invalid") from exc
    _require(isinstance(report, dict) and isinstance(report.get("verdict"), dict) and isinstance(report.get("blocks"), list), "gate.report.invalid")
    return report


def _write_or_print(document: dict[str, Any], out: Path | None, commit: bool) -> None:
    encoded = canonical_json_bytes(document).decode("utf-8")
    if commit:
        if out is None:
            raise EvidenceError("--commit requires --out")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


def parser() -> argparse.ArgumentParser:
    top = ContractArgumentParser(description=__doc__)
    sub = top.add_subparsers(dest="command", required=True, parser_class=ContractArgumentParser)
    for name in ("plan", "status"):
        command = sub.add_parser(name)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--workspace-root", type=Path, default=Path("."))
    urls = sub.add_parser("urls")
    urls.add_argument("--spec", type=Path, required=True)
    urls.add_argument("--observed-at")
    urls.add_argument("--out", type=Path)
    urls.add_argument("--commit", action="store_true")
    journey = sub.add_parser("journey")
    journey.add_argument("--spec", type=Path, required=True)
    journey.add_argument("--journey-id", required=True)
    journey.add_argument("--run-json", type=Path, required=True)
    journey.add_argument("--workspace-root", type=Path, default=Path("."))
    journey.add_argument("--out", type=Path)
    journey.add_argument("--commit", action="store_true")
    journey_run = sub.add_parser("journey-run")
    journey_run.add_argument("--spec", type=Path, required=True)
    journey_run.add_argument("--journey-id", required=True)
    journey_run.add_argument("--dataset-file", type=Path, required=True)
    journey_run.add_argument("--fixed-clock", required=True)
    journey_run.add_argument("--locale", required=True)
    journey_run.add_argument("--timezone", required=True)
    journey_run.add_argument("--appearance", choices=("light", "dark"), required=True)
    journey_run.add_argument("--evidence-kind", choices=("release-equivalent-simulator", "exact-device"), default="release-equivalent-simulator")
    journey_run.add_argument("--destination")
    journey_run.add_argument("--test", action="append", required=True)
    journey_run.add_argument("--workspace-root", type=Path, default=Path("."))
    journey_run.add_argument("--out", type=Path)
    journey_run.add_argument("--commit", action="store_true")
    demo_run = sub.add_parser("demo-run")
    demo_run.add_argument("--spec", type=Path, required=True)
    demo_run.add_argument("--destination", required=True)
    demo_run.add_argument("--live-mirror-bundle", type=Path, required=True)
    demo_run.add_argument("--locale", required=True)
    demo_run.add_argument("--timezone", required=True)
    demo_run.add_argument("--workspace-root", type=Path, default=Path("."))
    demo_run.add_argument("--out", type=Path)
    demo_run.add_argument("--commit", action="store_true")
    attest = sub.add_parser("attest")
    attest.add_argument("--spec", type=Path, required=True)
    attest.add_argument("--actor", choices=("human", "agent"), required=True)
    attest.add_argument("--subject", required=True)
    attest.add_argument("--pre-root-sha256", required=True)
    attest.add_argument("--observed-at", required=True)
    attest.add_argument("--expires-at", required=True)
    attest.add_argument("--out", type=Path)
    attest.add_argument("--commit", action="store_true")
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        spec = _load(args.spec)
        if args.command in {"plan", "status"}:
            document = build_plan(spec, args.workspace_root)
            if args.command == "status":
                document = apply_gate_blocks(document, evaluate_gate(args.spec, args.workspace_root))
        elif args.command == "urls":
            observed = args.observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            document = produce_url_checks(spec, observed_at=observed)
            _write_or_print(document, args.out, args.commit)
            return 0 if all(item["status"] == "pass" for item in document["results"]) else 2
        elif args.command == "journey":
            document = produce_journey(spec, args.journey_id, _load(args.run_json), workspace_root=args.workspace_root)
            _write_or_print(document, args.out, args.commit)
            return 0
        elif args.command == "journey-run":
            run = execute_journey_run(
                workspace_root=args.workspace_root.resolve(),
                dataset_file=args.dataset_file.resolve(),
                fixed_clock=args.fixed_clock,
                locale=args.locale,
                timezone_name=args.timezone,
                appearance=args.appearance,
                tests=args.test,
                evidence_kind=args.evidence_kind,
                destination=args.destination,
            )
            document = produce_journey(spec, args.journey_id, run, workspace_root=args.workspace_root)
            _write_or_print(document, args.out, args.commit)
            return 0
        elif args.command == "demo-run":
            identity = resolve_demo_identity(spec, args.live_mirror_bundle)
            run = execute_demo_run(
                workspace_root=args.workspace_root.resolve(), destination=args.destination,
                account_identity_sha256=identity["identitySHA256"],
                locale=args.locale, timezone_name=args.timezone,
            )
            demo_account = ((run.get("demoEvidence") or {}).get("account") or {})
            demo_account["accountRef"] = identity["accountRef"]
            document = produce_demo_access(spec, run, workspace_root=args.workspace_root)
            _write_or_print(document, args.out, args.commit)
            return 0
        else:
            document = produce_attestation(
                spec,
                actor=args.actor,
                subject=args.subject,
                root_sha256=args.pre_root_sha256,
                observed_at=args.observed_at,
                expires_at=args.expires_at,
            )
            _write_or_print(document, args.out, args.commit)
            return 0
        print(json.dumps(document, ensure_ascii=False, sort_keys=True))
        return 0 if document["status"] == "pass" else 2
    except EvidenceError as exc:
        print(json.dumps({"schema": PLAN_SCHEMA, "status": "block", "error": str(exc)}, sort_keys=True))
        return _evidence_error_exit_code(exc)


if __name__ == "__main__":
    raise SystemExit(main())

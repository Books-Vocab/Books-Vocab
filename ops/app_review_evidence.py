#!/usr/bin/env -S uv run --python 3.13
"""Typed, fail-closed producers and plan for App Review evidence.

Network scope is HTTPS GET only.  The tool never writes App Store Connect, and
writes locally only when ``--commit`` is explicit.  Note that ``refresh-anchor``
is the one subcommand whose ``--commit`` writes the *spec* rather than evidence:
the spec is the baseline evidence is compared against, so that write moves the
thing that judges, not the thing being judged.  That write therefore evaluates
the gate first and refuses while it is red; ``--acknowledge-gate-block`` is the
named, reported override, not a quieter default.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.streaming_command import run_streamed_command  # noqa: E402
from reviewer_evidence import (  # noqa: E402
    EvidenceError as ReviewerEvidenceError,
    materialize_tracked_file,
)


URL_SCHEMA = "kg.app_review.url_checks.v1"
JOURNEY_SCHEMA = "kg.app_review.journey.v1"
PLAN_SCHEMA = "kg.app_review.evidence_plan.v1"
ANCHOR_SCHEMA = "kg.app_review.anchor_refresh.v1"
PROJECT_FILE_REL = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
_ANCHOR_FIELD = "desiredManifestSHA256"
_ANCHOR_RE = re.compile(r'("desiredManifestSHA256"\s*:\s*)"([0-9a-f]{64})"')
# A cold spec blocks on ~48 codes at once.  Splicing all of them into one refusal
# is the same as printing none: the operator scrolls past it to the override.
_GATE_BLOCK_PREVIEW = 6
# The only block a spec write can clear (ops/app_review_gate.py:988).
_ANCHOR_BLOCK_CODE = "desired.manifest-sha256"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PRODUCER_TYPES = {
    "desired-bundle",
    "asc-live-mirror",
    "ios-ui-journey",
    "demo-access",
    "url-checks",
    "catalog-appearance",
    "agent-attestation",
    "human-attestation",
}


class EvidenceError(RuntimeError):
    pass


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


def _materialize_tracked_file(
    *, workspace_root: Path, commit: str, rel_path: str, destination: Path,
) -> Path:
    """Producer-scoped view of `reviewer_evidence.materialize_tracked_file`.

    The primitive is shared so that the two tools minting the "these bytes are
    commit X" claim cannot disagree on it; only the blame prefix is local, because
    the gate reads these strings as block codes and ``desired`` names the producer
    whose bundle is unusable when this fails.
    """
    try:
        return materialize_tracked_file(
            workspace_root=workspace_root,
            commit=commit,
            rel_path=rel_path,
            destination=destination,
        )
    except ReviewerEvidenceError as exc:
        raise EvidenceError(f"desired.{exc}") from exc


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
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


def _publish_directory_atomically(staged: Path, destination: Path) -> None:
    """Publish a complete directory with no missing/partial reader window."""
    if not destination.exists():
        os.replace(staged, destination)
        return
    if sys.platform != "darwin":
        raise EvidenceError("desired.atomic-replace.unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    renameatx_np = libc.renameatx_np
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    at_fdcwd = -2
    rename_swap = 0x00000002
    result = renameatx_np(
        at_fdcwd, os.fsencode(staged), at_fdcwd, os.fsencode(destination), rename_swap
    )
    if result != 0:
        errno_value = ctypes.get_errno()
        raise EvidenceError(f"desired.atomic-replace.errno:{errno_value}")


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


def produce_appearance(spec: dict[str, Any], catalog_root: Path) -> dict[str, Any]:
    proof = _load(catalog_root / "catalog_appearance.json")
    receipt = _load(catalog_root / "catalog_run_receipt.json")
    target = spec.get("target") or {}
    _require(proof.get("schema") == "kg.catalog.appearance.v1", "appearance.schema")
    _require((proof.get("verdict") or {}).get("status") == "pass", "appearance.status")
    _require(receipt.get("schema") == "kg.ios.catalog.run_receipt.v1" and receipt.get("status") == "pass", "appearance.receipt")
    for field, target_key in (("sourceCommit", "sourceCommit"), ("datasetID", "datasetID"), ("datasetSHA256", "datasetSHA256")):
        _require(proof.get(field) == target.get(target_key), f"appearance.{field}")
        _require(receipt.get(field) == target.get(target_key), f"appearance.receipt.{field}")
    _require(proof.get("fixedClock") == receipt.get("fixedClock"), "appearance.fixedClock")
    return proof


def produce_desired_bundle(
    spec: dict[str, Any], *, workspace_root: Path, profile_file: Path,
    render_output_dir: Path, bundle_dir: Path, fixed_clock: str, locale: str,
    commit: bool,
) -> dict[str, Any]:
    """Rebuild desired evidence from tracked profile/render outputs and generators."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import capture_profile as capture  # noqa: PLC0415

    target = spec.get("target") or {}
    profile = capture.load_profile(profile_file)
    render_spec = capture.reviewer_render_spec(profile)
    with tempfile.TemporaryDirectory(prefix="kg-app-review-desired-") as raw_tmp:
        temp = Path(raw_tmp)
        # Resolve the pinned source first: an unusable sourceCommit must stop the
        # run before any generator burns time producing evidence nothing can sign.
        project_file = _materialize_tracked_file(
            workspace_root=workspace_root,
            commit=str(target.get("sourceCommit") or ""),
            rel_path=PROJECT_FILE_REL,
            destination=temp / "source" / Path(PROJECT_FILE_REL).name,
        )
        world_spec = temp / "ui_world.spec.json"
        dataset = temp / "ui_world.json"
        generated_outputs = temp / "outputs"
        generated_outputs.mkdir()
        shape = workspace_root / "ops/demo/marketing_account/shape_history.py"
        build_demo = workspace_root / "ops/demo/build_demo.py"
        source_spec = workspace_root / "ops/demo/marketing_account/marketing_account_spec.json"
        history_plan = workspace_root / "ops/demo/marketing_account/history_plan.json"
        commands = [
            [sys.executable, str(shape), str(source_spec), str(history_plan), "--out", str(world_spec)],
            [sys.executable, str(build_demo), "emit-ios", "--spec", str(world_spec), "--out", str(dataset), "--plan", str(history_plan), "--commit", "--json"],
        ]
        for producer_name, command in zip(("desired-shape", "desired-build"), commands, strict=True):
            completed = _run_producer_command(
                command, cwd=workspace_root, producer_name=producer_name,
            )
            if completed.returncode != 0:
                raise EvidenceError(f"desired.generator.exit:{completed.returncode}")
        _require(_sha(dataset.read_bytes()) == target.get("datasetSHA256"), "desired.datasetSHA256")

        shots: list[dict[str, Any]] = []
        for shot in render_spec["shots"]:
            source = render_output_dir / shot["outputName"]
            _require(source.is_file(), f"desired.output.{shot['id']}")
            staged = generated_outputs / source.name
            shutil.copyfile(source, staged)
            data = staged.read_bytes()
            shots.append({
                "id": shot["id"], "outputName": source.name,
                "appearance": shot.get("appearance"), "status": "verified",
                "byteSize": len(data), "sha256": _sha(data),
            })
        render_digest = _sha(json.dumps(render_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        promotion = {
            "schema": "kg.app_review.promotion_manifest.v1",
            "profileID": profile.profile_id,
            "profileSHA256": _sha(profile_file.read_bytes()),
            "datasetSHA256": _sha(dataset.read_bytes()),
            "renderSpecSHA256": render_digest,
            "shots": shots,
        }
        promotion_path = temp / "promotion_manifest.json"
        promotion_path.write_text(json.dumps(promotion, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        destination = bundle_dir.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage_root = Path(tempfile.mkdtemp(prefix=".kg-app-review-stage-", dir=destination.parent)) if commit else temp
        staged_bundle = stage_root / "bundle"
        command = [
            sys.executable, str(workspace_root / "ops/capture_profile.py"), "reviewer-evidence", str(profile_file),
            "--dataset-file", str(dataset), "--render-output-dir", str(generated_outputs),
            "--promotion-manifest", str(promotion_path), "--bundle-dir", str(staged_bundle),
            "--project-file", str(project_file),
            "--source-commit", str(target.get("sourceCommit")), "--fixed-clock", fixed_clock,
            "--locale", locale, "--expect-marketing-version", str(target.get("marketingVersion")),
            "--expect-build-number", str(target.get("buildNumber")),
        ]
        if commit:
            command.append("--commit")
        completed = _run_producer_command(
            command, cwd=workspace_root, producer_name="desired-bundle",
        )
        if completed.returncode != 0:
            if commit:
                shutil.rmtree(stage_root, ignore_errors=True)
            raise EvidenceError(f"desired.bundle.exit:{completed.returncode}")
        document = json.loads(completed.stdout)
        if commit:
            try:
                _publish_directory_atomically(staged_bundle, destination)
            finally:
                # After RENAME_SWAP, stage_root/bundle is the previous complete
                # destination. Removing it cannot affect the newly published path.
                shutil.rmtree(stage_root, ignore_errors=True)
        return document


def rewrite_anchor(spec_text: str, new_anchor: str) -> tuple[str, str]:
    """Swap the one anchor literal in `spec_text`; return (updated text, old value).

    Textual on purpose.  Re-serializing the parsed document would let key order,
    indentation or number formatting ride along under a commit that claims to
    have moved one hash, so the substitution is verified twice instead: exactly
    one literal matched, and the reparsed document differs from the original in
    that field alone.
    """
    _require(bool(_SHA_RE.fullmatch(new_anchor)), f"anchor.value:{new_anchor!r}")
    matches = _ANCHOR_RE.findall(spec_text)
    _require(len(matches) == 1, f"anchor.occurrences:{len(matches)}")
    old_anchor = matches[0][1]
    updated = _ANCHOR_RE.sub(lambda match: f'{match.group(1)}"{new_anchor}"', spec_text, count=1)
    expected = json.loads(spec_text)
    _require(isinstance(expected.get("target"), dict), "anchor.target")
    expected["target"][_ANCHOR_FIELD] = new_anchor
    # This reparse is the guard that actually holds. The regex only narrows the
    # candidates; cases like an uppercase digest in target, or a same-named key
    # in a sibling object, reach here still wrong and die on this line.
    _require(json.loads(updated) == expected, "anchor.collateral-change")
    return updated, old_anchor


def _write_text_atomically(path: Path, text: str) -> None:
    """Replace `path` by rename, never by truncating it in place.

    The spec is the one git-tracked control-plane file this module writes, and
    it was the only write here lacking the atomicity the bundle publisher
    already has.  A crash mid-write left a truncated gate input behind.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        staged = Path(handle.name)
    os.replace(staged, path)


def _gate_block_codes(report: dict[str, Any]) -> list[str]:
    return [
        block["code"] for block in report.get("blocks") or []
        if isinstance(block, dict) and block.get("code")
    ]


def _refuse_if_gate_blocks(spec_path: Path, workspace_root: Path) -> None:
    """Refuse to move the anchor while the gate that reads it is red.

    Re-measuring an anchor and erasing a block are the same keystrokes, and only
    the gate's current colour tells them apart: green means the spec is being
    re-baselined from a state everyone agrees is good, red means the one thing
    that noticed the drift is about to be overwritten by the drift itself.

    Anything that is not an explicit pass refuses, including a gate that could
    not answer: a verdict word this code has never seen must not read as consent.

    The refusal quotes the gate's own block codes, anchor-related ones first.  A
    generic "gate is blocking" leaves the operator to go look up what they were
    about to erase, and an operator who has to go looking reaches for the
    override instead; a preview ordered by the gate's own emission order shows
    the relevant code only by luck.
    """
    report = evaluate_gate(spec_path, workspace_root)
    verdict = report.get("verdict") or {}
    if verdict.get("status") == "pass":
        return
    codes = _gate_block_codes(report)
    # Stable sort: the anchor's own block leads, everything else keeps gate order.
    ordered = sorted(codes, key=lambda code: not code.startswith("desired."))
    named = ",".join(ordered[:_GATE_BLOCK_PREVIEW]) or str(verdict.get("status") or "unknown")
    raise EvidenceError(
        f"anchor.gate-blocked:{named} ({len(codes)} blocks total — "
        f"`app_review_evidence.py status --spec {spec_path} "
        f"--workspace-root {workspace_root}` lists them all. "
        f"Writing the anchor would erase the {_ANCHOR_BLOCK_CODE} block among "
        "them and change nothing else; confirm the bundle change was intended, "
        "then re-run with --acknowledge-gate-block)"
    )


def _observe_gate_blocks(spec_path: Path, workspace_root: Path) -> list[str] | None:
    """Record what an acknowledged write is about to silence, without gating on it.

    The write destroys its own evidence: once the anchor moves, nothing on disk
    separates an override of one block from an override of forty-eight, so this
    report is the only place that record can still exist.

    It must not become a second gate, though.  The override exists for the case
    where the gate cannot be satisfied, and that includes the case where it
    cannot be run — hence ``None`` ("nobody looked") rather than a refusal.
    """
    try:
        return _gate_block_codes(evaluate_gate(spec_path, workspace_root))
    except Exception:  # noqa: BLE001 — observation is best-effort by construction
        return None


def refresh_desired_anchor(
    spec_path: Path, *, workspace_root: Path, profile_file: Path,
    render_output_dir: Path, fixed_clock: str, locale: str, commit: bool,
    acknowledge_gate_block: bool = False,
) -> dict[str, Any]:
    """Recompute target.desiredManifestSHA256 from a rebuilt bundle and write it back.

    This is the only sanctioned way to move that anchor.  Updating it by hand is
    how an anchor rots: it is the single thing that speaks when the evidence
    drifts, and hand-editing it is indistinguishable from silencing it.

    The value is measured from a bundle published into a temp directory — the
    same bytes the gate hashes — rather than derived from the returned manifest,
    so the number written back is one that was actually observed on disk.

    A committing refresh is gated on the gate: see ``_refuse_if_gate_blocks``.
    The check runs before the rebuild rather than beside the write, so the
    dangerous case is the cheap one to be told about — the cost of that ordering
    is that a refresh which would have been a no-op is refused too, since
    whether it moves anything is not knowable before the rebuild.
    """
    spec = _load(spec_path)
    spec_text = spec_path.read_text(encoding="utf-8")
    # Every precondition rewrite_anchor enforces is decidable from the text
    # alone, so decide them now: a spec this function could never rewrite should
    # not cost a full bundle rebuild to discover that.
    rewrite_anchor(spec_text, "0" * 64)
    gate_blocks: list[str] | None = None
    if not commit:
        # Nothing is being written, so there is no block to acknowledge; letting
        # the flag through would make any later tally of overrides count dry-runs.
        if acknowledge_gate_block:
            raise EvidenceError(
                "anchor.acknowledge-without-commit (--acknowledge-gate-block "
                "overrides a refusal that only --commit can trigger)"
            )
        gate_check = "not-required"
    elif acknowledge_gate_block:
        gate_check = "acknowledged"
        gate_blocks = _observe_gate_blocks(spec_path, workspace_root)
    else:
        _refuse_if_gate_blocks(spec_path, workspace_root)
        gate_check = "pass"
        gate_blocks = []
    with tempfile.TemporaryDirectory(prefix="kg-app-review-anchor-") as raw_tmp:
        bundle_dir = Path(raw_tmp) / "bundle"
        produce_desired_bundle(
            spec, workspace_root=workspace_root, profile_file=profile_file,
            render_output_dir=render_output_dir, bundle_dir=bundle_dir,
            fixed_clock=fixed_clock, locale=locale, commit=True,
        )
        measured = _sha((bundle_dir / "manifest.json").read_bytes())
    # The rebuild takes seconds, and the text captured before it is what gets
    # written back. Anyone who edited the spec meanwhile would have their edit
    # silently reverted, so refuse instead.
    if spec_path.read_text(encoding="utf-8") != spec_text:
        raise EvidenceError("anchor.spec-changed-during-rebuild")
    updated, old_anchor = rewrite_anchor(spec_text, measured)
    changed = old_anchor != measured
    if changed and commit:
        _write_text_atomically(spec_path, updated)
    return {
        "schema": ANCHOR_SCHEMA,
        "spec": str(spec_path),
        "field": f"target.{_ANCHOR_FIELD}",
        "old": old_anchor,
        "new": measured,
        "changed": changed,
        "commit": commit,
        "acknowledgedGateBlock": acknowledge_gate_block,
        "gateCheck": gate_check,
        "gateBlocks": gate_blocks,
        "status": "current" if not changed else ("written" if commit else "dry-run"),
    }


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
    for key in ("desiredBundle", "liveMirrorBundle", "demoAccess", "urlChecks", "appearanceProof"):
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
        "appearanceProof": ("appearance.",),
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
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if commit:
        if out is None:
            raise EvidenceError("--commit requires --out")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    sub = top.add_subparsers(dest="command", required=True)
    for name in ("plan", "status"):
        command = sub.add_parser(name)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--workspace-root", type=Path, default=Path("."))
    desired = sub.add_parser("desired")
    desired.add_argument("--spec", type=Path, required=True)
    desired.add_argument("--profile", type=Path, required=True)
    desired.add_argument("--render-output-dir", type=Path, required=True)
    desired.add_argument("--bundle-dir", type=Path, required=True)
    desired.add_argument("--fixed-clock", required=True)
    desired.add_argument("--locale", required=True)
    desired.add_argument("--workspace-root", type=Path, default=Path("."))
    desired.add_argument("--commit", action="store_true")
    refresh = sub.add_parser(
        "refresh-anchor",
        help=(
            "rebuild the desired bundle and write its manifest sha256 back to "
            "target.desiredManifestSHA256 (dry-run unless --commit); the only "
            "sanctioned way to move that anchor"
        ),
    )
    refresh.add_argument("--spec", type=Path, required=True)
    refresh.add_argument("--profile", type=Path, required=True)
    refresh.add_argument("--render-output-dir", type=Path, required=True)
    refresh.add_argument("--fixed-clock", required=True)
    refresh.add_argument("--locale", required=True)
    refresh.add_argument("--workspace-root", type=Path, default=Path("."))
    refresh.add_argument(
        "--commit", action="store_true",
        help="write the spec; without it the old->new comparison is printed and nothing is written",
    )
    refresh.add_argument(
        "--acknowledge-gate-block", action="store_true",
        help=(
            "write even though the App Review gate is blocking. --commit otherwise "
            "evaluates the gate first and refuses while it is red, because writing "
            "the anchor erases the very block that noticed the drift. This flag is a "
            "human assertion that the bundle change was intended: it strips the "
            "gate of its veto but still records the blocks it was overriding in the "
            "report's gateBlocks. Requires --commit"
        ),
    )
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
    appearance = sub.add_parser("appearance")
    appearance.add_argument("--spec", type=Path, required=True)
    appearance.add_argument("--catalog-root", type=Path, required=True)
    appearance.add_argument("--out", type=Path)
    appearance.add_argument("--commit", action="store_true")
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
        elif args.command == "desired":
            document = produce_desired_bundle(
                spec, workspace_root=args.workspace_root.resolve(), profile_file=args.profile.resolve(),
                render_output_dir=args.render_output_dir.resolve(), bundle_dir=args.bundle_dir,
                fixed_clock=args.fixed_clock, locale=args.locale, commit=args.commit,
            )
            print(json.dumps(document, ensure_ascii=False, sort_keys=True))
            return 0
        elif args.command == "refresh-anchor":
            document = refresh_desired_anchor(
                args.spec, workspace_root=args.workspace_root.resolve(),
                profile_file=args.profile.resolve(),
                render_output_dir=args.render_output_dir.resolve(),
                fixed_clock=args.fixed_clock, locale=args.locale, commit=args.commit,
                acknowledge_gate_block=args.acknowledge_gate_block,
            )
            print(json.dumps(document, ensure_ascii=False, sort_keys=True))
            return 0
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
        elif args.command == "appearance":
            document = produce_appearance(spec, args.catalog_root)
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
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

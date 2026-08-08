#!/usr/bin/env -S uv run --python 3.13
"""Closed-world App Review gate and reviewer-visible HTML bundle.

This tool is read-only with respect to App Store Connect. ``dry-run`` and
``verify --spec`` consume already captured, hash-closed evidence. Offline
evaluation is always BLOCK; callers may only select ``online`` when the live
mirror and URL checks were freshly produced from their real services.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))
from catalog_appearance_proof import APPEARANCE_SCHEMA, validate_appearance_proof


SPEC_SCHEMA = "kg.app_review.gate.v1"
JOURNEY_SCHEMA = "kg.app_review.journey.v1"
DEMO_SCHEMA = "kg.app_review.demo_access.v1"
URL_SCHEMA = "kg.app_review.url_checks.v1"
ATTESTATION_SCHEMA = "kg.app_review.attestation.v1"
REPORT_SCHEMA = "kg.app_review.gate_report.v1"
BUNDLE_SCHEMA = "kg.app_review.reviewer_bundle.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# The referent for `build.project` is the gate's own constant, never a path read
# out of the manifest under audit: evidence allowed to name its own comparison
# target can always name one it happens to match.  `build.project.path` is the
# bundle-internal staging path (`inputs/project.pbxproj`) and says nothing about
# where those bytes came from.
_PROJECT_SOURCE_PATH = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
_REGULAR_FILE_MODES = {"100644", "100755"}
_SURFACE_KINDS = {"metadata", "review-notes", "screenshot-copy", "website"}
_JOURNEY_EVIDENCE_KINDS = {"exact-device", "release-equivalent-simulator"}
_DEMO_EVIDENCE_KINDS = {"exact-device", "live-demo"}
_CLAIM_EVIDENCE_KINDS = _JOURNEY_EVIDENCE_KINDS | _DEMO_EVIDENCE_KINDS | {"live-url"}
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
_TARGET_KEYS = {
    "appID",
    "bundleID",
    "platform",
    "versionID",
    "marketingVersion",
    "buildID",
    "buildNumber",
    "sourceCommit",
    "datasetID",
    "datasetSHA256",
    "desiredManifestSHA256",
    "screenshotDisplayType",
    "demoAccountIdentitySHA256",
}
_REQUIRED_DESIRED_EVIDENCE = (
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
_REVIEW_FIELDS = {
    "contactFirstName",
    "contactLastName",
    "contactPhone",
    "contactEmail",
    "demoAccountName",
    "demoAccountPassword",
    "notes",
}


class GateError(RuntimeError):
    """The gate contract or evidence bundle cannot be interpreted safely."""


@dataclass(frozen=True)
class GateResult:
    document: dict[str, Any]
    html: str
    files: dict[str, bytes]


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_sha(value: Any) -> str:
    return _sha(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def _git_blob_sha256(
    root: Path, commit: str, rel_path: str
) -> tuple[str | None, str | None]:
    """sha256 of `rel_path` exactly as recorded at `commit`, or (None, reason).

    Kept self-contained rather than shared with the evidence producers on
    purpose: this gate hashes its own source into every bundle it writes, so the
    logic that decides whether a claim is true has to be inside the file that
    gets hashed.  Reasons are returned instead of raised so an unresolvable
    referent reaches the caller as a named block; "could not check" must never
    read the same as "checked and fine".

    ``git cat-file blob`` exits 0 for a symlink entry and hands back the link
    target's bytes, so the tree entry's mode is verified before its content.
    """
    if not _COMMIT_RE.fullmatch(commit or ""):
        return None, f"source.commit is not a 40-hex git commit: {commit!r}"

    def run(*args: str, text: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=text, check=False
        )

    try:
        if run("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").returncode != 0:
            return None, f"source.commit is unreachable from {root}: {commit}"
        entry = run("ls-tree", "--full-tree", commit, "--", rel_path)
        if entry.returncode != 0 or not entry.stdout.strip():
            return None, f"{rel_path} does not exist at {commit}"
        mode, kind, _rest = entry.stdout.split(maxsplit=2)
        if kind != "blob" or mode not in _REGULAR_FILE_MODES:
            return None, f"{rel_path} at {commit} is not a regular file: mode={mode} kind={kind}"
        blob = run("cat-file", "blob", f"{commit}:{rel_path}", text=False)
        if blob.returncode != 0:
            return None, f"{rel_path} cannot be read at {commit}"
    except OSError as exc:
        return None, f"git is unavailable: {exc}"
    return _sha(blob.stdout), None


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must be a JSON object")
    return value, payload


def _require_exact_keys(value: Any, expected: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise GateError(
            f"{label} keys do not match closed contract: "
            f"expected={sorted(expected)} actual={actual}"
        )
    return value


def _relative_path(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise GateError(f"{label} path must be a non-empty relative path")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise GateError(f"{label} path is unsafe: {value}")
    root_resolved = root.resolve()
    resolved = (root / rel).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise GateError(f"{label} path escapes workspace: {value}")
    return resolved


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise GateError(f"{label} must be a timezone-aware ISO8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError(f"{label} must be a timezone-aware ISO8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GateError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _fresh(
    value: Any,
    *,
    observed_at: datetime,
    max_age_hours: Any,
    label: str,
) -> tuple[bool, str | None]:
    try:
        timestamp = _parse_time(value, label=label)
    except GateError as exc:
        return False, str(exc)
    if not isinstance(max_age_hours, (int, float)) or max_age_hours <= 0:
        return False, f"{label} maxAgeHours must be positive"
    age_hours = (observed_at - timestamp).total_seconds() / 3600
    if age_hours < 0:
        return False, f"{label} is in the future"
    if age_hours > float(max_age_hours):
        return False, f"{label} is stale by {age_hours:.2f} hours"
    return True, None


def load_spec(path: Path) -> dict[str, Any]:
    spec, _ = _read_json(path, label="gate spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise GateError(f"gate spec schema must be {SPEC_SCHEMA}")
    if set(spec) != {"schema", "target", "artifacts", "claims", "requiredLiveURLs", "freshness", "producers"}:
        raise GateError("gate spec top-level keys do not match the closed contract")
    target = spec.get("target")
    if not isinstance(target, dict) or set(target) != _TARGET_KEYS:
        raise GateError("gate spec target keys do not match the closed contract")
    for key in _TARGET_KEYS:
        if not isinstance(target.get(key), str) or not target[key]:
            raise GateError(f"gate spec target.{key} must be a non-empty string")
    if target["platform"] != "IOS":
        raise GateError("gate spec target.platform must be IOS")
    if not _COMMIT_RE.fullmatch(target["sourceCommit"]):
        raise GateError("gate spec sourceCommit must be a full git SHA")
    for key in ("datasetSHA256", "desiredManifestSHA256", "demoAccountIdentitySHA256"):
        if not _SHA_RE.fullmatch(target[key]):
            raise GateError(f"gate spec target.{key} must be SHA-256")

    artifacts = spec.get("artifacts")
    expected_artifact_keys = {
        "desiredBundle",
        "liveMirrorBundle",
        "journeys",
        "demoAccess",
        "urlChecks",
        "appearanceProof",
        "attestations",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifact_keys:
        raise GateError("gate spec artifacts keys do not match the closed contract")
    for key in ("desiredBundle", "liveMirrorBundle"):
        _relative_path(Path("."), artifacts[key], label=key)
    journeys = artifacts.get("journeys")
    if not isinstance(journeys, list) or not journeys:
        raise GateError("gate spec must require at least one journey")
    journey_ids: list[str] = []
    for item in journeys:
        if not isinstance(item, dict) or set(item) != {"id", "path", "maxAgeHours"}:
            raise GateError("gate journey ref keys do not match the closed contract")
        if not isinstance(item.get("id"), str) or not _SAFE_ID_RE.fullmatch(item["id"]):
            raise GateError("gate journey id is unsafe")
        _relative_path(Path("."), item.get("path"), label=f"journey {item.get('id')}")
        if not isinstance(item.get("maxAgeHours"), (int, float)) or item["maxAgeHours"] <= 0:
            raise GateError(f"journey {item['id']} maxAgeHours must be positive")
        journey_ids.append(item["id"])
    if len(set(journey_ids)) != len(journey_ids):
        raise GateError("gate journey ids must be unique")
    for key in ("demoAccess", "urlChecks"):
        item = artifacts.get(key)
        if not isinstance(item, dict) or set(item) != {"path", "maxAgeHours"}:
            raise GateError(f"gate {key} ref keys do not match the closed contract")
        _relative_path(Path("."), item["path"], label=key)
        if not isinstance(item["maxAgeHours"], (int, float)) or item["maxAgeHours"] <= 0:
            raise GateError(f"gate {key} maxAgeHours must be positive")
    appearance = artifacts.get("appearanceProof")
    if not isinstance(appearance, dict) or set(appearance) != {"path", "maxAgeHours", "sha256"}:
        raise GateError("gate appearanceProof ref keys do not match the closed contract")
    _relative_path(Path("."), appearance["path"], label="appearanceProof")
    if not isinstance(appearance["maxAgeHours"], (int, float)) or appearance["maxAgeHours"] <= 0:
        raise GateError("gate appearanceProof maxAgeHours must be positive")
    if appearance["sha256"] != "pending" and (
        not isinstance(appearance["sha256"], str) or not _SHA_RE.fullmatch(appearance["sha256"])
    ):
        raise GateError("gate appearanceProof sha256 must be SHA-256 or pending")
    attestations = artifacts.get("attestations")
    if not isinstance(attestations, dict) or set(attestations) != {"human", "agent"}:
        raise GateError("gate attestations must require human and agent")
    for actor, value in attestations.items():
        _relative_path(Path("."), value, label=f"attestation {actor}")

    required_producer_ids = {
        "desiredBundle",
        "liveMirrorBundle",
        "demoAccess",
        "urlChecks",
        "appearanceProof",
        "attestation.human",
        "attestation.agent",
        *(f"journey.{journey_id}" for journey_id in journey_ids),
    }
    producers = spec.get("producers")
    if not isinstance(producers, dict) or set(producers) != required_producer_ids:
        raise GateError("gate producers must exactly cover every required artifact")
    for producer_id, producer in producers.items():
        if not isinstance(producer, dict) or set(producer) != {"type", "authority", "command"}:
            raise GateError(f"producer {producer_id} keys do not match the closed contract")
        if producer.get("type") not in _PRODUCER_TYPES:
            raise GateError(f"producer {producer_id} type is invalid")
        for field in ("authority", "command"):
            if not isinstance(producer.get(field), str) or not producer[field]:
                raise GateError(f"producer {producer_id}.{field} must be non-empty")
    if producers["attestation.human"]["type"] != "human-attestation":
        raise GateError("human attestation must declare human authority")

    claims = spec.get("claims")
    if not isinstance(claims, list) or not claims:
        raise GateError("gate claims must be a non-empty list")
    claim_ids: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {
            "id",
            "surface",
            "statement",
            "feature",
            "journeyIDs",
            "entitlement",
            "acceptedEvidenceKinds",
        }:
            raise GateError("gate claim keys do not match the closed contract")
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not _SAFE_ID_RE.fullmatch(claim_id):
            raise GateError("gate claim id is unsafe")
        surface = claim.get("surface")
        if (
            not isinstance(surface, dict)
            or set(surface) != {"kind", "ref"}
            or surface.get("kind") not in _SURFACE_KINDS
            or not isinstance(surface.get("ref"), str)
            or not surface["ref"]
        ):
            raise GateError(f"claim {claim_id} surface is invalid")
        if not isinstance(claim.get("statement"), str) or not claim["statement"]:
            raise GateError(f"claim {claim_id} statement is missing")
        if not isinstance(claim.get("feature"), str) or not claim["feature"]:
            raise GateError(f"claim {claim_id} feature is missing")
        if claim.get("entitlement") not in {"none", "free", "pro"}:
            raise GateError(f"claim {claim_id} entitlement is invalid")
        linked = claim.get("journeyIDs")
        if not isinstance(linked, list) or any(item not in journey_ids for item in linked):
            raise GateError(f"claim {claim_id} references unknown journeys")
        kinds = claim.get("acceptedEvidenceKinds")
        if (
            not isinstance(kinds, list)
            or not kinds
            or len(set(kinds)) != len(kinds)
            or any(item not in _CLAIM_EVIDENCE_KINDS for item in kinds)
        ):
            raise GateError(f"claim {claim_id} acceptedEvidenceKinds is invalid")
        if claim["entitlement"] == "pro" and "release-equivalent-simulator" in kinds:
            raise GateError(f"claim {claim_id} Pro evidence cannot accept fixture simulator")
        claim_ids.append(claim_id)
    if len(set(claim_ids)) != len(claim_ids):
        raise GateError("gate claim ids must be unique")

    live_urls = spec.get("requiredLiveURLs")
    if not isinstance(live_urls, list) or not live_urls:
        raise GateError("gate requiredLiveURLs must be non-empty")
    url_ids: list[str] = []
    for item in live_urls:
        if not isinstance(item, dict) or set(item) != {"id", "url", "claimIDs"}:
            raise GateError("requiredLiveURL keys do not match the closed contract")
        if not isinstance(item.get("id"), str) or not _SAFE_ID_RE.fullmatch(item["id"]):
            raise GateError("requiredLiveURL id is unsafe")
        if not isinstance(item.get("url"), str) or not item["url"].startswith("https://"):
            raise GateError(f"requiredLiveURL {item.get('id')} must use HTTPS")
        if not isinstance(item.get("claimIDs"), list) or any(
            claim_id not in claim_ids for claim_id in item["claimIDs"]
        ):
            raise GateError(f"requiredLiveURL {item['id']} has unknown claims")
        url_ids.append(item["id"])
    if len(set(url_ids)) != len(url_ids):
        raise GateError("requiredLiveURL ids must be unique")
    freshness = spec.get("freshness")
    if not isinstance(freshness, dict) or set(freshness) != {
        "liveMirrorMaxAgeHours",
        "attestationMaxAgeHours",
    }:
        raise GateError("gate freshness keys do not match the closed contract")
    if any(not isinstance(value, (int, float)) or value <= 0 for value in freshness.values()):
        raise GateError("gate freshness values must be positive")
    return spec


def _block(blocks: list[dict[str, Any]], code: str, expected: Any, actual: Any) -> None:
    blocks.append({"code": code, "expected": expected, "actual": actual})


def _exact_keys(
    value: Any,
    expected: set[str],
    *,
    code: str,
    blocks: list[dict[str, Any]],
) -> bool:
    actual = set(value) if isinstance(value, dict) else set()
    if not isinstance(value, dict) or actual != expected:
        _block(blocks, code, sorted(expected), sorted(actual))
        return False
    return True


def _target_matches(target: dict[str, Any], actual: dict[str, Any], *, prefix: str, blocks: list[dict[str, Any]]) -> None:
    mapping = {
        "bundleID": "bundleId",
        "marketingVersion": "marketingVersion",
        "buildNumber": "buildNumber",
        "sourceCommit": "sourceCommit",
    }
    for expected_key, actual_key in mapping.items():
        if actual.get(actual_key) != target[expected_key]:
            _block(blocks, f"{prefix}.target.{expected_key}", target[expected_key], actual.get(actual_key))


def _map_file(files: dict[str, bytes], rel: str, payload: bytes) -> None:
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts or rel in files:
        raise GateError(f"reviewer bundle path is unsafe or duplicated: {rel}")
    files[rel] = payload


def _load_live_bundle(
    path: Path,
    *,
    files: dict[str, bytes],
) -> tuple[dict[str, Any], str]:
    manifest, manifest_bytes = _read_json(path / "manifest.json", label="live mirror closure")
    if manifest.get("schema") != "kg.app_review.asc_mirror_bundle.v1":
        raise GateError("live mirror closure schema is invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise GateError("live mirror closure files must be a list")
    expected_paths: set[str] = set()
    staged_files: dict[str, bytes] = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "byteSize", "sha256"}:
            raise GateError("live mirror closure entry is invalid")
        rel = item.get("path")
        source = _relative_path(path, rel, label="live mirror file")
        payload = source.read_bytes() if source.is_file() else b""
        if (
            not payload
            or len(payload) != item.get("byteSize")
            or _sha(payload) != item.get("sha256")
        ):
            raise GateError(f"live mirror closure hash/size mismatch: {rel}")
        expected_paths.add(rel)
        output_rel = rel if rel.startswith("live/images/") else f"inputs/live/{rel}"
        _map_file(staged_files, output_rel, payload)
    actual_paths = {
        file.relative_to(path).as_posix()
        for file in path.rglob("*")
        if file.is_file() and file.relative_to(path).as_posix() != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise GateError(
            f"live mirror closure is not exact: missing={sorted(expected_paths - actual_paths)} "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    _map_file(staged_files, "inputs/live/manifest.json", manifest_bytes)
    audit, _ = _read_json(path / "audit.json", label="live mirror audit")
    if audit.get("schema") != "kg.app_review.asc_audit.v1":
        raise GateError("live mirror audit schema is invalid")
    _require_exact_keys(
        audit,
        {"schema", "mode", "verdict", "desired", "live", "mismatches"},
        label="live mirror audit",
    )
    if audit.get("mode") != "read-only":
        raise GateError("live mirror audit mode must be read-only")
    _require_exact_keys(
        audit.get("verdict"), {"status", "mismatchCount"}, label="live mirror verdict"
    )
    desired = _require_exact_keys(
        audit.get("desired"),
        {"schema", "manifestSHA256", "build", "locale", "target", "outputs"},
        label="live mirror desired",
    )
    _require_exact_keys(
        desired.get("build"), {"marketingVersion", "buildNumber"}, label="live mirror desired build"
    )
    for index, item in enumerate(desired.get("outputs") or []):
        _require_exact_keys(
            item,
            {"order", "shotID", "fileName", "sha256", "sourceMD5", "byteSize", "width", "height"},
            label=f"live mirror desired output {index}",
        )
    live = _require_exact_keys(
        audit.get("live"),
        {"observedAt", "appID", "version", "build", "submission", "metadata", "reviewDetail", "screenshots"},
        label="live mirror live",
    )
    _require_exact_keys(
        live.get("version"),
        {"id", "versionString", "platform", "state", "selectedBuildRelationshipID", "includedBuildMatchCount"},
        label="live mirror version",
    )
    _require_exact_keys(
        live.get("build"),
        {"id", "number", "processingState", "audienceType", "usesNonExemptEncryption"},
        label="live mirror build",
    )
    submission = _require_exact_keys(
        live.get("submission"),
        {"id", "state", "platform", "submittedDate", "item"},
        label="live mirror submission",
    )
    _require_exact_keys(
        submission.get("item"), {"id", "state", "versionID"}, label="live mirror submission item"
    )
    metadata = _require_exact_keys(
        live.get("metadata"), {"id", "locale", "fields"}, label="live mirror metadata"
    )
    _require_exact_keys(
        metadata.get("fields"),
        {"description", "keywords", "marketingUrl", "promotionalText", "supportUrl", "whatsNew"},
        label="live mirror metadata fields",
    )
    review = _require_exact_keys(
        live.get("reviewDetail"),
        {"id", "demoAccountRequired", "fields"},
        label="live mirror review detail",
    )
    screenshots = _require_exact_keys(
        live.get("screenshots"),
        {"locale", "displayType", "setID", "matchingSetCount", "relationshipCount", "relationshipTotal", "items"},
        label="live mirror screenshots",
    )
    review_fields = review.get("fields")
    if not isinstance(review_fields, dict) or set(review_fields) != _REVIEW_FIELDS:
        raise GateError("live mirror review fields do not match the redacted closed contract")
    for field, value in review_fields.items():
        expected_keys = {"present", "fingerprint", "ref"}
        if field == "demoAccountName":
            expected_keys.add("identitySHA256")
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise GateError(f"live mirror review field is not safely redacted: {field}")
        if not isinstance(value.get("present"), bool):
            raise GateError(f"live mirror review field presence is unknown: {field}")
        fingerprint = value.get("fingerprint")
        if value["present"] and (
            not isinstance(fingerprint, str) or not _SHA_RE.fullmatch(fingerprint)
        ):
            raise GateError(f"live mirror review field fingerprint is invalid: {field}")
        if not value["present"] and fingerprint is not None:
            raise GateError(f"live mirror absent review field has a fingerprint: {field}")
        if field == "demoAccountName":
            identity = value.get("identitySHA256")
            if value["present"] and (
                not isinstance(identity, str) or not _SHA_RE.fullmatch(identity)
            ):
                raise GateError("live mirror demo account identity fingerprint is invalid")
            if not value["present"] and identity is not None:
                raise GateError("live mirror absent demo account has an identity fingerprint")
        if not isinstance(value.get("ref"), str) or not value["ref"].startswith("asc://"):
            raise GateError(f"live mirror review field ref is invalid: {field}")
    for index, item in enumerate(screenshots.get("items") or []):
        _require_exact_keys(
            item,
            {"order", "id", "fileName", "state", "width", "height", "sourceFileChecksum", "ref", "bundlePath", "liveBytes"},
            label=f"live mirror screenshot {index}",
        )
        rel = item.get("bundlePath")
        if not isinstance(rel, str) or rel not in expected_paths or not rel.startswith("live/images/"):
            raise GateError(f"live mirror screenshot bundle path is invalid: {rel}")
        payload = (path / rel).read_bytes()
        live_bytes = _require_exact_keys(
            item.get("liveBytes"),
            {"status", "sha256", "byteSize", "width", "height"},
            label=f"live mirror screenshot {index} bytes",
        )
        if (
            live_bytes.get("status") != "verified"
            or live_bytes.get("sha256") != _sha(payload)
            or live_bytes.get("byteSize") != len(payload)
        ):
            raise GateError(f"live mirror screenshot bytes drift: {rel}")
    mismatches = audit.get("mismatches")
    if not isinstance(mismatches, list):
        raise GateError("live mirror mismatches must be a list")
    for index, mismatch in enumerate(mismatches):
        _require_exact_keys(
            mismatch,
            {"code", "classification", "expected", "actual"},
            label=f"live mirror mismatch {index}",
        )
    if (audit.get("verdict") or {}).get("mismatchCount") != len(mismatches):
        raise GateError("live mirror mismatchCount drift")
    verdict_status = (audit.get("verdict") or {}).get("status")
    if verdict_status not in {"pass", "fail"} or (verdict_status == "pass") != (len(mismatches) == 0):
        raise GateError("live mirror verdict/mismatches consistency drift")
    version = live["version"]
    build = live["build"]
    if (
        version.get("platform") != "IOS"
        or not isinstance(version.get("state"), str)
        or version.get("includedBuildMatchCount") != 1
        or version.get("selectedBuildRelationshipID") != build.get("id")
    ):
        raise GateError("live mirror selected version/build relationship is unknown")
    if (
        build.get("processingState") != "VALID"
        or build.get("audienceType") != "APP_STORE_ELIGIBLE"
        or not isinstance(build.get("usesNonExemptEncryption"), bool)
    ):
        raise GateError("live mirror build processing/audience/compliance is not ready")
    submission_item = submission["item"]
    if (
        submission.get("state") not in {"WAITING_FOR_REVIEW", "IN_REVIEW"}
        or submission.get("platform") != "IOS"
        or submission_item.get("state") != "READY_FOR_REVIEW"
        or submission_item.get("versionID") != version.get("id")
    ):
        raise GateError("live mirror submission item is not reviewer-ready")
    if metadata.get("locale") != desired.get("locale"):
        raise GateError("live mirror metadata locale drift")
    metadata_fields = metadata["fields"]
    for field in ("description", "keywords", "promotionalText", "supportUrl"):
        if not isinstance(metadata_fields.get(field), str) or not metadata_fields[field]:
            raise GateError(f"live mirror required metadata is unknown: {field}")
    if not isinstance(review.get("id"), str) or not isinstance(review.get("demoAccountRequired"), bool):
        raise GateError("live mirror review detail identity/demo requirement is unknown")
    for field in ("contactFirstName", "contactLastName", "contactPhone", "contactEmail", "notes"):
        if review_fields[field].get("present") is not True:
            raise GateError(f"live mirror required review field is missing: {field}")
    if review.get("demoAccountRequired") and any(
        review_fields[field].get("present") is not True
        for field in ("demoAccountName", "demoAccountPassword")
    ):
        raise GateError("live mirror demo credentials are missing")
    screenshot_items = screenshots.get("items")
    if not isinstance(screenshot_items, list):
        raise GateError("live mirror screenshot items must be a list")
    if (
        screenshots.get("matchingSetCount") != 1
        or screenshots.get("relationshipCount") != len(screenshot_items)
        or screenshots.get("relationshipTotal") != len(screenshot_items)
    ):
        raise GateError("live mirror screenshot relationship/pagination closure is unknown")
    if screenshots.get("locale") != desired.get("locale"):
        raise GateError("live mirror screenshot locale drift")
    file_names = [item.get("fileName") for item in screenshot_items if isinstance(item, dict)]
    if len(set(file_names)) != len(screenshot_items):
        raise GateError("live mirror screenshot filenames are not unique")
    for index, item in enumerate(screenshot_items):
        live_bytes = item.get("liveBytes") or {}
        if (
            item.get("order") != index + 1
            or item.get("state") != "COMPLETE"
            or not isinstance(item.get("width"), int)
            or not isinstance(item.get("height"), int)
            or item["width"] <= 0
            or item["height"] <= 0
            or not isinstance(item.get("sourceFileChecksum"), str)
            or not _MD5_RE.fullmatch(item["sourceFileChecksum"])
            or live_bytes.get("status") != "verified"
            or (live_bytes.get("width"), live_bytes.get("height"))
            != (item.get("width"), item.get("height"))
        ):
            raise GateError(f"live mirror screenshot required evidence is not ready: {index}")
        if verdict_status == "pass":
            desired_output = desired["outputs"][index] if index < len(desired["outputs"]) else {}
            if (
                item.get("fileName") != desired_output.get("fileName")
                or item.get("sourceFileChecksum") != desired_output.get("sourceMD5")
            ):
                raise GateError(f"live mirror screenshot source checksum/order drift: {index}")
    semantic_paths = {"audit.json", "desired/manifest.json"}
    desired_manifest_payload = (path / "desired" / "manifest.json").read_bytes()
    if _sha(desired_manifest_payload) != desired.get("manifestSHA256"):
        raise GateError("live mirror nested desired manifest hash drift")
    for index, item in enumerate(desired.get("outputs") or []):
        file_name = item.get("fileName")
        if not isinstance(file_name, str) or not _SAFE_FILE_RE.fullmatch(file_name):
            raise GateError(f"live mirror desired filename is unsafe: {file_name}")
        rel = f"desired/outputs/{file_name}"
        semantic_paths.add(rel)
        payload = (path / rel).read_bytes()
        if _sha(payload) != item.get("sha256") or len(payload) != item.get("byteSize"):
            raise GateError(f"live mirror nested desired output drift: {rel}")
    for item in screenshots.get("items") or []:
        semantic_paths.add(item["bundlePath"])
    if expected_paths != semantic_paths:
        raise GateError(
            "live mirror semantic closure is not exact: "
            f"missing={sorted(semantic_paths - expected_paths)} "
            f"extra={sorted(expected_paths - semantic_paths)}"
        )
    for rel, payload in staged_files.items():
        _map_file(files, rel, payload)
    return audit, _sha(manifest_bytes)


def _load_desired_bundle(
    path: Path,
    *,
    workspace_root: Path,
    files: dict[str, bytes],
) -> tuple[dict[str, Any], str]:
    manifest, manifest_bytes = _read_json(path / "manifest.json", label="desired evidence")
    if manifest.get("schema") != "kg.app_review.submission.v1":
        raise GateError("desired evidence schema is invalid")
    _require_exact_keys(
        manifest,
        {"schema", "verdict", "build", "source", "capture", "outputs", "provenance"},
        label="desired manifest",
    )
    verdict = _require_exact_keys(
        manifest.get("verdict"), {"status", "requiredEvidence"}, label="desired verdict"
    )
    evidence = verdict.get("requiredEvidence")
    if verdict.get("status") != "pass" or evidence != [
        {"id": evidence_id, "status": "verified"}
        for evidence_id in _REQUIRED_DESIRED_EVIDENCE
    ]:
        raise GateError("desired evidence requiredEvidence is not the closed verified contract")
    build = _require_exact_keys(
        manifest.get("build"),
        {"marketingVersion", "buildNumber", "project"},
        label="desired build",
    )
    project = _require_exact_keys(
        build.get("project"), {"path", "sha256"}, label="desired build.project"
    )
    source = _require_exact_keys(
        manifest.get("source"), {"commit"}, label="desired source"
    )
    capture = _require_exact_keys(
        manifest.get("capture"),
        {"profile", "dataset", "device", "fixedClock", "locale", "promotionManifest", "renderSpec"},
        label="desired capture",
    )
    profile = _require_exact_keys(
        capture.get("profile"), {"schema", "id", "path", "sha256"}, label="desired profile"
    )
    dataset = _require_exact_keys(
        capture.get("dataset"), {"schema", "id", "path", "sha256"}, label="desired dataset"
    )
    device = _require_exact_keys(
        capture.get("device"), {"destination"}, label="desired device"
    )
    promotion = _require_exact_keys(
        capture.get("promotionManifest"),
        {"schema", "path", "sha256"},
        label="desired promotionManifest",
    )
    render_spec = _require_exact_keys(
        capture.get("renderSpec"), {"sha256", "value"}, label="desired renderSpec"
    )
    if not isinstance(render_spec.get("value"), dict) or render_spec.get("sha256") != _json_sha(
        render_spec.get("value")
    ):
        raise GateError("desired renderSpec hash mismatch")
    provenance = _require_exact_keys(
        manifest.get("provenance"),
        {"generators", "inputDigests", "rebuild", "sourceCommit"},
        label="desired provenance",
    )
    input_digests = _require_exact_keys(
        provenance.get("inputDigests"),
        {"dataset", "profile", "project", "promotionManifest", "renderSpec"},
        label="desired provenance.inputDigests",
    )
    rebuild = _require_exact_keys(
        provenance.get("rebuild"),
        {"dataset", "deviceDestination", "entrypoint", "fixedClock", "locale", "profile"},
        label="desired provenance.rebuild",
    )
    generators = provenance.get("generators")
    if not isinstance(generators, list) or not generators:
        raise GateError("desired provenance.generators must be non-empty")
    for index, generator in enumerate(generators):
        _require_exact_keys(
            generator, {"path", "sha256"}, label=f"desired provenance.generator {index}"
        )
        if not isinstance(generator.get("path"), str) or not _SHA_RE.fullmatch(
            str(generator.get("sha256"))
        ):
            raise GateError(f"desired provenance.generator {index} is invalid")
    if provenance.get("sourceCommit") != source.get("commit"):
        raise GateError("desired provenance sourceCommit drift")
    digest_bindings = {
        "dataset": dataset.get("sha256"),
        "profile": profile.get("sha256"),
        "project": project.get("sha256"),
        "promotionManifest": promotion.get("sha256"),
        "renderSpec": render_spec.get("sha256"),
    }
    if input_digests != digest_bindings:
        raise GateError("desired provenance inputDigests drift")
    rebuild_bindings = {
        "dataset": dataset.get("path"),
        "deviceDestination": device.get("destination"),
        "entrypoint": rebuild.get("entrypoint"),
        "fixedClock": capture.get("fixedClock"),
        "locale": capture.get("locale"),
        "profile": profile.get("path"),
    }
    if (
        rebuild != rebuild_bindings
        or not isinstance(rebuild.get("entrypoint"), str)
        or not rebuild["entrypoint"]
    ):
        raise GateError("desired provenance rebuild bindings drift")
    # Everything above is the bundle agreeing with itself, which a bundle built
    # from the working tree does just as well as one built from the commit it
    # names.  This is the only check that leaves the bundle to ask git what
    # `source.commit` actually contains.
    blob_sha, unresolved = _git_blob_sha256(
        workspace_root, str(source.get("commit") or ""), _PROJECT_SOURCE_PATH
    )
    if unresolved is not None:
        raise GateError(
            f"desired build.project cannot be checked against source commit: {unresolved}"
        )
    if blob_sha != project.get("sha256"):
        raise GateError(
            "desired build.project sha256 does not match source commit blob: "
            f"commit={source.get('commit')} path={_PROJECT_SOURCE_PATH} "
            f"blob={blob_sha} manifest={project.get('sha256')}"
        )
    desired_files: dict[str, bytes] = {}
    _map_file(desired_files, "inputs/desired/manifest.json", manifest_bytes)
    referenced = [
        ("project", project.get("path"), project.get("sha256")),
        ("capture profile", profile.get("path"), profile.get("sha256")),
        ("capture dataset", dataset.get("path"), dataset.get("sha256")),
        ("promotion manifest", promotion.get("path"), promotion.get("sha256")),
    ]
    expected_source_paths: set[str] = set()
    for label, rel, expected_sha in referenced:
        # Not named `source`: that name holds the manifest's source block, which
        # the checks above still need to mean what it says.
        staged = _relative_path(path, rel, label=label)
        payload = staged.read_bytes() if staged.is_file() else b""
        if not payload or not isinstance(expected_sha, str) or _sha(payload) != expected_sha:
            raise GateError(f"desired {label} hash mismatch: {rel}")
        expected_source_paths.add(rel)
        _map_file(desired_files, f"inputs/desired/{rel}", payload)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise GateError("desired outputs must be non-empty")
    for index, item in enumerate(outputs):
        _require_exact_keys(
            item,
            {"shotID", "sourceScenario", "appearance", "file", "byteSize", "sha256"},
            label=f"desired output {index}",
        )
        staged = _relative_path(path, item.get("file"), label=f"desired output {index}")
        payload = staged.read_bytes() if staged.is_file() else b""
        if (
            not payload
            or len(payload) != item.get("byteSize")
            or _sha(payload) != item.get("sha256")
        ):
            raise GateError(f"desired output hash/size mismatch: {item.get('file')}")
        expected_source_paths.add(item["file"])
        _map_file(desired_files, f"inputs/desired/{item['file']}", payload)
    actual_source_paths = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.relative_to(path).as_posix() != "manifest.json"
    }
    if actual_source_paths != expected_source_paths:
        raise GateError(
            f"desired evidence closure is not exact: missing={sorted(expected_source_paths - actual_source_paths)} "
            f"extra={sorted(actual_source_paths - expected_source_paths)}"
        )
    for rel, payload in desired_files.items():
        _map_file(files, rel, payload)
    return manifest, _sha(manifest_bytes)


def _load_optional_json(
    root: Path,
    rel: str,
    *,
    label: str,
    bundle_rel: str,
    files: dict[str, bytes],
) -> dict[str, Any] | None:
    path = _relative_path(root, rel, label=label)
    if not path.is_file():
        return None
    value, payload = _read_json(path, label=label)
    _map_file(files, bundle_rel, payload)
    return value


def _load_evidence_artifacts(
    value: dict[str, Any],
    *,
    root: Path,
    prefix: str,
    files: dict[str, bytes],
    blocks: list[dict[str, Any]],
) -> bool:
    valid = True
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        _block(blocks, f"{prefix}.artifacts", "non-empty hash list", artifacts)
        return False
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "kind"}:
            _block(blocks, f"{prefix}.artifact.{index}.shape", "path/sha256/kind", item)
            valid = False
            continue
        try:
            source = _relative_path(root, item.get("path"), label=f"{prefix} artifact")
        except GateError as exc:
            _block(blocks, f"{prefix}.artifact.{index}.path", "safe path", str(exc))
            valid = False
            continue
        payload = source.read_bytes() if source.is_file() else b""
        if not payload:
            _block(blocks, f"{prefix}.artifact.{index}.missing", item.get("path"), "missing")
            valid = False
            continue
        actual = _sha(payload)
        if actual != item.get("sha256"):
            _block(blocks, f"{prefix}.artifact.{index}.sha256", item.get("sha256"), actual)
            valid = False
            continue
        safe_prefix = re.sub(r"[^a-zA-Z0-9._-]", "_", prefix)
        _map_file(files, f"inputs/evidence/{safe_prefix}/{index:02d}_{source.name}", payload)
    return valid


def _pre_root(files: dict[str, bytes]) -> str:
    inventory = [
        {"path": rel, "byteSize": len(payload), "sha256": _sha(payload)}
        for rel, payload in sorted(files.items())
    ]
    return _sha(_canonical({"schema": "kg.app_review.pre_attestation.v1", "files": inventory}))


def _render_html(document: dict[str, Any]) -> str:
    reviewer = document["reviewerView"]
    metadata_rows = "".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in reviewer.get("metadata", {}).items()
    )
    review_rows = "".join(
        "<tr><th>{}</th><td>present={} · fingerprint={} · {}</td></tr>".format(
            html.escape(key),
            html.escape(str(value.get("present"))),
            html.escape("present" if value.get("fingerprint") else "absent"),
            html.escape(str(value.get("ref"))),
        )
        for key, value in reviewer.get("reviewDetail", {}).get("fields", {}).items()
    )
    shots = "".join(
        "<figure><img src=\"{}\" alt=\"{}\"><figcaption>#{} {}</figcaption></figure>".format(
            html.escape(str(item.get("bundlePath")), quote=True),
            html.escape(str(item.get("fileName")), quote=True),
            html.escape(str(item.get("order"))),
            html.escape(str(item.get("fileName"))),
        )
        for item in reviewer.get("screenshots", [])
    )
    claim_rows = "".join(
        "<tr><th>{}</th><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(item["id"]),
            html.escape(item["surface"]),
            html.escape(item["feature"]),
            html.escape(item["entitlement"]),
            html.escape(", ".join(item["evidence"])),
        )
        for item in document.get("claims", [])
    )
    blocks = "".join(
        f"<li><code>{html.escape(item['code'])}</code>: expected {html.escape(str(item['expected']))}; "
        f"actual {html.escape(str(item['actual']))}</li>"
        for item in document.get("blocks", [])
    )
    verdict = document["verdict"]["status"].upper()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>App Review Gate</title>
<style>body{{font:15px system-ui;margin:2rem;max-width:1200px}}.verdict{{font-size:2rem;font-weight:800}}table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{border:1px solid #ccc;padding:.5rem;text-align:left;vertical-align:top}}.shots{{display:flex;gap:1rem;overflow:auto;padding-bottom:.5rem}}figure{{margin:0;min-width:240px}}img{{width:240px;height:auto;border:1px solid #aaa}}code{{font-family:ui-monospace,monospace}}details{{margin:1.5rem 0}}summary{{cursor:pointer;font-size:1.25rem;font-weight:700}}</style></head>
<body><h1>Apple reviewer mirror</h1><div class="verdict">{html.escape(verdict)}</div>
<p>Target {html.escape(document['target']['marketingVersion'])} ({html.escape(document['target']['buildNumber'])}) · observation {html.escape(document['observationMode'])}</p>
<h2>Live ASC screenshot order and bytes</h2><div class="shots">{shots}</div>
<h2>Live ASC metadata</h2><table>{metadata_rows}</table>
<h2>Live review information (redacted)</h2><table>{review_rows}</table>
<details><summary>Blocking reasons ({document['verdict']['blockCount']})</summary><ul>{blocks or '<li>none</li>'}</ul></details>
<h2>Claim evidence</h2><table><tr><th>Claim</th><th>Surface</th><th>Feature</th><th>Entitlement</th><th>Evidence</th></tr>{claim_rows}</table>
</body></html>"""


def evaluate_gate(
    *,
    spec_path: Path,
    workspace_root: Path,
    observed_at: str,
    observation_mode: str,
) -> GateResult:
    if observation_mode not in {"offline", "online"}:
        raise GateError("observation mode must be offline or online")
    observed = _parse_time(observed_at, label="observed-at")
    root = workspace_root.resolve()
    spec = load_spec(spec_path)
    spec_bytes = spec_path.read_bytes()
    target = spec["target"]
    blocks: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    _map_file(files, "inputs/spec.json", spec_bytes)
    tools_root = Path(__file__).resolve().parent
    for tool_name in ("app_review_gate.py", "asc_reviewer_mirror.py", "asc_text_bundle.py"):
        _map_file(
            files,
            f"inputs/tools/{tool_name}",
            (tools_root / tool_name).read_bytes(),
        )
    if observation_mode == "offline":
        _block(blocks, "observation.offline", "fresh online observation", "offline")

    desired: dict[str, Any] = {}
    desired_hash: str | None = None
    try:
        desired_path = _relative_path(root, spec["artifacts"]["desiredBundle"], label="desiredBundle")
        desired, desired_hash = _load_desired_bundle(
            desired_path, workspace_root=root, files=files
        )
    except (GateError, OSError) as exc:
        _block(blocks, "desired.invalid", "valid desired bundle", str(exc))
    if desired:
        if desired_hash != target["desiredManifestSHA256"]:
            _block(blocks, "desired.manifest-sha256", target["desiredManifestSHA256"], desired_hash)
        desired_values = {
            "marketingVersion": ((desired.get("build") or {}).get("marketingVersion")),
            "buildNumber": ((desired.get("build") or {}).get("buildNumber")),
            "sourceCommit": ((desired.get("source") or {}).get("commit")),
            "datasetID": (((desired.get("capture") or {}).get("dataset") or {}).get("id")),
            "datasetSHA256": (((desired.get("capture") or {}).get("dataset") or {}).get("sha256")),
        }
        for key, actual in desired_values.items():
            if actual != target[key]:
                _block(blocks, f"desired.target.{key}", target[key], actual)
        if ((desired.get("verdict") or {}).get("status")) != "pass":
            _block(blocks, "desired.status", "pass", (desired.get("verdict") or {}).get("status"))

    live: dict[str, Any] = {}
    live_root: str | None = None
    try:
        live_path = _relative_path(root, spec["artifacts"]["liveMirrorBundle"], label="liveMirrorBundle")
        live, live_root = _load_live_bundle(live_path, files=files)
    except (GateError, OSError) as exc:
        _block(blocks, "live-mirror.invalid", "exact hash-closed live mirror", str(exc))
    live_body = live.get("live") if isinstance(live.get("live"), dict) else {}
    if live:
        if ((live.get("verdict") or {}).get("status")) != "pass":
            _block(blocks, "live-mirror.status", "pass", (live.get("verdict") or {}).get("status"))
            for mismatch in live.get("mismatches") or []:
                if isinstance(mismatch, dict) and isinstance(mismatch.get("code"), str):
                    _block(
                        blocks,
                        f"live-mirror.{mismatch['code']}",
                        mismatch.get("expected"),
                        mismatch.get("actual"),
                    )
        if ((live.get("desired") or {}).get("manifestSHA256")) != target["desiredManifestSHA256"]:
            _block(
                blocks,
                "live-mirror.desired-root",
                target["desiredManifestSHA256"],
                (live.get("desired") or {}).get("manifestSHA256"),
            )
        desired_outputs = [
            {
                "fileName": Path(item.get("file", "")).name,
                "sha256": item.get("sha256"),
                "byteSize": item.get("byteSize"),
            }
            for item in (desired.get("outputs") or [])
            if isinstance(item, dict)
        ]
        mirror_desired_outputs = [
            {
                "fileName": item.get("fileName"),
                "sha256": item.get("sha256"),
                "byteSize": item.get("byteSize"),
            }
            for item in ((live.get("desired") or {}).get("outputs") or [])
            if isinstance(item, dict)
        ]
        if desired_outputs != mirror_desired_outputs:
            _block(
                blocks,
                "live-mirror.desired-outputs-root",
                desired_outputs,
                mirror_desired_outputs,
            )
        version = live_body.get("version") or {}
        build = live_body.get("build") or {}
        live_targets = {
            "appID": live_body.get("appID"),
            "versionID": version.get("id"),
            "marketingVersion": version.get("versionString"),
            "buildID": build.get("id"),
            "buildNumber": build.get("number"),
            "platform": version.get("platform"),
            "screenshotDisplayType": (live_body.get("screenshots") or {}).get("displayType"),
        }
        for key, actual in live_targets.items():
            if actual != target[key]:
                _block(blocks, f"live-mirror.target.{key}", target[key], actual)
        live_output_bytes = [
            {
                "fileName": item.get("fileName"),
                "sha256": (item.get("liveBytes") or {}).get("sha256"),
                "byteSize": (item.get("liveBytes") or {}).get("byteSize"),
            }
            for item in (((live_body.get("screenshots") or {}).get("items")) or [])
            if isinstance(item, dict)
        ]
        if live_output_bytes != desired_outputs:
            _block(
                blocks,
                "live-mirror.live-outputs-root",
                desired_outputs,
                live_output_bytes,
            )
        fresh, reason = _fresh(
            live_body.get("observedAt"),
            observed_at=observed,
            max_age_hours=spec["freshness"]["liveMirrorMaxAgeHours"],
            label="live mirror observedAt",
        )
        if not fresh:
            _block(blocks, "live-mirror.freshness", "fresh", reason)

    evidence_by_claim: dict[str, list[str]] = {claim["id"]: [] for claim in spec["claims"]}
    journey_evidence_by_id: dict[str, str] = {}
    journey_summaries: list[dict[str, Any]] = []
    for ref in spec["artifacts"]["journeys"]:
        try:
            journey = _load_optional_json(
                root,
                ref["path"],
                label=f"journey {ref['id']}",
                bundle_rel=f"inputs/journeys/{ref['id']}.json",
                files=files,
            )
        except GateError as exc:
            _block(blocks, f"journey.{ref['id']}.invalid", "valid JSON", str(exc))
            continue
        if journey is None:
            _block(blocks, f"journey.{ref['id']}.missing", ref["path"], "missing")
            continue
        prefix = f"journey.{ref['id']}"
        shape_ok = _exact_keys(
            journey,
            {"schema", "id", "claimIDs", "target", "execution", "world", "result", "artifacts"},
            code=f"{prefix}.shape",
            blocks=blocks,
        )
        if journey.get("schema") != JOURNEY_SCHEMA or journey.get("id") != ref["id"]:
            _block(blocks, f"{prefix}.schema", {"schema": JOURNEY_SCHEMA, "id": ref["id"]}, {"schema": journey.get("schema"), "id": journey.get("id")})
            continue
        journey_target = journey.get("target") or {}
        shape_ok = _exact_keys(
            journey_target,
            {"bundleId", "marketingVersion", "buildNumber", "sourceCommit"},
            code=f"{prefix}.target.shape",
            blocks=blocks,
        ) and shape_ok
        _target_matches(target, journey_target, prefix=prefix, blocks=blocks)
        world = journey.get("world") or {}
        shape_ok = _exact_keys(
            world,
            {"datasetID", "sha256", "fixedClock"},
            code=f"{prefix}.world.shape",
            blocks=blocks,
        ) and shape_ok
        for key, target_key in (("datasetID", "datasetID"), ("sha256", "datasetSHA256")):
            if world.get(key) != target[target_key]:
                _block(blocks, f"{prefix}.world.{key}", target[target_key], world.get(key))
        if desired and world.get("fixedClock") != ((desired.get("capture") or {}).get("fixedClock")):
            _block(blocks, f"{prefix}.world.fixedClock", (desired.get("capture") or {}).get("fixedClock"), world.get("fixedClock"))
        result = journey.get("result") or {}
        shape_ok = _exact_keys(
            result,
            {"status", "testsExecuted", "startedAt", "finishedAt"},
            code=f"{prefix}.result.shape",
            blocks=blocks,
        ) and shape_ok
        status = result.get("status")
        if status != "pass":
            _block(blocks, f"{prefix}.status", "pass", status)
        if not isinstance(result.get("testsExecuted"), int) or result["testsExecuted"] <= 0:
            _block(blocks, f"{prefix}.tests", ">0", result.get("testsExecuted"))
        fresh, reason = _fresh(
            result.get("finishedAt"), observed_at=observed, max_age_hours=ref["maxAgeHours"], label=f"{prefix} finishedAt"
        )
        if not fresh:
            _block(blocks, f"{prefix}.freshness", "fresh", reason)
        try:
            started = _parse_time(result.get("startedAt"), label=f"{prefix} startedAt")
            finished = _parse_time(result.get("finishedAt"), label=f"{prefix} finishedAt")
            if started > finished:
                _block(blocks, f"{prefix}.time-order", "startedAt <= finishedAt", result)
                shape_ok = False
        except GateError as exc:
            _block(blocks, f"{prefix}.time-order", "valid ordered timestamps", str(exc))
            shape_ok = False
        execution = journey.get("execution") or {}
        shape_ok = _exact_keys(
            execution,
            {
                "evidenceKind",
                "configuration",
                "device",
                "os",
                "locale",
                "timezone",
                "appearance",
                "networkMode",
            },
            code=f"{prefix}.execution.shape",
            blocks=blocks,
        ) and shape_ok
        for field in ("configuration", "device", "os", "locale", "timezone", "appearance", "networkMode"):
            if not isinstance(execution.get(field), str) or not execution[field]:
                _block(blocks, f"{prefix}.execution.{field}", "non-empty string", execution.get(field))
                shape_ok = False
        evidence_kind = execution.get("evidenceKind")
        if evidence_kind not in _JOURNEY_EVIDENCE_KINDS:
            _block(blocks, f"{prefix}.evidence-kind", sorted(_JOURNEY_EVIDENCE_KINDS), evidence_kind)
        claim_ids = journey.get("claimIDs")
        expected_claims = sorted(
            claim["id"] for claim in spec["claims"] if ref["id"] in claim["journeyIDs"]
        )
        if not isinstance(claim_ids, list) or sorted(claim_ids) != expected_claims:
            _block(blocks, f"{prefix}.claims", expected_claims, claim_ids)
        artifacts_ok = _load_evidence_artifacts(
            journey, root=root, prefix=prefix, files=files, blocks=blocks
        )
        if (
            status == "pass"
            and fresh
            and artifacts_ok
            and shape_ok
            and evidence_kind in _JOURNEY_EVIDENCE_KINDS
            and isinstance(claim_ids, list)
        ):
            journey_evidence_by_id[ref["id"]] = evidence_kind
            for claim_id in claim_ids:
                if claim_id in evidence_by_claim:
                    evidence_by_claim[claim_id].append(f"journey:{ref['id']}:{evidence_kind}")
        journey_summaries.append({"id": ref["id"], "status": status, "evidenceKind": evidence_kind})

    demo_ref = spec["artifacts"]["demoAccess"]
    demo_load_failed = False
    try:
        demo = _load_optional_json(
            root,
            demo_ref["path"],
            label="demo access",
            bundle_rel="inputs/demo-access.json",
            files=files,
        )
    except GateError as exc:
        _block(blocks, "demo.invalid", "valid JSON", str(exc))
        demo = None
        demo_load_failed = True
    demo_ok = False
    if demo is None and not demo_load_failed:
        _block(blocks, "demo.missing", demo_ref["path"], "missing")
    elif demo is not None:
        demo_shape_ok = _exact_keys(
            demo,
            {
                "schema",
                "evidenceKind",
                "target",
                "execution",
                "account",
                "observedAt",
                "result",
                "artifacts",
            },
            code="demo.shape",
            blocks=blocks,
        )
        if demo.get("schema") != DEMO_SCHEMA:
            _block(blocks, "demo.schema", DEMO_SCHEMA, demo.get("schema"))
        demo_target = demo.get("target") or {}
        demo_shape_ok = _exact_keys(
            demo_target,
            {"bundleId", "marketingVersion", "buildNumber", "sourceCommit"},
            code="demo.target.shape",
            blocks=blocks,
        ) and demo_shape_ok
        _target_matches(target, demo_target, prefix="demo", blocks=blocks)
        evidence_kind = demo.get("evidenceKind")
        if evidence_kind not in _DEMO_EVIDENCE_KINDS:
            _block(blocks, "demo.evidence-kind", sorted(_DEMO_EVIDENCE_KINDS), evidence_kind)
        demo_execution = demo.get("execution") or {}
        demo_shape_ok = _exact_keys(
            demo_execution,
            {
                "configuration",
                "device",
                "os",
                "locale",
                "timezone",
                "networkMode",
                "fixtureDataUsed",
            },
            code="demo.execution.shape",
            blocks=blocks,
        ) and demo_shape_ok
        for field in ("configuration", "device", "os", "locale", "timezone", "networkMode"):
            if not isinstance(demo_execution.get(field), str) or not demo_execution[field]:
                _block(blocks, f"demo.execution.{field}", "non-empty string", demo_execution.get(field))
                demo_shape_ok = False
        if demo_execution.get("configuration") != "Release":
            _block(blocks, "demo.execution.configuration", "Release", demo_execution.get("configuration"))
            demo_shape_ok = False
        if demo_execution.get("networkMode") != "live":
            _block(blocks, "demo.execution.network-mode", "live", demo_execution.get("networkMode"))
            demo_shape_ok = False
        if demo_execution.get("fixtureDataUsed") is not False:
            _block(blocks, "demo.fixture-data", False, demo_execution.get("fixtureDataUsed"))
            demo_shape_ok = False
        demo_account = demo.get("account") or {}
        demo_shape_ok = _exact_keys(
            demo_account,
            {"provenance", "accountRef", "accountIdentitySHA256", "entitlementSource"},
            code="demo.account.shape",
            blocks=blocks,
        ) and demo_shape_ok
        live_demo_account = (((live_body.get("reviewDetail") or {}).get("fields") or {}).get("demoAccountName") or {})
        expected_account = {
            "provenance": "live-account",
            "accountRef": live_demo_account.get("ref"),
            "accountIdentitySHA256": live_demo_account.get("identitySHA256"),
            "entitlementSource": "live-backend",
        }
        if live_demo_account.get("identitySHA256") != target["demoAccountIdentitySHA256"]:
            _block(blocks, "demo.account.target-binding", target["demoAccountIdentitySHA256"], live_demo_account.get("identitySHA256"))
            demo_shape_ok = False
        if demo_account != expected_account:
            _block(blocks, "demo.account.live-binding", expected_account, demo_account)
            demo_shape_ok = False
        demo_result = demo.get("result") or {}
        demo_shape_ok = _exact_keys(
            demo_result,
            {"status", "login", "entitlements", "testsExecuted"},
            code="demo.result.shape",
            blocks=blocks,
        ) and demo_shape_ok
        if demo_result.get("status") != "pass" or demo_result.get("login") != "pass":
            _block(blocks, "demo.status", {"status": "pass", "login": "pass"}, demo_result)
        if "pro" not in (demo_result.get("entitlements") or []):
            _block(blocks, "demo.entitlement", "pro", demo_result.get("entitlements"))
        if not isinstance(demo_result.get("testsExecuted"), int) or demo_result["testsExecuted"] <= 0:
            _block(blocks, "demo.tests", ">0", demo_result.get("testsExecuted"))
            demo_shape_ok = False
        fresh, reason = _fresh(
            demo.get("observedAt"), observed_at=observed, max_age_hours=demo_ref["maxAgeHours"], label="demo observedAt"
        )
        if not fresh:
            _block(blocks, "demo.freshness", "fresh", reason)
        demo_artifacts_ok = _load_evidence_artifacts(
            demo, root=root, prefix="demo", files=files, blocks=blocks
        )
        demo_ok = (
            demo.get("schema") == DEMO_SCHEMA
            and evidence_kind in _DEMO_EVIDENCE_KINDS
            and demo_result.get("status") == "pass"
            and demo_result.get("login") == "pass"
            and "pro" in (demo_result.get("entitlements") or [])
            and fresh
            and demo_artifacts_ok
            and demo_shape_ok
        )
        if demo_ok:
            for claim in spec["claims"]:
                if evidence_kind in claim["acceptedEvidenceKinds"]:
                    evidence_by_claim[claim["id"]].append(f"demo:{evidence_kind}")

    url_ref = spec["artifacts"]["urlChecks"]
    urls_load_failed = False
    try:
        urls = _load_optional_json(
            root,
            url_ref["path"],
            label="URL checks",
            bundle_rel="inputs/url-checks.json",
            files=files,
        )
    except GateError as exc:
        _block(blocks, "urls.invalid", "valid JSON", str(exc))
        urls = None
        urls_load_failed = True
    if urls is None and not urls_load_failed:
        _block(blocks, "urls.missing", url_ref["path"], "missing")
    elif urls is not None:
        urls_shape_ok = _exact_keys(
            urls,
            {"schema", "observedAt", "results"},
            code="urls.shape",
            blocks=blocks,
        )
        if urls.get("schema") != URL_SCHEMA:
            _block(blocks, "urls.schema", URL_SCHEMA, urls.get("schema"))
        fresh, reason = _fresh(
            urls.get("observedAt"), observed_at=observed, max_age_hours=url_ref["maxAgeHours"], label="URL checks observedAt"
        )
        if not fresh:
            _block(blocks, "urls.freshness", "fresh", reason)
        results = urls.get("results") if isinstance(urls.get("results"), list) else []
        for index, item in enumerate(results):
            urls_shape_ok = _exact_keys(
                item,
                {"id", "url", "status", "httpStatus", "finalUrl", "contentSHA256"},
                code=f"urls.result.{index}.shape",
                blocks=blocks,
            ) and urls_shape_ok
        by_id = {item.get("id"): item for item in results if isinstance(item, dict) and isinstance(item.get("id"), str)}
        if len(by_id) != len(results):
            _block(blocks, "urls.closed", "unique result per required URL", results)
        required_ids = {item["id"] for item in spec["requiredLiveURLs"]}
        if set(by_id) != required_ids:
            _block(blocks, "urls.closed", sorted(required_ids), sorted(by_id))
        for required in spec["requiredLiveURLs"]:
            result = by_id.get(required["id"])
            live_metadata_fields = ((live_body.get("metadata") or {}).get("fields") or {})
            metadata_field = {"marketing": "marketingUrl", "support": "supportUrl"}.get(
                required["id"]
            )
            if metadata_field and live_metadata_fields.get(metadata_field) != required["url"]:
                _block(
                    blocks,
                    f"url.{required['id']}.live-metadata",
                    required["url"],
                    live_metadata_fields.get(metadata_field),
                )
            if required["id"] == "terms" and required["url"] not in str(
                live_metadata_fields.get("description") or ""
            ):
                _block(
                    blocks,
                    "url.terms.live-metadata",
                    f"description contains {required['url']}",
                    "missing",
                )
            if not isinstance(result, dict):
                _block(blocks, f"url.{required['id']}.missing", required["url"], "missing")
                continue
            ok = (
                result.get("url") == required["url"]
                and result.get("finalUrl") == required["url"]
                and result.get("status") == "pass"
                and isinstance(result.get("httpStatus"), int)
                and 200 <= result["httpStatus"] < 400
                and isinstance(result.get("contentSHA256"), str)
                and bool(_SHA_RE.fullmatch(result["contentSHA256"]))
                and fresh
                and urls_shape_ok
            )
            if not ok:
                _block(blocks, f"url.{required['id']}.status", "fresh exact HTTPS 2xx/3xx", result)
            else:
                for claim_id in required["claimIDs"]:
                    evidence_by_claim[claim_id].append(f"url:{required['id']}:live-url")

    appearance_ref = spec["artifacts"]["appearanceProof"]
    appearance_path = _relative_path(root, appearance_ref["path"], label="appearanceProof")
    if appearance_ref["sha256"] == "pending":
        _block(blocks, "appearance.sha256.pending", "pinned SHA-256", "pending")
    elif appearance_path.is_file():
        actual_appearance_sha = _sha(appearance_path.read_bytes())
        if actual_appearance_sha != appearance_ref["sha256"]:
            _block(
                blocks,
                "appearance.sha256",
                appearance_ref["sha256"],
                actual_appearance_sha,
            )
    try:
        appearance = _load_optional_json(
            root,
            appearance_ref["path"],
            label="appearance proof",
            bundle_rel="inputs/appearance-proof.json",
            files=files,
        )
    except GateError as exc:
        _block(blocks, "appearance.invalid", "valid JSON", str(exc))
        appearance = None
        appearance_load_failed = True
    else:
        appearance_load_failed = False
    if appearance is None and not appearance_load_failed:
        _block(blocks, "appearance.missing", appearance_ref["path"], "missing")
    elif appearance is not None:
        appearance_validation = validate_appearance_proof(
            appearance,
            source_commit=target["sourceCommit"],
            dataset_id=target["datasetID"],
            dataset_sha256=target["datasetSHA256"],
            fixed_clock=((desired.get("capture") or {}).get("fixedClock")) if desired else None,
        )
        for issue in appearance_validation["issues"]:
            _block(blocks, issue["code"], issue["expected"], issue["actual"])
        fresh, reason = _fresh(
            appearance.get("observedAt"),
            observed_at=observed,
            max_age_hours=appearance_ref["maxAgeHours"],
            label="appearance proof observedAt",
        )
        if not fresh:
            _block(blocks, "appearance.freshness", "fresh", reason)

    pre_root = _pre_root(files)
    attestation_summaries: dict[str, Any] = {}
    for actor, rel in spec["artifacts"]["attestations"].items():
        try:
            attestation = _load_optional_json(
                root,
                rel,
                label=f"{actor} attestation",
                bundle_rel=f"inputs/attestations/{actor}.json",
                files=files,
            )
        except GateError as exc:
            _block(blocks, f"attestation.{actor}.invalid", "valid JSON", str(exc))
            continue
        if attestation is None:
            _block(blocks, f"attestation.{actor}.missing", rel, "missing")
            continue
        _exact_keys(
            attestation,
            {
                "schema",
                "actorType",
                "subject",
                "attestationKind",
                "claimIDs",
                "status",
                "preAttestationRootSHA256",
                "observedAt",
                "expiresAt",
            },
            code=f"attestation.{actor}.shape",
            blocks=blocks,
        )
        if attestation.get("schema") != ATTESTATION_SCHEMA or attestation.get("actorType") != actor:
            _block(blocks, f"attestation.{actor}.schema", {"schema": ATTESTATION_SCHEMA, "actorType": actor}, {"schema": attestation.get("schema"), "actorType": attestation.get("actorType")})
        if attestation.get("status") != "attested":
            _block(blocks, f"attestation.{actor}.status", "attested", attestation.get("status"))
        if attestation.get("attestationKind") != "semantic":
            _block(
                blocks,
                f"attestation.{actor}.kind",
                "semantic",
                attestation.get("attestationKind"),
            )
        expected_claim_ids = [claim["id"] for claim in spec["claims"]]
        if attestation.get("claimIDs") != expected_claim_ids:
            _block(
                blocks,
                f"attestation.{actor}.claims",
                expected_claim_ids,
                attestation.get("claimIDs"),
            )
        if not isinstance(attestation.get("subject"), str) or not attestation["subject"]:
            _block(blocks, f"attestation.{actor}.subject", "non-empty string", attestation.get("subject"))
        if attestation.get("preAttestationRootSHA256") != pre_root:
            _block(blocks, f"attestation.{actor}.root", pre_root, attestation.get("preAttestationRootSHA256"))
        fresh, reason = _fresh(
            attestation.get("observedAt"),
            observed_at=observed,
            max_age_hours=spec["freshness"]["attestationMaxAgeHours"],
            label=f"{actor} attestation observedAt",
        )
        try:
            expires = _parse_time(attestation.get("expiresAt"), label=f"{actor} attestation expiresAt")
            unexpired = expires >= observed
        except GateError as exc:
            unexpired = False
            reason = str(exc)
        if not fresh or not unexpired:
            _block(blocks, f"attestation.{actor}.freshness", "fresh and unexpired", reason or attestation.get("expiresAt"))
        attestation_summaries[actor] = {
            "subject": attestation.get("subject"),
            "attestationKind": attestation.get("attestationKind"),
            "claimIDs": attestation.get("claimIDs"),
            "status": attestation.get("status"),
            "observedAt": attestation.get("observedAt"),
            "expiresAt": attestation.get("expiresAt"),
        }

    claims_report: list[dict[str, Any]] = []
    live_names = {
        item.get("fileName")
        for item in (((live_body.get("screenshots") or {}).get("items")) or [])
        if isinstance(item, dict) and isinstance(item.get("fileName"), str)
    }
    desired_names = {
        Path(item.get("file", "")).name
        for item in (desired.get("outputs") or [])
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }
    required_url_ids = {item["id"] for item in spec["requiredLiveURLs"]}
    for claim in spec["claims"]:
        accepted = []
        for evidence in evidence_by_claim[claim["id"]]:
            kind = evidence.rsplit(":", 1)[-1]
            if kind in claim["acceptedEvidenceKinds"]:
                accepted.append(evidence)
        missing_journeys = [
            journey_id
            for journey_id in claim["journeyIDs"]
            if journey_evidence_by_id.get(journey_id) not in claim["acceptedEvidenceKinds"]
        ]
        if missing_journeys:
            _block(
                blocks,
                f"claim.{claim['id']}.journeys",
                claim["journeyIDs"],
                sorted(set(claim["journeyIDs"]) - set(missing_journeys)),
            )
        if not accepted or missing_journeys:
            _block(blocks, f"claim.{claim['id']}.evidence", claim["acceptedEvidenceKinds"], evidence_by_claim[claim["id"]])
        surface = claim["surface"]
        if surface["kind"] == "metadata":
            value = ((live_body.get("metadata") or {}).get("fields") or {}).get(surface["ref"])
            if not isinstance(value, str) or not value:
                _block(blocks, f"claim.{claim['id']}.surface", f"live metadata {surface['ref']}", value)
        elif surface["kind"] == "review-notes":
            value = (((live_body.get("reviewDetail") or {}).get("fields") or {}).get(surface["ref"]))
            if not isinstance(value, dict) or value.get("present") is not True:
                _block(blocks, f"claim.{claim['id']}.surface", f"present review field {surface['ref']}", value)
        elif surface["kind"] == "screenshot-copy":
            if surface["ref"] not in live_names or surface["ref"] not in desired_names:
                _block(
                    blocks,
                    f"claim.{claim['id']}.surface",
                    {"desired": surface["ref"], "live": surface["ref"]},
                    {"desired": surface["ref"] in desired_names, "live": surface["ref"] in live_names},
                )
        elif surface["kind"] == "website" and surface["ref"] not in required_url_ids:
            _block(blocks, f"claim.{claim['id']}.surface", sorted(required_url_ids), surface["ref"])
        claims_report.append(
            {
                "id": claim["id"],
                "surface": f"{claim['surface']['kind']}:{claim['surface']['ref']}",
                "statement": claim["statement"],
                "feature": claim["feature"],
                "entitlement": claim["entitlement"],
                "evidence": accepted,
            }
        )

    metadata = (live_body.get("metadata") or {}).get("fields") or {}
    raw_review = (live_body.get("reviewDetail") or {})
    safe_review_fields: dict[str, Any] = {}
    for field, value in (raw_review.get("fields") or {}).items():
        allowed_keys = {"present", "fingerprint", "ref"}
        if field == "demoAccountName":
            allowed_keys.add("identitySHA256")
        if not isinstance(value, dict) or not set(value).issubset(allowed_keys):
            _block(blocks, f"live-mirror.review-detail.{field}.secret-shape", sorted(allowed_keys), sorted(value) if isinstance(value, dict) else type(value).__name__)
            continue
        safe_review_fields[field] = {
            key: value.get(key)
            for key in ("present", "fingerprint", "identitySHA256", "ref")
            if key in allowed_keys
        }
    screenshots = sorted(
        [item for item in ((live_body.get("screenshots") or {}).get("items") or []) if isinstance(item, dict)],
        key=lambda item: item.get("order") if isinstance(item.get("order"), int) else 10**9,
    )
    reviewer_screenshots = [
        {
            "order": item.get("order"),
            "fileName": item.get("fileName"),
            "bundlePath": item.get("bundlePath"),
            "sha256": (item.get("liveBytes") or {}).get("sha256"),
            "byteSize": (item.get("liveBytes") or {}).get("byteSize"),
            "width": (item.get("liveBytes") or {}).get("width"),
            "height": (item.get("liveBytes") or {}).get("height"),
        }
        for item in screenshots
    ]
    document = {
        "schema": REPORT_SCHEMA,
        "observationMode": observation_mode,
        "observedAt": observed_at,
        "verdict": {"status": "pass" if not blocks else "block", "blockCount": len(blocks)},
        "target": target,
        "roots": {
            "specSHA256": _sha(spec_bytes),
            "desiredManifestSHA256": desired_hash,
            "liveMirrorRootSHA256": live_root,
        },
        "preAttestationRootSHA256": pre_root,
        "blocks": blocks,
        "journeys": journey_summaries,
        "attestations": attestation_summaries,
        "claims": claims_report,
        "reviewerView": {
            "version": live_body.get("version") or {},
            "build": live_body.get("build") or {},
            "submission": live_body.get("submission") or {},
            "metadata": metadata,
            "reviewDetail": {
                "id": raw_review.get("id"),
                "demoAccountRequired": raw_review.get("demoAccountRequired"),
                "fields": safe_review_fields,
            },
            "screenshots": reviewer_screenshots,
        },
    }
    return GateResult(document=document, html=_render_html(document), files=files)


def write_bundle(result: GateResult, destination: Path) -> None:
    if destination.exists():
        raise GateError(f"reviewer bundle already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=str(destination.parent)))
    try:
        payloads = dict(result.files)
        payloads["report.json"] = _canonical(result.document)
        payloads["report.html"] = result.html.encode("utf-8")
        entries: list[dict[str, Any]] = []
        for rel, payload in sorted(payloads.items()):
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            entries.append({"path": rel, "byteSize": len(payload), "sha256": _sha(payload)})
        (staging / "manifest.json").write_bytes(_canonical({"schema": BUNDLE_SCHEMA, "files": entries}))
        os.replace(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_bundle(path: Path) -> dict[str, Any]:
    manifest, _ = _read_json(path / "manifest.json", label="reviewer bundle manifest")
    if manifest.get("schema") != BUNDLE_SCHEMA or not isinstance(manifest.get("files"), list):
        raise GateError("reviewer bundle closure schema/files are invalid")
    expected: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "byteSize", "sha256"}:
            raise GateError("reviewer bundle closure entry is invalid")
        if item.get("path") in expected:
            raise GateError(f"reviewer bundle closure has duplicate path: {item.get('path')}")
        source = _relative_path(path, item.get("path"), label="reviewer bundle file")
        payload = source.read_bytes() if source.is_file() else b""
        if len(payload) != item.get("byteSize") or _sha(payload) != item.get("sha256"):
            raise GateError(f"reviewer bundle closure hash/size mismatch: {item.get('path')}")
        expected.add(item["path"])
    actual = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.relative_to(path).as_posix() != "manifest.json"
    }
    if expected != actual:
        raise GateError(
            f"reviewer bundle closure is not exact: missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    report, _ = _read_json(path / "report.json", label="reviewer bundle report")
    if report.get("schema") != REPORT_SCHEMA:
        raise GateError("reviewer bundle report schema is invalid")
    verdict = report.get("verdict") or {}
    if (
        verdict.get("status") not in {"pass", "block"}
        or not isinstance(verdict.get("blockCount"), int)
        or verdict["blockCount"] != len(report.get("blocks") or [])
        or (verdict["status"] == "pass") != (verdict["blockCount"] == 0)
    ):
        raise GateError("reviewer bundle report verdict/blocks drift")
    return {
        "schema": BUNDLE_SCHEMA,
        "status": "pass",
        "fileCount": len(expected),
        "gateVerdict": verdict["status"],
        "submitReady": verdict["status"] == "pass",
    }


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    sub = top.add_subparsers(dest="command", required=True)
    for name in ("dry-run", "verify"):
        command = sub.add_parser(name, help=f"{name} the closed-world reviewer evidence gate")
        if name == "verify":
            command.add_argument("--bundle", type=Path, help="verify an existing reviewer bundle closure")
        command.add_argument("--spec", type=Path, help=f"checked-in {SPEC_SCHEMA} submission spec")
        command.add_argument("--workspace-root", type=Path, default=Path("."))
        command.add_argument("--observed-at", help="timezone-aware evaluation time (default current UTC)")
        command.add_argument(
            "--observation-mode",
            choices=("offline", "online"),
            default="offline",
            help="offline always BLOCK; online requires freshly captured live evidence",
        )
        if name == "verify":
            command.add_argument("--bundle-dir", type=Path, help="new local reviewer bundle destination")
            command.add_argument("--commit", action="store_true", help="atomically write the local bundle; never writes ASC")
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "verify" and args.bundle:
            if args.spec or args.commit or args.bundle_dir:
                raise GateError("--bundle cannot be combined with --spec/--commit/--bundle-dir")
            verification = verify_bundle(args.bundle)
            print(_canonical(verification).decode(), end="")
            return 0 if verification["submitReady"] else 2
        if not args.spec:
            raise GateError("--spec is required for gate evaluation")
        if args.command == "dry-run" and getattr(args, "commit", False):
            raise GateError("dry-run never writes")
        if args.command == "verify" and args.commit and not args.bundle_dir:
            raise GateError("--commit requires --bundle-dir")
        result = evaluate_gate(
            spec_path=args.spec,
            workspace_root=args.workspace_root,
            observed_at=args.observed_at or datetime.now(timezone.utc).isoformat(),
            observation_mode=args.observation_mode,
        )
        if args.command == "verify" and args.commit:
            write_bundle(result, args.bundle_dir)
        output = dict(result.document)
        output["bundle"] = {
            "status": "written" if args.command == "verify" and args.commit else "dry-run",
            "path": str(args.bundle_dir) if args.command == "verify" and args.bundle_dir else None,
        }
        print(_canonical(output).decode(), end="")
        return 0 if result.document["verdict"]["status"] == "pass" else 2
    except GateError as exc:
        output = {
            "schema": REPORT_SCHEMA,
            "verdict": {"status": "block", "blockCount": 1},
            "blocks": [{"code": "gate.error", "expected": "valid closed-world evidence", "actual": str(exc)}],
        }
        print(_canonical(output).decode(), end="")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""Read-only App Store reviewer mirror and desired↔live coherence audit.

The command only performs ASC GETs and Apple CDN image GETs. It never submits,
withdraws, edits metadata, or uploads screenshots. stdout is stable JSON and
review-detail secrets are represented only by presence, keyed fingerprint, and
an ASC object reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from asc_text_bundle import (  # noqa: E402
    ASCConfig,
    ASCReadClient,
    DEFAULT_APP_ID,
    DEFAULT_ISSUER_ID,
    DEFAULT_KEY_DIR,
    DEFAULT_KEY_ID,
)


AUDIT_SCHEMA = "kg.app_review.asc_audit.v1"
BUNDLE_SCHEMA = "kg.app_review.asc_mirror_bundle.v1"
DESIRED_SCHEMA = "kg.app_review.manual_asc_bundle.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_REQUIRED_METADATA_FIELDS = ("description", "keywords", "promotionalText", "supportUrl")
_METADATA_FIELDS = (
    "description",
    "keywords",
    "marketingUrl",
    "promotionalText",
    "supportUrl",
    "whatsNew",
)
_REVIEW_SECRET_FIELDS = (
    "contactFirstName",
    "contactLastName",
    "contactPhone",
    "contactEmail",
    "demoAccountName",
    "demoAccountPassword",
    "notes",
)
class MirrorError(RuntimeError):
    """Required desired/live evidence could not be asserted safely."""


class ReadClient(Protocol):
    def get_json(self, path: str) -> dict[str, Any]: ...

    def get_asset_bytes(self, url: str) -> bytes: ...

    def fingerprint_secret(self, context: str, value: str) -> str: ...


@dataclass(frozen=True)
class AuditResult:
    document: dict[str, Any]
    image_bytes: dict[str, bytes]
    desired_files: dict[str, bytes]


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_reviewer_identity_sha256(value: str) -> str:
    """Match iOS: trim Unicode whitespace, NFC, en_US_POSIX lowercase, UTF-8 SHA256."""
    normalized = unicodedata.normalize("NFC", value.strip()).lower()
    return _sha256(normalized.encode("utf-8"))


def _md5(payload: bytes) -> str:
    # Apple exposes sourceFileChecksum as MD5; SHA-256 remains the bundle authority.
    return hashlib.md5(payload).hexdigest()


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise MirrorError("reviewer screenshot bytes are not a PNG with an IHDR")
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    if width <= 0 or height <= 0:
        raise MirrorError("reviewer screenshot PNG dimensions are invalid")
    return width, height


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MirrorError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MirrorError(f"{label} must be a JSON object")
    return value


def _exact_mapping(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise MirrorError(f"{label} must contain exact keys {sorted(keys)}; got {actual}")
    return value


def _bundle_payload(bundle: Path, rel: Any, *, label: str) -> tuple[str, bytes]:
    if not isinstance(rel, str) or not rel:
        raise MirrorError(f"{label} path is invalid")
    parts = Path(rel).parts
    if Path(rel).is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise MirrorError(f"{label} path is unsafe: {rel}")
    path = bundle.joinpath(*parts)
    if not path.is_file():
        raise MirrorError(f"{label} is missing: {path}")
    return rel, path.read_bytes()


def _validate_observed_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MirrorError("observed-at must be a timezone-aware ISO8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MirrorError("observed-at must include a timezone")


def _desired(bundle: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest_path = bundle / "manifest.json"
    manifest_bytes = manifest_path.read_bytes() if manifest_path.is_file() else b""
    if not manifest_bytes:
        raise MirrorError(f"desired bundle manifest is missing: {manifest_path}")
    manifest = _read_json(manifest_path, label="desired manifest")
    if manifest.get("schema") != DESIRED_SCHEMA:
        raise MirrorError(f"desired manifest schema must be {DESIRED_SCHEMA}")
    _exact_mapping(
        manifest,
        {"schema", "verdict", "build", "source", "dataset", "fixedClock", "locale", "displayType", "outputs"},
        label="desired manifest",
    )
    verdict = _exact_mapping(manifest.get("verdict"), {"status"}, label="desired verdict")
    if verdict.get("status") != "pass":
        raise MirrorError("desired reviewer evidence verdict must be pass")
    build = _exact_mapping(
        manifest.get("build"), {"marketingVersion", "buildNumber", "project"}, label="desired build"
    )
    project = _exact_mapping(build.get("project"), {"path", "sha256"}, label="desired build.project")
    source = _exact_mapping(manifest.get("source"), {"commit"}, label="desired source")
    dataset = _exact_mapping(
        manifest.get("dataset"), {"schema", "id", "path", "sha256"}, label="desired dataset"
    )
    marketing = build.get("marketingVersion")
    number = build.get("buildNumber")
    if not isinstance(marketing, str) or not marketing or not isinstance(number, str) or not number:
        raise MirrorError("desired manifest build tuple is incomplete")
    if not isinstance(source.get("commit"), str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source["commit"]):
        raise MirrorError("desired source commit is invalid")
    if dataset.get("schema") != "kg.fixture.dataset.v2" or not isinstance(dataset.get("id"), str) or not dataset["id"]:
        raise MirrorError("desired dataset identity is invalid")
    fixed_clock = manifest.get("fixedClock")
    if not isinstance(fixed_clock, str):
        raise MirrorError("desired fixedClock is invalid")
    _validate_observed_at(fixed_clock)
    locale = manifest.get("locale")
    display_type = manifest.get("displayType")
    outputs = manifest.get("outputs")
    if not isinstance(locale, str) or not locale:
        raise MirrorError("desired manifest locale is missing")
    if not isinstance(display_type, str) or not display_type:
        raise MirrorError("desired manifest displayType is missing")
    if not isinstance(outputs, list) or not outputs:
        raise MirrorError("desired outputs must be a non-empty list")

    desired_files: dict[str, bytes] = {"manifest.json": manifest_bytes}
    expected_paths: set[str] = set()
    for label, item in (("project", project), ("dataset", dataset)):
        rel, payload = _bundle_payload(bundle, item.get("path"), label=f"desired {label}")
        if not _SHA256_RE.fullmatch(str(item.get("sha256") or "")) or _sha256(payload) != item["sha256"]:
            raise MirrorError(f"desired {label} hash mismatch: {rel}")
        expected_paths.add(rel)
        desired_files[rel] = payload

    normalized_outputs: list[dict[str, Any]] = []
    names: set[str] = set()
    output_ids: set[str] = set()
    for index, output in enumerate(outputs):
        output = _exact_mapping(
            output, {"id", "appearance", "file", "byteSize", "sha256"}, label=f"desired output {index}"
        )
        output_id = output.get("id")
        if not isinstance(output_id, str) or not output_id or output_id in output_ids:
            raise MirrorError(f"desired output id is invalid or duplicated: {output_id}")
        output_ids.add(output_id)
        if output.get("appearance") not in {"light", "dark"}:
            raise MirrorError(f"desired output appearance is invalid: {output.get('appearance')}")
        rel = output.get("file")
        rel, payload = _bundle_payload(bundle, rel, label=f"desired output {index}")
        if len(Path(rel).parts) != 2 or Path(rel).parts[0] != "outputs":
            raise MirrorError(f"desired output path mismatch at index {index}: {rel}")
        name = Path(rel).name
        if not _SAFE_NAME_RE.fullmatch(name) or not name.lower().endswith(".png") or name in names:
            raise MirrorError(f"desired output filename is unsafe or duplicated: {name}")
        names.add(name)
        digest = _sha256(payload)
        if digest != output.get("sha256") or len(payload) != output.get("byteSize"):
            raise MirrorError(f"desired output checksum/size drift: {rel}")
        width, height = _png_dimensions(payload)
        expected_paths.add(rel)
        desired_files[rel] = payload
        normalized_outputs.append(
            {
                "order": index + 1,
                "shotID": output_id,
                "fileName": name,
                "sha256": digest,
                "sourceMD5": _md5(payload),
                "byteSize": len(payload),
                "width": width,
                "height": height,
            }
        )
    actual_paths = {
        item.relative_to(bundle).as_posix()
        for item in bundle.rglob("*")
        if item.is_file() and item != manifest_path
    }
    if actual_paths != expected_paths:
        raise MirrorError(
            f"desired evidence closure is not exact: missing={sorted(expected_paths - actual_paths)} "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    return (
        {
            "schema": DESIRED_SCHEMA,
            "manifestSHA256": _sha256(manifest_bytes),
            "build": {"marketingVersion": marketing, "buildNumber": number},
            "locale": locale,
            "displayType": display_type,
            "outputs": normalized_outputs,
        },
        desired_files,
    )


def _api(client: ReadClient, path: str, *, label: str) -> dict[str, Any]:
    payload = client.get_json(path)
    if not isinstance(payload, dict):
        raise MirrorError(f"ASC {label} returned an unknown response shape")
    if "_httpError" in payload:
        # Deliberately do not include _detail: Apple errors can echo reviewer fields.
        raise MirrorError(f"ASC {label} failed: HTTP {payload.get('_httpError')}")
    return payload


def _included(payload: dict[str, Any], type_name: str) -> list[dict[str, Any]]:
    return [
        item
        for item in (payload.get("included") or [])
        if isinstance(item, dict) and item.get("type") == type_name
    ]


def _relationship_id(resource: dict[str, Any], name: str) -> str | None:
    data = ((((resource.get("relationships") or {}).get(name) or {}).get("data")))
    return data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), str) else None


def _relationship_ids(resource: dict[str, Any], name: str) -> list[str]:
    data = ((((resource.get("relationships") or {}).get(name) or {}).get("data")))
    if not isinstance(data, list):
        return []
    return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]


def _fingerprint_field(
    client: ReadClient,
    review_id: str | None,
    field: str,
    value: Any,
) -> dict[str, Any]:
    present = value is not None and value != ""
    context = f"appStoreReviewDetails/{review_id or 'missing'}#{field}"
    document = {
        "present": present,
        "fingerprint": client.fingerprint_secret(context, str(value)) if present else None,
        "ref": f"asc://appStoreReviewDetails/{review_id or 'missing'}#{field}",
    }
    if field == "demoAccountName":
        document["identitySHA256"] = normalized_reviewer_identity_sha256(str(value)) if present else None
    return document


def _resolve_version_id(
    client: ReadClient, app_id: str, desired_version: str
) -> str:
    encoded = quote(desired_version, safe="")
    payload = _api(
        client,
        f"/v1/apps/{app_id}/appStoreVersions?filter%5Bplatform%5D=IOS&filter%5BversionString%5D={encoded}&limit=50",
        label="appStoreVersions",
    )
    matches = [
        item
        for item in (payload.get("data") or [])
        if isinstance(item, dict)
        and (item.get("attributes") or {}).get("platform") == "IOS"
        and (item.get("attributes") or {}).get("versionString") == desired_version
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise MirrorError(
            f"ASC version resolution is not unique for IOS {desired_version}: count={len(matches)}"
        )
    return matches[0]["id"]


def _submission(
    client: ReadClient, app_id: str, version_id: str
) -> dict[str, Any] | None:
    payload = _api(
        client,
        f"/v1/apps/{app_id}/reviewSubmissions?limit=50",
        label="reviewSubmissions",
    )
    matches: list[dict[str, Any]] = []
    active_submissions = [
        item
        for item in (payload.get("data") or [])
        if isinstance(item, dict)
        and (item.get("attributes") or {}).get("state")
        in {"WAITING_FOR_REVIEW", "IN_REVIEW"}
    ]
    for submission in active_submissions:
        if not isinstance(submission, dict) or not isinstance(submission.get("id"), str):
            continue
        sid = submission["id"]
        items_payload = _api(
            client,
            f"/v1/reviewSubmissions/{sid}/items?include=appStoreVersion&limit=50",
            label=f"reviewSubmissionItems/{sid}",
        )
        for item in items_payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            related_version = _relationship_id(item, "appStoreVersion")
            if related_version == version_id:
                matches.append(
                    {
                        "id": sid,
                        "state": (submission.get("attributes") or {}).get("state"),
                        "platform": (submission.get("attributes") or {}).get("platform"),
                        "submittedDate": (submission.get("attributes") or {}).get("submittedDate"),
                        "item": {
                            "id": item.get("id"),
                            "state": (item.get("attributes") or {}).get("state"),
                            "versionID": related_version,
                        },
                    }
                )
    return matches[0] if len(matches) == 1 else {"matchCount": len(matches)}


def _asset_url(template: Any, width: Any, height: Any) -> str | None:
    if not isinstance(template, str) or not isinstance(width, int) or not isinstance(height, int):
        return None
    url = template.replace("{w}", str(width)).replace("{h}", str(height)).replace("{f}", "png")
    return url if "{" not in url and "}" not in url else None


def _live_snapshot(
    client: ReadClient,
    *,
    app_id: str,
    version_id: str,
    locale: str,
    display_type: str,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    version_payload = _api(
        client,
        f"/v1/appStoreVersions/{version_id}?include=build,appStoreVersionLocalizations,appStoreReviewDetail",
        label="appStoreVersion",
    )
    version = version_payload.get("data")
    if not isinstance(version, dict) or version.get("id") != version_id:
        raise MirrorError("ASC appStoreVersion identity mismatch")
    version_attrs = version.get("attributes") or {}
    build_relationship_id = _relationship_id(version, "build")
    builds = [item for item in _included(version_payload, "builds") if item.get("id") == build_relationship_id]
    build = builds[0] if len(builds) == 1 else None
    build_attrs = (build or {}).get("attributes") or {}

    loc_relationship_ids = set(_relationship_ids(version, "appStoreVersionLocalizations"))
    locs = [
        item
        for item in _included(version_payload, "appStoreVersionLocalizations")
        if item.get("id") in loc_relationship_ids and (item.get("attributes") or {}).get("locale") == locale
    ]
    loc = locs[0] if len(locs) == 1 else None
    loc_attrs = (loc or {}).get("attributes") or {}
    loc_id = loc.get("id") if isinstance(loc, dict) else None

    review_relationship_id = _relationship_id(version, "appStoreReviewDetail")
    reviews = [
        item
        for item in _included(version_payload, "appStoreReviewDetails")
        if item.get("id") == review_relationship_id
    ]
    review = reviews[0] if len(reviews) == 1 else None
    review_attrs = (review or {}).get("attributes") or {}
    review_id = review.get("id") if isinstance(review, dict) else None

    images: dict[str, bytes] = {}
    screenshot_items: list[dict[str, Any]] = []
    set_id: str | None = None
    set_count = 0
    relationship_count = 0
    relationship_total: int | None = None
    if isinstance(loc_id, str):
        screenshot_payload = _api(
            client,
            f"/v1/appStoreVersionLocalizations/{loc_id}/appScreenshotSets?include=appScreenshots&limit=50",
            label="appScreenshotSets",
        )
        sets = [
            item
            for item in (screenshot_payload.get("data") or [])
            if isinstance(item, dict)
            and (item.get("attributes") or {}).get("screenshotDisplayType") == display_type
        ]
        set_count = len(sets)
        if len(sets) == 1:
            target_set = sets[0]
            set_id = target_set.get("id") if isinstance(target_set.get("id"), str) else None
            relationship = ((target_set.get("relationships") or {}).get("appScreenshots") or {})
            relationship_ids = _relationship_ids(target_set, "appScreenshots")
            relationship_count = len(relationship_ids)
            paging_total = (((relationship.get("meta") or {}).get("paging") or {}).get("total"))
            relationship_total = paging_total if isinstance(paging_total, int) else None
            shot_by_id = {
                item.get("id"): item
                for item in _included(screenshot_payload, "appScreenshots")
                if isinstance(item.get("id"), str)
            }
            for index, shot_id in enumerate(relationship_ids, start=1):
                shot = shot_by_id.get(shot_id)
                attrs = (shot or {}).get("attributes") or {}
                asset = attrs.get("imageAsset") or {}
                file_name = attrs.get("fileName")
                width = asset.get("width")
                height = asset.get("height")
                state = ((attrs.get("assetDeliveryState") or {}).get("state"))
                source_checksum = attrs.get("sourceFileChecksum")
                url = _asset_url(asset.get("templateUrl"), width, height)
                live_bytes: dict[str, Any] = {"status": "unknown", "sha256": None, "byteSize": None}
                bundle_path: str | None = None
                if isinstance(file_name, str) and _SAFE_NAME_RE.fullmatch(file_name) and url:
                    try:
                        payload = client.get_asset_bytes(url)
                        fetched_width, fetched_height = _png_dimensions(payload)
                    except Exception:
                        payload = b""
                    if payload:
                        bundle_path = f"live/images/{index:02d}_{file_name}"
                        images[bundle_path] = payload
                        live_bytes = {
                            "status": "verified",
                            "sha256": _sha256(payload),
                            "byteSize": len(payload),
                            "width": fetched_width,
                            "height": fetched_height,
                        }
                screenshot_items.append(
                    {
                        "order": index,
                        "id": shot_id,
                        "fileName": file_name,
                        "state": state,
                        "width": width,
                        "height": height,
                        "sourceFileChecksum": source_checksum,
                        "ref": f"asc://appScreenshots/{shot_id}",
                        "bundlePath": bundle_path,
                        "liveBytes": live_bytes,
                    }
                )

    return (
        {
            "observedAt": observed_at,
            "appID": app_id,
            "version": {
                "id": version_id,
                "versionString": version_attrs.get("versionString"),
                "platform": version_attrs.get("platform"),
                "state": version_attrs.get("appStoreState"),
                "selectedBuildRelationshipID": build_relationship_id,
                "includedBuildMatchCount": len(builds),
            },
            "build": {
                "id": (build or {}).get("id"),
                "number": build_attrs.get("version"),
                "processingState": build_attrs.get("processingState"),
                "audienceType": build_attrs.get("buildAudienceType"),
                "usesNonExemptEncryption": build_attrs.get("usesNonExemptEncryption"),
            },
            "submission": _submission(client, app_id, version_id),
            "metadata": {
                "id": loc_id,
                "locale": loc_attrs.get("locale"),
                "fields": {field: loc_attrs.get(field) for field in _METADATA_FIELDS},
            },
            "reviewDetail": {
                "id": review_id,
                "demoAccountRequired": review_attrs.get("demoAccountRequired"),
                "fields": {
                    field: _fingerprint_field(client, review_id, field, review_attrs.get(field))
                    for field in _REVIEW_SECRET_FIELDS
                },
            },
            "screenshots": {
                "locale": locale,
                "displayType": display_type,
                "setID": set_id,
                "matchingSetCount": set_count,
                "relationshipCount": relationship_count,
                "relationshipTotal": relationship_total,
                "items": screenshot_items,
            },
        },
        images,
    )


def _diff(desired: dict[str, Any], live: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []

    def mismatch(code: str, expected: Any, actual: Any, *, classification: str = "mismatch") -> None:
        mismatches.append(
            {"code": code, "classification": classification, "expected": expected, "actual": actual}
        )

    version = live["version"]
    build = live["build"]
    if version.get("versionString") != desired["build"]["marketingVersion"]:
        mismatch("version.string", desired["build"]["marketingVersion"], version.get("versionString"), classification="stale")
    if version.get("platform") != "IOS":
        mismatch("version.platform", "IOS", version.get("platform"), classification="unknown" if version.get("platform") is None else "mismatch")
    if not isinstance(version.get("state"), str):
        mismatch("version.state.unknown", "known", version.get("state"), classification="unknown")
    if version.get("includedBuildMatchCount") != 1 or version.get("selectedBuildRelationshipID") != build.get("id"):
        mismatch(
            "version.selected-build-relationship",
            version.get("selectedBuildRelationshipID"),
            {"includedID": build.get("id"), "matchCount": version.get("includedBuildMatchCount")},
            classification="unknown",
        )
    if build.get("number") != desired["build"]["buildNumber"]:
        mismatch("build.number", desired["build"]["buildNumber"], build.get("number"), classification="stale")
    processing = build.get("processingState")
    if processing is None:
        mismatch("build.processing.unknown", "VALID", None, classification="unknown")
    elif processing != "VALID":
        mismatch("build.processing", "VALID", processing)
    if build.get("audienceType") != "APP_STORE_ELIGIBLE":
        mismatch("build.audience", "APP_STORE_ELIGIBLE", build.get("audienceType"), classification="unknown" if build.get("audienceType") is None else "mismatch")
    compliance = build.get("usesNonExemptEncryption")
    if not isinstance(compliance, bool):
        mismatch("build.compliance.unknown", "boolean", compliance, classification="unknown")

    submission = live.get("submission")
    if not isinstance(submission, dict) or submission.get("matchCount") is not None:
        mismatch("submission.item", "exactly one item for selected version", submission, classification="unknown")
    else:
        if submission.get("state") not in {"WAITING_FOR_REVIEW", "IN_REVIEW"}:
            mismatch("submission.state", ["WAITING_FOR_REVIEW", "IN_REVIEW"], submission.get("state"))
        item = submission.get("item") or {}
        if item.get("versionID") != version.get("id"):
            mismatch("submission.item.version", version.get("id"), item.get("versionID"), classification="stale")
        if item.get("state") != "READY_FOR_REVIEW":
            mismatch("submission.item.state", "READY_FOR_REVIEW", item.get("state"))

    metadata = live["metadata"]
    if metadata.get("locale") != desired["locale"]:
        mismatch("metadata.locale", desired["locale"], metadata.get("locale"), classification="unknown" if metadata.get("locale") is None else "mismatch")
    for field in _REQUIRED_METADATA_FIELDS:
        if not isinstance((metadata.get("fields") or {}).get(field), str) or not metadata["fields"][field]:
            mismatch(f"metadata.{field}.unknown", "present string", metadata["fields"].get(field), classification="unknown")

    review = live["reviewDetail"]
    if not isinstance(review.get("id"), str):
        mismatch("review-detail.missing", "present", review.get("id"), classification="unknown")
    for field in ("contactFirstName", "contactLastName", "contactPhone", "contactEmail", "notes"):
        if not review["fields"][field]["present"]:
            mismatch(f"review-detail.{field}.unknown", "present", False, classification="unknown")
    if review.get("demoAccountRequired") is True:
        for field in ("demoAccountName", "demoAccountPassword"):
            if not review["fields"][field]["present"]:
                mismatch(f"review-detail.{field}.unknown", "present", False, classification="unknown")
    elif review.get("demoAccountRequired") is not False:
        mismatch("review-detail.demoAccountRequired.unknown", "boolean", review.get("demoAccountRequired"), classification="unknown")

    screenshots = live["screenshots"]
    if screenshots.get("matchingSetCount") != 1:
        mismatch("screenshots.target-set", 1, screenshots.get("matchingSetCount"), classification="unknown")
    desired_items = desired["outputs"]
    live_items = screenshots["items"]
    desired_names = [item["fileName"] for item in desired_items]
    live_names = [item.get("fileName") for item in live_items]
    if screenshots.get("relationshipCount") != len(live_items):
        mismatch(
            "screenshots.relationship-closure",
            screenshots.get("relationshipCount"),
            len(live_items),
            classification="unknown",
        )
    if screenshots.get("relationshipTotal") != len(live_items):
        mismatch(
            "screenshots.pagination-closure",
            len(live_items),
            screenshots.get("relationshipTotal"),
            classification="unknown",
        )
    if len({name for name in live_names if isinstance(name, str)}) != len(live_names):
        mismatch("screenshots.duplicate-filenames", "unique", live_names)
    if len(desired_names) != len(live_names):
        mismatch("screenshots.count", len(desired_names), len(live_names))
    if desired_names != live_names:
        mismatch("screenshots.order", desired_names, live_names)
    missing = [name for name in desired_names if name not in live_names]
    extra = [name for name in live_names if name not in desired_names]
    if missing:
        mismatch("screenshots.missing", desired_names, missing)
    if extra:
        mismatch("screenshots.extra", [], extra)
    desired_by_name = {item["fileName"]: item for item in desired_items}
    for item in live_items:
        name = item.get("fileName")
        if item.get("state") != "COMPLETE":
            mismatch(f"screenshots.state:{name}", "COMPLETE", item.get("state"), classification="unknown" if item.get("state") is None else "mismatch")
        if (item.get("liveBytes") or {}).get("status") != "verified":
            mismatch(f"screenshots.live-bytes:{name}", "verified", (item.get("liveBytes") or {}).get("status"), classification="unknown")
        if not isinstance(item.get("width"), int) or not isinstance(item.get("height"), int) or item.get("width", 0) <= 0 or item.get("height", 0) <= 0:
            mismatch(
                f"screenshots.dimensions.unknown:{name}",
                "positive integer width/height",
                {"width": item.get("width"), "height": item.get("height")},
                classification="unknown",
            )
        if not isinstance(item.get("sourceFileChecksum"), str) or not _MD5_RE.fullmatch(item["sourceFileChecksum"]):
            mismatch(
                f"screenshots.source-checksum.unknown:{name}",
                "32 lowercase hex",
                item.get("sourceFileChecksum"),
                classification="unknown",
            )
        live_bytes = item.get("liveBytes") or {}
        if (live_bytes.get("width"), live_bytes.get("height")) != (item.get("width"), item.get("height")):
            mismatch(
                f"screenshots.live-dimensions:{name}",
                {"width": item.get("width"), "height": item.get("height")},
                {"width": live_bytes.get("width"), "height": live_bytes.get("height")},
            )
        desired_item = desired_by_name.get(name)
        if desired_item:
            if live_bytes.get("sha256") != desired_item["sha256"]:
                mismatch(
                    f"screenshots.live-sha256:{name}",
                    desired_item["sha256"],
                    live_bytes.get("sha256"),
                    classification="stale",
                )
            if item.get("sourceFileChecksum") != desired_item["sourceMD5"]:
                mismatch(f"screenshots.source-checksum:{name}", desired_item["sourceMD5"], item.get("sourceFileChecksum"), classification="stale")
            if (item.get("width"), item.get("height")) != (desired_item["width"], desired_item["height"]):
                mismatch(
                    f"screenshots.dimensions:{name}",
                    {"width": desired_item["width"], "height": desired_item["height"]},
                    {"width": item.get("width"), "height": item.get("height")},
                )
    return mismatches


def run_audit(
    client: ReadClient,
    *,
    desired_bundle: Path,
    app_id: str,
    version_id: str | None,
    locale: str,
    display_type: str,
    observed_at: str,
) -> AuditResult:
    _validate_observed_at(observed_at)
    desired, desired_files = _desired(desired_bundle)
    if locale != desired["locale"]:
        raise MirrorError(f"requested locale {locale} does not match desired locale {desired['locale']}")
    if display_type != desired["displayType"]:
        raise MirrorError(
            f"requested display type {display_type} does not match desired display type {desired['displayType']}"
        )
    resolved_version_id = version_id or _resolve_version_id(
        client, app_id, desired["build"]["marketingVersion"]
    )
    live, images = _live_snapshot(
        client,
        app_id=app_id,
        version_id=resolved_version_id,
        locale=locale,
        display_type=display_type,
        observed_at=observed_at,
    )
    mismatches = _diff(desired, live)
    document = {
        "schema": AUDIT_SCHEMA,
        "mode": "read-only",
        "verdict": {"status": "pass" if not mismatches else "fail", "mismatchCount": len(mismatches)},
        "desired": desired,
        "live": live,
        "mismatches": mismatches,
    }
    return AuditResult(document=document, image_bytes=images, desired_files=desired_files)


def write_bundle(result: AuditResult, *, desired_bundle: Path, bundle_dir: Path) -> None:
    del desired_bundle  # bytes were pinned during run_audit; never recopy mutable sources.
    if bundle_dir.exists():
        raise MirrorError(f"ASC reviewer mirror bundle 已存在: {bundle_dir}")
    bundle_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{bundle_dir.name}.tmp-", dir=str(bundle_dir.parent)))
    try:
        payloads: dict[str, bytes] = {
            "audit.json": canonical_json_bytes(result.document),
            **{f"desired/{path}": payload for path, payload in result.desired_files.items()},
            **result.image_bytes,
        }
        files: list[dict[str, Any]] = []
        for rel, payload in sorted(payloads.items()):
            parts = Path(rel).parts
            if Path(rel).is_absolute() or ".." in parts:
                raise MirrorError(f"unsafe mirror bundle path: {rel}")
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            staged = path.read_bytes()
            files.append({"path": rel, "byteSize": len(staged), "sha256": _sha256(staged)})
        closure = {"schema": BUNDLE_SCHEMA, "files": files}
        (staging / "manifest.json").write_bytes(canonical_json_bytes(closure))
        os.replace(staging, bundle_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    sub = top.add_subparsers(dest="command", required=True)
    audit = sub.add_parser(
        "audit",
        help="read-only live ASC reviewer mirror and desired coherence diff",
        description=(
            "Read-only: fetch the selected ASC version/build/submission/metadata/review-detail/"
            "screenshot bytes, redact secrets, and fail closed against a desired evidence bundle."
        ),
    )
    audit.add_argument("--desired-bundle", type=Path, required=True)
    audit.add_argument("--app-id", default=DEFAULT_APP_ID)
    audit.add_argument("--version-id", help="exact ASC appStoreVersion id; default resolves desired versionString")
    audit.add_argument("--locale", default="zh-Hant")
    audit.add_argument("--display-type", required=True, help="exact ASC screenshot display target, e.g. APP_IPHONE_65")
    audit.add_argument("--observed-at", help="timezone-aware observation time (default: current UTC)")
    audit.add_argument("--key", default=os.environ.get("ASC_KEY_ID", DEFAULT_KEY_ID))
    audit.add_argument("--issuer-id", default=os.environ.get("ASC_ISSUER_ID", DEFAULT_ISSUER_ID))
    audit.add_argument("--key-dir", default=os.environ.get("ASC_KEY_DIR", DEFAULT_KEY_DIR))
    audit.add_argument("--timeout", type=float, default=20.0, help="per-request timeout seconds")
    audit.add_argument("--bundle-dir", type=Path, help="local hash-closed evidence destination")
    audit.add_argument("--commit", action="store_true", help="write the local bundle atomically; ASC remains read-only")
    return top


def _failure_document(exc: MirrorError) -> dict[str, Any]:
    return {
        "schema": AUDIT_SCHEMA,
        "mode": "read-only",
        "verdict": {"status": "fail", "mismatchCount": 1},
        "desired": None,
        "live": None,
        "mismatches": [
            {"code": "audit.error", "classification": "unknown", "expected": "verified", "actual": str(exc)}
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command != "audit":
        raise AssertionError(args.command)
    if args.commit and args.bundle_dir is None:
        print(canonical_json_bytes(_failure_document(MirrorError("--commit requires --bundle-dir"))).decode(), end="")
        return 1
    observed_at = args.observed_at or datetime.now(timezone.utc).isoformat()
    try:
        config = ASCConfig(
            key_id=args.key,
            issuer_id=args.issuer_id,
            key_dir=Path(args.key_dir),
            app_id=args.app_id,
            version_id=args.version_id,
        )
        if args.timeout <= 0:
            raise MirrorError("--timeout must be greater than zero")
        client = ASCReadClient.connect(config, timeout_seconds=args.timeout)
        result = run_audit(
            client,
            desired_bundle=args.desired_bundle,
            app_id=args.app_id,
            version_id=args.version_id,
            locale=args.locale,
            display_type=args.display_type,
            observed_at=observed_at,
        )
        if args.commit:
            write_bundle(result, desired_bundle=args.desired_bundle, bundle_dir=args.bundle_dir)
        output = dict(result.document)
        output["bundle"] = {
            "status": "written" if args.commit else "dry-run",
            "path": str(args.bundle_dir) if args.bundle_dir else None,
        }
        print(canonical_json_bytes(output).decode("utf-8"), end="")
        return 0 if result.document["verdict"]["status"] == "pass" else 2
    except MirrorError as exc:
        print(canonical_json_bytes(_failure_document(exc)).decode("utf-8"), end="")
        return 1
    except Exception:
        # Never serialize exception reprs: auth libraries can retain key/token context.
        print(canonical_json_bytes(_failure_document(MirrorError("unexpected read-only audit failure"))).decode("utf-8"), end="")
        return 1


if __name__ == "__main__":
    sys.exit(main())

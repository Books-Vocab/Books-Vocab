#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""Dump/apply App Store Connect text and review metadata as one JSON bundle.

Read-only dump:
  ./ops/asc_text_bundle.py dump --output /tmp/asc_text.json

Dry-run edited JSON against live ASC:
  ./ops/asc_text_bundle.py apply /tmp/asc_text_edited.json

Write edited text fields back to ASC:
  ./ops/asc_text_bundle.py apply /tmp/asc_text_edited.json --yes

Scope is intentionally text/review metadata only. It does not submit for
review, withdraw, upload screenshots, or change pricing/release controls.
"""

from __future__ import annotations

import argparse
import logging
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


DEFAULT_KEY_ID = "TCXVHFRXMS"
DEFAULT_ISSUER_ID = "d7f86188-7c56-46f7-bc99-f889421025fa"
DEFAULT_APP_ID = "6759816274"
DEFAULT_KEY_DIR = "~/.secrets/apple"
ASC_BASE = "https://api.appstoreconnect.apple.com"
SCHEMA = "kg.asc_text_bundle.v1"

APP_INFO_LOC_FIELDS = ("name", "subtitle", "privacyPolicyUrl", "privacyChoicesUrl")
EULA_FIELDS = ("agreementText",)
VERSION_LOC_FIELDS = (
    "description",
    "keywords",
    "marketingUrl",
    "promotionalText",
    "supportUrl",
    "whatsNew",
)
VERSION_FIELDS = ("copyright",)
REVIEW_FIELDS = (
    "contactFirstName",
    "contactLastName",
    "contactPhone",
    "contactEmail",
    "demoAccountName",
    "demoAccountPassword",
    "demoAccountRequired",
    "notes",
)
SUB_GROUP_LOC_FIELDS = ("name", "customAppName")
SUB_FIELDS = ("reviewNote",)
SUB_LOC_FIELDS = ("name", "description")


@dataclass(frozen=True)
class ASCConfig:
    key_id: str
    issuer_id: str
    key_dir: Path
    app_id: str
    version_id: str | None = None


@dataclass(frozen=True)
class Change:
    method: str
    path: str
    type: str
    id: str
    fields: tuple[str, ...]
    body: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "type": self.type,
            "id": self.id,
            "fields": list(self.fields),
            "body": self.body,
        }


def mint_token(config: ASCConfig) -> str:
    import jwt

    p8_path = config.key_dir.expanduser() / f"AuthKey_{config.key_id}.p8"
    with p8_path.open(encoding="utf-8") as f:
        p8 = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": config.issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        p8,
        algorithm="ES256",
        headers={"kid": config.key_id, "typ": "JWT"},
    )


def request_json(path: str, token: str, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(ASC_BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {"_ok": resp.status}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except Exception:
            _LOGGER.warning(
                "ASC request HTTPError returned non-JSON payload for path=%s: %r",
                path,
                raw[:500],
                exc_info=True,
            )
            detail = {"raw": raw[:500]}
        return {"_httpError": e.code, "_detail": detail}
    except urllib.error.URLError as e:
        sys.stderr.write(f"[asc_text_bundle] network error: {e}\n")
        return {"_httpError": "network", "_detail": {"reason": str(e.reason)}}


def require_ok(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    if "_httpError" in payload:
        raise SystemExit(f"✗ {label} failed: HTTP {payload['_httpError']} {payload.get('_detail')}")
    return payload


def included(payload: dict[str, Any], type_name: str) -> list[dict[str, Any]]:
    return [item for item in payload.get("included", []) if item.get("type") == type_name]


def attrs(item: dict[str, Any] | None) -> dict[str, Any]:
    return (item or {}).get("attributes") or {}


def one_or_none(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


def newest_version(versions: list[dict[str, Any]]) -> dict[str, Any]:
    if not versions:
        raise SystemExit("✗ no appStoreVersions found")
    active_states = {
        "PREPARE_FOR_SUBMISSION",
        "WAITING_FOR_REVIEW",
        "IN_REVIEW",
        "PENDING_DEVELOPER_RELEASE",
        "REJECTED",
        "DEVELOPER_REJECTED",
        "METADATA_REJECTED",
    }
    active = [v for v in versions if attrs(v).get("appStoreState") in active_states]
    pool = active or versions
    return sorted(pool, key=lambda v: attrs(v).get("createdDate") or "", reverse=True)[0]


def get_version(config: ASCConfig, token: str) -> dict[str, Any]:
    if config.version_id:
        version = request_json(
            f"/v1/appStoreVersions/{config.version_id}?include=appStoreVersionLocalizations,appStoreReviewDetail,build",
            token,
        )
        return require_ok("appStoreVersion", version)
    versions = request_json(
        f"/v1/apps/{config.app_id}/appStoreVersions?include=appStoreVersionLocalizations,appStoreReviewDetail,build&limit=50",
        token,
    )
    require_ok("appStoreVersions", versions)
    version = newest_version(versions.get("data") or [])
    version_id = version["id"]
    return require_ok(
        "appStoreVersion",
        request_json(
            f"/v1/appStoreVersions/{version_id}?include=appStoreVersionLocalizations,appStoreReviewDetail,build",
            token,
        ),
    )


def screenshot_summary(version_loc_id: str, token: str) -> list[dict[str, Any]]:
    sets_payload = require_ok(
        "appScreenshotSets",
        request_json(
            f"/v1/appStoreVersionLocalizations/{version_loc_id}/appScreenshotSets?limit=50",
            token,
        ),
    )
    out: list[dict[str, Any]] = []
    for sset in sets_payload.get("data") or []:
        screenshots = require_ok(
            "appScreenshots",
            request_json(f"/v1/appScreenshotSets/{sset['id']}/appScreenshots?limit=50", token),
        )
        out.append(
            {
                "id": sset["id"],
                "displayType": attrs(sset).get("screenshotDisplayType"),
                "screenshots": [
                    {
                        "id": shot["id"],
                        "fileName": attrs(shot).get("fileName"),
                        "state": ((attrs(shot).get("assetDeliveryState") or {}).get("state")),
                        "width": (((attrs(shot).get("imageAsset") or {}).get("width"))),
                        "height": (((attrs(shot).get("imageAsset") or {}).get("height"))),
                        "templateUrl": ((attrs(shot).get("imageAsset") or {}).get("templateUrl")),
                    }
                    for shot in screenshots.get("data") or []
                ],
            }
        )
    return out


def preview_summary(version_loc_id: str, token: str) -> dict[str, Any]:
    previews = require_ok(
        "appPreviewSets",
        request_json(
            f"/v1/appStoreVersionLocalizations/{version_loc_id}/appPreviewSets?limit=50",
            token,
        ),
    )
    return {"count": len(previews.get("data") or [])}


def subscription_summary(sub_id: str, token: str) -> dict[str, Any]:
    locs = require_ok(
        "subscriptionLocalizations",
        request_json(f"/v1/subscriptions/{sub_id}/subscriptionLocalizations?limit=50", token),
    )
    review_shot = request_json(f"/v1/subscriptions/{sub_id}/appStoreReviewScreenshot", token)
    intro = require_ok(
        "subscriptionIntroductoryOffers",
        request_json(f"/v1/subscriptions/{sub_id}/introductoryOffers?limit=200", token),
    )
    promo = require_ok(
        "subscriptionPromotionalOffers",
        request_json(f"/v1/subscriptions/{sub_id}/promotionalOffers?limit=50", token),
    )
    offer_codes = require_ok(
        "subscriptionOfferCodes",
        request_json(f"/v1/subscriptions/{sub_id}/offerCodes?limit=50", token),
    )
    prices = require_ok(
        "subscriptionPrices",
        request_json(
            f"/v1/subscriptions/{sub_id}/prices?include=subscriptionPricePoint,territory&limit=200",
            token,
        ),
    )
    inc = prices.get("included") or []
    rows = []
    for row in prices.get("data") or []:
        rel = row.get("relationships") or {}
        terr = ((rel.get("territory") or {}).get("data") or {}).get("id")
        price_point = ((rel.get("subscriptionPricePoint") or {}).get("data") or {}).get("id")
        price = next(
            (
                attrs(item).get("customerPrice")
                for item in inc
                if item.get("type") == "subscriptionPricePoints" and item.get("id") == price_point
            ),
            None,
        )
        rows.append({"territory": terr, "customerPrice": price})
    sample_territories = {"TWN", "USA", "JPN", "CAN", "GBR"}
    return {
        "localizations": [
            {
                "id": loc["id"],
                "locale": attrs(loc).get("locale"),
                "name": attrs(loc).get("name"),
                "description": attrs(loc).get("description"),
                "state": attrs(loc).get("state"),
            }
            for loc in locs.get("data") or []
        ],
        "reviewScreenshot": (
            None
            if "_httpError" in review_shot or review_shot.get("data") is None
            else {
                "id": review_shot["data"]["id"],
                "fileName": attrs(review_shot["data"]).get("fileName"),
                "state": ((attrs(review_shot["data"]).get("assetDeliveryState") or {}).get("state")),
                "width": ((attrs(review_shot["data"]).get("imageAsset") or {}).get("width")),
                "height": ((attrs(review_shot["data"]).get("imageAsset") or {}).get("height")),
                "templateUrl": ((attrs(review_shot["data"]).get("imageAsset") or {}).get("templateUrl")),
            }
        ),
        "prices": {
            "count": len(rows),
            "sample": [row for row in rows if row["territory"] in sample_territories],
        },
        "introductoryOffers": {
            "count": len(intro.get("data") or []),
            "unique": sorted(
                {
                    "{offerMode} {duration} x{numberOfPeriods} start={startDate} end={endDate}".format(
                        **{
                            **attrs(item),
                            "endDate": attrs(item).get("endDate") or "none",
                        }
                    )
                    for item in intro.get("data") or []
                }
            ),
        },
        "promotionalOffers": {"count": len(promo.get("data") or [])},
        "offerCodes": {"count": len(offer_codes.get("data") or [])},
    }


def dump_bundle(config: ASCConfig) -> dict[str, Any]:
    token = mint_token(config)
    app = require_ok("app", request_json(f"/v1/apps/{config.app_id}", token))
    app_infos = require_ok(
        "appInfos",
        request_json(
            f"/v1/apps/{config.app_id}/appInfos?include=appInfoLocalizations,primaryCategory,secondaryCategory,ageRatingDeclaration",
            token,
        ),
    )
    app_info = one_or_none(app_infos)
    eula = request_json(f"/v1/apps/{config.app_id}/endUserLicenseAgreement", token)
    version_payload = get_version(config, token)
    version = one_or_none(version_payload)
    if not version:
        raise SystemExit("✗ no target appStoreVersion")
    version_locs = included(version_payload, "appStoreVersionLocalizations")
    review_detail = next(iter(included(version_payload, "appStoreReviewDetails")), None)
    build = next(iter(included(version_payload, "builds")), None)
    groups_payload = require_ok(
        "subscriptionGroups",
        request_json(
            f"/v1/apps/{config.app_id}/subscriptionGroups?include=subscriptionGroupLocalizations,subscriptions&limit=50",
            token,
        ),
    )
    reviews = require_ok(
        "customerReviews",
        request_json(f"/v1/apps/{config.app_id}/customerReviews?sort=-createdDate&limit=20&include=response", token),
    )
    accessibility = require_ok(
        "accessibilityDeclarations",
        request_json(f"/v1/apps/{config.app_id}/accessibilityDeclarations", token),
    )

    app_info_locs = included(app_infos, "appInfoLocalizations")
    group_locs = included(groups_payload, "subscriptionGroupLocalizations")
    subscriptions = included(groups_payload, "subscriptions")
    groups = []
    for group in groups_payload.get("data") or []:
        group_sub_ids = {
            item["id"]
            for item in (((group.get("relationships") or {}).get("subscriptions") or {}).get("data") or [])
        }
        group_loc_ids = {
            item["id"]
            for item in (
                ((group.get("relationships") or {}).get("subscriptionGroupLocalizations") or {}).get("data") or []
            )
        }
        group_subs = []
        for sub in subscriptions:
            if sub["id"] not in group_sub_ids:
                continue
            details = subscription_summary(sub["id"], token)
            group_subs.append(
                {
                    "id": sub["id"],
                    "name": attrs(sub).get("name"),
                    "productId": attrs(sub).get("productId"),
                    "state": attrs(sub).get("state"),
                    "subscriptionPeriod": attrs(sub).get("subscriptionPeriod"),
                    "reviewNote": attrs(sub).get("reviewNote"),
                    **details,
                }
            )
        groups.append(
            {
                "id": group["id"],
                "referenceName": attrs(group).get("referenceName"),
                "localizations": [
                    {
                        "id": loc["id"],
                        "locale": attrs(loc).get("locale"),
                        "name": attrs(loc).get("name"),
                        "customAppName": attrs(loc).get("customAppName"),
                        "state": attrs(loc).get("state"),
                    }
                    for loc in group_locs
                    if loc["id"] in group_loc_ids
                ],
                "subscriptions": group_subs,
            }
        )

    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "app": {
            "id": config.app_id,
            "name": attrs(one_or_none(app)).get("name"),
            "bundleId": attrs(one_or_none(app)).get("bundleId"),
            "sku": attrs(one_or_none(app)).get("sku"),
            "primaryLocale": attrs(one_or_none(app)).get("primaryLocale"),
            "contentRightsDeclaration": attrs(one_or_none(app)).get("contentRightsDeclaration"),
        },
        "appInfo": {
            "id": app_info["id"] if app_info else None,
            "state": attrs(app_info).get("state"),
            "appStoreAgeRating": attrs(app_info).get("appStoreAgeRating"),
            "primaryCategory": (((app_info or {}).get("relationships") or {}).get("primaryCategory") or {}).get(
                "data", {}
            ).get("id"),
            "secondaryCategory": (((app_info or {}).get("relationships") or {}).get("secondaryCategory") or {}).get(
                "data", {}
            ).get("id"),
            "localizations": [
                {field: attrs(loc).get(field) for field in ("id",)}
                for loc in []
            ],
        },
        "eula": (
            None
            if "_httpError" in eula or eula.get("data") is None
            else {"id": eula["data"]["id"], "agreementText": attrs(eula["data"]).get("agreementText")}
        ),
        "appStoreVersion": {
            "id": version["id"],
            "versionString": attrs(version).get("versionString"),
            "appStoreState": attrs(version).get("appStoreState"),
            "reviewType": attrs(version).get("reviewType"),
            "releaseType": attrs(version).get("releaseType"),
            "copyright": attrs(version).get("copyright"),
            "build": (
                None
                if build is None
                else {
                    "id": build["id"],
                    "version": attrs(build).get("version"),
                    "uploadedDate": attrs(build).get("uploadedDate"),
                    "processingState": attrs(build).get("processingState"),
                    "buildAudienceType": attrs(build).get("buildAudienceType"),
                    "usesNonExemptEncryption": attrs(build).get("usesNonExemptEncryption"),
                    "minOsVersion": attrs(build).get("minOsVersion"),
                }
            ),
            "localizations": [
                {
                    "id": loc["id"],
                    **{field: attrs(loc).get(field) for field in ("locale", *VERSION_LOC_FIELDS)},
                    "screenshots": screenshot_summary(loc["id"], token),
                    "appPreviews": preview_summary(loc["id"], token),
                }
                for loc in version_locs
            ],
            "reviewDetail": (
                None
                if review_detail is None
                else {"id": review_detail["id"], **{field: attrs(review_detail).get(field) for field in REVIEW_FIELDS}}
            ),
        },
        "subscriptions": {"groups": groups},
        "reviews": {
            "count": len(reviews.get("data") or []),
            "items": [
                {
                    "id": item["id"],
                    "territory": attrs(item).get("territory"),
                    "rating": attrs(item).get("rating"),
                    "title": attrs(item).get("title"),
                    "body": attrs(item).get("body"),
                    "createdDate": attrs(item).get("createdDate"),
                }
                for item in reviews.get("data") or []
            ],
        },
        "accessibilityDeclarations": {
            "count": len(accessibility.get("data") or []),
            "items": accessibility.get("data") or [],
        },
        "nonApiChecklist": [
            "Resolution Center rejection text is not exposed by public API; inspect ASC GUI.",
            "App Privacy nutrition labels are not exposed by public API; inspect ASC GUI.",
            "Screenshot image content can be listed by API but semantic review still needs visual inspection.",
        ],
    } | {
        "appInfo": {
            "id": app_info["id"] if app_info else None,
            "state": attrs(app_info).get("state"),
            "appStoreAgeRating": attrs(app_info).get("appStoreAgeRating"),
            "primaryCategory": (((app_info or {}).get("relationships") or {}).get("primaryCategory") or {}).get(
                "data", {}
            ).get("id"),
            "secondaryCategory": (((app_info or {}).get("relationships") or {}).get("secondaryCategory") or {}).get(
                "data", {}
            ).get("id"),
            "localizations": [
                {"id": loc["id"], **{field: attrs(loc).get(field) for field in ("locale", *APP_INFO_LOC_FIELDS)}}
                for loc in app_info_locs
            ],
        }
    }


def changes_for_object(
    current: dict[str, Any],
    edited: dict[str, Any],
    fields: tuple[str, ...],
    type_name: str,
    path_prefix: str,
) -> Change | None:
    obj_id = edited.get("id") or current.get("id")
    if not obj_id:
        return None
    changed = {field: edited.get(field) for field in fields if current.get(field) != edited.get(field)}
    if not changed:
        return None
    return Change(
        method="PATCH",
        path=f"{path_prefix}/{obj_id}",
        type=type_name,
        id=obj_id,
        fields=tuple(changed.keys()),
        body={"data": {"type": type_name, "id": obj_id, "attributes": changed}},
    )


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items if item.get("id")}


def compute_changes(current: dict[str, Any], edited: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    current_app_locs = by_id(((current.get("appInfo") or {}).get("localizations") or []))
    for loc in ((edited.get("appInfo") or {}).get("localizations") or []):
        change = changes_for_object(
            current_app_locs.get(loc.get("id"), {}),
            loc,
            APP_INFO_LOC_FIELDS,
            "appInfoLocalizations",
            "/v1/appInfoLocalizations",
        )
        if change:
            changes.append(change)

    if current.get("eula") and edited.get("eula"):
        change = changes_for_object(
            current["eula"],
            edited["eula"],
            EULA_FIELDS,
            "endUserLicenseAgreements",
            "/v1/endUserLicenseAgreements",
        )
        if change:
            changes.append(change)

    current_version = current.get("appStoreVersion") or {}
    edited_version = edited.get("appStoreVersion") or {}
    change = changes_for_object(
        current_version,
        edited_version,
        VERSION_FIELDS,
        "appStoreVersions",
        "/v1/appStoreVersions",
    )
    if change:
        changes.append(change)

    current_version_locs = by_id(current_version.get("localizations") or [])
    for loc in edited_version.get("localizations") or []:
        change = changes_for_object(
            current_version_locs.get(loc.get("id"), {}),
            loc,
            VERSION_LOC_FIELDS,
            "appStoreVersionLocalizations",
            "/v1/appStoreVersionLocalizations",
        )
        if change:
            changes.append(change)

    if current_version.get("reviewDetail") and edited_version.get("reviewDetail"):
        change = changes_for_object(
            current_version["reviewDetail"],
            edited_version["reviewDetail"],
            REVIEW_FIELDS,
            "appStoreReviewDetails",
            "/v1/appStoreReviewDetails",
        )
        if change:
            changes.append(change)

    current_groups = by_id(((current.get("subscriptions") or {}).get("groups") or []))
    for group in ((edited.get("subscriptions") or {}).get("groups") or []):
        current_group = current_groups.get(group.get("id"), {})
        current_group_locs = by_id(current_group.get("localizations") or [])
        for loc in group.get("localizations") or []:
            change = changes_for_object(
                current_group_locs.get(loc.get("id"), {}),
                loc,
                SUB_GROUP_LOC_FIELDS,
                "subscriptionGroupLocalizations",
                "/v1/subscriptionGroupLocalizations",
            )
            if change:
                changes.append(change)
        current_subs = by_id(current_group.get("subscriptions") or [])
        for sub in group.get("subscriptions") or []:
            current_sub = current_subs.get(sub.get("id"), {})
            change = changes_for_object(
                current_sub,
                sub,
                SUB_FIELDS,
                "subscriptions",
                "/v1/subscriptions",
            )
            if change:
                changes.append(change)
            current_sub_locs = by_id(current_sub.get("localizations") or [])
            for loc in sub.get("localizations") or []:
                change = changes_for_object(
                    current_sub_locs.get(loc.get("id"), {}),
                    loc,
                    SUB_LOC_FIELDS,
                    "subscriptionLocalizations",
                    "/v1/subscriptionLocalizations",
                )
                if change:
                    changes.append(change)
    return changes


def validate_changes(changes: list[Change]) -> list[str]:
    errors: list[str] = []
    for change in changes:
        attributes = ((change.body.get("data") or {}).get("attributes") or {})
        if change.type == "subscriptionLocalizations" and "description" in attributes:
            value = attributes["description"] or ""
            if len(value) > 55:
                errors.append(
                    f"subscriptionLocalizations {change.id} description is {len(value)} chars; ASC max is 55"
                )
        if change.type == "appInfoLocalizations" and "subtitle" in attributes:
            value = attributes["subtitle"] or ""
            if len(value) > 30:
                errors.append(f"appInfoLocalizations {change.id} subtitle is {len(value)} chars; ASC max is 30")
        if change.type == "appStoreVersionLocalizations" and "promotionalText" in attributes:
            value = attributes["promotionalText"] or ""
            if len(value) > 170:
                errors.append(
                    f"appStoreVersionLocalizations {change.id} promotionalText is {len(value)} chars; ASC max is 170"
                )
        if change.type == "appStoreVersionLocalizations" and "keywords" in attributes:
            value = attributes["keywords"] or ""
            if len(value) > 100:
                errors.append(f"appStoreVersionLocalizations {change.id} keywords is {len(value)} chars; ASC max is 100")
    return errors


def write_bundle(bundle: dict[str, Any], output: str | None) -> None:
    text = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(output)
    else:
        print(text, end="")


def cmd_dump(args: argparse.Namespace) -> int:
    config = ASCConfig(
        key_id=args.key,
        issuer_id=args.issuer_id,
        key_dir=Path(args.key_dir),
        app_id=args.app_id,
        version_id=args.version_id,
    )
    write_bundle(dump_bundle(config), args.output)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    edited = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if edited.get("schema") != SCHEMA:
        raise SystemExit(f"✗ unsupported schema: {edited.get('schema')}")
    version_id = args.version_id or ((edited.get("appStoreVersion") or {}).get("id"))
    config = ASCConfig(
        key_id=args.key,
        issuer_id=args.issuer_id,
        key_dir=Path(args.key_dir),
        app_id=args.app_id or ((edited.get("app") or {}).get("id") or DEFAULT_APP_ID),
        version_id=version_id,
    )
    current = dump_bundle(config)
    changes = compute_changes(current, edited)
    validation_errors = validate_changes(changes)
    summary = {"dryRun": not args.yes, "changeCount": len(changes), "changes": [c.to_json() for c in changes]}
    if validation_errors:
        summary["validationErrors"] = validation_errors
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if validation_errors:
        return 2
    if not args.yes or not changes:
        return 0
    token = mint_token(config)
    for change in changes:
        result = request_json(change.path, token, method=change.method, body=change.body)
        require_ok(change.path, result)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--key", default=os.environ.get("ASC_KEY_ID", DEFAULT_KEY_ID))
    p.add_argument("--issuer-id", default=os.environ.get("ASC_ISSUER_ID", DEFAULT_ISSUER_ID))
    p.add_argument("--key-dir", default=os.environ.get("ASC_KEY_DIR", DEFAULT_KEY_DIR))
    p.add_argument("--app-id", default=DEFAULT_APP_ID)
    sub = p.add_subparsers(dest="cmd", required=True)

    dump = sub.add_parser("dump", help="dump ASC text/review metadata JSON")
    dump.add_argument("--version-id")
    dump.add_argument("--output", "-o")
    dump.set_defaults(func=cmd_dump)

    apply = sub.add_parser("apply", help="dry-run or apply edited JSON back to ASC")
    apply.add_argument("file")
    apply.add_argument("--version-id")
    apply.add_argument("--yes", action="store_true", help="actually PATCH ASC; default is dry-run")
    apply.set_defaults(func=cmd_apply)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

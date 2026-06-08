from __future__ import annotations

from collections import Counter
import hashlib
import struct
from pathlib import Path

from catalog_review_taxonomy import (
    build_manifest_indexes,
    build_surface_index,
    build_taxonomy,
    classify_lane,
    classify_quality_tier,
    normalize_label,
    slugify,
)


def build_asset_id(rel_path: Path) -> str:
    rel_text = rel_path.with_suffix("").as_posix()
    digest = hashlib.blake2s(rel_text.encode("utf-8"), digest_size=4).hexdigest()
    return f"{slugify(rel_text)}--{digest}"


def build_cluster_id(category: str, title: str) -> str:
    """Stable scene identity = (category, title), the unit light/dark pair into.

    A raw blake2s digest of the title disambiguates the slug, so CJK titles (which
    slugify collapses to "item") and slug-colliding titles ("Completed · 短" vs
    "· 長") stay distinct scenes instead of merging and hiding shots.
    """
    digest = hashlib.blake2s(title.encode("utf-8"), digest_size=2).hexdigest()
    return f"{slugify(category)}--{slugify(title)}--{digest}"


def has_prefix(category: str, prefixes: tuple[str, ...]) -> bool:
    return any(category.startswith(prefix) for prefix in prefixes)


def classify_promise(category: str, profile: dict) -> str:
    for promise_def in profile["promises"]:
        promise = promise_def["name"]
        needles = promise_def["needles"]
        if any(needle in category for needle in needles):
            return promise
    return "Weak"


def classify_eligibility(category: str, promise: str, profile: dict) -> str:
    """Where could this asset be used (marketing readiness).

    Intentionally does NOT fold ``promise == "Weak"`` into ``engineering``:
    a promise-unclassified building block is not the same as deliberate
    engineering coverage. Weakness is tracked on the orthogonal ``qualityTier``
    axis, keeping the marketing/engineering boundary honest.
    """
    engineering_only = tuple(profile["eligibility"]["engineeringOnlyPrefixes"])
    marketing_eligible = tuple(profile["eligibility"]["marketingEligiblePrefixes"])
    if has_prefix(category, engineering_only):
        return "engineering"
    if has_prefix(category, marketing_eligible):
        return "marketing"
    return "review"


def is_new_since_release(category: str, profile: dict, marker: str) -> bool:
    return category in set(profile["releaseMarkers"].get(marker, []))


def is_hero_candidate(category: str, profile: dict) -> bool:
    return has_prefix(category, tuple(profile["heroCandidatePrefixes"]))


def read_png_size(path: Path) -> tuple[int, int]:
    """(width, height) from the PNG IHDR header — assets have heterogeneous
    shapes (full screens vs thin tickers vs square badges), so the gallery must
    render each at its true aspect ratio instead of one hard-coded phone box."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or len(header) < 24:
        return (0, 0)
    width, height = struct.unpack(">II", header[16:24])
    return (width, height)


def collect_items(source_root: Path, profile: dict, *, release_marker: str = "pr878") -> list[dict]:
    items: list[dict] = []
    for path in sorted(source_root.rglob("*.png")):
        rel = path.relative_to(source_root)
        if len(rel.parts) < 3:
            continue
        device_dir = rel.parts[0]
        category_dir = rel.parts[1]
        title = normalize_label(path.stem)
        category = normalize_label(category_dir)
        appearance = "dark" if "(dark)" in device_dir else "light"
        device = device_dir.replace(" (dark)", "")
        promise = classify_promise(category, profile)
        eligibility = classify_eligibility(category, promise, profile)
        taxonomy = build_taxonomy(category, title, profile)
        hero_candidate = is_hero_candidate(category, profile)
        cluster_id = build_cluster_id(category, title)
        asset_id = build_asset_id(rel)
        width, height = read_png_size(path)
        items.append({
            "assetID": asset_id,
            "clusterID": cluster_id,
            "relPath": rel.as_posix(),
            "deviceDir": device_dir,
            "device": device,
            "appearance": appearance,
            "width": width,
            "height": height,
            "category": category,
            "title": title,
            "promise": promise,
            "eligibility": eligibility,
            "lane": classify_lane(taxonomy["surfaceRole"], eligibility),
            "qualityTier": classify_quality_tier(promise, eligibility, hero_candidate),
            "newSincePr878": is_new_since_release(category, profile, release_marker),
            "heroCandidate": hero_candidate,
            **taxonomy,
        })
    return items


def build_manifest(items: list[dict], profile: dict, *, state_file: str | None = None, review_state: dict | None = None) -> dict:
    counts = Counter(item["promise"] for item in items)
    category_counts = Counter(item["category"] for item in items)
    eligibility_counts = Counter(item["eligibility"] for item in items)
    indexes = build_manifest_indexes(items)
    surfaces = build_surface_index(items)
    state_entries = review_state.get("entries", {}) if review_state else {}
    items_with_state = []
    for item in items:
        state_entry = state_entries.get(item["assetID"], {})
        item_with_state = dict(item)
        item_with_state["reviewStatus"] = state_entry.get("status", "")
        item_with_state["reviewNote"] = state_entry.get("note", "")
        items_with_state.append(item_with_state)
    return {
        "schema": "kg.catalog.review.v1",
        "profile": {
            "path": str(profile.get("_path", "")),
            "schema": profile.get("schema"),
        },
        "stateFile": state_file,
        "totalImages": len(items),
        "sceneCount": len({item["clusterID"] for item in items}),
        "promiseCounts": dict(counts),
        "categoryCounts": dict(category_counts),
        "eligibilityCounts": dict(eligibility_counts),
        **indexes,
        "newSincePr878Count": sum(1 for item in items if item["newSincePr878"]),
        "heroCandidateCount": sum(1 for item in items if item["heroCandidate"]),
        "stateCounts": dict(Counter(item["reviewStatus"] for item in items_with_state if item["reviewStatus"])),
        "surfaces": surfaces,
        "items": items_with_state,
    }

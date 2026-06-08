from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re

from catalog_review_taxonomy import build_manifest_indexes, build_taxonomy


def build_node_tree(items: list[dict]) -> dict:
    feature_groups: dict[str, list[dict]] = {}
    for item in items:
        feature_groups.setdefault(item["feature"], []).append(item)

    feature_nodes: list[dict] = []
    for feature_label in sorted(feature_groups):
        feature_items = feature_groups[feature_label]
        feature_slug = slugify(feature_label)

        surface_groups: dict[str, list[dict]] = {}
        for item in feature_items:
            surface_groups.setdefault(item["surfaceKey"], []).append(item)

        surface_nodes: list[dict] = []
        for surface_key in sorted(surface_groups, key=lambda key: surface_groups[key][0]["surface"].lower()):
            surface_items = surface_groups[surface_key]
            sample = surface_items[0]
            surface_path = f"{feature_slug}/{surface_key}"

            state_groups: dict[str, list[dict]] = {}
            for item in surface_items:
                state_groups.setdefault(item["stateKey"], []).append(item)

            state_nodes: list[dict] = []
            for state_key in sorted(state_groups, key=lambda key: state_groups[key][0]["stateLabel"].lower()):
                state_items = state_groups[state_key]
                state_sample = state_items[0]
                state_path = f"{surface_path}/{state_key}"
                asset_nodes = [
                    {
                        "nodePath": f"{state_path}/{asset['assetID']}",
                        "kind": "asset",
                        "label": f"{asset['device']} · {asset['appearance']}",
                        "assetID": asset["assetID"],
                        "relPath": asset["relPath"],
                        "device": asset["device"],
                        "appearance": asset["appearance"],
                        "eligibility": asset["eligibility"],
                        "heroCandidate": asset["heroCandidate"],
                        "newSincePr878": asset["newSincePr878"],
                    }
                    for asset in sorted(
                        state_items,
                        key=lambda asset: (asset["device"].lower(), asset["appearance"], asset["assetID"]),
                    )
                ]
                state_nodes.append({
                    "nodePath": state_path,
                    "kind": "state",
                    "label": state_sample["stateLabel"],
                    "count": len(state_items),
                    "children": asset_nodes,
                })

            surface_nodes.append({
                "nodePath": surface_path,
                "kind": "surface",
                "label": sample["surface"],
                "promise": sample["promise"],
                "assetKind": sample["assetKind"],
                "surfaceRole": sample["surfaceRole"],
                "heroCandidate": any(item["heroCandidate"] for item in surface_items),
                "count": len(surface_items),
                "children": state_nodes,
            })

        feature_nodes.append({
            "nodePath": feature_slug,
            "kind": "feature",
            "label": feature_label,
            "count": len(feature_items),
            "children": surface_nodes,
        })

    return {
        "nodePath": "",
        "kind": "root",
        "label": "KG",
        "count": len(items),
        "children": feature_nodes,
    }


def normalize_label(text: str) -> str:
    return text.replace("_", " ").strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def build_asset_id(rel_path: Path) -> str:
    rel_text = rel_path.with_suffix("").as_posix()
    digest = hashlib.blake2s(rel_text.encode("utf-8"), digest_size=4).hexdigest()
    return f"{slugify(rel_text)}--{digest}"


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
    engineering_only = tuple(profile["eligibility"]["engineeringOnlyPrefixes"])
    marketing_eligible = tuple(profile["eligibility"]["marketingEligiblePrefixes"])
    if has_prefix(category, engineering_only):
        return "engineering"
    if has_prefix(category, marketing_eligible):
        return "marketing"
    if promise == "Weak":
        return "engineering"
    return "review"


def is_new_since_release(category: str, profile: dict, marker: str) -> bool:
    return category in set(profile["releaseMarkers"].get(marker, []))


def is_hero_candidate(category: str, profile: dict) -> bool:
    return has_prefix(category, tuple(profile["heroCandidatePrefixes"]))


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
        cluster_id = f"{slugify(category)}--{slugify(title)}"
        asset_id = build_asset_id(rel)
        items.append({
            "assetID": asset_id,
            "clusterID": cluster_id,
            "relPath": rel.as_posix(),
            "deviceDir": device_dir,
            "device": device,
            "appearance": appearance,
            "category": category,
            "title": title,
            "promise": promise,
            "eligibility": eligibility,
            "newSincePr878": is_new_since_release(category, profile, release_marker),
            "heroCandidate": is_hero_candidate(category, profile),
            **taxonomy,
        })
    return items


def build_manifest(items: list[dict], profile: dict) -> dict:
    counts = Counter(item["promise"] for item in items)
    category_counts = Counter(item["category"] for item in items)
    eligibility_counts = Counter(item["eligibility"] for item in items)
    indexes = build_manifest_indexes(items)
    return {
        "schema": "kg.catalog.atlas.v1",
        "profile": {
            "path": str(profile.get("_path", "")),
            "schema": profile.get("schema"),
        },
        "totalImages": len(items),
        "promiseCounts": dict(counts),
        "categoryCounts": dict(category_counts),
        "eligibilityCounts": dict(eligibility_counts),
        **indexes,
        "newSincePr878Count": sum(1 for item in items if item["newSincePr878"]),
        "heroCandidateCount": sum(1 for item in items if item["heroCandidate"]),
        "tree": build_node_tree(items),
        "items": items,
    }

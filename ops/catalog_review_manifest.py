from __future__ import annotations

from collections import Counter
from pathlib import Path


def normalize_label(text: str) -> str:
    return text.replace("_", " ").strip()


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
        items.append({
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
        })
    return items


def build_manifest(items: list[dict], profile: dict) -> dict:
    counts = Counter(item["promise"] for item in items)
    category_counts = Counter(item["category"] for item in items)
    eligibility_counts = Counter(item["eligibility"] for item in items)
    return {
        "schema": "kg.catalog.review.v1",
        "profile": {
            "path": str(profile.get("_path", "")),
            "schema": profile.get("schema"),
        },
        "totalImages": len(items),
        "promiseCounts": dict(counts),
        "categoryCounts": dict(category_counts),
        "eligibilityCounts": dict(eligibility_counts),
        "newSincePr878Count": sum(1 for item in items if item["newSincePr878"]),
        "heroCandidateCount": sum(1 for item in items if item["heroCandidate"]),
        "items": items,
    }

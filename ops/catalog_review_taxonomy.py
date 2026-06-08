from __future__ import annotations

from collections import Counter
import re


def normalize_label(text: str) -> str:
    return text.replace("_", " ").strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def split_surface(category: str) -> tuple[str, str]:
    if " · " in category:
        surface, variant = category.split(" · ", 1)
        return surface.strip(), variant.strip()
    return category.strip(), ""


def classify_feature(category: str, profile: dict) -> str:
    for feature_def in profile.get("features", []):
        if any(needle in category for needle in feature_def["needles"]):
            return feature_def["name"]
    return "Misc"


def classify_asset_kind(category: str, surface: str) -> str:
    text = f"{category} {surface}"
    if any(token in text for token in (" View", "Bookshelf", "Knowledge Graph", "Reader ·", "Today Review", "Sync View", "Welcome")):
        return "screen"
    if any(token in text for token in (" Sheet", "Popover", "Picker", "Login", "Paywall")):
        return "overlay"
    if any(token in text for token in (" Presenter", "Components", "Controls", "Actions", "Sections", "Badge", "Ticker", "Toolbar", "Calendar", "Heatmap", "Capsule", "Chip", "Row", "Hero", "Banner", "Shimmer")):
        return "component"
    return "scene"


def classify_surface_role(surface: str, category: str, kind: str) -> str:
    if kind == "screen":
        return "feature-surface"
    if kind == "overlay":
        return "overlay"
    if "Presenter" in category:
        return "presenter"
    if kind == "component":
        return "building-block"
    return "scene"


def classify_state_label(title: str, variant: str) -> str:
    if title and title.lower() not in {"preview", "default"}:
        return title
    if variant:
        return variant
    return title or "Default"


def build_taxonomy(category: str, title: str, profile: dict) -> dict:
    surface, surface_variant = split_surface(category)
    feature = classify_feature(category, profile)
    kind = classify_asset_kind(category, surface)
    surface_role = classify_surface_role(surface, category, kind)
    state_label = classify_state_label(title, surface_variant)
    state_group = surface_variant or "Default"
    return {
        "feature": feature,
        "surface": surface,
        "surfaceVariant": surface_variant,
        "surfaceKey": slugify(f"{feature}-{surface}"),
        "stateLabel": state_label,
        "stateGroup": state_group,
        "stateKey": slugify(state_label),
        "assetKind": kind,
        "surfaceRole": surface_role,
    }


def build_manifest_indexes(items: list[dict]) -> dict:
    feature_counts = Counter(item["feature"] for item in items)
    surface_counts = Counter(item["surface"] for item in items)
    kind_counts = Counter(item["assetKind"] for item in items)
    role_counts = Counter(item["surfaceRole"] for item in items)
    return {
        "featureCounts": dict(feature_counts),
        "surfaceCounts": dict(surface_counts),
        "assetKindCounts": dict(kind_counts),
        "surfaceRoleCounts": dict(role_counts),
    }

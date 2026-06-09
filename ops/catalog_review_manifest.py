from __future__ import annotations

from collections import Counter
import hashlib
import json
import struct
import zlib
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


def read_png_transparent_margin(path: Path) -> bool:
    """True if the asset is rendered on a transparent canvas (a component/overlay
    floating on emptiness) rather than a full-bleed screen.

    This is the only honest screen-vs-component signal: capture renders screens,
    overlays, and components all at the same 1179x2556 size, so dimensions and
    category names can't tell them apart — but a component leaves its margins
    transparent while a real screen fills them. We decode just the first scanline
    (cheap) and read its top-left and top-right pixel alpha. Anything that isn't a
    readable 8-bit RGBA PNG is treated as opaque, so a decode failure can never
    fabricate a false component.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read()
    except OSError:
        return False
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 26:
        return False
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    if color_type != 6 or bit_depth != 8 or width < 1:
        return False  # only 8-bit RGBA carries alpha; treat everything else as opaque
    idat = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        ctype = data[offset + 4:offset + 8]
        if ctype == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        elif ctype == b"IEND":
            break
        offset += 12 + length
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return False
    stride = 4 * width
    if len(raw) < 1 + stride:
        return False
    # First scanline only. Its up/upleft neighbours are 0, so Sub(1)/Paeth(4)
    # reduce to "add left", Average(3) to "add left//2"; None(0)/Up(2) leave bytes raw.
    filter_type = raw[0]
    row = bytearray(raw[1:1 + stride])
    if filter_type in (1, 4):
        for i in range(4, len(row)):
            row[i] = (row[i] + row[i - 4]) & 0xFF
    elif filter_type == 3:
        for i in range(4, len(row)):
            row[i] = (row[i] + row[i - 4] // 2) & 0xFF
    top_left_alpha = row[3]
    top_right_alpha = row[4 * (width - 1) + 3]
    return top_left_alpha < 16 and top_right_alpha < 16


def load_catalog_index(source_root: Path) -> dict[str, dict]:
    """Read the source-of-truth taxonomy index emitted by the iOS snapshot run.

    Returns ``{category: {kind, feature, screen, backing}}`` keyed by the raw
    category string (which matches ``normalize_label(category_dir)``); ``backing``
    is the source-declared production view type (absent for inline-composed
    surfaces). The full entry dict is preserved; unknown keys ride along inert.
    An empty dict when
    the file is absent or malformed — the gallery then falls back to the
    pixel/regex heuristics, so legacy/un-blessed artifacts still render."""
    index_path = source_root / "catalog_index.json"
    if not index_path.is_file():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    surfaces = data.get("surfaces", {}) if isinstance(data, dict) else {}
    if not isinstance(surfaces, dict):
        return {}
    # Drop corrupted per-entry values (string/list instead of object) so a bad
    # entry falls back to heuristics for that one category rather than crashing.
    return {category: entry for category, entry in surfaces.items() if isinstance(entry, dict)}


def load_ui_graph(source_root: Path) -> dict:
    """Read optional ui_graph sidecar emitted next to snapshot artifacts."""
    graph_path = source_root / "ui_graph.json"
    if not graph_path.is_file():
        return {}
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("schema") != "kg.ui.graph.v1":
        return {}
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        return {}
    return data


def enrich_surface_index_with_graph(surfaces: list[dict], items: list[dict], graph_payload: dict) -> list[dict]:
    first_item_by_surface: dict[str, dict] = {}
    for item in items:
        first_item_by_surface.setdefault(item["surface"], item)

    nodes = {
        node["usr"]: node
        for node in graph_payload.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("usr"), str) and isinstance(node.get("name"), str)
    }
    deps: dict[str, set[str]] = {usr: set() for usr in nodes}
    users: dict[str, set[str]] = {usr: set() for usr in nodes}
    for edge in graph_payload.get("edges", []):
        if not isinstance(edge, dict):
            continue
        a = edge.get("from")
        b = edge.get("to")
        if a not in nodes or b not in nodes:
            continue
        deps[a].add(b)
        users[b].add(a)

    surface_nodes: dict[str, list[dict]] = {}
    for node in nodes.values():
        for surface_name in node.get("surface", []):
            if isinstance(surface_name, str):
                surface_nodes.setdefault(surface_name, []).append(node)

    enriched: list[dict] = []
    for surface in surfaces:
        item = first_item_by_surface.get(surface["surface"], {})
        backing = item.get("backing", "")
        matches = surface_nodes.get(surface["surface"], [])
        dependent_surfaces: set[str] = set()
        dep_names: set[str] = set()
        user_names: set[str] = set()
        external_in = 0
        for node in matches:
            usr = node["usr"]
            external_in += int(node.get("externalIn", 0) or 0)
            dep_names.update(nodes[dep_usr]["name"] for dep_usr in deps.get(usr, ()) if dep_usr in nodes)
            for user_usr in users.get(usr, ()):
                user_names.add(nodes[user_usr]["name"])
                for surface_name in nodes[user_usr].get("surface", []):
                    if surface_name != surface["surface"]:
                        dependent_surfaces.add(surface_name)

        if not backing:
            status = "no-backing"
        elif not graph_payload:
            status = "graph-missing"
        elif not matches:
            status = "unresolved"
        elif len(matches) > 1:
            status = "ambiguous"
        else:
            status = "linked"

        health: list[str] = []
        if status != "linked":
            health.append(status)
        if status == "linked" and not user_names and external_in == 0:
            health.append("isolated")
        if len(dependent_surfaces) >= 3:
            health.append("high-impact")

        enriched_surface = dict(surface)
        enriched_surface["backing"] = backing
        enriched_surface["graph"] = {
            "status": status,
            "matchedNodeCount": len(matches),
            "depCount": len(dep_names),
            "userCount": len(user_names),
            "dependentSurfaceCount": len(dependent_surfaces),
            "externalIn": external_in,
            "deps": sorted(dep_names),
            "directUsers": sorted(user_names),
            "dependentSurfaces": sorted(dependent_surfaces),
            "health": health,
        }
        enriched.append(enriched_surface)
    return enriched


def collect_items(source_root: Path, profile: dict, *, release_marker: str = "pr878") -> list[dict]:
    index = load_catalog_index(source_root)
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
        transparent_margin = read_png_transparent_margin(path)
        declared = index.get(category)
        taxonomy = build_taxonomy(
            category, title, profile, transparent_margin=transparent_margin, declared=declared
        )
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
            "transparentMargin": transparent_margin,
            "category": category,
            "title": title,
            "promise": promise,
            "eligibility": eligibility,
            "lane": classify_lane(taxonomy["surfaceRole"], eligibility, taxonomy["sourceDeclared"]),
            "qualityTier": classify_quality_tier(promise, eligibility, hero_candidate),
            "newSincePr878": is_new_since_release(category, profile, release_marker),
            "heroCandidate": hero_candidate,
            **taxonomy,
        })
    return items


def build_manifest(
    items: list[dict],
    profile: dict,
    *,
    state_file: str | None = None,
    review_state: dict | None = None,
    source_root: Path | None = None,
) -> dict:
    counts = Counter(item["promise"] for item in items)
    category_counts = Counter(item["category"] for item in items)
    eligibility_counts = Counter(item["eligibility"] for item in items)
    indexes = build_manifest_indexes(items)
    graph_payload = load_ui_graph(source_root) if source_root else {}
    surfaces = enrich_surface_index_with_graph(build_surface_index(items), items, graph_payload)
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

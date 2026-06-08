from __future__ import annotations

from collections import Counter
import re


def normalize_label(text: str) -> str:
    return text.replace("_", " ").strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def split_surface(category: str) -> tuple[str, str]:
    """Split a snapshot category into (surfaceGroup, surfaceVariant).

    The capture convention is ``"<Group>"`` or ``"<Group> · <Variant>"``. The
    *group* is a family of related surfaces (e.g. "Reader"); the full category
    (e.g. "Reader · Quota") is the first-class *surface* you compare states in.
    """
    if " · " in category:
        group, variant = category.split(" · ", 1)
        return group.strip(), variant.strip()
    return category.strip(), ""


def classify_feature(category: str, profile: dict) -> str:
    for feature_def in profile.get("features", []):
        if any(needle in category for needle in feature_def["needles"]):
            return feature_def["name"]
    return "Misc"


def classify_asset_kind(category: str, group: str) -> str:
    text = f"{category} {group}"
    # A presenter is a dev harness even when its name embeds a screen token
    # ("Today Review Presenter" contains the "Today Review" screen token). Match
    # it first so a harness can never be mistaken for a shippable screen and get
    # held to feature-surface coverage it should never have.
    if "Presenter" in category:
        return "component"
    if any(token in text for token in (" View", "Bookshelf", "Knowledge Graph", "Reader ·", "Today Review", "Sync View", "Welcome")):
        return "screen"
    if any(token in text for token in (" Sheet", "Popover", "Picker", "Login", "Paywall")):
        return "overlay"
    if any(token in text for token in (" Presenter", "Components", "Controls", "Actions", "Sections", "Badge", "Ticker", "Toolbar", "Calendar", "Heatmap", "Capsule", "Chip", "Row", "Hero", "Banner", "Shimmer")):
        return "component"
    return "scene"


def classify_surface_role(group: str, category: str, kind: str) -> str:
    if kind == "screen":
        return "feature-surface"
    if kind == "overlay":
        return "overlay"
    if "Presenter" in category:
        return "presenter"
    if kind == "component":
        return "building-block"
    return "scene"


# --- State facet -----------------------------------------------------------
# The raw scenario title (PNG stem) is screenshot-first free text (448 distinct
# values across 996 shots). ``stateFacet`` distils it into a small, comparable
# vocabulary so a surface's scenes can be ordered by a canonical state sequence
# and cross-surface "show me every empty state" queries become possible.
# Rules are priority-ordered: first match wins.
# Each rule carries (a) the original English vocabulary, (b) English idioms that
# were silently leaking into ``default`` ("logged out", "with X", "wrapping",
# "bound clamp"; plus broadening a11y xxxl→xxl so standalone "XXL" matches), and
# (c) CJK tokens — the labels are bilingual but the regex was Latin-only, so ~46
# Chinese scenes fell through to default. Tokens are added only where the mapping
# is unambiguous; genuine design-spec labels (Typography, Palette, layout modes)
# are intentionally left in ``default``.
_STATE_FACET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("loading", re.compile(r"loading|shimmer|placeholder|skeleton|fetching|authenticat|deleting|saving|sync(ing)?|generating|in progress|下載中|載入中|同步中|計算中|產生中|處理中")),
    ("error", re.compile(r"error|fail|unavailable|offline|expired|exhausted|critical|denied|missing|invalid|conflict|revoked|\bout of\b|recovery")),
    ("empty", re.compile(r"\bempty\b|\bno \b|\bnone\b|\bzero\b|^0 |\bblank\b|first run|\bfresh\b|nothing|logged\s+out|signed\s+out|\bguest\b|\bunlearned\b|未登入")),
    ("a11y", re.compile(r"a11y|accessib|dynamic type|large numbers|xxl|\bbig text\b")),
    ("overflow", re.compile(r"\blong\b|overflow|truncat|stress|\bmany\b|\blarge\b|\bheavy\b|wrap|multiline|\bnarrow\b|\bdense\b|\bdepth\b|超長|密集")),
    ("bounds", re.compile(r"\bmin\b|\bmax\b|bounds?|minimum|maximum|\bshort\b|\bcompact\b|\bsingle\b|\btight\b|at maximum|at minimum|clamp|僅")),
    ("disabled", re.compile(r"disabled|locked|read.?only|paywall|gated|\bpro\b|\bfree\b|關閉|停用|鎖定|凍結")),
    ("selected", re.compile(r"selected|\bactive\b|\bfocus\b|highlight|expanded|collapsed?|toggled|revealed|展開|收合|選取")),
    ("populated", re.compile(r"populated|loaded|content|\bfull\b|\bgrid\b|\blist\b|multiple|stacked|\brich\b|\bmixed\b|\bboth\b|completed|progress|pending|\bdue\b|continue|session|\bhero\b|\bcard\b|\bwith\b|完成|部分|含")),
]
STATE_FACET_ORDER = [
    "default",
    "populated",
    "selected",
    "empty",
    "loading",
    "disabled",
    "bounds",
    "overflow",
    "error",
    "a11y",
]


def classify_state_facet(state_label: str) -> str:
    text = state_label.lower()
    if text in {"", "default", "preview", "normal"}:
        return "default"
    for name, pattern in _STATE_FACET_RULES:
        if pattern.search(text):
            return name
    return "default"


def state_facet_rank(facet: str) -> int:
    try:
        return STATE_FACET_ORDER.index(facet)
    except ValueError:
        return len(STATE_FACET_ORDER)


# --- Lane (structural role) & quality tier ---------------------------------
# ``lane`` is the single structural classification used as the gallery's primary
# segmentation. It answers "what kind of asset is this", not "how good is it".
LANE_ORDER = ["feature-surface", "overlay", "building-block", "engineering-only"]


def classify_lane(surface_role: str, eligibility: str) -> str:
    if surface_role == "feature-surface":
        return "feature-surface"
    if surface_role == "overlay":
        return "overlay"
    if surface_role == "presenter":
        return "engineering-only"
    if eligibility == "engineering":
        return "engineering-only"
    return "building-block"


# ``qualityTier`` is the orthogonal quality/convergence axis (hero ↔ weak). It is
# what powers hero/weak shortlisting and the "weak / cull" view. ``rejected`` is
# layered dynamically by the renderer from live review state, so the static tier
# only spans hero → marketing → weak → keep.
QUALITY_TIER_ORDER = ["hero", "marketing", "keep", "weak"]


def classify_quality_tier(promise: str, eligibility: str, hero_candidate: bool) -> str:
    if hero_candidate:
        return "hero"
    if eligibility == "marketing":
        return "marketing"
    if promise == "Weak":
        return "weak"
    return "keep"


# --- Coverage expectation (lane-aware) -------------------------------------
# A flat "10 facets per surface" target lies: of 142 surfaces ~44% are
# engineering-only harness and a third are pure building blocks, none of which
# ship as a user-facing screen. Coverage is only a meaningful backlog for the
# surfaces a user actually sees in distinct states. So the gap is measured
# against the facets each *lane* is genuinely expected to cover; lanes with an
# empty expectation are reported as "not tracked" (—), never as a gap.
EXPECTED_FACETS_BY_LANE: dict[str, tuple[str, ...]] = {
    # A shippable screen should prove its ship-critical states.
    "feature-surface": ("default", "populated", "empty", "loading", "error"),
    # A sheet/popover mainly varies between idle, in-flight, and failure.
    "overlay": ("default", "loading", "error"),
    # Building blocks are covered by their *variants*, not a facet checklist.
    "building-block": (),
    # Dev harness / presenters never ship — no coverage target.
    "engineering-only": (),
}


def expected_facets_for_lane(lane: str) -> tuple[str, ...]:
    return EXPECTED_FACETS_BY_LANE.get(lane, ())


def build_taxonomy(category: str, title: str, profile: dict) -> dict:
    group, surface_variant = split_surface(category)
    feature = classify_feature(category, profile)
    kind = classify_asset_kind(category, group)
    surface_role = classify_surface_role(group, category, kind)
    state_label = title or surface_variant or "Default"
    facet = classify_state_facet(state_label)
    return {
        "feature": feature,
        "surfaceGroup": group,
        "surfaceGroupKey": slugify(f"{feature}-{group}"),
        # The full category is the first-class surface (the unit you compare states in).
        "surface": category,
        "surfaceVariant": surface_variant,
        "surfaceKey": slugify(f"{feature}-{category}"),
        "stateLabel": state_label,
        "stateFacet": facet,
        "stateFacetRank": state_facet_rank(facet),
        "assetKind": kind,
        "surfaceRole": surface_role,
    }


def build_manifest_indexes(items: list[dict]) -> dict:
    return {
        "featureCounts": dict(Counter(item["feature"] for item in items)),
        "surfaceGroupCounts": dict(Counter(item["surfaceGroup"] for item in items)),
        "surfaceCounts": dict(Counter(item["surface"] for item in items)),
        "assetKindCounts": dict(Counter(item["assetKind"] for item in items)),
        "surfaceRoleCounts": dict(Counter(item["surfaceRole"] for item in items)),
        "laneCounts": dict(Counter(item["lane"] for item in items)),
        "qualityTierCounts": dict(Counter(item["qualityTier"] for item in items)),
        "stateFacetCounts": dict(Counter(item["stateFacet"] for item in items)),
    }


def _rollup_eligibility(values: set[str]) -> str:
    """Collapse a surface's per-scene eligibilities to its best (most usable) tier."""
    for tier in ("marketing", "review", "engineering"):
        if tier in values:
            return tier
    return "engineering"


def build_surface_index(items: list[dict]) -> list[dict]:
    """First-class surface objects: one entry per full surface (category).

    Each surface carries its scene roster (a scene = one clusterID = a state
    rendered light+dark), the state facets it covers, the facets it is missing
    (the coverage gap), and lane / quality rollups. This is what lets the gallery
    treat the surface — not the PNG — as the unit of management.
    """
    by_surface: dict[str, list[dict]] = {}
    for item in items:
        by_surface.setdefault(item["surfaceKey"], []).append(item)

    surfaces: list[dict] = []
    for key, group in by_surface.items():
        first = group[0]
        scenes = {item["clusterID"] for item in group}
        facet_scenes: dict[str, set[str]] = {}
        for item in group:
            facet_scenes.setdefault(item["stateFacet"], set()).add(item["clusterID"])
        facets_present = sorted(facet_scenes, key=state_facet_rank)
        lane = first["lane"]
        expected = expected_facets_for_lane(lane)
        present_set = set(facets_present)
        # List/container feature-surfaces (Bookshelf View, Podcast Home View…)
        # have no separate idle "default" shot — their canonical resting state IS
        # "populated" (content already loaded). When populated is present but
        # default is not, default is not a real gap; drop it so the backlog stays
        # honest instead of demanding a default shot that conceptually can't exist.
        if lane == "feature-surface" and "populated" in present_set and "default" not in present_set:
            expected = tuple(facet for facet in expected if facet != "default")
        missing = [facet for facet in expected if facet not in present_set]
        surfaces.append({
            "surfaceKey": key,
            "surface": first["surface"],
            "surfaceGroup": first["surfaceGroup"],
            "surfaceGroupKey": first["surfaceGroupKey"],
            "feature": first["feature"],
            "lane": lane,
            "surfaceRole": first["surfaceRole"],
            "promise": first["promise"],
            "eligibility": _rollup_eligibility({item["eligibility"] for item in group}),
            "sceneCount": len(scenes),
            "shotCount": len(group),
            "facetsPresent": facets_present,
            "facetSceneCounts": {facet: len(ids) for facet, ids in facet_scenes.items()},
            # Lane-aware coverage: a gap is an *expected* facet that is absent.
            # coverageTracked separates "all expected states present" (gap 0) from
            # "this lane has no coverage target at all" (— in the UI).
            "expectedFacets": list(expected),
            "missingFacets": missing,
            "coverageGap": len(missing),
            "coverageTracked": bool(expected),
            "heroCandidate": any(item["heroCandidate"] for item in group),
            "marketingScenes": len({item["clusterID"] for item in group if item["eligibility"] == "marketing"}),
            "newScenes": len({item["clusterID"] for item in group if item["newSincePr878"]}),
        })
    surfaces.sort(key=lambda s: (s["feature"], s["surfaceGroup"], s["surface"]))
    return surfaces

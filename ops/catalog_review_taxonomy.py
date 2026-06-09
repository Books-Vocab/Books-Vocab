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


_OVERLAY_TOKENS = (" Sheet", "Popover", "Picker", "Login", "Paywall", "Overlay", "Translation")


def classify_asset_kind(category: str, group: str, transparent_margin: bool = False) -> str:
    text = f"{category} {group}"
    # A presenter is a dev harness even when its name embeds a screen token
    # ("Today Review Presenter" contains the "Today Review" screen token). Match
    # it first so a harness can never be mistaken for a shippable screen and get
    # held to feature-surface coverage it should never have.
    if "Presenter" in category:
        return "component"
    # The pixel signal beats the name. Capture renders components/overlays on a
    # transparent 1179x2556 canvas, so a transparent margin means "not a full-bleed
    # screen" no matter how screen-like the category name is (e.g. "Reader ·
    # Translation" is an overlay, "Bookshelf" card shots are components). This is
    # what name-token matching alone gets wrong.
    if transparent_margin:
        if any(token in text for token in _OVERLAY_TOKENS):
            return "overlay"
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
    # NOTE: "pro"/"free" name a subscription *tier*, not a disabled control — they
    # used to live here and bucketed active subscriptions ("Pro Active") as
    # disabled, the opposite of their meaning. Tier labels now fall through to
    # selected ("active") / default; only genuine locked/gated states stay here.
    ("disabled", re.compile(r"disabled|locked|read.?only|paywall|gated|關閉|停用|鎖定|凍結")),
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


def classify_lane(surface_role: str, eligibility: str, source_declared: bool = False) -> str:
    if surface_role == "feature-surface":
        return "feature-surface"
    if surface_role == "overlay":
        return "overlay"
    if surface_role == "presenter":
        return "engineering-only"
    # Source-declared buildingBlock is authoritative: a stale profile eligibility
    # must NOT demote a real, declared component into the engineering lane.
    # (declared wins — no consumption-side profile patch.)
    if source_declared:
        return "building-block"
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


# A feature-surface that exhibits any of these is data-bearing (it loads/holds
# content) and therefore owes the full data lifecycle. A surface that shows none
# of them is static/presentational and owes only its default state.
_DATA_LIFECYCLE_FACETS = frozenset({"populated", "empty", "loading"})


# --- Source-declared taxonomy (ground truth) -------------------------------
# `CatalogScene.swift` is the single source of truth for a surface's kind/feature/
# screen. The iOS snapshot run emits `catalog_index.json`, and these maps translate
# its enum raw values into the gallery's classification vocabulary — retiring the
# transparent-margin pixel sniff + "Presenter"/" View" regex for any category the
# index covers. Heuristics remain the fallback when the index is absent (legacy or
# un-blessed artifacts), so `declared=None` reproduces the old behaviour exactly.
_DECLARED_KIND_TO_ASSET = {
    "featureScreen": "screen",
    "overlay": "overlay",
    "buildingBlock": "component",
    "engineering": "component",
}
_DECLARED_KIND_TO_SURFACE_ROLE = {
    "featureScreen": "feature-surface",
    "overlay": "overlay",
    "buildingBlock": "building-block",
    "engineering": "presenter",
}
_DECLARED_FEATURE_DISPLAY = {
    "reader": "Reader",
    "vocabulary": "Vocabulary",
    "notebook": "Notebook",
    "bookshelf": "Bookshelf",
    "podcast": "Podcast",
    "review": "Review",
    "settings": "Settings",
    "monetization": "Monetization",
    "onboarding": "Onboarding",
    "misc": "Misc",
}


def build_taxonomy(
    category: str,
    title: str,
    profile: dict,
    transparent_margin: bool = False,
    declared: dict | None = None,
) -> dict:
    group, surface_variant = split_surface(category)
    if declared:
        feature = _DECLARED_FEATURE_DISPLAY.get(declared.get("feature", ""), classify_feature(category, profile))
        kind = _DECLARED_KIND_TO_ASSET.get(declared.get("kind", ""), classify_asset_kind(category, group, transparent_margin))
        surface_role = _DECLARED_KIND_TO_SURFACE_ROLE.get(declared.get("kind", ""), classify_surface_role(group, category, kind))
        screen = declared.get("screen", "")
        backing = declared.get("backing", "")
    else:
        feature = classify_feature(category, profile)
        kind = classify_asset_kind(category, group, transparent_margin)
        surface_role = classify_surface_role(group, category, kind)
        screen = ""
        backing = ""
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
        # Source-declared full-screen identity (empty for overlays/blocks and when
        # the surface predates the index). Powers the gallery's 1:1 screen↔surface view.
        "screen": screen,
        "backing": backing,
        "sourceDeclared": bool(declared),
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
        # A surface's lane is the majority lane across its shots, not the first
        # shot's. Some categories mix component shots (transparent canvas) with a
        # couple of real screen shots (e.g. "Bookshelf" = mostly cards + a few
        # full-bleed states); a first-shot heuristic would flip the whole surface
        # on one stray shot. Majority keeps the surface's identity stable.
        lane = Counter(item["lane"] for item in group).most_common(1)[0][0]
        surface_role = Counter(item["surfaceRole"] for item in group).most_common(1)[0][0]
        expected = expected_facets_for_lane(lane)
        present_set = set(facets_present)
        if lane == "feature-surface":
            # A flat per-lane expectation lies for static screens: an onboarding
            # flow, a settings form, or a presentational card has no empty/
            # loading/error state, yet the lane checklist demands all three. A
            # surface owes the data lifecycle only if it actually exhibits one of
            # its states (populated/empty/loading); otherwise it owes just the
            # default. This is derived from the shots themselves — no per-surface
            # curation — so it stays self-maintaining as new screens are added.
            if not (present_set & _DATA_LIFECYCLE_FACETS):
                expected = ("default",)
            # List/container feature-surfaces (Bookshelf View, Podcast Home View…)
            # have no separate idle "default" shot — their canonical resting state
            # IS "populated" (content already loaded). When populated is present
            # but default is not, default is not a real gap; drop it so the
            # backlog stays honest instead of demanding a conceptually-absent shot.
            elif "populated" in present_set and "default" not in present_set:
                expected = tuple(facet for facet in expected if facet != "default")
        missing = [facet for facet in expected if facet not in present_set]
        surfaces.append({
            "surfaceKey": key,
            "surface": first["surface"],
            "surfaceGroup": first["surfaceGroup"],
            "surfaceGroupKey": first["surfaceGroupKey"],
            "feature": first["feature"],
            "lane": lane,
            "surfaceRole": surface_role,
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

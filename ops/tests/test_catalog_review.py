from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load_module("catalog_review_taxonomy", ROOT / "ops" / "catalog_review_taxonomy.py")
manifest_module = load_module("catalog_review_manifest", ROOT / "ops" / "catalog_review_manifest.py")
profile_module = load_module("catalog_review_profile", ROOT / "ops" / "catalog_review_profile.py")
state_module = load_module("catalog_review_state", ROOT / "ops" / "catalog_review_state.py")
renderer_module = load_module("catalog_review_renderer", ROOT / "ops" / "catalog_review_renderer.py")
sync_module = load_module("catalog_review_sync", ROOT / "ops" / "catalog_review_sync.py")
render_entry_module = load_module("render_catalog_review", ROOT / "ops" / "render_catalog_review.py")
build_asset_id = manifest_module.build_asset_id
REVIEW_CLI = ROOT / "ops" / "catalog_review_cli.py"


def _make_rgba_png(path: Path, width: int, height: int, *, corner_alpha: int) -> None:
    """Write a minimal 8-bit RGBA PNG whose left/right column has the given alpha
    (the rest opaque), so tests can simulate a component on a transparent canvas
    (corner_alpha=0) vs a full-bleed screen (corner_alpha=255) with no PIL dep."""
    import struct
    import zlib

    def chunk(typ: bytes, payload: bytes) -> bytes:
        body = typ + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = bytearray()
    for _y in range(height):
        raw.append(0)  # filter: None
        for x in range(width):
            edge = x == 0 or x == width - 1
            raw += bytes((10, 20, 30, corner_alpha if edge else 255))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
    path.write_bytes(png)


def test_read_png_transparent_margin_separates_component_from_screen(tmp_path: Path):
    """Components are rendered centered on a transparent 1179x2556 canvas, screens
    fill it — same size, so only the pixel alpha tells them apart. The detector
    reads the first scanline's corner alpha."""
    comp = tmp_path / "component.png"
    screen = tmp_path / "screen.png"
    _make_rgba_png(comp, 40, 30, corner_alpha=0)     # transparent margins → component
    _make_rgba_png(screen, 40, 30, corner_alpha=255)  # opaque → full-bleed screen
    assert manifest_module.read_png_transparent_margin(comp) is True
    assert manifest_module.read_png_transparent_margin(screen) is False
    # non-PNG / unreadable must be treated as opaque (never a false component)
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not a png")
    assert manifest_module.read_png_transparent_margin(junk) is False


def test_collect_items_assigns_stable_asset_ids(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    items = manifest_module.collect_items(source_root, profile)
    assert items
    assert len({item["assetID"] for item in items}) == len(items)
    sample = next(item for item in items if item["category"] == "Settings View")
    assert sample["assetID"]
    assert sample["clusterID"]
    assert "--" in sample["assetID"]
    assert " " not in sample["assetID"]
    assert sample["feature"] == "Settings"
    # depth-0 category: surface == surfaceGroup == category
    assert sample["surface"] == "Settings View"
    assert sample["surfaceGroup"] == "Settings View"
    assert sample["assetKind"] == "screen"
    assert sample["surfaceRole"] == "feature-surface"
    assert sample["lane"] == "feature-surface"
    assert sample["stateFacet"]
    assert sample["qualityTier"]


def test_collect_items_builds_feature_surface_state_taxonomy(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    reader_dir = source_root / "iPhone 15 Pro portrait" / "Reader_·_Translation"
    reader_dir.mkdir(parents=True)
    (reader_dir / "Hero.png").write_bytes(b"png")
    settings_dir = source_root / "iPhone 15 Pro portrait" / "Settings_·_ParamRow"
    settings_dir.mkdir(parents=True)
    (settings_dir / "Subscribed.png").write_bytes(b"png")

    items = manifest_module.collect_items(source_root, profile)
    by_category = {item["category"]: item for item in items}

    reader = by_category["Reader · Translation"]
    assert reader["feature"] == "Reader"
    # depth-1 category: surface is the FULL category (first-class), surfaceGroup is the pre-· token
    assert reader["surface"] == "Reader · Translation"
    assert reader["surfaceGroup"] == "Reader"
    assert reader["surfaceVariant"] == "Translation"
    assert reader["stateLabel"] == "Hero"
    assert reader["assetKind"] == "screen"

    settings = by_category["Settings · ParamRow"]
    assert settings["feature"] == "Settings"
    assert settings["surface"] == "Settings · ParamRow"
    assert settings["surfaceGroup"] == "Settings"
    assert settings["surfaceVariant"] == "ParamRow"
    assert settings["stateLabel"] == "Subscribed"
    assert settings["assetKind"] == "component"


def test_collect_items_consumes_catalog_index_ground_truth(tmp_path: Path):
    """The source-of-truth ``catalog_index.json`` emitted by the iOS snapshot run
    overrides the pixel/regex guess. A podcast-player surface *declared* as a
    ``featureScreen`` is a screen even though its PNG carries a transparent margin
    (which the heuristic alone would read as a component)."""
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Podcast_Player_View"
    img_dir.mkdir(parents=True)
    # transparent margin → the pixel heuristic would call this a "component"
    _make_rgba_png(img_dir / "Preview_episode.png", 40, 30, corner_alpha=0)
    (source_root / "catalog_index.json").write_text(
        json.dumps({
            "version": 1,
            "surfaces": {
                "Podcast Player View": {
                    "kind": "featureScreen", "feature": "podcast", "screen": "podcastPlayer",
                },
            },
        }),
        encoding="utf-8",
    )

    items = manifest_module.collect_items(source_root, profile)
    item = next(i for i in items if i["category"] == "Podcast Player View")
    assert item["assetKind"] == "screen"            # index beats the transparent-margin pixel guess
    assert item["surfaceRole"] == "feature-surface"
    assert item["lane"] == "feature-surface"
    assert item["feature"] == "Podcast"
    assert item["screen"] == "podcastPlayer"
    assert item["backing"] == ""


def test_collect_items_survives_malformed_index_entry(tmp_path: Path):
    """A corrupted entry value (string instead of dict, e.g. hand-edited JSON)
    must fall back to heuristics for that category — not crash with AttributeError.
    Honours load_catalog_index's "malformed → fallback" contract per-entry."""
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    img_dir.mkdir(parents=True)
    _make_rgba_png(img_dir / "Signed_out.png", 40, 30, corner_alpha=255)  # opaque → screen
    (source_root / "catalog_index.json").write_text(
        json.dumps({"version": 1, "surfaces": {"Settings View": "not-a-dict"}}),
        encoding="utf-8",
    )
    items = manifest_module.collect_items(source_root, profile)  # must not raise
    item = next(i for i in items if i["category"] == "Settings View")
    assert item["assetKind"] == "screen"      # heuristic fallback for the bad entry
    assert item["sourceDeclared"] is False
    assert item["screen"] == ""
    assert item["backing"] == ""


def test_collect_items_falls_back_to_heuristics_without_index(tmp_path: Path):
    """No ``catalog_index.json`` (legacy / un-blessed artifact) → the pixel/regex
    heuristics still classify, and the declared ``screen`` is empty."""
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    img_dir.mkdir(parents=True)
    _make_rgba_png(img_dir / "Signed_out.png", 40, 30, corner_alpha=255)  # opaque → full-bleed screen
    items = manifest_module.collect_items(source_root, profile)
    item = next(i for i in items if i["category"] == "Settings View")
    assert item["assetKind"] == "screen"
    assert item["surfaceRole"] == "feature-surface"
    assert item["screen"] == ""
    assert item["backing"] == ""


def test_collect_items_preserve_declared_backing_name(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    img_dir.mkdir(parents=True)
    _make_rgba_png(img_dir / "Signed_out.png", 40, 30, corner_alpha=255)
    (source_root / "catalog_index.json").write_text(
        json.dumps({
            "version": 1,
            "surfaces": {
                "Settings View": {
                    "kind": "featureScreen",
                    "feature": "settings",
                    "screen": "settings",
                    "backing": "SettingsPresenter",
                },
            },
        }),
        encoding="utf-8",
    )
    items = manifest_module.collect_items(source_root, profile)
    item = next(i for i in items if i["category"] == "Settings View")
    assert item["backing"] == "SettingsPresenter"


def test_build_manifest_enriches_surfaces_with_ui_graph_summary(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    img_dir.mkdir(parents=True)
    _make_rgba_png(img_dir / "Signed_out.png", 40, 30, corner_alpha=255)
    (source_root / "catalog_index.json").write_text(
        json.dumps({
            "version": 1,
            "surfaces": {
                "Settings View": {
                    "kind": "featureScreen",
                    "feature": "settings",
                    "screen": "settings",
                    "backing": "SettingsPresenter",
                },
            },
        }),
        encoding="utf-8",
    )
    (source_root / "ui_graph.json").write_text(
        json.dumps({
            "schema": "kg.ui.graph.v1",
            "nodes": [
                {"usr": "s:settings", "name": "SettingsPresenter", "kind": "struct", "surface": ["Settings View"], "externalIn": 1},
                {"usr": "s:plan", "name": "SettingsPlanComparisonTable", "kind": "struct", "surface": [], "externalIn": 0},
                {"usr": "s:detail", "name": "SettingsAccountDetailView", "kind": "struct", "surface": ["Settings Account Detail"], "externalIn": 0},
            ],
            "edges": [
                {"from": "s:settings", "to": "s:plan"},
                {"from": "s:detail", "to": "s:settings"},
            ],
        }),
        encoding="utf-8",
    )
    items = manifest_module.collect_items(source_root, profile)
    manifest = manifest_module.build_manifest(items, profile, source_root=source_root)
    surface = next(s for s in manifest["surfaces"] if s["surface"] == "Settings View")
    assert surface["backing"] == "SettingsPresenter"
    assert surface["graph"]["status"] == "linked"
    assert surface["graph"]["depCount"] == 1
    assert surface["graph"]["userCount"] == 1
    assert surface["graph"]["externalIn"] == 1
    assert surface["graph"]["dependentSurfaceCount"] == 1
    assert surface["graph"]["deps"] == ["SettingsPlanComparisonTable"]
    assert surface["graph"]["dependentSurfaces"] == ["Settings Account Detail"]
    assert surface["graph"]["health"] == []


def test_build_manifest_marks_missing_graph_linkage_states(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    img_dir = source_root / "iPhone 15 Pro portrait" / "Podcast_Shelf"
    img_dir.mkdir(parents=True)
    _make_rgba_png(img_dir / "Default.png", 40, 30, corner_alpha=0)
    (source_root / "catalog_index.json").write_text(
        json.dumps({
            "version": 1,
            "surfaces": {
                "Podcast Shelf": {
                    "kind": "buildingBlock",
                    "feature": "podcast",
                },
                "Podcast Hero": {
                    "kind": "buildingBlock",
                    "feature": "podcast",
                    "backing": "PodcastSeriesHero",
                },
            },
        }),
        encoding="utf-8",
    )
    items = manifest_module.collect_items(source_root, profile)
    items.append({
        **items[0],
        "category": "Podcast Hero",
        "surface": "Podcast Hero",
        "surfaceKey": "podcast-podcast-hero",
        "surfaceGroup": "Podcast",
        "surfaceGroupKey": "podcast-podcast",
        "stateLabel": "Default",
        "clusterID": "podcast-hero--default--00",
        "assetID": "podcast-hero--default--asset",
        "backing": "PodcastSeriesHero",
    })
    manifest = manifest_module.build_manifest(items, profile, source_root=source_root)
    shelf = next(s for s in manifest["surfaces"] if s["surface"] == "Podcast Shelf")
    hero = next(s for s in manifest["surfaces"] if s["surface"] == "Podcast Hero")
    assert shelf["graph"]["status"] == "no-backing"
    assert shelf["graph"]["health"] == ["no-backing"]
    assert hero["graph"]["status"] == "graph-missing"
    assert hero["graph"]["health"] == ["graph-missing"]


def _surface_item(surface, lane, surface_role, cluster, facet, **extra):
    base = {
        "surfaceKey": surface.lower().replace(" ", "-"),
        "surface": surface,
        "surfaceGroup": surface.split(" · ")[0],
        "surfaceGroupKey": surface.split(" · ")[0].lower().replace(" ", "-"),
        "feature": surface.split(" · ")[0],
        "lane": lane,
        "surfaceRole": surface_role,
        "promise": "Continue",
        "eligibility": "review",
        "clusterID": cluster,
        "stateFacet": facet,
        "heroCandidate": False,
        "newSincePr878": False,
    }
    base.update(extra)
    return base


def test_surface_index_computes_lane_aware_coverage_gap():
    """Coverage gap must be measured against the facets a lane is *expected* to
    cover, not a flat 10-facet target — otherwise engineering-only harness rows
    and pure building blocks fabricate gaps they should never be held to."""
    taxonomy = sys.modules["catalog_review_taxonomy"]

    items = [
        # feature-surface with only default + populated present (missing empty/loading/error)
        _surface_item("Bookshelf View", "feature-surface", "feature-surface", "c1", "default"),
        _surface_item("Bookshelf View", "feature-surface", "feature-surface", "c2", "populated"),
        # engineering-only harness — must carry NO coverage target
        _surface_item("Translation Vocab Presenter", "engineering-only", "presenter", "c3", "default"),
        # building block — variant-driven, not facet-gap-tracked
        _surface_item("iCloud Progress Badge", "building-block", "building-block", "c4", "default"),
    ]
    surfaces = {s["surface"]: s for s in taxonomy.build_surface_index(items)}

    fs = surfaces["Bookshelf View"]
    assert fs["expectedFacets"] == ["default", "populated", "empty", "loading", "error"]
    assert fs["coverageTracked"] is True
    assert set(fs["missingFacets"]) == {"empty", "loading", "error"}
    assert fs["coverageGap"] == 3

    eng = surfaces["Translation Vocab Presenter"]
    assert eng["expectedFacets"] == []
    assert eng["coverageTracked"] is False
    assert eng["missingFacets"] == []
    assert eng["coverageGap"] == 0

    block = surfaces["iCloud Progress Badge"]
    assert block["coverageTracked"] is False
    assert block["coverageGap"] == 0


def test_state_facet_classifies_cjk_and_english_edge_labels():
    """The facet classifier is English-regex-first, so CJK scene labels and a
    handful of English idioms (logged out / with X / wrapping / bound clamp)
    silently fell into ``default``, inflating the bucket and hiding real state
    coverage. Verify the semantically-clear ones now route correctly while
    genuine design-spec labels stay ``default``."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    f = taxonomy.classify_state_facet

    # English idioms that were leaking into default
    assert f("Logged Out") == "empty"
    assert f("Signed out · with vocab") == "empty"  # signed-out wins over "with"
    assert f("With Books") == "populated"
    assert f("With notebooks · follow global") == "populated"
    assert f("Wrapping") == "overflow"          # \bwrap\b never matched -ing
    assert f("Lower bound clamp") == "bounds"   # rule said "bounds" not "bound"
    assert f("Over 100% (clamped)") == "bounds"
    assert f("XXL · auto-pause off") == "a11y"

    # CJK labels — pure-English regex was blind to all of these
    assert f("超長單字") == "overflow"
    assert f("下載中 (25%)") == "loading"
    assert f("未登入 無同步列") == "empty"
    assert f("自動同步關閉") == "disabled"
    assert f("自訂模式 展開參數") == "selected"
    assert f("僅書名") == "bounds"
    assert f("部分已解釋") == "populated"

    # Negative: design-system spec / neutral labels must stay default,
    # and "logged in" must NOT be mistaken for the logged-out empty state.
    assert f("Typography") == "default"
    assert f("Palette · Dark") == "default"
    assert f("Logged in") == "default"


def test_subscription_tier_is_not_a_disabled_state():
    """A subscription tier label ("Pro", "Free") names *which plan*, not a
    disabled control. The disabled rule was matching the bare tokens \\bpro\\b /
    \\bfree\\b, so an *active* subscription ("Pro Active", "Subscribed · Pro
    Active") was bucketed as ``disabled`` — the exact opposite of its meaning,
    polluting the disabled facet and hiding these as default/selected states."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    f = taxonomy.classify_state_facet

    # Tier labels must NOT read as disabled
    assert f("Pro Active") != "disabled"
    assert f("Subscribed · Pro Active") != "disabled"
    assert f("Pro active (renewing)") != "disabled"
    assert f("Free Preview") == "default"
    assert f("Initials · Pro") == "default"
    assert f("Initials · Free") == "default"
    assert f("Free vs Pro") == "default"
    # "active" is the meaningful state for an active plan
    assert f("Pro Active") == "selected"

    # Genuine disabled / locked states must STILL classify as disabled
    assert f("Disabled pair") == "disabled"
    assert f("Both disabled") == "disabled"
    assert f("自動同步關閉") == "disabled"
    assert f("Paywall") == "disabled"
    assert f("Gated") == "disabled"
    assert f("Locked") == "disabled"


def test_lane_and_feature_classification_corrections():
    """Presenter (dev harness) must never be read as a shippable screen, and the
    feature needles must claim the surfaces that legitimately belong to a feature
    while leaving genuinely cross-cutting ones (design tokens) in Misc."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")

    # "Today Review Presenter" embeds the "Today Review" screen token but is a
    # presenter harness — Presenter must win, landing it in engineering-only.
    assert taxonomy.classify_asset_kind("Today Review Presenter", "Today Review") == "component"
    tax = taxonomy.build_taxonomy("Today Review Presenter", "Default", profile)
    assert tax["surfaceRole"] == "presenter"
    assert taxonomy.classify_lane("presenter", "review") == "engineering-only"

    # feature needles claim the surfaces that were falling into Misc
    assert taxonomy.classify_feature("Translation Vocab Presenter", profile) == "Vocabulary"
    assert taxonomy.classify_feature("KG Empty State", profile) == "Vocabulary"
    assert taxonomy.classify_feature("Delete Account Sheet", profile) == "Settings"
    # genuinely cross-cutting categories stay Misc (honest, not forced)
    assert taxonomy.classify_feature("Design Tokens", profile) == "Misc"


def test_declared_building_block_lane_ignores_stale_profile_eligibility():
    """Source-declared buildingBlock must lane as building-block even when the
    (stale) profile marks its eligibility 'engineering' — declared kind wins, no
    consumption-side profile patch. Regression: a vocab component (e.g. Selection
    Toolbar, reclassified from eng→block) was rendering as engineering-only because
    the profile eligibility overrode the declared kind."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    # declared buildingBlock (surfaceRole building-block) wins over engineering eligibility
    assert taxonomy.classify_lane("building-block", "engineering", source_declared=True) == "building-block"
    # declared engineering (surfaceRole presenter) is still engineering-only
    assert taxonomy.classify_lane("presenter", "review", source_declared=True) == "engineering-only"
    # legacy / un-declared artifacts keep the old eligibility-based demotion
    assert taxonomy.classify_lane("building-block", "engineering", source_declared=False) == "engineering-only"


def test_list_surface_default_populated_equivalence():
    """A list/container feature-surface whose resting state IS 'populated' has no
    separate idle 'default' shot — default must not be reported as a gap. But a
    surface that does ship a default shot still expects the full set."""
    taxonomy = sys.modules["catalog_review_taxonomy"]

    list_items = [
        _surface_item("Bookshelf View", "feature-surface", "feature-surface", "c1", "populated"),
        _surface_item("Bookshelf View", "feature-surface", "feature-surface", "c2", "empty"),
    ]
    surf = {s["surface"]: s for s in taxonomy.build_surface_index(list_items)}["Bookshelf View"]
    assert "default" not in surf["expectedFacets"]   # populated covers the idle state
    assert "default" not in surf["missingFacets"]

    # Synthetic name: the real "Stats View" is populated-only in production, so a
    # neutral label avoids implying production behaviour that's actually the
    # opposite. A screen that DOES ship a distinct idle default keeps the full set.
    with_default = [
        _surface_item("Param Form View", "feature-surface", "feature-surface", "d1", "default"),
        _surface_item("Param Form View", "feature-surface", "feature-surface", "d2", "populated"),
    ]
    surf2 = {s["surface"]: s for s in taxonomy.build_surface_index(with_default)}["Param Form View"]
    assert "default" in surf2["expectedFacets"]
    assert "default" not in surf2["missingFacets"]


def test_static_feature_surface_does_not_owe_the_data_lifecycle():
    """A flat per-lane expectation makes the gap column lie: a static screen
    (onboarding steps, a settings form, a presentational card) that legitimately
    has no empty/loading/error state gets flagged as missing all three — noise,
    not backlog. A surface owes the data lifecycle only if it actually exhibits
    one (populated/empty/loading); otherwise it owes just `default`. Derived from
    the shots themselves, so it stays self-maintaining (no per-surface curation)."""
    taxonomy = sys.modules["catalog_review_taxonomy"]

    # Static screen: only default + quality facets, never a data-lifecycle state.
    static_items = [
        _surface_item("Welcome", "feature-surface", "feature-surface", "w1", "default"),
        _surface_item("Welcome", "feature-surface", "feature-surface", "w2", "a11y"),
        _surface_item("Welcome", "feature-surface", "feature-surface", "w3", "overflow"),
    ]
    surf = {s["surface"]: s for s in taxonomy.build_surface_index(static_items)}["Welcome"]
    assert surf["expectedFacets"] == ["default"]
    assert surf["coverageGap"] == 0          # empty/loading/error are NOT owed
    assert surf["coverageTracked"] is True   # still a tracked feature-surface

    # Data-bearing screen: exhibits a lifecycle state, so it owes the full set
    # and a genuinely-absent lifecycle facet stays a real gap.
    data_items = [
        _surface_item("Today Review", "feature-surface", "feature-surface", "t1", "default"),
        _surface_item("Today Review", "feature-surface", "feature-surface", "t2", "populated"),
    ]
    surf2 = {s["surface"]: s for s in taxonomy.build_surface_index(data_items)}["Today Review"]
    assert "empty" in surf2["expectedFacets"]
    assert "empty" in surf2["missingFacets"]
    assert "loading" in surf2["missingFacets"]
    assert "error" in surf2["missingFacets"]


def test_asset_kind_uses_transparent_pixel_signal():
    """Name tokens can't tell a component from a screen (both are 1179x2556).
    A transparent margin (component rendered on an empty canvas) overrides the
    name-based screen guess; a full-bleed (opaque) asset keeps the screen verdict."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    ak = taxonomy.classify_asset_kind

    # transparent → never a screen; overlay if it reads as a floating layer
    assert ak("Bookshelf", "Bookshelf", transparent_margin=True) == "component"
    assert ak("Reader · Translation", "Reader", transparent_margin=True) == "overlay"
    assert ak("Reader · Quota", "Reader", transparent_margin=True) == "component"
    # opaque full-bleed → the name-based screen verdict stands (no false demotion)
    assert ak("Reader · TOC", "Reader", transparent_margin=False) == "screen"
    assert ak("Bookshelf View", "Bookshelf", transparent_margin=False) == "screen"


def test_surface_lane_is_majority_vote_across_shots():
    """A category that mixes component shots (transparent) with a few real screen
    shots — like Bookshelf — must take the majority lane, not whichever shot is
    first, so a card grab-bag isn't mislabeled feature-surface by one stray shot."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    # screen shots FIRST (minority) so a first-shot heuristic would wrongly pick
    # feature-surface; only a true majority vote yields building-block.
    items = [
        _surface_item("Bookshelf", "feature-surface", "feature-surface", f"s{i}", "empty")
        for i in range(3)
    ] + [
        _surface_item("Bookshelf", "building-block", "building-block", f"c{i}", "populated")
        for i in range(11)
    ]
    surf = {s["surface"]: s for s in taxonomy.build_surface_index(items)}["Bookshelf"]
    assert surf["lane"] == "building-block"  # 11 component shots outvote 3 screen shots


def test_presenter_named_category_is_engineering_only_even_when_full_bleed():
    """A presenter harness renders full-bleed (so the transparent-pixel signal
    can't catch it), so presenter-ness must live in the category name. The fix is
    at the iOS source — KGVocabPresenterScenarios captures as "KG Vocab Presenter",
    not "KG Vocab View" — so the existing `"Presenter" in category` rule lands it in
    engineering-only without a consumption-side profile patch."""
    taxonomy = sys.modules["catalog_review_taxonomy"]
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    tax = taxonomy.build_taxonomy("KG Vocab Presenter", "Populated", profile, transparent_margin=False)
    assert tax["assetKind"] == "component"
    assert tax["surfaceRole"] == "presenter"
    assert taxonomy.classify_lane(tax["surfaceRole"], "review") == "engineering-only"
    # the real production list view stays a feature-surface
    real = taxonomy.build_taxonomy("Vocabulary List View", "Populated", profile, transparent_margin=False)
    assert real["surfaceRole"] == "feature-surface"


def test_review_state_preserves_existing_annotations():
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    items = [
        {
            "assetID": "settings-view--signed-out--iphone-15-pro--light",
            "relPath": "iPhone 15 Pro portrait/Settings_View/Signed_out.png",
            "promise": "Continue",
            "category": "Settings View",
            "title": "Signed out",
            "device": "iPhone 15 Pro",
            "appearance": "light",
        }
    ]
    existing = {
        "schema": "kg.catalog.review.state.v1",
        "entries": {
            "settings-view--signed-out--iphone-15-pro--light": {
                "status": "shortlist",
                "note": "hero",
            }
        },
    }

    review_state = state_module.build_review_state(items, profile, existing)
    entry = review_state["entries"]["settings-view--signed-out--iphone-15-pro--light"]
    assert entry["status"] == "shortlist"
    assert entry["note"] == "hero"
    assert entry["category"] == "Settings View"


def test_render_catalog_review_writes_manifest_html_and_state(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    state_path = tmp_path / "out" / "review_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": "kg.catalog.review.state.v1",
                "entries": {
                    build_asset_id(Path("iPhone 15 Pro portrait/Settings_View/Signed_out.png")): {
                        "status": "review",
                        "note": "check copy",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(tmp_path / "out"),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["stateFile"].endswith("review_state.json")

    manifest = json.loads((tmp_path / "out" / "review_manifest.json").read_text(encoding="utf-8"))
    expected_asset_id = build_asset_id(Path("iPhone 15 Pro portrait/Settings_View/Signed_out.png"))
    assert manifest["stateFile"] == "review_state.json"
    assert manifest["featureCounts"]["Settings"] == 1
    assert manifest["surfaceCounts"]["Settings View"] == 1
    assert manifest["items"][0]["assetID"] == expected_asset_id
    assert manifest["items"][0]["reviewStatus"] == "review"
    assert manifest["items"][0]["reviewNote"] == "check copy"

    review_state = json.loads((tmp_path / "out" / "review_state.json").read_text(encoding="utf-8"))
    assert review_state["entries"][expected_asset_id]["status"] == "review"
    review_html = (tmp_path / "out" / "review.html").read_text(encoding="utf-8")
    assert "KG UI Gallery" in review_html
    # three-bucket lane model is the gallery's primary segmentation
    assert "畫面" in review_html and "浮層" in review_html and "組件" in review_html
    # the heuristic curation layer is NOT surfaced in the gallery view
    assert "Eligibility" not in review_html
    assert "Quality tier" not in review_html


def test_render_html_is_three_bucket_and_curation_free():
    """The gallery view surfaces only the source-declared axes (feature → surface
    → state → shot + three-bucket lane). The heuristic curation layer that still
    lives in the manifest for the CLI workflow (eligibility / qualityTier / hero /
    promise / coverage facets / review-state) must NOT leak into the rendered UI."""
    manifest = {
        "surfaces": [
            {"surfaceKey": "reader-foo", "surface": "Foo", "surfaceGroup": "G",
             "feature": "Reader", "lane": "feature-surface", "shotCount": 2,
             "backing": "FooView",
             "graph": {
                 "status": "linked",
                 "matchedNodeCount": 1,
                 "depCount": 2,
                 "userCount": 1,
                 "dependentSurfaceCount": 1,
                 "externalIn": 0,
                 "deps": ["BarView", "BazView"],
                 "directUsers": ["ReaderShell"],
                 "dependentSurfaces": ["Reader Home"],
                 "health": [],
             }},
        ],
        "items": [
            {"surfaceKey": "reader-foo", "clusterID": "c", "stateLabel": "Default",
             "relPath": "a.png", "width": 10, "height": 20, "assetID": "id1", "appearance": "light"},
            {"surfaceKey": "reader-foo", "clusterID": "c", "stateLabel": "Default",
             "relPath": "b.png", "width": 10, "height": 20, "assetID": "id2", "appearance": "dark"},
        ],
        "featureCounts": {"Reader": 1}, "sceneCount": 1, "totalImages": 2,
        "laneCounts": {"feature-surface": 2},
    }
    html = renderer_module.render_html(manifest)
    assert "__MANIFEST__" not in html                      # data hole filled
    # three-bucket lane labels + /admin design tokens present
    for token in ["畫面", "浮層", "組件", "工程", "KG UI Gallery", "JetBrains+Mono", "--ink: #2a2520"]:
        assert token in html, f"missing {token}"
    for token in ["結構", "backing", "depends", "impacts", "FooView"]:
        assert token in html, f"missing graph token {token}"
    # curation UI must be absent from the gallery chrome
    for banned in ["Eligibility", "Quality tier", "Coverage", "qualityTier",
                   "stateFacet", "facet-rail", "再看"]:
        assert banned not in html, f"curation leak: {banned}"
    # the search box must be wired to state-filtering (regression: it had no
    # listener after the rewrite, so state.search was read but never assigned).
    assert 'getElementById("search").addEventListener' in html
    assert "state.search = " in html


def test_render_catalog_review_surfaces_graph_summary_in_html(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    _make_rgba_png(image_dir / "Signed_out.png", 40, 30, corner_alpha=255)
    (source_root / "catalog_index.json").write_text(
        json.dumps({
            "version": 1,
            "surfaces": {
                "Settings View": {
                    "kind": "featureScreen",
                    "feature": "settings",
                    "screen": "settings",
                    "backing": "SettingsPresenter",
                },
                "Settings Account Detail": {
                    "kind": "featureScreen",
                    "feature": "settings",
                    "screen": "settingsAccountDetail",
                    "backing": "SettingsAccountDetailView",
                },
            },
        }),
        encoding="utf-8",
    )
    (source_root / "ui_graph.json").write_text(
        json.dumps({
            "schema": "kg.ui.graph.v1",
            "nodes": [
                {"usr": "s:settings", "name": "SettingsPresenter", "kind": "struct", "surface": ["Settings View"], "externalIn": 1},
                {"usr": "s:plan", "name": "SettingsPlanComparisonTable", "kind": "struct", "surface": [], "externalIn": 0},
                {"usr": "s:detail", "name": "SettingsAccountDetailView", "kind": "struct", "surface": ["Settings Account Detail"], "externalIn": 0},
            ],
            "edges": [
                {"from": "s:settings", "to": "s:plan"},
                {"from": "s:detail", "to": "s:settings"},
            ],
        }),
        encoding="utf-8",
    )

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr
    review_html = (output_root / "review.html").read_text(encoding="utf-8")
    assert "SettingsPresenter" in review_html
    assert "SettingsPlanComparisonTable" in review_html
    assert "Settings Account Detail" in review_html
    assert "結構" in review_html


def test_render_html_escapes_breakout_sequences():
    """The manifest is embedded inside a <script>; </script> and the JS line
    separators U+2028/U+2029 inside string values must be neutralised so the
    payload can't break out of the tag or the JS string parser."""
    sep_2028, sep_2029 = chr(0x2028), chr(0x2029)
    manifest = {
        "surfaces": [], "items": [], "featureCounts": {}, "sceneCount": 0, "totalImages": 0,
        "laneCounts": {}, "evil": "</script><b>&" + sep_2028 + sep_2029,
    }
    html = renderer_module.render_html(manifest)
    assert "</script><b>" not in html                      # tag-breakout neutralised
    assert "\\u003c/script\\u003e\\u003cb\\u003e" in html    # evil payload < > escaped
    assert sep_2028 not in html and sep_2029 not in html    # raw separators gone
    assert "\\u2028" in html and "\\u2029" in html           # escaped forms present
    assert "\\u0026" in html                               # & escaped


def test_gallery_requires_source_declared_when_index_present(tmp_path: Path):
    """Presence-gated fail-loud: an index present means it's the source of truth
    and must be complete; a no-index source is explicit legacy mode (no enforce)."""
    require = render_entry_module._require_source_declared
    src = tmp_path / "src"
    src.mkdir()
    items = [{"category": "Foo", "sourceDeclared": True},
             {"category": "Bar", "sourceDeclared": False}]

    # no index file → legacy fallback, never raises
    require(items, src)

    # index present but a rendered category is undeclared → drift → raise, named
    (src / "catalog_index.json").write_text(json.dumps({"version": 1, "surfaces": {}}), encoding="utf-8")
    try:
        require(items, src)
        raise AssertionError("expected SystemExit for undeclared surface")
    except SystemExit as exc:
        assert "Bar" in str(exc) and "Foo" not in str(exc)

    # index present and every rendered category declared → passes
    require([{"category": "Foo", "sourceDeclared": True}], src)


def test_catalog_review_cli_gaps_query(tmp_path: Path):
    """The machine face must let an agent query surface coverage directly instead
    of parsing the whole manifest: which shippable surfaces are missing which
    ship-critical states, filterable by lane / missing-facet, with untracked
    lanes (building blocks, harness) never fabricating a gap."""
    source_root = tmp_path / "snapshots"
    screen_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    screen_dir.mkdir(parents=True)
    # Data-bearing (it ships a populated state), so it owes the full lifecycle and
    # genuinely misses loading. A default-ONLY screen would be static and owe
    # nothing beyond default — that's the honest-gap behaviour, not a query bug.
    (screen_dir / "Populated.png").write_bytes(b"png")  # → missing empty/loading/error
    badge_dir = source_root / "iPhone 15 Pro portrait" / "iCloud_Progress_Badge"
    badge_dir.mkdir(parents=True)
    (badge_dir / "Idle.png").write_bytes(b"png")  # building-block → untracked, must never show as a gap

    output_root = tmp_path / "out"
    render = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "render_catalog_review.py"), str(source_root),
         "--output-root", str(output_root), "--profile", str(ROOT / "ops" / "catalog_review_profile.json")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert render.returncode == 0, render.stderr

    gaps = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "gaps", "--missing", "loading"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert gaps.returncode == 0, gaps.stderr
    payload = json.loads(gaps.stdout)
    assert payload["status"] == "ok"
    surfaces = {s["surface"]: s for s in payload["surfaces"]}
    assert "Settings View" in surfaces
    assert "loading" in surfaces["Settings View"]["missingFacets"]
    assert surfaces["Settings View"]["lane"] == "feature-surface"
    # untracked building block must never appear as a gap
    assert "iCloud Progress Badge" not in surfaces

    # lane filter narrows to a single lane
    overlay = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "gaps", "--lane", "overlay"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert overlay.returncode == 0, overlay.stderr
    assert all(s["lane"] == "overlay" for s in json.loads(overlay.stdout)["surfaces"])


def test_catalog_review_cli_can_summarize_show_and_mark(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    asset_id = build_asset_id(Path("iPhone 15 Pro portrait/Settings_View/Signed_out.png"))

    summary = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "summary"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert summary.returncode == 0, summary.stderr
    summary_payload = json.loads(summary.stdout)
    assert summary_payload["totalImages"] == 1
    assert summary_payload["stateEntries"] == 1

    show = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "show", asset_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert show.returncode == 0, show.stderr
    show_payload = json.loads(show.stdout)
    assert show_payload["asset"]["assetID"] == asset_id
    assert show_payload["history"] == []
    assert show_payload["permalink"].endswith(f"#asset-{asset_id}")

    mark = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "mark", asset_id, "--status", "shortlist", "--note", "hero"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert mark.returncode == 0, mark.stderr
    mark_payload = json.loads(mark.stdout)
    assert mark_payload["reviewStatus"] == "shortlist"
    assert mark_payload["note"] == "hero"

    state_payload = json.loads((output_root / "review_state.json").read_text(encoding="utf-8"))
    assert state_payload["entries"][asset_id]["status"] == "shortlist"
    assert state_payload["entries"][asset_id]["updatedAt"]
    assert state_payload["entries"][asset_id]["history"][-1]["action"] == "mark"
    assert state_payload["entries"][asset_id]["history"][-1]["status"] == "shortlist"
    manifest_after_mark = json.loads((output_root / "review_manifest.json").read_text(encoding="utf-8"))
    assert manifest_after_mark["stateCounts"]["shortlist"] == 1
    assert manifest_after_mark["items"][0]["reviewStatus"] == "shortlist"
    review_html = (output_root / "review.html").read_text(encoding="utf-8")
    assert '"stateCounts": {"shortlist": 1}' in review_html

    listed = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "list",
            "--status",
            "shortlist",
            "--search",
            "settings view",
            "--limit",
            "5",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["count"] == 1
    assert listed_payload["items"][0]["assetID"] == asset_id
    assert listed_payload["items"][0]["effectiveStatus"] == "shortlist"

    listed_by_note = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "list",
            "--search",
            "hero",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert listed_by_note.returncode == 0, listed_by_note.stderr
    listed_by_note_payload = json.loads(listed_by_note.stdout)
    assert listed_by_note_payload["count"] == 1
    assert listed_by_note_payload["items"][0]["assetID"] == asset_id


def test_catalog_review_cli_can_bulk_apply_with_dry_run_and_commit(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")
    (image_dir / "Signed_in.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    dry_run = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "apply",
            "--category",
            "Settings View",
            "--status",
            "review",
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    dry_run_payload = json.loads(dry_run.stdout)
    assert dry_run_payload["dryRun"] is True
    assert dry_run_payload["appliedCount"] == 2
    state_before = json.loads((output_root / "review_state.json").read_text(encoding="utf-8"))
    assert all(entry["status"] == "" for entry in state_before["entries"].values())

    apply = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "apply",
            "--category",
            "Settings View",
            "--status",
            "review",
            "--note",
            "batch-pass",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert apply.returncode == 0, apply.stderr
    apply_payload = json.loads(apply.stdout)
    assert apply_payload["dryRun"] is False
    assert apply_payload["appliedCount"] == 2
    assert all(item["reviewStatus"] == "review" for item in apply_payload["items"])
    assert all(item["effectiveStatus"] == "review" for item in apply_payload["items"])
    assert all(item["updatedAt"] for item in apply_payload["items"])

    state_after = json.loads((output_root / "review_state.json").read_text(encoding="utf-8"))
    assert all(entry["status"] == "review" for entry in state_after["entries"].values())
    assert all(entry["note"] == "batch-pass" for entry in state_after["entries"].values())
    assert all(entry["updatedAt"] for entry in state_after["entries"].values())
    assert all(entry["history"][-1]["action"] == "apply" for entry in state_after["entries"].values())
    manifest_after = json.loads((output_root / "review_manifest.json").read_text(encoding="utf-8"))
    assert manifest_after["stateCounts"]["review"] == 2

    stats = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "stats",
            "--status",
            "review",
            "--limit",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert stats.returncode == 0, stats.stderr
    stats_payload = json.loads(stats.stdout)
    assert stats_payload["count"] == 2
    assert stats_payload["effectiveStatusCounts"]["review"] == 2
    assert stats_payload["topCategories"][0]["category"] == "Settings View"

    report = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "report",
            "--limit",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    settings_promise = next(p for p in report_payload["promises"] if p["promise"] == "Weak")
    assert settings_promise["review"] == 2
    assert settings_promise["unmarked"] == 0
    assert settings_promise["topUnmarkedCategories"] == []
    assert report_payload["nextActions"] == []


def test_catalog_review_report_emits_next_actions_for_unmarked_work(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Reader_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Hero.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    report = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "report",
            "--limit",
            "5",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    assert payload["nextActions"]
    first = payload["nextActions"][0]
    assert first["promise"] == "Read"
    assert first["kind"] in {"hero-unmarked", "top-unmarked-category"}
    assert first["command"].startswith("./ops/catalog_review_cli.py ")
    assert first["commandAction"]["kind"] in {"inspect", "narrow"}
    assert first["commandAction"]["intent"] in {"gather-evidence", "reduce-review-scope"}


def test_catalog_review_report_hero_command_returns_hero_candidates(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Podcast_Home_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    report = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "report",
            "--limit",
            "5",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert report.returncode == 0, report.stderr
    hero_command = json.loads(report.stdout)["nextActions"][0]["command"]

    listed = subprocess.run(
        ["zsh", "-lc", hero_command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["count"] == 1
    assert listed_payload["items"][0]["heroCandidate"] is True


def test_catalog_review_report_commands_quote_root_paths(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Podcast_Home_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out with space"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    report = subprocess.run(
        [
            sys.executable,
            str(REVIEW_CLI),
            str(output_root),
            "report",
            "--limit",
            "5",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert report.returncode == 0, report.stderr

    payload = json.loads(report.stdout)
    for action in payload["nextActions"]:
        replay = subprocess.run(
            ["zsh", "-lc", action["command"]],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert replay.returncode == 0, replay.stderr


def test_catalog_review_verify_reports_ok_and_detects_drift(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    verify_ok = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify_ok.returncode == 0, verify_ok.stderr
    verify_ok_payload = json.loads(verify_ok.stdout)
    assert verify_ok_payload["status"] == "ok"
    assert verify_ok_payload["errors"] == []

    state_path = output_root / "review_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["entries"] = {}
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    verify_bad = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify_bad.returncode == 1
    verify_bad_payload = json.loads(verify_bad.stdout)
    assert verify_bad_payload["status"] == "error"
    assert "missing-state-entries" in verify_bad_payload["errors"]


def test_catalog_review_verify_detects_schema_drift_and_repair_fixes_it(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    asset_id = build_asset_id(Path("iPhone 15 Pro portrait/Settings_View/Signed_out.png"))
    state_path = output_root / "review_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["schema"] = "legacy"
    state_payload["entries"][asset_id]["status"] = "review"
    state_payload["entries"][asset_id]["note"] = "legacy-state"
    state_payload["entries"][asset_id]["history"] = []
    state_payload["entries"][asset_id]["updatedAt"] = None
    state_payload["entries"][asset_id]["category"] = "Wrong Category"
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    verify_bad = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify_bad.returncode == 1, verify_bad.stderr
    verify_bad_payload = json.loads(verify_bad.stdout)
    assert "invalid-state-schema" in verify_bad_payload["errors"]
    assert "state-metadata-drift" in verify_bad_payload["errors"]
    assert "state-schema-errors" in verify_bad_payload["errors"]

    repair_dry_run = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "repair", "--dry-run", "--limit", "1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repair_dry_run.returncode == 0, repair_dry_run.stderr
    repair_dry_run_payload = json.loads(repair_dry_run.stdout)
    assert repair_dry_run_payload["repairCount"] >= 1
    assert repair_dry_run_payload["truncatedRepairCount"] >= 0
    assert any("backfilled-history" in repair["repairs"] for repair in repair_dry_run_payload["sampleRepairs"])
    assert "repairs" not in repair_dry_run_payload

    repair = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "repair", "--include-repairs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repair.returncode == 0, repair.stderr
    repair_payload = json.loads(repair.stdout)
    assert repair_payload["repairCount"] >= 1
    assert repair_payload["repairTypeCounts"]["backfilled-history"] >= 1
    assert "repairs" in repair_payload

    repaired_state = json.loads(state_path.read_text(encoding="utf-8"))
    repaired_entry = repaired_state["entries"][asset_id]
    assert repaired_state["schema"] == "kg.catalog.review.state.v1"
    assert repaired_entry["category"] == "Settings View"
    assert repaired_entry["history"][-1]["action"] == "repair"
    assert repaired_entry["updatedAt"] == repaired_entry["history"][-1]["at"]

    verify_ok = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "verify"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verify_ok.returncode == 0, verify_ok.stderr
    verify_ok_payload = json.loads(verify_ok.stdout)
    assert verify_ok_payload["status"] == "ok"


def test_catalog_review_doctor_aggregates_verify_repair_and_report(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Reader_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Hero.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    state_path = output_root / "review_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    asset_id = next(iter(state_payload["entries"]))
    state_payload["entries"][asset_id].pop("history", None)
    state_payload["entries"][asset_id].pop("updatedAt", None)
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    doctor = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "doctor", "--limit", "2"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stderr
    payload = json.loads(doctor.stdout)
    assert payload["status"] == "needs-attention"
    assert payload["verify"]["status"] == "error"
    assert "state-schema-errors" in payload["verify"]["errors"]
    assert payload["repair"]["repairCount"] == 1
    assert payload["repair"]["sampleRepairs"][0]["assetID"] == asset_id
    assert payload["report"]["promises"][0]["promise"] == "Read"
    assert payload["report"]["nextActions"]
    assert payload["focusRecommendations"][0]["promise"] == "Read"
    assert payload["focusRecommendations"][0]["attentionScore"] > 0
    assert payload["focusRecommendations"][0]["recommendedActions"]
    assert payload["focusRecommendations"][0]["recommendedActions"][0]["promise"] == "Read"
    assert payload["focusRecommendations"][0]["recommendedActions"][0]["commandAction"]["kind"] in {"inspect", "narrow"}
    assert payload["coreRecommendations"][0]["promise"] == "Read"
    assert payload["heroFirstCoreRecommendations"][0]["promise"] == "Read"
    assert payload["coverageFirstCoreRecommendations"][0]["promise"] == "Read"
    assert payload["heroFirstPlaybook"]["mode"] == "hero-first"
    assert payload["coverageFirstPlaybook"]["mode"] == "coverage-first"
    assert payload["heroFirstPlaybook"]["firstCommand"]
    assert payload["coverageFirstPlaybook"]["firstCommand"]
    assert payload["heroFirstPlaybook"]["firstAction"]["kind"] in {"inspect", "narrow"}
    assert payload["coverageFirstPlaybook"]["firstAction"]["kind"] in {"inspect", "narrow"}
    assert payload["heroFirstPlaybook"]["starterPlan"]["source"] == "playbook"
    assert payload["heroFirstPlaybook"]["starterPlan"]["sourceMode"] == "hero-first"
    assert payload["heroFirstPlaybook"]["starterPlan"]["primary"]["command"] == payload["heroFirstPlaybook"]["firstCommand"]
    assert payload["coverageFirstPlaybook"]["starterPlan"]["primary"]["command"] == payload["coverageFirstPlaybook"]["firstCommand"]
    assert payload["cleanupRecommendations"] == []
    assert payload["blockingErrors"] == []


def test_catalog_review_doctor_needs_attention_is_non_blocking(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Podcast_Home_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    doctor = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "doctor"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stderr
    payload = json.loads(doctor.stdout)
    assert payload["status"] == "needs-attention"
    assert payload["blockingErrors"] == []


def test_catalog_review_doctor_projected_modes_keep_repair_plan_non_blocking(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Reader_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Hero.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    state_path = output_root / "review_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    asset_id = next(iter(state_payload["entries"]))
    state_payload["entries"][asset_id].pop("history", None)
    state_payload["entries"][asset_id].pop("updatedAt", None)
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hero_mode = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "doctor", "--limit", "2", "--mode", "hero-first"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert hero_mode.returncode == 0, hero_mode.stderr
    hero_payload = json.loads(hero_mode.stdout)
    assert hero_payload["mode"] == "hero-first"
    assert hero_payload["health"]["severity"] == "warn"
    assert hero_payload["health"]["verifyStatus"] == "error"
    assert hero_payload["health"]["repairCount"] == 1
    assert hero_payload["health"]["canProceed"] is True
    assert hero_payload["health"]["shouldRepairFirst"] is True
    assert hero_payload["health"]["needsReviewAttention"] is True
    assert hero_payload["health"]["recommendedOperatorAction"] == "repair-first"
    assert hero_payload["health"]["recommendedCommand"].endswith(" repair")
    assert hero_payload["health"]["followupCommand"].endswith(" verify")
    assert hero_payload["health"]["actionPlan"]["source"] == "repair"
    assert hero_payload["health"]["actionPlan"]["sourceMode"] == "hero-first"
    assert hero_payload["health"]["actionPlan"]["primary"]["command"].endswith(" repair")
    assert hero_payload["health"]["actionPlan"]["followup"]["command"].endswith(" verify")
    assert hero_payload["health"]["actionPlan"]["primary"]["command"] == hero_payload["health"]["recommendedCommand"]
    assert hero_payload["health"]["actionPlan"]["followup"]["command"] == hero_payload["health"]["followupCommand"]
    assert hero_payload["health"]["actionCommands"][0]["role"] == "primary"
    assert hero_payload["health"]["actionCommands"][0]["kind"] == "mutate"
    assert hero_payload["health"]["actionCommands"][0]["intent"] == "change-review-state"
    assert hero_payload["health"]["actionCommands"][0]["dryRunSafe"] is False
    assert hero_payload["health"]["actionCommands"][1]["role"] == "followup"
    assert hero_payload["health"]["actionCommands"][1]["kind"] == "verify"
    assert hero_payload["health"]["actionCommands"][1]["intent"] == "check-artifact-health"
    assert hero_payload["health"]["actionCommands"][1]["dryRunSafe"] is True
    assert hero_payload["health"]["summary"]["blockingErrorCount"] == 0
    assert hero_payload["recommendations"][0]["promise"] == "Read"
    assert hero_payload["playbook"]["mode"] == "hero-first"
    assert "verify" not in hero_payload
    assert "repair" not in hero_payload

    hero_shortcut = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "hero", "--limit", "2"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert hero_shortcut.returncode == 0, hero_shortcut.stderr
    hero_shortcut_payload = json.loads(hero_shortcut.stdout)
    assert hero_shortcut_payload["mode"] == "hero-first"
    assert hero_shortcut_payload["health"]["recommendedOperatorAction"] == "repair-first"


def test_multi_device_manifest_devices_and_cluster_identity(tmp_path: Path):
    """Multi-device snapshots: scene identity (clusterID) stays device-free so the
    same state pairs light/dark *within* each device, while the manifest exposes an
    ordered ``devices`` list (canonical iPhone first) for the gallery's device toggle."""
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    for device_dir in (
        "iPhone 15 Pro portrait",
        "iPhone 15 Pro portrait (dark)",
        "iPad Pro 11 landscape",
        "iPad Pro 11 landscape (dark)",
    ):
        image_dir = source_root / device_dir / "Settings_View"
        image_dir.mkdir(parents=True)
        (image_dir / "Signed_out.png").write_bytes(b"png")

    items = manifest_module.collect_items(source_root, profile)
    assert len(items) == 4
    assert {item["device"] for item in items} == {"iPhone 15 Pro portrait", "iPad Pro 11 landscape"}
    assert len({item["clusterID"] for item in items}) == 1  # device-free scene identity
    assert len({item["assetID"] for item in items}) == 4    # per-shot identity stays unique

    manifest = manifest_module.build_manifest(items, profile)
    assert manifest["devices"] == ["iPhone 15 Pro portrait", "iPad Pro 11 landscape"]


def test_render_html_consumes_devices_for_device_toggle(tmp_path: Path):
    """The gallery template must consume MANIFEST.devices and scope scene pairing
    to the selected device — otherwise a second device's shots silently shadow the
    first device's light/dark pairs inside the same cluster."""
    manifest = {
        "schema": "kg.catalog.review.v1",
        "devices": ["iPhone 15 Pro portrait", "iPad Pro 11 landscape"],
        "surfaces": [],
        "items": [],
    }
    html = renderer_module.render_html(manifest)
    assert "MANIFEST.devices" in html
    assert 'id="device-seg"' in html
    assert "state.device" in html


def test_render_html_embeds_uitest_videos():
    """UITest run recordings are page data: render_html embeds the archive index
    entries (with page-relative src) into the UITEST_VIDEOS hole so the gallery
    can offer a recordings section alongside the shot lanes."""
    manifest = {"schema": "kg.catalog.review.v1", "surfaces": [], "items": []}
    videos = [
        {
            "file": "20260611-120000-ui.mp4",
            "src": "uitest-videos/20260611-120000-ui.mp4",
            "recordedAtUtc": "2026-06-11T12:00:00Z",
            "scope": "ui",
            "caller": "test-caller",
            "sizeBytes": 1234,
        }
    ]
    html = renderer_module.render_html(manifest, ui_test_videos=videos)
    assert "20260611-120000-ui.mp4" in html
    assert "UITEST_VIDEOS" in html
    assert "<video" in html

    bare = renderer_module.render_html(manifest)
    assert "20260611-120000-ui.mp4" not in bare
    assert "UITEST_VIDEOS = null" in bare


def test_write_review_outputs_links_sibling_uitest_videos(tmp_path: Path):
    """write_review_outputs hard-links the archived recordings listed in the
    sibling build/snapshots/uitest-videos/index.json into <root>/uitest-videos/
    so review.html stays self-contained for both file:// and the http server
    (which serves --directory <root> and cannot reach ../)."""
    snapshots = tmp_path / "snapshots"
    archive = snapshots / "uitest-videos"
    archive.mkdir(parents=True)
    (archive / "20260611-120000-ui.mp4").write_bytes(b"fake-mp4")
    (archive / "index.json").write_text(
        json.dumps(
            {
                "schema": "kg.ios.uitest-videos.v1",
                "videos": [
                    {
                        "file": "20260611-120000-ui.mp4",
                        "recordedAtUtc": "2026-06-11T12:00:00Z",
                        "scope": "ui",
                        "caller": "test-caller",
                        "sizeBytes": 8,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    root = snapshots / "catalog-full-20260611-130000"
    root.mkdir()
    manifest = {"schema": "kg.catalog.review.v1", "surfaces": [], "items": []}
    sync_module.write_review_outputs(root, manifest, {"entries": {}})
    linked = root / "uitest-videos" / "20260611-120000-ui.mp4"
    assert linked.is_file() and linked.read_bytes() == b"fake-mp4"
    html = (root / "review.html").read_text(encoding="utf-8")
    assert "uitest-videos/20260611-120000-ui.mp4" in html
    # the persisted manifest stays a pure shot manifest — recordings are page data
    persisted = json.loads((root / "review_manifest.json").read_text(encoding="utf-8"))
    assert "uiTestVideos" not in persisted


def test_write_review_outputs_without_video_archive_is_clean(tmp_path: Path):
    """No sibling archive (or an unreadable index) must not break review output
    and must not fabricate an empty recordings dir."""
    root = tmp_path / "catalog-full-20260611-130000"
    root.mkdir()
    manifest = {"schema": "kg.catalog.review.v1", "surfaces": [], "items": []}
    sync_module.write_review_outputs(root, manifest, {"entries": {}})
    html = (root / "review.html").read_text(encoding="utf-8")
    assert "UITEST_VIDEOS = null" in html
    assert not (root / "uitest-videos").exists()

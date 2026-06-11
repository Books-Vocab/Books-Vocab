"""Pure-logic tests for the contact-sheet montage tool (grid math + item
selection). PIL is lazy-imported inside the render path, so this module loads
and these run in the plain backend venv with no Pillow."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "catalog_contact_sheet", ROOT / "ops" / "catalog_contact_sheet.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plan_grid_dims_and_cell_positions():
    mod = _load()
    cw, ch, cols, rows, cells = mod.plan_grid(
        6, cols=3, cell_w=320, cell_h=694, label_h=40, gap=16, pad=24
    )
    assert (cols, rows) == (3, 2)
    assert len(cells) == 6
    assert cw == 24 * 2 + 3 * 320 + 2 * 16
    assert ch == 24 * 2 + 2 * (694 + 40) + 1 * 16
    assert cells[0] == (24, 24)
    assert cells[1] == (24 + 320 + 16, 24)               # next column
    assert cells[3] == (24, 24 + (694 + 40) + 16)        # next row


def test_plan_grid_cols_capped_to_n():
    mod = _load()
    _, _, cols, rows, cells = mod.plan_grid(
        2, cols=3, cell_w=100, cell_h=200, label_h=20, gap=10, pad=10
    )
    assert (cols, rows) == (2, 1)
    assert len(cells) == 2


def test_select_items_filters_appearance_and_lane_and_sorts():
    mod = _load()
    manifest = {"items": [
        {"surface": "B", "appearance": "light", "lane": "overlay",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "d", "feature": "G"},
        {"surface": "A", "appearance": "dark", "lane": "feature-surface",
         "stateFacet": "empty", "stateFacetRank": 3, "stateLabel": "e", "feature": "F"},
        {"surface": "A", "appearance": "light", "lane": "feature-surface",
         "stateFacet": "empty", "stateFacetRank": 3, "stateLabel": "e", "feature": "F"},
    ]}
    sel = mod.select_items(manifest, lane="feature-surface", appearance="light")
    assert [s["surface"] for s in sel] == ["A"]
    assert mod.select_items(manifest, appearance="both") and len(
        mod.select_items(manifest, appearance="both")) == 3
    # limit truncates after sort
    assert len(mod.select_items(manifest, appearance="both", limit=2)) == 2


def test_select_items_by_ids_preserves_requested_order():
    mod = _load()
    manifest = {"items": [
        {"assetID": "x1", "surface": "A", "appearance": "light", "lane": "l",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "a", "feature": "F"},
        {"assetID": "x2", "surface": "B", "appearance": "light", "lane": "l",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "b", "feature": "F"},
        {"assetID": "x3", "surface": "C", "appearance": "light", "lane": "l",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "c", "feature": "F"},
    ]}
    # ids select exactly those, in the REQUESTED order (not canonical sort)
    sel = mod.select_items(manifest, ids=["x3", "x1"], appearance="both")
    assert [s["assetID"] for s in sel] == ["x3", "x1"]
    # unknown id is silently skipped, not an error
    assert [s["assetID"] for s in mod.select_items(
        manifest, ids=["x2", "nope"], appearance="both")] == ["x2"]


def test_select_items_ids_intersect_other_filters():
    mod = _load()
    manifest = {"items": [
        {"assetID": "x1", "surface": "A", "appearance": "light", "lane": "l",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "a", "feature": "F"},
        {"assetID": "x2", "surface": "A", "appearance": "dark", "lane": "l",
         "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "a", "feature": "F"},
    ]}
    sel = mod.select_items(manifest, ids=["x1", "x2"], appearance="light")
    assert [s["assetID"] for s in sel] == ["x1"]


def test_apply_take_evenly_and_named_positions():
    mod = _load()
    items = [{"assetID": f"x{i}"} for i in range(1, 9)]
    assert [it["assetID"] for it in mod.apply_take(items, "evenly:4")] == [
        "x1", "x3", "x6", "x8"
    ]
    assert [it["assetID"] for it in mod.apply_take(items, "first,middle,last")] == [
        "x1", "x4", "x8"
    ]
    assert [it["assetID"] for it in mod.apply_take(items, "2,4,nope,99")] == [
        "x2", "x4"
    ]


def test_build_ui_step_manifest_orders_numeric_steps(tmp_path):
    mod = _load()
    png_header = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 8
        + (100).to_bytes(4, "big")
        + (200).to_bytes(4, "big")
    )
    for name in ("08-playback-sustained.png", "01-launch.png", "03-series-detail.png"):
        (tmp_path / name).write_bytes(png_header)
    manifest = mod.build_ui_step_manifest(tmp_path)
    assert manifest["source"] == "uitest"
    assert [item["assetID"] for item in manifest["items"]] == [
        "01-launch", "03-series-detail", "08-playback-sustained"
    ]
    assert manifest["items"][1]["stateLabel"] == "series-detail"


def test_resolve_crop_box_presets():
    mod = _load()
    assert mod.resolve_crop_box(100, 200, None) == (0, 0, 100, 200)
    assert mod.resolve_crop_box(100, 200, "full") == (0, 0, 100, 200)
    assert mod.resolve_crop_box(100, 200, "top") == (0, 0, 100, 100)
    assert mod.resolve_crop_box(100, 200, "bottom") == (0, 100, 100, 200)
    assert mod.resolve_crop_box(100, 200, "center") == (25, 50, 75, 150)
    assert mod.resolve_crop_box(100, 200, "left") == (0, 0, 50, 200)
    assert mod.resolve_crop_box(100, 200, "right") == (50, 0, 100, 200)


def test_resolve_crop_box_fractional_and_clamps():
    mod = _load()
    assert mod.resolve_crop_box(100, 200, "0,0,0.5,0.5") == (0, 0, 50, 100)
    # x+w / y+h overshoot clamps to image bounds, never out of range
    assert mod.resolve_crop_box(100, 200, "0.5,0.5,1,1") == (50, 100, 100, 200)
    # degenerate (zero-area) request falls back to full frame, not an empty box
    assert mod.resolve_crop_box(100, 200, "0,0,0,0") == (0, 0, 100, 200)


def _write_minimal_png(path: Path, width: int = 100, height: int = 200):
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 8
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def test_build_ui_step_manifest_excludes_generated_sheets(tmp_path):
    mod = _load()
    for name in ("01-launch.png", "02-player.png",
                 "contact_sheet.png", "quick4_contact_sheet.png"):
        _write_minimal_png(tmp_path / name)
    manifest = mod.build_ui_step_manifest(tmp_path)
    assert [item["assetID"] for item in manifest["items"]] == [
        "01-launch", "02-player"
    ]


def test_images_source_excludes_generated_sheets(tmp_path):
    mod = _load()
    for name in ("01-launch.png", "contact_sheet.png", "quick4_contact_sheet.png"):
        _write_minimal_png(tmp_path / name)
    bundle = mod._resolve_source(tmp_path, "images")
    assert [item["relPath"] for item in bundle.manifest["items"]] == ["01-launch.png"]


def test_apply_take_evenly_single_item_no_crash():
    mod = _load()
    items = [{"assetID": "only"}]
    assert mod.apply_take(items, "evenly:4") == items


def test_select_items_device_defaults_to_canonical_and_filters_explicitly():
    """Multi-device manifests: default sheet selection sticks to the canonical
    device (manifest devices[0]) so state rows don't interleave iPhone/iPad
    twins; --device picks another device; 'all' disables the filter."""
    mod = _load()
    manifest = {
        "devices": ["iPhone 15 Pro portrait", "iPad Pro 11 landscape"],
        "items": [
            {"surface": "A", "appearance": "light", "lane": "feature-surface",
             "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "d",
             "feature": "F", "device": "iPhone 15 Pro portrait"},
            {"surface": "A", "appearance": "light", "lane": "feature-surface",
             "stateFacet": "default", "stateFacetRank": 0, "stateLabel": "d",
             "feature": "F", "device": "iPad Pro 11 landscape"},
        ],
    }
    default_sel = mod.select_items(manifest, appearance="light")
    assert [s["device"] for s in default_sel] == ["iPhone 15 Pro portrait"]
    pad_sel = mod.select_items(manifest, appearance="light", device="iPad Pro 11 landscape")
    assert [s["device"] for s in pad_sel] == ["iPad Pro 11 landscape"]
    all_sel = mod.select_items(manifest, appearance="light", device="all")
    assert len(all_sel) == 2
    # single-device legacy manifests (no devices field) keep today's behavior
    legacy = {"items": [dict(manifest["items"][0])]}
    assert len(mod.select_items(legacy, appearance="light")) == 1

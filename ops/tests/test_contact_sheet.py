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

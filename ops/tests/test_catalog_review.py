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
build_asset_id = manifest_module.build_asset_id
CATALOG_CLI = ROOT / "ops" / "catalog_review_cli.py"


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
    assert reader["surface"] == "Reader"
    assert reader["surfaceVariant"] == "Translation"
    assert reader["stateLabel"] == "Hero"
    assert reader["assetKind"] == "screen"

    settings = by_category["Settings · ParamRow"]
    assert settings["feature"] == "Settings"
    assert settings["assetKind"] == "component"


def test_build_manifest_emits_four_level_node_tree(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    light_dir = source_root / "iPhone 15 Pro portrait" / "Reader_·_Translation"
    light_dir.mkdir(parents=True)
    (light_dir / "Default.png").write_bytes(b"png")
    (light_dir / "Loading.png").write_bytes(b"png")
    dark_dir = source_root / "iPhone 15 Pro portrait (dark)" / "Reader_·_Translation"
    dark_dir.mkdir(parents=True)
    (dark_dir / "Default.png").write_bytes(b"png")
    (source_root / "iPhone 15 Pro portrait" / "Settings_View").mkdir(parents=True)
    (source_root / "iPhone 15 Pro portrait" / "Settings_View" / "Signed_out.png").write_bytes(b"png")

    items = manifest_module.collect_items(source_root, profile)
    manifest = manifest_module.build_manifest(items, profile)
    tree = manifest["tree"]

    assert manifest["schema"] == "kg.catalog.atlas.v1"
    assert "stateCounts" not in manifest
    assert "stateFile" not in manifest
    for item in manifest["items"]:
        assert "reviewStatus" not in item
        assert "reviewNote" not in item

    assert tree["kind"] == "root"
    assert tree["nodePath"] == ""
    feature_labels = [child["label"] for child in tree["children"]]
    assert feature_labels == sorted(feature_labels)

    reader = next(child for child in tree["children"] if child["label"] == "Reader")
    assert reader["count"] == 3
    reader_surface = next(s for s in reader["children"] if s["label"] == "Reader")
    assert reader_surface["promise"] == "Read"
    assert reader_surface["heroCandidate"] is True

    translation_state = next(state for state in reader_surface["children"] if state["label"] == "Translation")
    assert translation_state["count"] == 2
    leaf = translation_state["children"][0]
    assert leaf["kind"] == "asset"
    assert leaf["relPath"].endswith(".png")
    assert leaf["nodePath"].startswith(translation_state["nodePath"] + "/")
    assert leaf["assetID"] in leaf["nodePath"]


def test_render_catalog_writes_manifest_and_canvas(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    image_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    image_dir.mkdir(parents=True)
    (image_dir / "Signed_out.png").write_bytes(b"png")

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
    assert payload["canvasHtml"].endswith("catalog.html")
    assert "reviewState" not in payload

    expected_asset_id = build_asset_id(Path("iPhone 15 Pro portrait/Settings_View/Signed_out.png"))
    output = tmp_path / "out"
    assert not (output / "review.html").exists()
    assert not (output / "review_state.json").exists()
    assert (output / "catalog.html").exists()

    manifest = json.loads((output / "review_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "kg.catalog.atlas.v1"
    assert manifest["items"][0]["assetID"] == expected_asset_id
    assert manifest["tree"]["kind"] == "root"

    canvas_html = (output / "catalog.html").read_text(encoding="utf-8")
    assert "KG UI Atlas" in canvas_html
    assert "JetBrains+Mono" in canvas_html
    assert 'xmlns="http://www.w3.org/2000/svg"' in canvas_html
    assert expected_asset_id in canvas_html
    assert "Iowan Old Style" not in canvas_html


def test_catalog_cli_tree_node_url_navigate_manifest(tmp_path: Path):
    source_root = tmp_path / "snapshots"
    light_dir = source_root / "iPhone 15 Pro portrait" / "Reader_·_Translation"
    light_dir.mkdir(parents=True)
    (light_dir / "Default.png").write_bytes(b"png")
    (light_dir / "Loading.png").write_bytes(b"png")
    dark_dir = source_root / "iPhone 15 Pro portrait (dark)" / "Reader_·_Translation"
    dark_dir.mkdir(parents=True)
    (dark_dir / "Default.png").write_bytes(b"png")

    output_root = tmp_path / "out"
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "render_catalog_review.py"),
            str(source_root),
            "--output-root",
            str(output_root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    tree_root = subprocess.run(
        [sys.executable, str(CATALOG_CLI), str(output_root), "tree", "--depth", "1"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert tree_root.returncode == 0, tree_root.stderr
    tree_payload = json.loads(tree_root.stdout)
    assert tree_payload["tree"]["kind"] == "root"
    reader_child = next(child for child in tree_payload["tree"]["children"] if child["label"] == "Reader")
    assert "childCount" in reader_child
    assert "children" not in reader_child

    tree_reader = subprocess.run(
        [sys.executable, str(CATALOG_CLI), str(output_root), "tree", "--node", "reader"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert tree_reader.returncode == 0, tree_reader.stderr
    reader_tree = json.loads(tree_reader.stdout)
    state_nodes = reader_tree["tree"]["children"][0]["children"]
    assert any(state["label"] == "Translation" for state in state_nodes)

    leaf_path = state_nodes[0]["children"][0]["nodePath"]

    node_cmd = subprocess.run(
        [sys.executable, str(CATALOG_CLI), str(output_root), "node", leaf_path],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert node_cmd.returncode == 0
    node_payload = json.loads(node_cmd.stdout)
    assert node_payload["node"]["kind"] == "asset"
    assert node_payload["node"]["relPath"].endswith(".png")
    assert node_payload["ancestors"][0] == "reader"

    missing = subprocess.run(
        [sys.executable, str(CATALOG_CLI), str(output_root), "node", "no/such/path"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["error"] == "node-not-found"

    url_cmd = subprocess.run(
        [sys.executable, str(CATALOG_CLI), str(output_root), "node-url", leaf_path,
         "--base", "http://127.0.0.1:8787/catalog.html"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert url_cmd.returncode == 0
    url_payload = json.loads(url_cmd.stdout)
    assert url_payload["url"] == f"http://127.0.0.1:8787/catalog.html#node={leaf_path}"

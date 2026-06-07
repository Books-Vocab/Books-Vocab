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


manifest_module = load_module("catalog_review_manifest", ROOT / "ops" / "catalog_review_manifest.py")
profile_module = load_module("catalog_review_profile", ROOT / "ops" / "catalog_review_profile.py")
state_module = load_module("catalog_review_state", ROOT / "ops" / "catalog_review_state.py")
build_asset_id = manifest_module.build_asset_id


def test_collect_items_assigns_stable_asset_ids():
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = ROOT / "build" / "snapshots" / "catalog-full-20260608-020244"

    items = manifest_module.collect_items(source_root, profile)
    assert items
    assert len({item["assetID"] for item in items}) == len(items)
    sample = next(item for item in items if item["category"] == "Settings View")
    assert sample["assetID"]
    assert sample["clusterID"]
    assert "--" in sample["assetID"]
    assert " " not in sample["assetID"]


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
    assert manifest["items"][0]["assetID"] == expected_asset_id
    assert manifest["items"][0]["reviewStatus"] == "review"
    assert manifest["items"][0]["reviewNote"] == "check copy"

    review_state = json.loads((tmp_path / "out" / "review_state.json").read_text(encoding="utf-8"))
    assert review_state["entries"][expected_asset_id]["status"] == "review"

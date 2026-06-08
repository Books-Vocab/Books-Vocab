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
build_asset_id = manifest_module.build_asset_id
REVIEW_CLI = ROOT / "ops" / "catalog_review_cli.py"


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
    assert sample["surface"] == "Settings View"
    assert sample["assetKind"] == "screen"
    assert sample["surfaceRole"] == "feature-surface"


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
    assert settings["surface"] == "Settings"
    assert settings["surfaceVariant"] == "ParamRow"
    assert settings["stateLabel"] == "Subscribed"
    assert settings["assetKind"] == "component"


def test_build_manifest_emits_four_level_node_tree(tmp_path: Path):
    profile = profile_module.load_profile(ROOT / "ops" / "catalog_review_profile.json")
    source_root = tmp_path / "snapshots"
    reader_light_dir = source_root / "iPhone 15 Pro portrait" / "Reader_·_Translation"
    reader_light_dir.mkdir(parents=True)
    (reader_light_dir / "Default.png").write_bytes(b"png")
    (reader_light_dir / "Loading.png").write_bytes(b"png")
    reader_dark_dir = source_root / "iPhone 15 Pro portrait (dark)" / "Reader_·_Translation"
    reader_dark_dir.mkdir(parents=True)
    (reader_dark_dir / "Default.png").write_bytes(b"png")
    settings_dir = source_root / "iPhone 15 Pro portrait" / "Settings_View"
    settings_dir.mkdir(parents=True)
    (settings_dir / "Signed_out.png").write_bytes(b"png")

    items = manifest_module.collect_items(source_root, profile)
    manifest = manifest_module.build_manifest(items, profile)
    tree = manifest["tree"]

    assert tree["kind"] == "root"
    assert tree["nodePath"] == ""
    assert tree["count"] == len(items)

    feature_labels = [child["label"] for child in tree["children"]]
    assert feature_labels == sorted(feature_labels)
    assert {"Reader", "Settings"}.issubset(set(feature_labels))

    reader = next(child for child in tree["children"] if child["label"] == "Reader")
    assert reader["kind"] == "feature"
    assert reader["nodePath"] == "reader"
    assert reader["count"] == 3
    surfaces = reader["children"]
    assert all(surface["kind"] == "surface" for surface in surfaces)
    reader_surface = next(s for s in surfaces if s["label"] == "Reader")
    assert reader_surface["promise"] == "Read"
    assert reader_surface["heroCandidate"] is True
    assert reader_surface["count"] == 3
    assert reader_surface["nodePath"].startswith("reader/")

    state_labels = [state["label"] for state in reader_surface["children"]]
    assert state_labels == sorted(state_labels, key=str.lower)
    translation_state = next(state for state in reader_surface["children"] if state["label"] == "Translation")
    assert translation_state["kind"] == "state"
    assert translation_state["count"] == 2
    appearances = sorted(asset["appearance"] for asset in translation_state["children"])
    assert appearances == ["dark", "light"]
    leaf = translation_state["children"][0]
    assert leaf["kind"] == "asset"
    assert leaf["relPath"].endswith(".png")
    assert leaf["nodePath"].startswith(translation_state["nodePath"] + "/")
    assert leaf["assetID"] in leaf["nodePath"]


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
    assert "KG UI Asset Gallery" in review_html
    assert "Feature" in review_html
    assert "Eligibility" in review_html


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


def test_catalog_review_cli_tree_node_url_navigate_manifest(tmp_path: Path):
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
            "--profile",
            str(ROOT / "ops" / "catalog_review_profile.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert render.returncode == 0, render.stderr

    tree_root = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "tree", "--depth", "1"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tree_root.returncode == 0, tree_root.stderr
    tree_payload = json.loads(tree_root.stdout)
    assert tree_payload["status"] == "ok"
    assert tree_payload["tree"]["kind"] == "root"
    feature_labels = [child["label"] for child in tree_payload["tree"]["children"]]
    assert "Reader" in feature_labels
    reader_child = next(child for child in tree_payload["tree"]["children"] if child["label"] == "Reader")
    assert "childCount" in reader_child
    assert "children" not in reader_child

    tree_reader = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "tree", "--node", "reader"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tree_reader.returncode == 0, tree_reader.stderr
    reader_tree = json.loads(tree_reader.stdout)
    assert reader_tree["tree"]["nodePath"] == "reader"
    state_nodes = reader_tree["tree"]["children"][0]["children"]
    assert any(state["label"] == "Translation" for state in state_nodes)

    leaf_path = state_nodes[0]["children"][0]["nodePath"]

    node_cmd = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "node", leaf_path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert node_cmd.returncode == 0, node_cmd.stderr
    node_payload = json.loads(node_cmd.stdout)
    assert node_payload["status"] == "ok"
    assert node_payload["node"]["kind"] == "asset"
    assert node_payload["node"]["relPath"].endswith(".png")
    assert node_payload["childCount"] == 0
    assert node_payload["ancestors"][0] == "reader"

    missing = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "node", "no/such/path"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["error"] == "node-not-found"

    url_cmd = subprocess.run(
        [sys.executable, str(REVIEW_CLI), str(output_root), "node-url", leaf_path, "--base", "http://127.0.0.1:8787/catalog.html"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert url_cmd.returncode == 0, url_cmd.stderr
    url_payload = json.loads(url_cmd.stdout)
    assert url_payload["url"] == f"http://127.0.0.1:8787/catalog.html#node={leaf_path}"


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

from __future__ import annotations

import importlib.util
import json
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


entry_module = load_module("catalog_review_entry", ROOT / "ops" / "catalog_review_entry.py")


def write_manifest(root: Path, name: str, *, total_images: int, continue_count: int, weak_count: int) -> None:
    artifact_root = root / name
    artifact_root.mkdir(parents=True)
    (artifact_root / "review_manifest.json").write_text(
        json.dumps({
            "totalImages": total_images,
            "promiseCounts": {
                "Continue": continue_count,
                "Weak": weak_count,
            },
            "stateCounts": {},
            "items": [
                {
                    "assetID": f"{name}-1",
                    "category": "Bookshelf",
                    "clusterID": "bookshelf",
                    "heroCandidate": True,
                    "newSincePr878": False,
                }
            ],
        }),
        encoding="utf-8",
    )


def test_choose_blessed_artifact_prefers_highest_total_images(tmp_path: Path):
    write_manifest(tmp_path, "catalog-full-older", total_images=896, continue_count=258, weak_count=364)
    write_manifest(tmp_path, "catalog-full-newer", total_images=1000, continue_count=290, weak_count=436)

    artifacts = entry_module.collect_review_artifacts(tmp_path)
    blessed = entry_module.choose_blessed_artifact(artifacts)

    assert blessed["name"] == "catalog-full-newer"
    assert blessed["totalImages"] == 1000
    assert blessed["promiseCounts"]["Continue"] == 290


def test_choose_blessed_artifact_breaks_ties_by_name(tmp_path: Path):
    write_manifest(tmp_path, "catalog-full-20260608-010944", total_images=1000, continue_count=258, weak_count=364)
    write_manifest(tmp_path, "catalog-full-20260608-020244", total_images=1000, continue_count=290, weak_count=436)

    artifacts = entry_module.collect_review_artifacts(tmp_path)
    blessed = entry_module.choose_blessed_artifact(artifacts)

    assert blessed["name"] == "catalog-full-20260608-020244"


def test_choose_blessed_artifact_prefers_usable_over_empty_newer_artifact(tmp_path: Path):
    write_manifest(tmp_path, "catalog-full-20260608-003356", total_images=1000, continue_count=290, weak_count=436)
    write_manifest(tmp_path, "catalog-full-20260608-999999", total_images=0, continue_count=0, weak_count=0)

    artifacts = entry_module.collect_review_artifacts(tmp_path)
    blessed = entry_module.choose_blessed_artifact(artifacts)

    assert blessed["name"] == "catalog-full-20260608-003356"
    assert blessed["isUsable"] is True


def test_prune_stale_artifacts_removes_empty_review_roots(tmp_path: Path):
    write_manifest(tmp_path, "catalog-full-empty", total_images=0, continue_count=0, weak_count=0)
    write_manifest(tmp_path, "catalog-full-usable", total_images=10, continue_count=2, weak_count=1)

    removed = entry_module.prune_stale_artifacts(tmp_path, dry_run=False)

    assert [item["name"] for item in removed] == ["catalog-full-empty"]
    assert not (tmp_path / "catalog-full-empty").exists()
    assert (tmp_path / "catalog-full-usable").exists()


def test_extract_directory_from_command():
    command = "/usr/bin/python3 -m http.server 8787 --directory /tmp/catalog-full-20260608-020244"
    assert entry_module.extract_directory_from_command(command) == "/tmp/catalog-full-20260608-020244"

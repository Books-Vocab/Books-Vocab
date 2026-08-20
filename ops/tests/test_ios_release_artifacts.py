from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))

import ios_release_artifacts as release_artifacts

APP_NAME = "BooksAndVocab.app"
BUNDLE_ID = "com.Max0228.BooksBrowser"


def make_app(
    root: Path,
    *,
    version: str,
    build: str,
    commit: str,
    destination: str = "platform=iOS Simulator,name=iPhone 17 Pro Max",
) -> Path:
    app = root / f"{version}-{build}-{commit[:8]}" / APP_NAME
    app.mkdir(parents=True)
    with (app / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": BUNDLE_ID,
                "CFBundleShortVersionString": version,
                "CFBundleVersion": build,
            },
            handle,
        )
    (app / "BooksAndVocab").write_bytes(f"{version}+{build}:{commit}".encode())
    Path(f"{app}.kg-provenance.json").write_text(
        json.dumps(
            {
                "schema": release_artifacts.INSTALL_PROVENANCE_SCHEMA,
                "projectRoot": "/tmp/kg-test",
                "head": commit,
                "configuration": "Debug",
                "destination": destination,
                "artifact": str(app),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return app


def record(
    root: Path,
    *,
    source: str,
    version: str,
    build: str,
    commit: str,
    app: Path | None,
) -> dict:
    return release_artifacts.record_release(
        root=root,
        source=source,
        version=version,
        build=build,
        commit=commit,
        app=app,
        source_ref=f"ios/{version}+{build}",
        released_at=None,
        keep=3,
    )


def test_retains_three_records_across_testflight_and_appstore(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    source_root = tmp_path / "source-apps"
    commit_a = "a" * 40
    commit_b = "b" * 40
    commit_c = "c" * 40
    app_a = make_app(source_root, version="2.0.0", build="1", commit=commit_a)
    app_b = make_app(source_root, version="2.0.1", build="2", commit=commit_b)
    app_c = make_app(source_root, version="2.0.2", build="3", commit=commit_c)

    testflight_a = record(
        root, source="testflight", version="2.0.0", build="1", commit=commit_a, app=app_a
    )
    appstore_a = record(
        root, source="appstore", version="2.0.0", build="1", commit=commit_a, app=None
    )
    assert testflight_a["record"]["artifactPath"] == appstore_a["record"]["artifactPath"]
    physical_a = root / testflight_a["record"]["artifactPath"]
    assert physical_a.is_dir()

    record(root, source="testflight", version="2.0.1", build="2", commit=commit_b, app=app_b)
    record(root, source="appstore", version="2.0.1", build="2", commit=commit_b, app=None)

    listed = release_artifacts.list_catalog(root=root, keep=3)
    assert [item["id"] for item in listed["records"]] == [
        "appstore:2.0.1+2",
        "testflight:2.0.1+2",
        "appstore:2.0.0+1",
    ]
    assert physical_a.is_dir(), "an alias still references the physical artifact"

    record(root, source="testflight", version="2.0.2", build="3", commit=commit_c, app=app_c)
    listed = release_artifacts.list_catalog(root=root, keep=3)
    assert len(listed["records"]) == 3
    assert all(item["commit"] != commit_a for item in listed["records"])
    assert not physical_a.exists(), "the fourth newest record evicts the old unreferenced app"
    assert release_artifacts.resolve_artifact(root=root, commit=commit_a, keep=3)["status"] == "miss"
    assert release_artifacts.validate_catalog(root=root, keep=3, deep=True)["status"] == "ok"


def test_rejects_device_app_even_when_bundle_metadata_matches(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    commit = "d" * 40
    app = make_app(
        tmp_path / "source-apps",
        version="2.0.0",
        build="1",
        commit=commit,
        destination="generic/platform=iOS",
    )

    with pytest.raises(release_artifacts.ArtifactError, match="不是 Simulator"):
        record(root, source="testflight", version="2.0.0", build="1", commit=commit, app=app)


def test_resolve_is_exact_commit_and_source_aware(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    commit = "e" * 40
    app = make_app(tmp_path / "source-apps", version="2.0.0", build="1", commit=commit)
    record(root, source="testflight", version="2.0.0", build="1", commit=commit, app=app)

    hit = release_artifacts.resolve_artifact(
        root=root, commit=commit, source="testflight", version="2.0.0", build="1", keep=3
    )
    assert hit["status"] == "hit"
    assert hit["appPath"].endswith("BooksAndVocab.app")
    assert release_artifacts.resolve_artifact(root=root, commit="f" * 40, keep=3)["status"] == "miss"
    assert release_artifacts.resolve_artifact(root=root, commit=commit, source="appstore", keep=3)["status"] == "miss"


def test_default_root_is_shared_by_worktrees() -> None:
    common_dir = subprocess.run(
        ["git", "-C", str(OPS_ROOT.parent), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected = Path(common_dir).resolve().parent / ".cache" / "ios-release-artifacts"
    assert release_artifacts.artifact_root() == expected.resolve()


def test_release_and_catalog_hooks_are_present() -> None:
    repo_root = OPS_ROOT.parent
    release_script = (repo_root / "ops" / "release.sh").read_text(encoding="utf-8")
    catalog_script = (repo_root / "ops" / "lib" / "ios_ops_catalog.sh").read_text(encoding="utf-8")
    assert "ios_release_record_testflight_artifact" in release_script
    assert "ios_release_record_appstore_artifact" in release_script
    assert "catalog_resolve_retained_app" in catalog_script
    assert "appSource" in catalog_script

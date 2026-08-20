from __future__ import annotations

import importlib.util
import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Self

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_report", ROOT / "ops" / "release_report.py"
)
assert SPEC and SPEC.loader
release_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_report)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "ios", "backend")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo_with_release_drift(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Release Report Test")

    (repo / "ios/BooksAndVocab.xcodeproj").mkdir(parents=True)
    (repo / "ios/BooksAndVocab.xcodeproj/project.pbxproj").write_text(
        "MARKETING_VERSION = 1.0.0;\n"
        "MARKETING_VERSION = 1.0.0;\n"
        "CURRENT_PROJECT_VERSION = 1;\n"
        "CURRENT_PROJECT_VERSION = 1;\n",
        encoding="utf-8",
    )
    (repo / "backend").mkdir()
    (repo / "backend/pyproject.toml").write_text(
        '[project]\nname = "kg"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (repo / "ios/BooksAndVocab/Feature.swift").parent.mkdir(parents=True)
    (repo / "ios/BooksAndVocab/Feature.swift").write_text(
        "let feature = \"old\"\n", encoding="utf-8"
    )
    (repo / "backend/src").mkdir(parents=True)
    (repo / "backend/src/service.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    release_sha = _commit(repo, "release: iOS 1.0.0 build 1")
    _git(repo, "tag", "ios/1.0.0+1", release_sha)
    _git(repo, "tag", "ios/1.0.0", release_sha)
    _git(repo, "branch", "prod", release_sha)

    (repo / "ios/BooksAndVocab/Feature.swift").write_text(
        "let feature = \"new\"\n", encoding="utf-8"
    )
    (repo / "backend/src/service.py").write_text("VALUE = 'new'\n", encoding="utf-8")
    main_sha = _commit(repo, "feat: change iOS and backend behavior")
    return repo, release_sha, main_sha


def test_parse_ios_settings_rejects_conflicting_values() -> None:
    with pytest.raises(release_report.ReportError, match="MARKETING_VERSION"):
        release_report.parse_ios_settings(
            "MARKETING_VERSION = 1.0.0;\nMARKETING_VERSION = 2.0.0;\n"
            "CURRENT_PROJECT_VERSION = 1;\n"
        )


def test_normalize_asc_snapshot_binds_ios_build_and_store_version() -> None:
    raw_builds = {
        "data": [
            {
                "type": "builds",
                "id": "build-10",
                "attributes": {
                    "version": "10",
                    "processingState": "VALID",
                    "uploadedDate": "2026-08-17T05:17:50Z",
                },
                "relationships": {
                    "preReleaseVersion": {
                        "data": {"type": "preReleaseVersions", "id": "pre-201"}
                    }
                },
            },
            {
                "type": "builds",
                "id": "mac-build-1",
                "attributes": {
                    "version": "1",
                    "processingState": "VALID",
                    "uploadedDate": "2026-08-18T05:17:50Z",
                },
                "relationships": {
                    "preReleaseVersion": {
                        "data": {"type": "preReleaseVersions", "id": "pre-mac"}
                    }
                },
            },
        ],
        "included": [
            {
                "type": "preReleaseVersions",
                "id": "pre-201",
                "attributes": {"version": "2.0.1", "platform": "IOS"},
            },
            {
                "type": "preReleaseVersions",
                "id": "pre-mac",
                "attributes": {"version": "2.0.1", "platform": "MAC_OS"},
            },
        ],
    }
    raw_versions = {
        "data": [
            {
                "type": "appStoreVersions",
                "id": "store-200",
                "attributes": {
                    "versionString": "2.0.0",
                    "appStoreState": "READY_FOR_SALE",
                    "platform": "IOS",
                },
            },
            {
                "type": "appStoreVersions",
                "id": "store-draft",
                "attributes": {
                    "versionString": "2.0.1",
                    "appStoreState": "PREPARE_FOR_SUBMISSION",
                    "platform": "IOS",
                },
            },
        ]
    }

    snapshot = release_report.normalize_asc_snapshot(raw_builds, raw_versions)

    assert snapshot["testflight"] == {
        "status": "observed",
        "version": "2.0.1",
        "build": "10",
        "ascBuildId": "build-10",
        "processingState": "VALID",
        "uploadedAt": "2026-08-17T05:17:50Z",
    }
    assert snapshot["appStore"] == {
        "status": "observed",
        "version": "2.0.0",
        "state": "READY_FOR_SALE",
        "ascVersionId": "store-200",
    }


def test_diff_refs_reports_source_delta(tmp_path: Path) -> None:
    repo, release_sha, main_sha = _repo_with_release_drift(tmp_path)

    result = release_report.diff_refs(repo, "ios", release_sha, main_sha)

    assert result["status"] == "changed"
    assert result["from"]["sha"] == release_sha
    assert result["to"]["sha"] == main_sha
    assert result["changedFiles"] == 1
    assert result["insertions"] == 1
    assert result["deletions"] == 1
    assert result["commitCount"] == 1
    assert result["files"] == [{"status": "M", "path": "ios/BooksAndVocab/Feature.swift"}]


def test_build_report_explains_ios_and_backend_drift(tmp_path: Path) -> None:
    repo, release_sha, main_sha = _repo_with_release_drift(tmp_path)
    asc_snapshot = {
        "testflight": {
            "status": "observed",
            "version": "1.0.0",
            "build": "1",
            "ascBuildId": "build-1",
            "processingState": "VALID",
            "uploadedAt": "2026-08-17T05:17:50Z",
        },
        "appStore": {
            "status": "observed",
            "version": "1.0.0",
            "state": "READY_FOR_SALE",
            "ascVersionId": "store-100",
        },
    }
    backend_live = {
        "status": "observed",
        "version": release_sha[:8],
        "startedAt": "2026-08-17T05:17:50Z",
        "migrationVersion": "inflections",
    }

    report = release_report.build_report(
        repo,
        main_ref="main",
        production_ref="prod",
        asc_snapshot=asc_snapshot,
        backend_live=backend_live,
        generated_at="2026-08-20T00:00:00Z",
    )

    assert report["schema"] == "kg.release.report.v1"
    assert report["repository"]["main"]["sha"] == main_sha
    assert report["ios"]["testflight"]["sourceBinding"]["status"] == "bound"
    assert report["ios"]["testflightToMain"]["changedFiles"] == 1
    assert report["backend"]["productionToMain"]["changedFiles"] == 1
    assert report["backend"]["production"]["liveAlignment"] == "aligned"
    assert report["verdict"]["status"] == "drift"

    human = release_report.render_report(report)
    assert "TestFlight 1.0.0 (build 1)" in human
    assert "backend" in human
    assert "DRIFT" in human


def test_report_marks_missing_release_tag_as_blocked(tmp_path: Path) -> None:
    repo, _, _ = _repo_with_release_drift(tmp_path)
    report = release_report.build_report(
        repo,
        main_ref="main",
        production_ref="prod",
        asc_snapshot={
            "testflight": {
                "status": "observed",
                "version": "9.9.9",
                "build": "99",
                "ascBuildId": "build-99",
                "processingState": "VALID",
                "uploadedAt": "2026-08-17T05:17:50Z",
            },
            "appStore": {"status": "unavailable", "reason": "fixture"},
        },
        backend_live={"status": "unavailable", "reason": "not requested"},
    )

    assert report["ios"]["testflight"]["sourceBinding"]["status"] == "unbound"
    assert report["ios"]["testflightToMain"]["status"] == "blocked"
    assert report["verdict"]["status"] == "blocked"


def test_backend_probe_sets_a_stable_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _Response:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"version": "abc12345"}).encode()

    def fake_urlopen(request: urllib.request.Request, timeout: int) -> _Response:
        captured["user-agent"] = request.get_header("User-agent") or ""
        captured["timeout"] = str(timeout)
        return _Response()

    monkeypatch.setattr(release_report.urllib.request, "urlopen", fake_urlopen)
    result = release_report.fetch_backend_live("https://example.test")

    assert result["status"] == "observed"
    assert captured == {"user-agent": "kg-release-report/1.0", "timeout": "10"}

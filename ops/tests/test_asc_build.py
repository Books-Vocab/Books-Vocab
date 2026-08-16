from __future__ import annotations

import pytest
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("asc_build", ROOT / "ops" / "asc_build.py")
assert SPEC and SPEC.loader
asc_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asc_build)


def _payload(*items: dict) -> dict:
    included = []
    seen = set()
    for item in items:
        relationship = (
            item.get("relationships", {}).get("preReleaseVersion", {}).get("data")
        )
        if not isinstance(relationship, dict):
            continue
        if relationship["id"] in seen:
            continue
        seen.add(relationship["id"])
        included.append(
            {
                "type": "preReleaseVersions",
                "id": relationship["id"],
                "attributes": item["_pre_release_attributes"],
            }
        )
    return {"data": list(items), "included": included}


def _build(
    *,
    build: str = "9",
    version: str = "2.0.1",
    platform: str = "IOS",
    state: str = "PROCESSING",
    build_id: str = "build-9",
    resource_type: str = "builds",
    version_value: object | None = None,
) -> dict:
    if version_value is None:
        version_value = build
    return {
        "type": resource_type,
        "id": build_id,
        "attributes": {
            "version": version_value,
            "processingState": state,
        },
        "relationships": {
            "preReleaseVersion": {
                "data": {"type": "preReleaseVersions", "id": f"pre-{version}"}
            }
        },
        "_pre_release_attributes": {"version": version, "platform": platform},
    }


def test_select_exact_build_returns_provenance() -> None:
    result = asc_build.select_exact_build(
        _payload(_build()), marketing_version="2.0.1", build_number="9"
    )

    assert result == {
        "schema": "kg.asc.build.v1",
        "id": "build-9",
        "version": "2.0.1",
        "build": "9",
        "platform": "IOS",
        "processingState": "PROCESSING",
    }


def test_select_exact_build_rejects_missing_or_mismatched_build() -> None:
    with pytest.raises(asc_build.NoExactBuild):
        asc_build.select_exact_build(
            _payload(_build(build="8")), marketing_version="2.0.1", build_number="9"
        )


def test_select_exact_build_rejects_ambiguous_matches() -> None:
    with pytest.raises(asc_build.AmbiguousExactBuild, match="count=2"):
        asc_build.select_exact_build(
            _payload(_build(build_id="build-a"), _build(build_id="build-b")),
            marketing_version="2.0.1",
            build_number="9",
        )


def test_select_exact_build_rejects_http_error() -> None:
    with pytest.raises(asc_build.AscBuildError, match="HTTP 403"):
        asc_build.select_exact_build(
            {"_httpError": 403, "_detail": {"errors": ["agreement"]}},
            marketing_version="2.0.1",
            build_number="9",
        )


def test_select_exact_build_requires_ios_prerelease_relationship() -> None:
    item = _build(platform="MAC_OS")
    with pytest.raises(asc_build.NoExactBuild):
        asc_build.select_exact_build(
            _payload(item), marketing_version="2.0.1", build_number="9"
        )


def test_select_exact_build_rejects_missing_prerelease_relationship() -> None:
    item = _build()
    del item["relationships"]
    with pytest.raises(asc_build.AscBuildError, match="preReleaseVersion"):
        asc_build.select_exact_build(
            _payload(item), marketing_version="2.0.1", build_number="9"
        )


def test_select_exact_build_rejects_wrong_resource_type_or_version_type() -> None:
    with pytest.raises(asc_build.AscBuildError, match="type"):
        asc_build.select_exact_build(
            _payload(_build(resource_type="not-builds")),
            marketing_version="2.0.1",
            build_number="9",
        )
    with pytest.raises(asc_build.AscBuildError, match="version"):
        asc_build.select_exact_build(
            _payload(_build(version_value=9)),
            marketing_version="2.0.1",
            build_number="9",
        )


@pytest.mark.parametrize("item", [{"type": "builds", "id": "missing-attrs"}, None])
def test_select_exact_build_rejects_malformed_data_entries(item: object) -> None:
    with pytest.raises(asc_build.AscBuildError, match="data entry"):
        asc_build.select_exact_build(
            {"data": [item]}, marketing_version="2.0.1", build_number="9"
        )


def test_select_exact_build_rejects_failed_processing_state() -> None:
    with pytest.raises(asc_build.AscBuildError, match="release-eligible"):
        asc_build.select_exact_build(
            _payload(_build(state="FAILED")),
            marketing_version="2.0.1",
            build_number="9",
        )


def test_lookup_exact_build_uses_app_and_build_filters_and_include(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_get(path: str, token: str) -> dict:
        captured["path"] = path
        captured["token"] = token
        return _payload(_build())

    monkeypatch.setattr(asc_build, "get", fake_get)
    monkeypatch.setattr(asc_build, "mint_token", lambda: "test-token")

    result = asc_build.lookup_exact_build("2.0.1", "9")
    parsed = urlsplit(captured["path"])
    assert parsed.path == "/v1/builds"
    query = parse_qs(parsed.query)
    assert query["filter[app]"] == [asc_build.APP_ID]
    assert query["filter[version]"] == ["9"]
    assert query["include"] == ["preReleaseVersion"]
    assert captured["token"] == "test-token"
    assert result["id"] == "build-9"


def test_main_maps_ambiguous_match_to_hard_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def ambiguous(*args: object, **kwargs: object) -> dict:
        raise asc_build.AmbiguousExactBuild("ambiguous")

    monkeypatch.setattr(asc_build, "lookup_exact_build", ambiguous)
    assert asc_build.main(["2.0.1", "9"]) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_main_maps_missing_match_to_retryable_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> dict:
        raise asc_build.NoExactBuild("not yet")

    monkeypatch.setattr(asc_build, "lookup_exact_build", missing)
    assert asc_build.main(["2.0.1", "9"]) == 3


def test_main_maps_unexpected_lookup_error_to_clean_hard_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*args: object, **kwargs: object) -> dict:
        raise ValueError("malformed response")

    monkeypatch.setattr(asc_build, "lookup_exact_build", broken)
    assert asc_build.main(["2.0.1", "9"]) == 1
    assert "malformed response" in capsys.readouterr().err

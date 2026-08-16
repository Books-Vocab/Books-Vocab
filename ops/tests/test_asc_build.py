from __future__ import annotations

import pytest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("asc_build", ROOT / "ops" / "asc_build.py")
assert SPEC and SPEC.loader
asc_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asc_build)


def _payload(*items: dict) -> dict:
    return {"data": list(items)}


def _build(*, build: str = "9", version: str = "2.0.1", state: str = "PROCESSING", build_id: str = "build-9") -> dict:
    return {
        "type": "builds",
        "id": build_id,
        "attributes": {
            "platform": "IOS",
            "versionString": version,
            "version": build,
            "processingState": state,
        },
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
    with pytest.raises(asc_build.NoExactBuild, match="count=2"):
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

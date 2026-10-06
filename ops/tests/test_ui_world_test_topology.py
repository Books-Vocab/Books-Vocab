"""Deterministic ownership routes for UI World fixture contract tests.

The full ``demo-data`` group is useful for release confidence, but it is too
broad for small fixture-contract changes.  This contract keeps the smaller
manifest, asset, projection, seed, review, malformed-input, and UI-evidence
routes explicit and fail-closed when collection becomes empty or ambiguous.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FILE = "ops/tests/test_ui_world_manifest.py"
EMITTER_FILES = frozenset(
    {
        "ops/tests/test_demo_ios_emitter.py",
        "ops/tests/test_demo_ios_spec_emitter.py",
    }
)
EVIDENCE_FILES = frozenset(
    {
        "ops/tests/test_uitest_evidence_contract.py",
        "ops/tests/test_uitest_flow_matrix.py",
        "ops/tests/test_uitest_review_page.py",
    }
)
ROUTE_FILES = (MANIFEST_FILE, *sorted(EMITTER_FILES), *sorted(EVIDENCE_FILES))
ROUTES = (
    "manifest-schema",
    "asset-preflight",
    "projection-catalog",
    "seed-emitter",
    "review-graph",
    "malformed-negative",
    "uitest-evidence",
)


def _node(path: str, name: str) -> str:
    return f"{path}::{name}"


REQUIRED_CONTROLS = {
    "manifest-schema": _node(MANIFEST_FILE, "test_validate_accepts_repo_ui_world"),
    "asset-preflight": _node(
        MANIFEST_FILE, "test_reader_real_book_is_a_distinguishable_two_chapter_epub"
    ),
    "projection-catalog": _node(
        MANIFEST_FILE,
        "test_marketing_demo_declares_canonical_explore_shared_decks_contract",
    ),
    "seed-emitter": _node(
        "ops/tests/test_demo_ios_emitter.py",
        "test_emit_ios_matches_committed_generated_fixture_dataset",
    ),
    "review-graph": _node(
        MANIFEST_FILE,
        "test_review_calendar_evidence_mapping_has_no_checkout_identity_fields",
    ),
    "malformed-negative": _node(
        MANIFEST_FILE, "test_validate_accepts_legacy_null_review_clock"
    ),
    "uitest-evidence": _node(
        "ops/tests/test_uitest_evidence_contract.py",
        "test_validate_bundle_requires_real_hashed_steps_and_provenance",
    ),
}

NEGATIVE_CONTROLS = {
    "manifest-schema": _node(
        MANIFEST_FILE, "test_validate_rejects_ui_world_without_top_level_shared_decks"
    ),
    "asset-preflight": _node(MANIFEST_FILE, "test_validate_rejects_asset_hash_drift"),
    "projection-catalog": _node(
        MANIFEST_FILE,
        "test_validate_rejects_stale_explore_surface_contract_projection",
    ),
    "seed-emitter": _node(
        "ops/tests/test_demo_ios_emitter.py",
        "test_emit_ios_rejects_unknown_top_level_key",
    ),
    "review-graph": _node(
        MANIFEST_FILE, "test_validate_rejects_graph_link_to_missing_in_seed_target"
    ),
    "malformed-negative": _node(
        MANIFEST_FILE, "test_validate_rejects_retired_dictionary_scenario_key"
    ),
    "uitest-evidence": _node(
        "ops/tests/test_uitest_evidence_contract.py",
        "test_validate_bundle_rejects_tampered_step",
    ),
}

MUTATION_CONTROLS = {
    "manifest-schema": NEGATIVE_CONTROLS["manifest-schema"],
    "asset-preflight": NEGATIVE_CONTROLS["asset-preflight"],
    "projection-catalog": NEGATIVE_CONTROLS["projection-catalog"],
    "seed-emitter": _node(
        "ops/tests/test_demo_ios_emitter.py",
        "test_emit_ios_rejects_non_identity_domain_drift",
    ),
    "review-graph": NEGATIVE_CONTROLS["review-graph"],
    "malformed-negative": REQUIRED_CONTROLS["malformed-negative"],
    "uitest-evidence": NEGATIVE_CONTROLS["uitest-evidence"],
}


def _collect(*selectors: str) -> tuple[str, ...]:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    result = subprocess.run(
        [
            uv,
            "run",
            "--no-project",
            "--python",
            "3.13",
            "--with",
            "pytest",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            *selectors,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 5:
        raise AssertionError(f"zero-selector collection: {selectors!r}")
    assert result.returncode == 0, (
        f"collection failed for {selectors!r} (exit {result.returncode}): "
        f"{result.stderr or result.stdout}"
    )
    nodeids = tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("ops/tests/") and "::" in line
    )
    assert nodeids, f"zero-selector collection: {selectors!r}"
    return nodeids


def _base_nodeid(nodeid: str) -> str:
    path, name = nodeid.split("::", 1)
    return f"{path}::{name.split('[', 1)[0]}"


def _route_for(path: str, name: str) -> str:
    if path in EVIDENCE_FILES:
        return "uitest-evidence"
    if path in EMITTER_FILES:
        return "seed-emitter"
    if path != MANIFEST_FILE:
        raise AssertionError(f"unrouted UI World test file: {path}")

    if name in {
        "test_validate_accepts_repo_ui_world",
        "test_validate_rejects_ui_world_without_top_level_shared_decks",
    }:
        return "manifest-schema"
    if name in {
        "test_validate_accepts_legacy_null_review_clock",
        "test_validate_rejects_retired_dictionary_scenario_key",
    }:
        return "malformed-negative"

    if any(
        token in name
        for token in (
            "asset",
            "reader_",
            "fixture_store",
            "manifest_path_resolver",
            "runtime_download",
            "book_install",
            "notebook_cover",
        )
    ):
        return "asset-preflight"
    if any(token in name for token in ("review", "graph", "vocabulary", "clock")):
        return "review-graph"
    if any(
        token in name
        for token in (
            "explore",
            "shared_deck",
            "scenario",
            "domain_id",
            "preference",
            "settings",
            "bookshelf",
            "notebook",
            "podcast",
            "today_review",
            "sync_presenter",
            "surface",
        )
    ):
        return "projection-catalog"
    if any(
        token in name
        for token in (
            "reject",
            "invalid",
            "missing",
            "unknown",
            "duplicate",
            "drift",
            "cycle",
            "null",
            "empty",
        )
    ):
        return "malformed-negative"
    return "manifest-schema"


def _routes_for_collected(collected: Counter[str]) -> dict[str, tuple[str, ...]]:
    routes: dict[str, list[str]] = {route: [] for route in ROUTES}
    for nodeid in sorted(collected):
        path, name = nodeid.split("::", 1)
        routes[_route_for(path, name)].append(nodeid)
    return {route: tuple(nodes) for route, nodes in routes.items()}


def _collected_bases() -> Counter[str]:
    collected: Counter[str] = Counter()
    for path in ROUTE_FILES:
        collected.update(_base_nodeid(nodeid) for nodeid in _collect(path))
    return collected


def test_routes_collect_without_zero_selectors_and_have_unique_nodeids():
    collected = _collected_bases()
    assert collected
    routes = _routes_for_collected(collected)
    assigned = Counter(nodeid for nodes in routes.values() for nodeid in nodes)
    assert all(count == 1 for count in assigned.values())
    assert set(assigned) == set(collected)
    assert all(routes[route] for route in ROUTES)


@pytest.mark.parametrize(
    "control_set", (REQUIRED_CONTROLS, NEGATIVE_CONTROLS, MUTATION_CONTROLS)
)
def test_each_route_has_a_named_control(control_set):
    collected = _collected_bases()
    routes = _routes_for_collected(collected)
    assigned = {nodeid: route for route, nodes in routes.items() for nodeid in nodes}
    assert set(control_set) == set(ROUTES)
    for route, nodeid in control_set.items():
        assert nodeid in assigned, nodeid
        assert assigned[nodeid] == route


@pytest.mark.parametrize(
    ("filename", "contents", "message"),
    (
        ("test_malformed_collection.py", "def broken(:\n", "collection failed"),
        ("test_zero_selector_collection.py", "VALUE = 1\n", "zero-selector"),
    ),
)
def test_collection_probe_fails_closed_for_malformed_or_zero_selector(
    tmp_path: Path, filename: str, contents: str, message: str
):
    path = tmp_path / filename
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(AssertionError, match=message):
        _collect(str(path))

"""Regression coverage for fail-closed ops world identity indexes."""

from kg.ops_world_diff import diff_seed_spec, diff_world_state


def _world_expected(*, notebooks=None, graphs=None):
    expected = {"schema": "kg.ops_world_expectation.v1"}
    if notebooks is not None:
        expected["notebooks"] = notebooks
    if graphs is not None:
        expected["graphs"] = graphs
    return expected


def _seed_expected(*, notebooks=None, links=None):
    expected = {"schema": "kg.seed_spec.v1"}
    if notebooks is not None:
        expected["notebooks"] = notebooks
    if links is not None:
        expected["links"] = links
    return expected


def _mismatch_keys(result):
    return [(item["kind"], item["path"]) for item in result["mismatches"]]


def test_world_diff_rejects_duplicate_notebook_aliases():
    actual = {
        "schema": "kg.ops_world_projection.v1",
        "notebooks": [
            {"id": "default", "name": "Blue", "color": "#111111"},
            {"id": "other", "name": "Blue", "color": "#111111"},
            {"id": "default", "name": "Green", "color": "#222222"},
        ],
    }
    expected = _world_expected(
        notebooks=[{"name": "Blue", "color": "#111111"}],
    )

    result = diff_world_state(actual, expected)

    assert result["ok"] is False
    assert ("duplicate-notebook", "notebooks[Blue]") in _mismatch_keys(result)
    assert ("duplicate-notebook", "notebooks[default]") in _mismatch_keys(result)


def test_world_diff_rejects_duplicate_graph_keys():
    actual = {
        "schema": "kg.ops_world_projection.v1",
        "graphs": [
            {"notebook_id": "first", "notebook_name": "Alpha", "links": []},
            {"notebook_id": "second", "notebook_name": "Alpha", "links": []},
        ],
    }
    expected = _world_expected(graphs=[{"notebook": "Alpha", "links": []}])

    result = diff_world_state(actual, expected)

    assert result["ok"] is False
    assert ("duplicate-graph", "graphs[Alpha]") in _mismatch_keys(result)


def test_world_diff_rejects_duplicate_link_keys():
    actual = {
        "schema": "kg.ops_world_projection.v1",
        "graphs": [{
            "notebook_name": "Alpha",
            "links": [
                {"from_content": "a", "to_content": "b", "kind": "related", "confidence": 0.9},
                {"from_content": "a", "to_content": "b", "kind": "related", "confidence": 0.9},
            ],
        }],
    }
    expected = _world_expected(graphs=[{
        "notebook": "Alpha",
        "links": [{"from": "a", "to": "b", "kind": "related", "confidence": 0.9}],
    }])

    result = diff_world_state(actual, expected)

    assert result["ok"] is False
    assert (
        "duplicate-link",
        "graphs[Alpha].links[a->b:related]",
    ) in _mismatch_keys(result)


def test_world_diff_preserves_valid_subset_comparison():
    actual = {
        "schema": "kg.ops_world_projection.v1",
        "notebooks": [
            {"id": "alpha", "name": "Alpha", "color": "#111111"},
            {"id": "beta", "name": "Beta", "color": "#222222"},
        ],
        "graphs": [{
            "notebook_name": "Alpha",
            "links": [
                {"from_content": "a", "to_content": "b", "kind": "related", "confidence": 0.9},
                {"from_content": "b", "to_content": "c", "kind": "related", "confidence": 0.8},
            ],
        }],
    }
    expected = _world_expected(
        notebooks=[{"name": "Alpha", "color": "#111111"}],
        graphs=[{
            "notebook": "Alpha",
            "links": [{"from": "a", "to": "b", "kind": "related", "confidence": 0.9}],
        }],
    )

    result = diff_world_state(actual, expected)

    assert result["ok"] is True
    assert result["mismatches"] == []


def test_seed_diff_rejects_duplicate_notebook_and_link_keys():
    actual = {
        "schema": "kg.seed_spec.v1",
        "notebooks": [
            {"name": "Alpha", "color": "#111111"},
            {"name": "Alpha", "color": "#111111"},
        ],
        "links": [
            {"notebook": "Alpha", "from": "a", "to": "b", "kind": "related", "confidence": 0.9},
            {"notebook": "Alpha", "from": "a", "to": "b", "kind": "related", "confidence": 0.9},
        ],
    }
    expected = _seed_expected(
        notebooks=[{"name": "Alpha", "color": "#111111"}],
        links=[{"notebook": "Alpha", "from": "a", "to": "b", "kind": "related", "confidence": 0.9}],
    )

    result = diff_seed_spec(actual, expected)

    assert result["ok"] is False
    assert ("duplicate-notebook", "notebooks[Alpha]") in _mismatch_keys(result)
    assert ("duplicate-link", "links[Alpha/a->b:related]") in _mismatch_keys(result)


def test_seed_diff_rejects_duplicate_expected_keys():
    actual = {
        "schema": "kg.seed_spec.v1",
        "notebooks": [{"name": "Alpha", "color": "#111111"}],
        "links": [{
            "notebook": "Alpha", "from": "a", "to": "b",
            "kind": "related", "confidence": 0.9,
        }],
    }
    expected = _seed_expected(
        notebooks=[
            {"name": "Alpha", "color": "#111111"},
            {"name": "Alpha", "color": "#111111"},
        ],
        links=[
            {"notebook": "Alpha", "from": "a", "to": "b", "kind": "related", "confidence": 0.9},
            {"notebook": "Alpha", "from": "a", "to": "b", "kind": "related", "confidence": 0.9},
        ],
    )

    result = diff_seed_spec(actual, expected)

    assert result["ok"] is False
    assert ("duplicate-notebook", "notebooks[Alpha]") in _mismatch_keys(result)
    assert ("duplicate-link", "links[Alpha/a->b:related]") in _mismatch_keys(result)


def test_duplicate_diagnostics_are_order_independent():
    expected = _world_expected(
        notebooks=[{"name": "Alpha"}],
        graphs=[{"notebook": "Alpha", "links": []}],
    )
    actual_a = {
        "notebooks": [
            {"id": "a", "name": "Alpha"},
            {"id": "b", "name": "Alpha"},
        ],
        "graphs": [
            {"notebook_id": "a", "notebook_name": "Alpha", "links": []},
            {"notebook_id": "b", "notebook_name": "Alpha", "links": []},
        ],
    }
    actual_b = {
        "notebooks": list(reversed(actual_a["notebooks"])),
        "graphs": list(reversed(actual_a["graphs"])),
    }

    result_a = diff_world_state(actual_a, expected)
    result_b = diff_world_state(actual_b, expected)

    assert result_a["ok"] is False
    assert _mismatch_keys(result_a) == _mismatch_keys(result_b)

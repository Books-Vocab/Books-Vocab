from pathlib import Path


ROOT = Path(__file__).parents[1] / "kg_board" / "web"
APP = (ROOT / "app.js").read_text()
CSS = (ROOT / "app.css").read_text()
INDEX = (ROOT / "index.html").read_text()


def test_matrix_has_the_same_fullscreen_viewer_contract_as_tree():
    assert 'id="scope-fullscreen-viewer"' in INDEX
    assert 'id="scope-fullscreen-canvas"' in INDEX
    assert 'id="scope-fullscreen-close"' in INDEX
    assert 'id="scope-fullscreen-fit"' in INDEX
    assert 'id="scope-fullscreen-reset"' in INDEX
    assert 'id="scope-fullscreen-zoom-in"' in INDEX
    assert 'id="scope-fullscreen-zoom-out"' in INDEX
    assert "openScopeFullscreen" in APP
    assert "fitScopeFullscreen" in APP
    assert "resetScopeFullscreen" in APP


def test_matrix_viewer_is_vector_or_dom_based_and_uses_shared_controls():
    assert "refreshScopeFullscreen" in APP
    assert "applyScopeFullscreenTransform" in APP
    assert ".scope-fullscreen-canvas" in CSS
    assert 'svg.style.transform="none"' in APP


def test_graph_keeps_horizontal_then_vertical_cross_lane_routing():
    assert "routeCrossLaneEdge" in APP
    assert "H ${startX} V ${startY}" in APP
    assert "quadraticCurveTo" not in APP
    assert "routeRailGroups" not in APP


def test_lane_labels_have_full_value_available_without_relying_on_ellipsis():
    assert 'data-branch-label="${esc(ref.branch)}"' in APP
    assert "tree-lane-label" in CSS
    assert "white-space:normal" in CSS


def test_primary_surfaces_do_not_render_second_hand_explanations():
    assert 'class="section-note"' not in INDEX
    assert 'class="scope-key"' not in INDEX
    assert 'class="scope-fullscreen-hint"' not in INDEX
    assert 'class="tree-fullscreen-hint"' not in INDEX
    assert 'class="tree-boundary-note"' not in INDEX
    assert "將游標移到 commit 或 branch 節點查看詳細資料" not in INDEX
    assert 'id="scope-state"' not in INDEX
    assert 'id="tree-state"' not in INDEX


def test_matrix_has_one_structured_header_row_and_a_file_inspector_mount():
    assert 'class="scope-header-row"' in APP
    assert "scope-column-fields" in APP
    assert 'id="scope-inspector"' in INDEX


def test_branch_index_is_a_first_hand_structured_surface_not_a_legend():
    assert 'id="branch-index"' in INDEX
    assert 'id="tree-legend"' not in INDEX
    assert "renderBranchIndex" in APP
    assert "branch-index-item" in APP
    assert ".branch-index" in CSS

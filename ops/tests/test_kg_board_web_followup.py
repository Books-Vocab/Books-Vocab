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
    assert ".scope-fullscreen-actions.tree-control-button{min-height:44px}" in "".join(CSS.split())
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


def test_shared_view_toolbar_and_matrix_geometry_are_real_css_contracts():
    assert 'class="board-toolbar scope-toolbar"' in INDEX
    assert 'class="board-toolbar tree-toolbar"' in INDEX
    compact_css = "".join(CSS.split())
    assert ".scope-controls{display:grid" in compact_css
    for variable in ("--scope-scale", "--scope-font-size", "--scope-column-width", "--scope-file-width", "--scope-head-height", "--scope-row-height"):
        assert variable in APP
        assert f"var({variable}" in CSS
    assert ".scope-workspace,.tree-workspace{display:grid" in compact_css
    assert "@media(max-width:860px)" in CSS
    assert "grid-template-columns:1fr" in CSS


def test_matrix_fit_reset_and_selection_use_stable_source_ids():
    assert "function fitScopeMatrix" in APP
    assert "table.scrollWidth" in APP
    assert "scopeZoom/100" in APP
    assert "scopeSelection" in APP
    assert "function setScopeSelection" in APP
    assert "function restoreScopeSelection" in APP
    assert "data-file-path" in APP
    assert "data-column-id" in APP
    assert "scope-cell-selected" in CSS
    assert "scope-row-selected" in CSS
    assert 'document.getElementById("scope-fit")?.addEventListener("click",()=>{fitScopeMatrix()})' in APP


def test_matrix_inspector_is_structured_and_not_an_empty_instruction_panel():
    assert 'id="scope-inspector"' in INDEX
    assert "MATRIX INSPECTOR" in APP
    for field in ("file_path", "column_id", "column_type", "operation", "state", "collision", "scope"):
        assert f'"{field}"' in APP
    assert "scope-inspector[hidden]" in CSS
    assert "scope-inspector" in APP
    assert "選取檔案或欄位查看" not in INDEX


def test_matrix_keeps_agent_identity_dirty_sources_and_live_snapshot_reload():
    for field in ("agent_title", "agent_status", "host", "thread", "dirty_file_count", "dirty_files"):
        assert f'"{field}"' in APP
    assert 'liveEvents.addEventListener("snapshot",scheduleLiveReload)' in APP
    assert 'setInterval(()=>load().catch(showLoadError),30000)' in APP
    assert "publish_event" not in APP
    assert "grid-area=" not in CSS


def test_graph_selection_is_first_hand_and_uses_one_structured_inspector():
    assert 'id="commit-inspector"' in INDEX
    assert 'id="tree-hover-card"' not in INDEX
    for function_name in (
        "setTreeSelection",
        "applyTreeSelection",
        "restoreTreeSelection",
        "renderTreeInspector",
        "selectBoundary",
    ):
        assert f"function {function_name}" in APP
    for source_field in (
        "sha",
        "subject",
        "author",
        "committed_at",
        "parents",
        "refs",
        "worktree",
        "diff_stat",
        "files",
        "boundary_id",
        "missing_parent",
        "integration_owner",
        "worktree_present",
    ):
        assert f'"{source_field}"' in APP
    for data_attribute in ("data-from-sha", "data-to-sha", "data-boundary-id", "data-branches"):
        assert data_attribute in APP
    for selection_class in ("tree-selected", "tree-related", "tree-edge-selected", "tree-branch-selected"):
        assert selection_class in CSS
    assert "refreshTreeFullscreen();" in APP
    assert "restoreTreeSelection();" in APP
    assert "function treeDisplayState(ref)" in APP
    assert 'scopeFieldMarkup("state",esc(treeDisplayState(ref)))' in APP


def test_mobile_keeps_tree_controls_and_places_inspector_after_graph_content():
    compact_css = "".join(CSS.split())
    assert ".tree-workspace{grid-template-columns:1fr}" in compact_css
    assert ".tree-workspace.commit-inspector{grid-column:1;grid-row:3}" in compact_css
    assert "@media(max-width:860px){.tree-controls{display:grid" in compact_css

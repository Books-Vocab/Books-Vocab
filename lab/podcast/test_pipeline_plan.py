from __future__ import annotations

import json
from pathlib import Path

import pipeline_plan


def test_stage_registry_matches_both_workflow_orders() -> None:
    root = Path(__file__).parent / "workflow_versions"
    expected = tuple(spec.name for spec in pipeline_plan.STAGE_SPECS)
    for version in ("v1", "v2"):
        workflow = json.loads((root / version / "workflow.json").read_text())
        specs = pipeline_plan.stage_specs_from_workflow(workflow)
        assert tuple(spec.name for spec in specs) == tuple(workflow["stage_order"])
        assert tuple(spec.name for spec in specs) == expected
    assert pipeline_plan.stage_spec("series-polish").series_wide is True
    assert pipeline_plan.stage_spec("publish").series_wide is True
    assert pipeline_plan.stage_spec("scriptwrite").approval_marker == ".plan_approved"
    assert pipeline_plan.stage_spec("tts-prep").approval_marker == ".script_approved"


def test_resolve_run_plan_applies_range_and_resume() -> None:
    config = pipeline_plan.PipelineConfig.from_names(
        ["prep", "architect", "scriptwrite", "publish"],
        skip_to="architect",
        stop_after="publish",
    )
    plan = pipeline_plan.resolve_run_plan(config, resume_index=0)
    assert plan.stage_names == ("architect", "scriptwrite", "publish")
    assert plan.start_index == 1
    assert plan.stop_index == 3
    assert plan.explicit_skip_index == 1

    resumed = pipeline_plan.resolve_run_plan(
        pipeline_plan.PipelineConfig.from_names(["prep", "architect", "scriptwrite"]),
        resume_index=2,
    )
    assert resumed.stage_names == ("scriptwrite",)
    assert resumed.explicit_skip_index is None


def test_only_episode_filters_series_wide_but_explicit_stage_wins() -> None:
    config = pipeline_plan.PipelineConfig.from_names(
        ["scriptwrite", "series-polish", "publish"], only_episode=3
    )
    plan = pipeline_plan.resolve_run_plan(config)
    assert plan.stage_names == ("scriptwrite",)
    assert plan.skipped_series_wide == ("series-polish", "publish")

    explicit = pipeline_plan.PipelineConfig.from_names(
        ["series-polish"], only_stage="series-polish", only_episode=3
    )
    assert pipeline_plan.resolve_run_plan(explicit).stage_names == ("series-polish",)


def test_invalid_ranges_are_rejected_before_runner_side_effects() -> None:
    config = pipeline_plan.PipelineConfig.from_names(
        ["prep", "publish"], skip_to="publish", stop_after="prep"
    )
    try:
        pipeline_plan.resolve_run_plan(config)
    except ValueError as exc:
        assert "after" in str(exc)
    else:
        raise AssertionError("reversed stage range must be rejected")


def test_workspace_state_owns_markers_and_manifest(tmp_path) -> None:
    state = pipeline_plan.WorkspaceState(tmp_path)

    assert state.marker_path("prep") == tmp_path / ".stage_prep_done"
    assert not state.stage_done("prep")
    state.mark_stage_done("prep", timestamp="2026-08-11T12:00:00")
    assert state.stage_done("prep")
    assert state.marker_path("prep").read_text() == "2026-08-11T12:00:00"

    manifest = {"workflow_version": "v1", "stage_order": ["prep"]}
    assert state.read_manifest() is None
    state.write_manifest(manifest)
    assert state.read_manifest() == manifest
    assert state.manifest_path() == tmp_path / "workflow_manifest.json"


def test_workspace_state_provenance_detects_content_not_mtime_drift(tmp_path) -> None:
    state = pipeline_plan.WorkspaceState(tmp_path)
    inputs = {
        "source/metadata.md": {
            "sha256": "input-sha",
            "bytes": 10,
            "mtime": "2026-08-11T12:00:00",
        }
    }
    prompt = {"name": "prep", "sha256": "prompt-sha", "path": "prompts/prep.md"}
    state.write_provenance(
        "prep",
        {
            "stage": "prep",
            "success": True,
            "input_artifacts": inputs,
            "prompt": prompt,
        },
    )

    assert state.has_provenance("prep")
    assert not state.provenance_is_stale(
        "prep",
        current_inputs={
            "source/metadata.md": {
                "sha256": "input-sha",
                "bytes": 10,
                "mtime": "2026-08-11T13:00:00",
            }
        },
        current_prompt=prompt,
    )
    assert state.provenance_is_stale(
        "prep",
        current_inputs={
            "source/metadata.md": {
                "sha256": "changed-sha",
                "bytes": 10,
                "mtime": "2026-08-11T13:00:00",
            }
        },
        current_prompt=prompt,
    )
    assert state.provenance_is_stale(
        "prep",
        current_inputs=inputs,
        current_prompt={"name": "prep", "sha256": "changed-prompt"},
    )


def test_workspace_state_missing_or_failed_provenance_is_safe(tmp_path) -> None:
    state = pipeline_plan.WorkspaceState(tmp_path)
    assert not state.has_provenance("prep")
    assert not state.provenance_is_stale("prep", current_inputs={}, current_prompt=None)

    state.write_provenance("prep", {"stage": "prep", "success": False})
    assert state.provenance_is_stale("prep", current_inputs={}, current_prompt=None)

    state.provenance_path("prep").write_text("not-json")
    try:
        state.read_provenance("prep")
    except ValueError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("malformed provenance must fail closed")


def test_pipeline_resume_rewinds_on_provenance_drift(tmp_path, monkeypatch) -> None:
    import pipeline

    state = pipeline_plan.WorkspaceState(tmp_path)
    state.mark_stage_done("prep", timestamp="2026-08-11T12:00:00")
    state.write_provenance(
        "prep",
        {
            "stage": "prep",
            "success": True,
            "input_artifacts": {"source/metadata.md": {"sha256": "old"}},
            "prompt": None,
        },
    )
    observed: dict[str, object] = {}

    def current_inputs(workspace, stage, only_episode):
        observed["only_episode"] = only_episode
        return {"source/metadata.md": {"sha256": "new"}}

    monkeypatch.setattr(pipeline, "capture_stage_inputs", current_inputs)
    monkeypatch.setattr(pipeline, "_stage_prompt_metadata", lambda *_: None)
    assert pipeline.detect_resume_point(tmp_path, ["prep", "analyst"]) == 0
    assert observed["only_episode"] is None

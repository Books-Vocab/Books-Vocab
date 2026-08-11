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


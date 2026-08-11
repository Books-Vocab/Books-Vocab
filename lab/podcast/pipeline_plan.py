"""Pure planning primitives for the podcast pipeline.

The runner used to keep stage order, series-wide semantics, and approval
boundaries in several unrelated constants and branches.  This module is
deliberately side-effect free: it owns the stage metadata and turns a workflow
definition plus CLI intent into a deterministic run plan.  ``pipeline.py``
keeps the legacy ``STAGES``/helper exports as compatibility aliases while all
new callers should use these typed objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


_STAGE_MARKER = ".stage_{name}_done"
_WORKFLOW_MANIFEST = "workflow_manifest.json"
_STAGE_PROVENANCE_DIR = "stage_provenance"


@dataclass(frozen=True)
class StageSpec:
    """Metadata required to plan one stage.

    ``series_wide`` controls the bare ``--only-episode`` filter.  An approval
    marker belongs to the stage it guards, which makes the gate boundary
    discoverable without a second map in the runner.
    """

    name: str
    series_wide: bool = False
    approval_marker: str | None = None
    prompt_name: str | None = None


_STAGE_DEFINITIONS: tuple[StageSpec, ...] = (
    StageSpec("prep", prompt_name="prep"),
    StageSpec("analyst", prompt_name="analyst"),
    StageSpec("architect", prompt_name="architect"),
    StageSpec("plan-review", prompt_name="plan_review"),
    StageSpec("enricher-gap", prompt_name="enricher_gap"),
    StageSpec("enricher", prompt_name="enricher"),
    StageSpec("scriptwrite", approval_marker=".plan_approved", prompt_name="scriptwriter"),
    StageSpec("series-polish", series_wide=True, prompt_name="series_polish"),
    StageSpec("script-review", prompt_name="script_review"),
    StageSpec("tts-prep", approval_marker=".script_approved", prompt_name="tts_prep"),
    StageSpec("synthesize"),
    StageSpec("audio-qa"),
    StageSpec("subtitle"),
    StageSpec("cover", series_wide=True, prompt_name="cover"),
    StageSpec("publish", series_wide=True),
)

STAGE_SPECS: tuple[StageSpec, ...] = _STAGE_DEFINITIONS
STAGE_SPEC_BY_NAME: Mapping[str, StageSpec] = {spec.name: spec for spec in STAGE_SPECS}


def stage_specs_from_order(order: Sequence[str]) -> tuple[StageSpec, ...]:
    """Resolve a workflow's ordered stage names to the canonical metadata."""

    names = tuple(order)
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("workflow stage_order must be a non-empty list of names")
    if len(set(names)) != len(names):
        raise ValueError("workflow stage_order contains duplicate stage names")
    unknown = [name for name in names if name not in STAGE_SPEC_BY_NAME]
    if unknown:
        raise ValueError(f"workflow references unknown stage(s): {', '.join(unknown)}")
    return tuple(STAGE_SPEC_BY_NAME[name] for name in names)


def stage_specs_from_workflow(workflow: Mapping[str, object]) -> tuple[StageSpec, ...]:
    """Build the canonical ordered registry from a loaded workflow JSON object."""

    order = workflow.get("stage_order")
    if not isinstance(order, list):
        raise ValueError("workflow stage_order must be a list")
    return stage_specs_from_order(order)


def stage_names(specs: Sequence[StageSpec]) -> tuple[str, ...]:
    return tuple(spec.name for spec in specs)


def stage_spec(name: str) -> StageSpec:
    try:
        return STAGE_SPEC_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown stage {name!r}") from exc


@dataclass(frozen=True)
class PipelineConfig:
    """Pure inputs that affect stage selection.

    The default stage registry is immutable; a workflow version can replace it
    with ``stage_specs_from_workflow`` before planning.
    """

    stages: tuple[StageSpec, ...] = field(default_factory=lambda: STAGE_SPECS)
    skip_to: str | None = None
    stop_after: str | None = None
    only_stage: str | None = None
    only_episode: int | None = None
    ignore_gates: bool = False

    @classmethod
    def from_names(cls, names: Sequence[str], **kwargs: object) -> "PipelineConfig":
        return cls(stages=stage_specs_from_order(names), **kwargs)


@dataclass(frozen=True)
class RunPlan:
    """Deterministic stage selection returned by :func:`resolve_run_plan`."""

    all_stages: tuple[StageSpec, ...]
    stages: tuple[StageSpec, ...]
    start_index: int
    stop_index: int
    explicit_skip_index: int | None
    skipped_series_wide: tuple[str, ...] = ()

    @property
    def stage_names(self) -> tuple[str, ...]:
        return stage_names(self.stages)

    @property
    def all_stage_names(self) -> tuple[str, ...]:
        return stage_names(self.all_stages)


def resolve_run_plan(config: PipelineConfig, *, resume_index: int = 0) -> RunPlan:
    """Resolve CLI range, auto-resume, and episode semantics without I/O."""

    specs = tuple(config.stages)
    if not specs:
        raise ValueError("pipeline has no stages")
    names = stage_names(specs)
    if len(set(names)) != len(names):
        raise ValueError("pipeline stage registry contains duplicate names")

    if config.only_stage and (config.skip_to or config.stop_after):
        raise ValueError("only_stage cannot be combined with skip_to or stop_after")

    start_name = config.only_stage or config.skip_to
    stop_name = config.only_stage or config.stop_after
    try:
        start_idx = names.index(start_name) if start_name else 0
    except ValueError as exc:
        raise ValueError(f"stage {start_name!r} is not in workflow stage_order") from exc
    try:
        stop_idx = names.index(stop_name) if stop_name else len(specs) - 1
    except ValueError as exc:
        raise ValueError(f"stage {stop_name!r} is not in workflow stage_order") from exc

    explicit_skip_idx = names.index(start_name) if start_name else None
    if start_idx > stop_idx:
        raise ValueError(f"skip_to {start_name!r} is after stop_after {stop_name!r}")
    if not start_name:
        if resume_index < 0 or resume_index > len(specs):
            raise ValueError(f"resume_index out of range: {resume_index}")
        start_idx = max(start_idx, resume_index)

    selected = list(specs[start_idx:stop_idx + 1])
    skipped: list[str] = []
    if config.only_episode is not None:
        for spec in selected:
            if spec.series_wide and config.only_stage != spec.name:
                skipped.append(spec.name)
        selected = [spec for spec in selected if spec.name not in skipped]

    return RunPlan(
        all_stages=specs,
        stages=tuple(selected),
        start_index=start_idx,
        stop_index=stop_idx,
        explicit_skip_index=explicit_skip_idx,
        skipped_series_wide=tuple(skipped),
    )


def render_stage_help(specs: Sequence[StageSpec]) -> str:
    """Render the numbered stage list used by CLI help/status output."""

    return "\n".join(f"    {idx}. {spec.name}" for idx, spec in enumerate(specs, 1))


@dataclass(frozen=True)
class WorkspaceState:
    """Filesystem state owned by a podcast pipeline workspace.

    The runner used to construct marker, manifest, and provenance paths at
    each call site.  Keeping those paths and the resume-drift comparison here
    gives the CLI and tests one state boundary without moving the stage
    implementation into the planner.  Missing provenance is deliberately
    treated as a legacy workspace: its marker remains authoritative until the
    stage is run again and writes a fresh record.
    """

    workspace: Path

    def marker_path(self, stage: str) -> Path:
        return self.workspace / _STAGE_MARKER.format(name=stage)

    def stage_done(self, stage: str) -> bool:
        return self.marker_path(stage).is_file()

    def approval_marker_path(self, marker: str) -> Path:
        """Return a human approval marker (for example ``.plan_approved``)."""

        return self.workspace / marker

    def mark_stage_done(self, stage: str, *, timestamp: str | None = None) -> Path:
        self.workspace.mkdir(parents=True, exist_ok=True)
        path = self.marker_path(stage)
        self._write_text_atomic(path, timestamp or datetime.now().isoformat(timespec="seconds"))
        return path

    def manifest_path(self) -> Path:
        return self.workspace / _WORKFLOW_MANIFEST

    def read_manifest(self) -> dict[str, Any] | None:
        path = self.manifest_path()
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return value

    def write_manifest(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(payload)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._write_json(self.manifest_path(), value)
        return value

    def provenance_path(self, stage: str, only_episode: int | None = None) -> Path:
        suffix = f"_ep_{only_episode}" if only_episode is not None else ""
        return self.workspace / _STAGE_PROVENANCE_DIR / f"{stage}{suffix}.json"

    def has_provenance(self, stage: str, only_episode: int | None = None) -> bool:
        return self.provenance_path(stage, only_episode).is_file()

    def read_provenance(
        self, stage: str, only_episode: int | None = None
    ) -> dict[str, Any] | None:
        path = self.provenance_path(stage, only_episode)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return value

    def write_provenance(
        self,
        stage: str,
        payload: Mapping[str, Any],
        only_episode: int | None = None,
    ) -> dict[str, Any]:
        value = dict(payload)
        self.provenance_path(stage, only_episode).parent.mkdir(parents=True, exist_ok=True)
        self._write_json(self.provenance_path(stage, only_episode), value)
        return value

    def provenance_is_stale(
        self,
        stage: str,
        *,
        current_inputs: Mapping[str, Any],
        current_prompt: Mapping[str, Any] | None,
        only_episode: int | None = None,
    ) -> bool:
        """Return whether a completed stage no longer matches its inputs.

        Artifact mtimes are intentionally ignored: rsync, checkout, and
        restore operations can rewrite mtimes without changing content.  A
        missing provenance record is a legacy workspace and therefore does not
        invalidate its existing marker; malformed JSON fails closed via
        :meth:`read_provenance`.
        """

        provenance = self.read_provenance(stage, only_episode)
        if provenance is None:
            return False
        if provenance.get("stage") not in (None, stage):
            return True
        if not provenance.get("success", False):
            return True
        recorded_inputs = provenance.get("input_artifacts", {})
        recorded_prompt = provenance.get("prompt")
        return (
            self._stable_identity(recorded_inputs)
            != self._stable_identity(current_inputs)
            or self._stable_identity(recorded_prompt)
            != self._stable_identity(current_prompt)
        )

    @classmethod
    def _stable_identity(cls, value: Any) -> Any:
        """Normalize JSON-like state for semantic, not timestamp, comparison."""

        if isinstance(value, Mapping):
            return {
                key: cls._stable_identity(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if key != "mtime"
            }
        if isinstance(value, (list, tuple)):
            return [cls._stable_identity(item) for item in value]
        return value

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        WorkspaceState._write_text_atomic(
            path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content)
        temporary.replace(path)

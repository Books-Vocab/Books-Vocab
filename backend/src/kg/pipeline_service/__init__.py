"""Pipeline service: enrich -> embed+judge -> difficulty background pipeline.

Refactored from a single ~634-line module into a package. This ``__init__``
re-exports every public *and* internal name the old module exposed so existing
callers and tests (which import internals like ``_run_step``,
``_step_embed_and_judge``, and monkeypatch ``_PIPELINE_RUNNING``) keep working
without changes.

Submodules:
- ``runstate``  - per-uid in-flight refcount + ``is_pipeline_running``
- ``steps``     - individual pipeline step handlers
- ``runner``    - ``_run_step`` wrapper + ``run_pipeline_background`` orchestrator
"""

from __future__ import annotations

from .runner import _STEP_ERRORS, _run_step, run_pipeline_background
from .runstate import _PIPELINE_RUNNING, _PIPELINE_RUNNING_LOCK, is_pipeline_running
from .steps import (
    _step_difficulty,
    _step_embed_and_judge,
    _step_enrich,
    _sync_embed_loop,
    _touch_linked_cards,
)

__all__ = [
    "_PIPELINE_RUNNING",
    "_PIPELINE_RUNNING_LOCK",
    "_STEP_ERRORS",
    "_run_step",
    "_step_difficulty",
    "_step_embed_and_judge",
    "_step_enrich",
    "_sync_embed_loop",
    "_touch_linked_cards",
    "is_pipeline_running",
    "run_pipeline_background",
]

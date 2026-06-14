from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks


def queue_pipeline_response(
    background_tasks: BackgroundTasks,
    user: dict[str, Any],
    *,
    run_pipeline_background_fn: Callable[[dict[str, object]], None],
) -> dict[str, str]:
    background_tasks.add_task(run_pipeline_background_fn, user)
    return {"status": "queued", "message": "Pipeline started in the background"}

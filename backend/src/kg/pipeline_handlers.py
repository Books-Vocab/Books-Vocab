from __future__ import annotations

from typing import Any, Callable

from fastapi import BackgroundTasks


def queue_pipeline_response(
    background_tasks: BackgroundTasks,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    run_pipeline_background_fn: Callable[[dict[str, Any]], Any],
) -> dict[str, str]:
    require_pro_access(user, "knowledge_sync")
    background_tasks.add_task(run_pipeline_background_fn, user)
    return {"status": "queued", "message": "Pipeline started in the background"}

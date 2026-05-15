from __future__ import annotations

import threading

# Per-uid refcount of in-flight + queued pipeline runs. Refcount (not bool)
# to defeat the race where the in-flight run's `finally` clears the flag
# AFTER the queued run has set it (the bool-flag impl observed: in-flight
# pop happens after lock release, queued set happens before lock acquire,
# so pop can clobber set). With refcount, both increments are visible and
# the flag only drops when every queued/running task has decremented.
_PIPELINE_RUNNING: dict[str, int] = {}
_PIPELINE_RUNNING_LOCK = threading.Lock()


def is_pipeline_running(user_id: str) -> bool:
    with _PIPELINE_RUNNING_LOCK:
        return _PIPELINE_RUNNING.get(user_id, 0) > 0

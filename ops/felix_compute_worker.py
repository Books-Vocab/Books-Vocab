"""Host-owned worker boundary; candidate requests cannot choose private paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class WorkerError(ValueError):
    """Worker request crossed a controller-owned boundary."""


class FelixComputeWorker:
    def __init__(self, *, controller_root: Path):
        self.controller_root = controller_root.resolve()

    def submit(self, request: dict[str, Any]) -> None:
        if not isinstance(request, dict):
            raise WorkerError("request-schema")
        if "receipt_key_path" in request or "source_root" not in request:
            raise WorkerError("controller-owned-path")
        source = Path(str(request["source_root"])).resolve()
        if self.controller_root not in source.parents and source != self.controller_root:
            raise WorkerError("source-root")
        raise WorkerError("controller-not-installed")


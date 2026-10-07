"""Eval configuration dataclass."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class EvalConfig:
    """Configuration for a single eval run."""

    prompt_name: str
    prompt_version: str | None = None
    dataset_name: str = ""
    models: tuple[str, ...] = ()
    limit: int | None = None
    sample_ids: tuple[str, ...] = ()
    concurrency: int = 5
    cloud_timeout_s: float = 60.0
    ollama_timeout_s: float = 300.0
    temperature: float = 0.3
    extra_scoring_kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        # concurrency < 1 → Semaphore(<1): every call waits forever.
        if self.concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {self.concurrency}")
        # limit 0 would be falsy-looking "no limit"; None is the only "all".
        if self.limit is not None and self.limit < 1:
            raise ValueError(f"limit must be >= 1 or None, got {self.limit}")

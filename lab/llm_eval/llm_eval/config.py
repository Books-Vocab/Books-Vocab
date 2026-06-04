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

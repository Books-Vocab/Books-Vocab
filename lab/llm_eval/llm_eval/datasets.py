"""Dataset loader for eval samples."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("llm_eval")

_DATASET_DIR = Path(__file__).parent.parent / "datasets"


def load_dataset(name: str) -> list[dict[str, Any]]:
    """Load a dataset by name from datasets/ (JSONL)."""
    path = _DATASET_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    samples = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSONL line in %s: %s", path, exc)
    return samples


def list_datasets() -> list[str]:
    """List available dataset names."""
    if not _DATASET_DIR.exists():
        return []
    return [
        p.stem
        for p in _DATASET_DIR.iterdir()
        if p.suffix == ".jsonl"
    ]

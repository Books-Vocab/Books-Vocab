"""Dataset loader for eval samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATASET_DIR = Path(__file__).parent.parent / "datasets"


def load_dataset(name: str) -> list[dict[str, Any]]:
    """Load a dataset by name from datasets/ (JSONL).

    Raises ValueError (with file:line) on malformed or non-object rows, and on
    names that could escape the datasets directory.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Invalid dataset name: {name!r}")
    path = _DATASET_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    samples = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{lineno}: malformed JSONL line: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(
                    f"{path}:{lineno}: expected a JSON object, got {type(row).__name__}"
                )
            samples.append(row)
    return samples


def list_datasets() -> list[str]:
    """List available dataset names."""
    if not _DATASET_DIR.exists():
        return []
    return [p.stem for p in _DATASET_DIR.iterdir() if p.suffix == ".jsonl"]

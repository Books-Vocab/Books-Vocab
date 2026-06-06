#!/usr/bin/env python
"""Sample private candidates into a pending human gold review queue."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "src"))

from llm_eval.gold_queue_cli import main


if __name__ == "__main__":
    raise SystemExit(main())

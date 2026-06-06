"""CLI helpers for human gold review queue generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_eval.gold_queue import SUPPORTED_PROMPTS, build_gold_review_queue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sample private candidates into a pending human gold review JSONL.",
    )
    parser.add_argument("--prompt", choices=sorted(SUPPORTED_PROMPTS), required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=_positive_int, default=50)
    parser.add_argument("--seed", type=int, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    rows = build_gold_review_queue(
        args.candidates,
        args.output,
        prompt_name=args.prompt,
        limit=args.limit,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "prompt_name": args.prompt,
                "output": str(args.output),
                "rows": len(rows),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed

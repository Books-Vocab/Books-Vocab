"""CLI helpers for private corpus construction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_eval.corpus import OUTPUT_FILES, build_private_corpus
from llm_eval.paths import (
    PRIVATE_CORPUS_DIR,
    add_allow_unignored_flag,
    refuse_committable_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build ignored private candidate corpora from a local user dump.",
    )
    parser.add_argument("dump_path", type=Path, help="Path to a local JSON user dump.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PRIVATE_CORPUS_DIR,
        help=f"Directory for private JSONL outputs (default: {PRIVATE_CORPUS_DIR}).",
    )
    add_allow_unignored_flag(parser)
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=None,
        help="Optional max source cards.",
    )
    parser.add_argument(
        "--context-chars",
        type=_positive_int,
        default=320,
        help="Maximum context characters kept per candidate.",
    )
    try:
        args = parser.parse_args(argv)
        refuse_committable_outputs(
            parser,
            [args.output_dir / name for name in OUTPUT_FILES.values()],
            allow=args.allow_unignored,
        )
    except SystemExit as exc:
        return int(exc.code)

    outputs = build_private_corpus(
        args.dump_path,
        args.output_dir,
        limit=args.limit,
        context_chars=args.context_chars,
    )
    summary = {
        "output_dir": str(args.output_dir),
        "files": {
            name: {
                "path": str(path),
                "rows": _count_jsonl_rows(path),
            }
            for name, path in outputs.items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed

"""CLI helpers for private corpus construction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_eval.corpus import build_private_corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build ignored private candidate corpora from a local user dump.",
    )
    parser.add_argument("dump_path", type=Path, help="Path to a local JSON user dump.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("private_corpus"),
        help="Directory for ignored private JSONL outputs.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max source cards.")
    parser.add_argument(
        "--context-chars",
        type=int,
        default=320,
        help="Maximum context characters kept per candidate.",
    )
    args = parser.parse_args(argv)

    outputs = build_private_corpus(
        args.dump_path,
        args.output_dir,
        limit=args.limit,
        context_chars=args.context_chars,
    )
    summary = {
        "dump_path": str(args.dump_path),
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
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

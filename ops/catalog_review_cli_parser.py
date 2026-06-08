from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Navigate the catalog UI atlas tree.")
    parser.add_argument("root", type=Path, help="Directory containing review_manifest.json (the blessed artifact root)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tree_cmd = subparsers.add_parser("tree")
    tree_cmd.add_argument("--node", default="")
    tree_cmd.add_argument("--depth", type=int, default=None)

    node_cmd = subparsers.add_parser("node")
    node_cmd.add_argument("node_path")

    url_cmd = subparsers.add_parser("node-url")
    url_cmd.add_argument("node_path")
    url_cmd.add_argument("--base", default=None)

    return parser


def dispatch_command(
    args: argparse.Namespace,
    root: Path,
    *,
    handlers: dict[str, Callable],
    parser: argparse.ArgumentParser,
) -> int:
    command = args.command
    dispatchers: dict[str, Callable[[], int]] = {
        "tree": lambda: handlers["tree"](root, node=args.node, depth=args.depth),
        "node": lambda: handlers["node"](root, args.node_path),
        "node-url": lambda: handlers["node_url"](root, args.node_path, base=args.base),
    }
    if command in dispatchers:
        return dispatchers[command]()
    parser.error(f"unknown command: {command}")
    return 2

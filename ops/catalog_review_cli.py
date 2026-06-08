#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

from catalog_review_cli_navigator import cmd_node, cmd_node_url, cmd_tree
from catalog_review_cli_parser import build_parser, dispatch_command


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    return dispatch_command(args, root, handlers={
        "tree": cmd_tree,
        "node": cmd_node,
        "node_url": cmd_node_url,
    }, parser=parser)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env -S uv run --python 3.13 python
from __future__ import annotations

from catalog_review_cli_maintenance import cmd_doctor, cmd_doctor_shortcut, cmd_repair, cmd_verify
from catalog_review_cli_mutations import cmd_apply, cmd_mark
from catalog_review_cli_parser import build_parser, dispatch_command
from catalog_review_cli_queries import cmd_gaps, cmd_list, cmd_report, cmd_show, cmd_stats, cmd_summary
from pathlib import Path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    return dispatch_command(args, root, handlers={
        "summary": cmd_summary,
        "show": cmd_show,
        "mark": cmd_mark,
        "list": cmd_list,
        "apply": cmd_apply,
        "stats": cmd_stats,
        "report": cmd_report,
        "gaps": cmd_gaps,
        "verify": cmd_verify,
        "repair": cmd_repair,
        "doctor": cmd_doctor,
        "shortcut": cmd_doctor_shortcut,
    }, parser=parser)


if __name__ == "__main__":
    raise SystemExit(main())

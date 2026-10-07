#!/usr/bin/env -S uv run --python 3.13 python
"""Keep exactly one GitHub issue in sync with the latest `doctor.py --ci --json` report.

    ./ops/doctor.py --ci --json > report.json; ./ops/doctor_issue.py report.json

* any warn/block finding and no open report issue -> create it
* findings changed since the last run             -> update the issue body
* findings unchanged                              -> do nothing (no weekly noise)
* every finding ok and an open report issue       -> close it with a comment

The issue carries the ``health-report`` label, which ``doctor.py`` excludes from
its own issue accounting.  Only this tool writes to it; it never touches any other
issue.  ``--dry-run`` prints the decision without calling GitHub.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

LABEL = "health-report"
TITLE = "Project health: attention needed"
GENERATED = "Generated: "


def render_body(report: dict[str, Any]) -> str:
    lines = [f"{GENERATED}{report.get('generated_at', 'unknown')}", ""]
    lines.append(
        "Findings from `./ops/doctor.py --ci` that are not ok. "
        "This issue updates itself and closes when everything is ok again."
    )
    for finding in report["findings"]:
        if finding["level"] == "ok":
            continue
        lines.append("")
        lines.append(
            f"- **{finding['level'].upper()} {finding['section']}**: {finding['summary']}"
        )
        lines.extend(f"  - {detail}" for detail in finding.get("detail", []))
    return "\n".join(lines) + "\n"


def _stable(body: str | None) -> str:
    """The body without its timestamp line, so an unchanged report compares equal."""
    return "\n".join(
        line for line in (body or "").splitlines() if not line.startswith(GENERATED)
    ).strip()


def plan(report: dict[str, Any], open_issue: dict[str, Any] | None) -> dict[str, Any]:
    worst = report.get("worst", "ok")
    if worst == "ok":
        if open_issue is None:
            return {"action": "noop", "reason": "all ok and no open report"}
        return {
            "action": "close",
            "number": open_issue["number"],
            "comment": f"All findings are ok as of {report.get('generated_at', 'now')}.",
        }
    body = render_body(report)
    if open_issue is None:
        return {"action": "create", "title": TITLE, "body": body}
    if _stable(open_issue.get("body")) == _stable(body):
        return {
            "action": "noop",
            "reason": "findings unchanged",
            "number": open_issue["number"],
        }
    return {"action": "update", "number": open_issue["number"], "body": body}


def gh(*argv: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["gh", *argv], input=stdin, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise SystemExit(
            f"doctor_issue: gh {' '.join(argv[:3])} failed: {done.stderr.strip()[-300:]}"
        )
    return done.stdout


def find_open_issue(repo: str | None) -> dict[str, Any] | None:
    scope = ["--repo", repo] if repo else []
    out = gh(
        "issue",
        "list",
        *scope,
        "--label",
        LABEL,
        "--state",
        "open",
        "--json",
        "number,body",
        "--limit",
        "5",
    )
    issues = json.loads(out or "[]")
    return issues[0] if issues else None


def apply(decision: dict[str, Any], repo: str | None) -> None:
    scope = ["--repo", repo] if repo else []
    match decision["action"]:
        case "create":
            gh(
                "label",
                "create",
                LABEL,
                *scope,
                "--color",
                "fbca04",
                "--description",
                "weekly doctor report",
                "--force",
            )
            gh(
                "issue",
                "create",
                *scope,
                "--title",
                decision["title"],
                "--label",
                LABEL,
                "--body-file",
                "-",
                stdin=decision["body"],
            )
        case "update":
            gh(
                "issue",
                "edit",
                str(decision["number"]),
                *scope,
                "--body-file",
                "-",
                stdin=decision["body"],
            )
        case "close":
            gh(
                "issue",
                "close",
                str(decision["number"]),
                *scope,
                "--comment",
                decision["comment"],
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("report", help="path to `doctor.py --ci --json` output")
    parser.add_argument("--repo", help="owner/name; default is the current repository")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)
    decision = plan(report, find_open_issue(args.repo))
    print(json.dumps(decision, ensure_ascii=False))
    if not args.dry_run:
        apply(decision, args.repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())

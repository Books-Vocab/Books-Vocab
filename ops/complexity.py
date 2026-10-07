#!/usr/bin/env -S uv run --python 3.13 python
"""Complexity budget: the delivery tooling may not quietly outgrow the product.

Tracked-line ceilings for the areas that only ever grow by accretion (`ops/`,
`docs/`, `.github/workflows/`) live in ``ops/complexity_budget.json``.

    ./ops/complexity.py check      # exit 1 when an area is over its ceiling
    ./ops/complexity.py ratchet    # lower ceilings to current + slack; never raises
    ./ops/complexity.py show       # numbers, headroom, and ops : ios ratio

Going over means one of two visible acts in the PR: delete something, or edit the
ceiling in the budget file so a reviewer sees the number and the reason.  The
ceiling is therefore a decision, not a side effect.  ``ratchet`` only moves it
down, so deletions are banked and cannot be spent again silently.

Exit code: 0 within budget, 1 over budget, 2 usage or unreadable budget.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "kg.complexity-budget.v1"
BUDGET_FILE = "ops/complexity_budget.json"
AREAS = {
    "ops": "ops/",
    "docs": "docs/",
    "workflows": ".github/workflows/",
}
# The product the tooling serves; reported as a ratio, never budgeted.
REFERENCE_AREA = "ios/"


class BudgetError(Exception):
    pass


def count_lines(repo: Path, prefix: str) -> int:
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", prefix],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    total = 0
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        path = repo / raw.decode()
        if path.is_file() and not path.is_symlink():
            total += path.read_bytes().count(b"\n")
    return total


def measure(repo: Path) -> dict[str, int]:
    measured = {name: count_lines(repo, prefix) for name, prefix in AREAS.items()}
    measured["reference"] = count_lines(repo, REFERENCE_AREA)
    return measured


def load_budget(path: Path) -> dict[str, Any]:
    try:
        budget = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BudgetError(f"cannot read {path}: {exc}") from exc
    if budget.get("schema") != SCHEMA:
        raise BudgetError(f"{path}: schema must be {SCHEMA!r}")
    for key in ("ceilings", "slack"):
        missing = sorted(set(AREAS) - set(budget.get(key, {})))
        if missing:
            raise BudgetError(f"{path}: {key} missing {missing}")
    return budget


def evaluate(measured: dict[str, int], budget: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in AREAS:
        ceiling = int(budget["ceilings"][name])
        now = measured[name]
        rows.append(
            {
                "area": name,
                "lines": now,
                "ceiling": ceiling,
                "headroom": ceiling - now,
                "over": now > ceiling,
            }
        )
    return rows


def ratcheted(measured: dict[str, int], budget: dict[str, Any]) -> dict[str, int]:
    """New ceilings: the lower of the current one and (measured + slack)."""
    return {
        name: min(
            int(budget["ceilings"][name]), measured[name] + int(budget["slack"][name])
        )
        for name in AREAS
    }


def ratio(measured: dict[str, int]) -> float | None:
    return (
        round(measured["ops"] / measured["reference"], 2)
        if measured["reference"]
        else None
    )


def render(rows: list[dict[str, Any]], measured: dict[str, int]) -> str:
    lines = []
    for row in rows:
        mark = "OVER" if row["over"] else "ok  "
        lines.append(
            f"[{mark}] {row['area']:9} {row['lines']:>8,} lines / ceiling {row['ceiling']:>8,}"
            f"  (headroom {row['headroom']:+,})"
        )
    value = ratio(measured)
    if value is not None:
        lines.append(
            f"        ops : ios = {value}  (tooling lines per product line; lower is healthier)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None, repo: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["check", "ratchet", "show"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = repo or Path(__file__).resolve().parents[1]
    try:
        budget_path = root / BUDGET_FILE
        budget = load_budget(budget_path)
        measured = measure(root)
    except (BudgetError, subprocess.CalledProcessError) as exc:
        print(f"complexity: {exc}", file=sys.stderr)
        return 2
    rows = evaluate(measured, budget)

    if args.command == "ratchet":
        new = ratcheted(measured, budget)
        lowered = {
            k: (budget["ceilings"][k], v)
            for k, v in new.items()
            if v < budget["ceilings"][k]
        }
        if lowered:
            budget["ceilings"] = new
            budget_path.write_text(
                json.dumps(budget, indent=2) + "\n", encoding="utf-8"
            )
        for area, (old, now) in lowered.items():
            print(f"ratchet: {area} ceiling {old:,} -> {now:,}")
        print(
            "ratchet: nothing to lower"
            if not lowered
            else "ratchet: wrote " + BUDGET_FILE
        )
        return 0

    if args.json:
        print(
            json.dumps(
                {"schema": SCHEMA, "areas": rows, "ops_to_ios": ratio(measured)},
                indent=2,
            )
        )
    else:
        print(render(rows, measured))
    over = [r["area"] for r in rows if r["over"]]
    if args.command == "check" and over:
        print(
            f"complexity: over budget: {', '.join(over)}. Delete something, or raise the ceiling in "
            f"{BUDGET_FILE} in this PR and say why.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env -S uv run --python 3.13 python
"""Complexity budget: the delivery tooling may not quietly outgrow the product.

Line ceilings (authored code and docs only, never data files) for the areas that only ever grow by accretion (`ops/`,
`docs/`, `.github/workflows/`) live in ``ops/complexity_budget.json``.

    ./ops/complexity.py check      # exit 1 when an area is over its ceiling
    ./ops/complexity.py ratchet    # lower ceilings to current + slack; never raises
    ./ops/complexity.py show       # numbers, headroom, and ops : ios ratio

Going over means one of two visible acts in the PR: delete something, or edit the
ceiling in the budget file so a reviewer sees the number and the reason.  The
ceiling is therefore a decision, not a side effect.  ``ratchet`` only moves it
down, so deletions are banked and cannot be spent again silently.

A lane gate judges the change, not the trunk: an area over its ceiling only fails ``check`` when
this change added more than the headroom the area had at the merge-base (``origin/main``, else
``main``), i.e. a base that is already red tolerates only a change that adds nothing; otherwise it
is reported as ``inherited``.  A lane that rebases onto a sibling's red base must delete or raise
the ceiling in its own PR.  The absolute judgement belongs to ``--strict``
(CI runs it on push to ``main``, see ``ci_args``), so a red trunk is still caught;
``--base REF`` overrides the base.  With no usable base the absolute judgement applies, loudly.

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
# Only authored text counts.  Fixtures, plists and recordings are data: regenerating
# one is not a change in complexity and must not be able to turn the gate red.
COUNTED_SUFFIXES = (".py", ".sh", ".md", ".yml", ".yaml", ".swift")


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
        if path.suffix in COUNTED_SUFFIXES and path.is_file() and not path.is_symlink():
            total += path.read_bytes().count(b"\n")
    return total


def ci_args(env: dict[str, str] | None = None) -> list[str]:
    """Extra ``check`` flags for the CI entry: absolute on push to main, delta-aware on PRs."""
    import os

    event = (os.environ if env is None else env).get("GITHUB_EVENT_NAME")
    return ["--strict"] if event == "push" else []


def merge_base(repo: Path, base: str | None) -> str | None:
    """Commit to diff against, or None when there is no usable base (absolute mode)."""
    for ref in [base] if base else ["origin/main", "main"]:
        found = subprocess.run(
            ["git", "merge-base", "HEAD", ref],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    return None


def line_deltas(repo: Path, base: str) -> dict[str, int]:
    """Counted lines added minus removed per area, working tree versus ``base``."""
    out = subprocess.run(
        ["git", "diff", "--numstat", "--no-renames", "-z", base, "--"],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    deltas = dict.fromkeys(AREAS, 0)
    for entry in out.split(b"\0"):
        if not entry:
            continue
        added, _, rest = entry.decode().partition("\t")
        removed, _, name = rest.partition("\t")
        if not added.isdigit() or not removed.isdigit():  # binary
            continue
        if not name.endswith(COUNTED_SUFFIXES):
            continue
        for area, prefix in AREAS.items():
            if name.startswith(prefix):
                deltas[area] += int(added) - int(removed)
    return deltas


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


def evaluate(
    measured: dict[str, int],
    budget: dict[str, Any],
    deltas: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """``deltas`` (lines this change added per area) judges the change against the headroom the
    area had at the merge-base: an area over its ceiling only fails when the change added more
    than that headroom (so an already-red base tolerates only delta <= 0).  ``slack`` is the
    ratchet's reset margin and plays no part here.  Without ``deltas`` the judgement is absolute."""
    rows = []
    for name in AREAS:
        ceiling = int(budget["ceilings"][name])
        now = measured[name]
        beyond = now > ceiling
        if deltas is None:
            grew = True
        else:
            delta = deltas.get(name, 0)
            grew = delta > max(0, ceiling - (now - delta))
        rows.append(
            {
                "area": name,
                "lines": now,
                "ceiling": ceiling,
                "headroom": ceiling - now,
                "over": beyond and grew,
                "inherited": beyond and not grew,
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
        mark = "OVER" if row["over"] else "base" if row["inherited"] else "ok  "
        note = (
            "  inherited: over at base, this change adds nothing"
            if row["inherited"]
            else ""
        )
        lines.append(
            f"[{mark}] {row['area']:9} {row['lines']:>8,} lines / ceiling {row['ceiling']:>8,}"
            f"  (headroom {row['headroom']:+,}){note}"
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
    parser.add_argument(
        "--base",
        help="ref to diff against (default: merge-base with origin/main, else main)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="judge absolute counts; ignore the base delta",
    )
    args = parser.parse_args(argv)
    root = repo or Path(__file__).resolve().parents[1]
    try:
        budget_path = root / BUDGET_FILE
        budget = load_budget(budget_path)
        measured = measure(root)
    except (BudgetError, subprocess.CalledProcessError) as exc:
        print(f"complexity: {exc}", file=sys.stderr)
        return 2
    deltas = None
    if not args.strict:
        base = merge_base(root, args.base)
        if base:
            try:
                deltas = line_deltas(root, base)
            except subprocess.CalledProcessError as exc:
                print(
                    f"complexity: diff failed ({exc}); judging absolute",
                    file=sys.stderr,
                )
        else:
            print(
                "complexity: no merge-base (origin/main or main); judging absolute",
                file=sys.stderr,
            )
    rows = evaluate(measured, budget, deltas)

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

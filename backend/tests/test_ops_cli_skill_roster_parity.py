"""Contract guard: the devops skill's ops-cli roster must list every subcommand.

`.claude/skills/devops/SKILL.md` is the *enumerated* agent-facing roster — the one
surface an agent actually loads when it triggers the `devops` skill for
「部署 / 用戶查詢 / 額度 / 遠端 / 維護」. A subcommand that exists in `ops_cli.py`
but is missing from that list is effectively invisible: the agent greps the skill,
sees no such command, concludes none exists, and falls back to hand-rolling
`db-query` SQL — exactly what `docs/reference/tech_index.md` forbids for the
dictionary runbook.

CLAUDE.md「Scope 規則」already requires `.claude/skills/` to be synced in the same
PR as a user/agent-facing CLI change. That rule was `[prompt]`-enforced only, and
it drifted. This test is the machine that enforces it.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from kg.ops_cli_parser import build_parser

ROOT = Path(__file__).resolve().parents[2]
DEVOPS_SKILL = ROOT / ".claude" / "skills" / "devops" / "SKILL.md"
ROSTER_HEADING = "### ops-cli 子指令"


def _registered_subcommands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("ops_cli parser exposes no subparsers — parity check is blind")


def _roster_block() -> str:
    """Return the fenced code block that follows the ops-cli roster heading."""
    lines = DEVOPS_SKILL.read_text(encoding="utf-8").splitlines()

    heads = [i for i, line in enumerate(lines) if line.strip() == ROSTER_HEADING]
    assert heads, f"{DEVOPS_SKILL} lost its `{ROSTER_HEADING}` heading"
    start = heads[0]

    fences = [i for i in range(start + 1, len(lines)) if lines[i].startswith("```")]
    assert len(fences) >= 2, f"`{ROSTER_HEADING}` is not followed by a closed code fence"
    return "\n".join(lines[fences[0] + 1 : fences[1]])


def _documented_subcommands() -> set[str]:
    return set(
        re.findall(
            r"^ops-cli\s+([a-z0-9][a-z0-9-]*)",
            _roster_block(),
            re.MULTILINE,
        )
    )


def test_every_ops_cli_subcommand_is_listed_in_the_devops_skill() -> None:
    missing = sorted(_registered_subcommands() - _documented_subcommands())

    assert not missing, (
        "these ops-cli subcommands exist but are absent from the enumerated roster in "
        f"{DEVOPS_SKILL.relative_to(ROOT)} — an agent loading the devops skill cannot "
        f"discover them and will hand-roll db-query SQL instead: {missing}"
    )


def test_devops_skill_roster_lists_no_phantom_subcommands() -> None:
    phantom = sorted(_documented_subcommands() - _registered_subcommands())

    assert not phantom, (
        f"{DEVOPS_SKILL.relative_to(ROOT)} documents ops-cli subcommands that no longer "
        f"exist; an agent will run them and get a parser error: {phantom}"
    )

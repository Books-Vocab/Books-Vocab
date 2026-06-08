"""Drift gate: judge prompt .md snapshots must match their source_of_truth.

The .md files under prompts/ are hand-copied snapshots of the production
prompts in backend/src/kg/judge/prompts.py. Their whole point is that the
eval workbench exercises the *real* production prompt — so a snapshot that
silently drifts from the constant it mirrors makes every eval result a lie.

This test re-derives the System block from each .md and asserts it is byte
-identical to the constant named in the file's ``source_of_truth`` meta.
Only the judge prompts (plain module-level string constants) are covered;
translate/enrich source_of_truth are functions that build prompts
dynamically and need a different harness.

If this fails after editing prompts.py: re-copy the System block into the
matching .md (and update manifest required_keys if the schema changed).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kg.judge.prompts import (
    BATCH_SYSTEM_PROMPT,
    MANUAL_LINK_SYSTEM_PROMPT,
    SELECTIVE_BATCH_SYSTEM_PROMPT,
)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _md_system_block(filename: str) -> str:
    txt = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
    assert "## System" in txt, f"{filename}: missing '## System' section"
    assert "## User" in txt, f"{filename}: missing '## User' section"
    m = re.search(r"## System\n(.*?)\n## User", txt, re.DOTALL)
    assert m, f"{filename}: '## System' must appear before '## User'"
    return m.group(1).strip()


def _jinja_to_format(s: str) -> str:
    """The selective prompt parameterizes via {n}/{max_links}; the .md renders
    them as jinja {{ n }}/{{ max_links }}. Normalize before comparing."""
    return s.replace("{{ n }}", "{n}").replace("{{ max_links }}", "{max_links}")


@pytest.mark.parametrize(
    "filename,constant,normalize",
    [
        ("judge_batch_v1.md", BATCH_SYSTEM_PROMPT, lambda s: s),
        ("judge_manual_v1.md", MANUAL_LINK_SYSTEM_PROMPT, lambda s: s),
        ("judge_selective_v1.md", SELECTIVE_BATCH_SYSTEM_PROMPT, _jinja_to_format),
    ],
)
def test_judge_md_system_matches_source_of_truth(filename, constant, normalize):
    md = normalize(_md_system_block(filename))
    assert md == constant.strip(), (
        f"{filename} System block drifted from its source_of_truth constant. "
        "Re-copy the production prompt into the .md."
    )

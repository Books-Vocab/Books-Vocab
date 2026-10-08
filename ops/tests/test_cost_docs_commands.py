"""Guard: cost docs only cite ops-cli commands/keys that really exist (#2327)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "docs/sop/cost_review.md", ROOT / "docs/reference/cost_baseline.md"]
PARSER = (ROOT / "backend/src/kg/ops_cli_parser.py").read_text(encoding="utf-8")
PARSER_COSTS = (ROOT / "backend/src/kg/ops_cli_costs.py").read_text(encoding="utf-8")
SOP = DOCS[0].read_text(encoding="utf-8")


def _lines(path: Path):
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), 1))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_cost_overview_is_per_user_not_by_service(doc):
    for n, line in _lines(doc):
        if "ops-cli cost-overview" in line:
            assert "by_service" not in line, f"{doc.name}:{n}"
            for key in re.findall(r"jq\s+'\.(\w+)", line):
                assert key in {"users", "count", "range", "since"}, (
                    f"{doc.name}:{n}: .{key}"
                )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_token_usage_sql_via_db_query(doc):
    text = doc.read_text(encoding="utf-8")
    assert not re.search(r"FROM\s+token_usage", text, re.IGNORECASE)


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_user_cost_summary_urls_quoted_with_user_id(doc):
    for n, line in _lines(doc):
        for m in re.finditer(r"""(["']?)https?://\S*user-cost-summary\S*""", line):
            url = m.group(0)
            assert url.startswith('"') and url.endswith('"'), f"{doc.name}:{n} unquoted"
            assert "user_id=" in url, f"{doc.name}:{n} missing user_id="


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_ops_cli_subcommands_and_flags_exist(doc):
    for n, line in _lines(doc):
        m = re.search(r"ops-cli\s+([a-z][a-z-]*)(.*)", line)
        if not m:
            continue
        sub, rest = m.groups()
        if sub == "timeseries":
            sub_m = re.match(r"\s+(cost|calls|active_users)\b", rest)
            assert sub_m, f"{doc.name}:{n} timeseries metric"
        assert f'add_parser("{sub}"' in PARSER, (
            f"{doc.name}:{n} unknown subcommand {sub}"
        )
        for flag in re.findall(r"(--[a-z][a-z-]*)", rest):
            assert flag in PARSER or flag == "--json", (
                f"{doc.name}:{n} unknown flag {flag}"
            )


def test_cited_json_keys_exist_in_cli_output():
    assert '"by_call_type"' in PARSER_COSTS and '"total_cost_usd"' in PARSER_COSTS
    assert '"users"' in PARSER_COSTS


def test_reconciliation_names_concrete_cost_overview_sum():
    section = SOP.split("對照 cost_baseline.md §4", 1)[1].split("---", 1)[0]
    assert "users[].total_cost_usd" in section

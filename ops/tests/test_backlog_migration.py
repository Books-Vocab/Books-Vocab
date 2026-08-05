"""Tests for the legacy-table importer and the generated view.

These two are only meaningful as a pair: the importer's acceptance condition is
that rendering what it imported reproduces the ledger, entry for entry. So the
central test here is a round trip, not a spot check on a few fields.

The importer must be RE-RUNNABLE and idempotent. That is not a nicety — the
source table is being edited by other sessions while this migration is in
flight (three concurrent writers were observed on the day it was written), so
the migration necessarily runs last, against a file that changed underneath it.
An importer that forked a second copy of every entry on the second run would be
unusable.

Silent loss is the failure mode that matters most: a row the parser does not
understand must be REPORTED, never dropped. A migration that quietly loses four
entries out of 59 looks exactly like a migration that worked.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("backlog", ROOT / "ops" / "backlog.py")
assert SPEC and SPEC.loader
BACKLOG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BACKLOG
SPEC.loader.exec_module(BACKLOG)

LEGACY_DOC = ROOT / "docs" / "runbook" / "improvement_backlog.md"


HEADER = (
    "| id | date | source | category | severity | status | detail | resolution |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _table(*rows: str) -> str:
    return "# Ledger\n\n## Ledger\n\n" + HEADER + "".join(r + "\n" for r in rows)


# ---------------------------------------------------------------------------
# 1. parsing the legacy row format
# ---------------------------------------------------------------------------

def test_parses_a_plain_row():
    text = _table("| IMP-0001 | 2026-06-13 | review gate | doc | low | fixed | it lied | `7c95a02` |")
    rows, problems = BACKLOG.parse_legacy_table(text)

    assert problems == []
    assert len(rows) == 1
    assert rows[0] == {
        "id": "IMP-0001",
        "date": "2026-06-13",
        "source": "review gate",
        "category": "doc",
        "severity": "low",
        "status": "fixed",
        "detail": "it lied",
        "resolution": "`7c95a02`",
    }


def test_escaped_pipes_inside_a_cell_survive():
    """IMP-0023 contains a literal `\\|\\| true` in its detail. Splitting on a
    naive `|` would tear that row into the wrong number of columns and either
    drop it or corrupt every field after it."""
    text = _table(
        r"| IMP-0023 | 2026-07-09 | backup | cli | med | open | wrap the flag in `\|\| true` | — |"
    )
    rows, problems = BACKLOG.parse_legacy_table(text)

    assert problems == []
    assert rows[0]["detail"] == "wrap the flag in `|| true`"


def test_em_dash_resolution_means_empty():
    text = _table("| IMP-0012 | 2026-07-08 | review | doc | low | open | a wall of text | — |")
    rows, _ = BACKLOG.parse_legacy_table(text)
    assert rows[0]["resolution"] == ""


def test_em_dash_prefix_with_content_is_not_empty():
    """`—(deploy 0611f3ca 解當下;monitoring 候選未做)` is a real resolution that
    merely starts with an em dash. Treating it as empty would silently discard
    the reason an entry is still open."""
    text = _table(
        "| IMP-0022 | 2026-07-09 | drift | tool | med | open | prod fell behind | —(deploy 0611f3ca 解當下) |"
    )
    rows, _ = BACKLOG.parse_legacy_table(text)
    assert rows[0]["resolution"] == "—(deploy 0611f3ca 解當下)"


def test_unescaped_pipe_is_recovered_with_whitespace_intact():
    """The real IMP-0017 shape: an unescaped `||` inside the detail, which
    splits the row into 10 columns.

    The whitespace assertion is the point. Cleaning each cell before rejoining
    would silently turn `|| true` into `||true` — text that survives the count
    check and looks fine, which is the worst kind of loss."""
    text = _table(
        "| IMP-0017 | 2026-07-08 | spec | tool | med | open | "
        "any pipeline not guarded by `|| true` can go silently green | — |"
    )
    rows, problems = BACKLOG.parse_legacy_table(text)

    assert len(rows) == 1
    assert rows[0]["detail"] == "any pipeline not guarded by `|| true` can go silently green"
    assert [p["kind"] for p in problems] == ["recovered-row"]
    assert problems[0]["id"] == "IMP-0017"


def test_recovery_refuses_when_the_anchor_columns_do_not_line_up():
    """Recovery is only licensed when the controlled-vocabulary columns confirm
    the shape. Otherwise report — guessing at the boundary would corrupt fields
    silently, which is the failure this whole module exists to prevent."""
    text = _table(
        "| IMP-0099 | 2026-07-08 | spec | NOT-A-CATEGORY | med | open | a | b | — |"
    )
    rows, problems = BACKLOG.parse_legacy_table(text)

    assert rows == []
    assert [p["kind"] for p in problems] == ["malformed-row"]


def test_recovered_row_round_trips_cleanly_afterwards(tmp_path):
    """Once recovered and stored, rendering must ESCAPE the pipes so the next
    parse needs no recovery at all — otherwise the damage is re-created on every
    render and the recovery warning never goes away."""
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(
        _table(
            "| IMP-0017 | 2026-07-08 | spec | tool | med | open | "
            "guard it with `|| true` | — |"
        ),
        store,
    )

    rendered = BACKLOG.render_view(store, verified_against="abc1234")
    rows, problems = BACKLOG.parse_legacy_table(rendered)

    assert problems == [], f"render re-introduced the damage: {problems}"
    assert rows[0]["detail"] == "guard it with `|| true`"


def test_malformed_row_is_reported_not_dropped():
    """The failure mode that must never be silent."""
    text = _table(
        "| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |",
        "| IMP-0002 | 2026-06-13 | too few columns |",
        "| IMP-0003 | 2026-06-13 | ok | doc | low | fixed | fine | — |",
    )
    rows, problems = BACKLOG.parse_legacy_table(text)

    assert len(rows) == 2
    assert len(problems) == 1
    assert problems[0]["kind"] == "malformed-row"
    assert problems[0]["id"] == "IMP-0002"


def test_non_table_prose_is_ignored():
    text = (
        "# Ledger\n\nsome prose with | a pipe | in it\n\n"
        + HEADER
        + "| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |\n"
    )
    rows, problems = BACKLOG.parse_legacy_table(text)
    assert [r["id"] for r in rows] == ["IMP-0001"]
    assert problems == []


# ---------------------------------------------------------------------------
# 2. import: idempotent, lossless, legacy ids preserved
# ---------------------------------------------------------------------------

def test_import_preserves_legacy_ids(tmp_path):
    store = tmp_path / "backlog"
    text = _table("| IMP-0052 | 2026-08-04 | probe | tool | high | fixed | flag went missing | `8aeb9e54b` |")

    result = BACKLOG.import_legacy(text, store)

    assert result["imported"] == 1
    assert (store / "IMP-0052.json").exists(), (
        "renumbering would break every in-prose cross-reference like 'see IMP-0052'"
    )


def test_import_is_byte_identical_on_rerun(tmp_path):
    store = tmp_path / "backlog"
    text = _table(
        "| IMP-0001 | 2026-06-13 | a | doc | low | fixed | first | — |",
        "| IMP-0002 | 2026-06-14 | b | cli | med | open | second | — |",
    )

    BACKLOG.import_legacy(text, store)
    first = {p.name: p.read_bytes() for p in sorted(store.glob("*.json"))}
    BACKLOG.import_legacy(text, store)
    second = {p.name: p.read_bytes() for p in sorted(store.glob("*.json"))}

    assert first == second


def test_rerun_picks_up_edits_made_between_runs(tmp_path):
    """The reason the importer is re-runnable at all: the source keeps changing
    while the migration is in flight, and the final run must absorb whatever
    landed in the meantime."""
    store = tmp_path / "backlog"
    before = _table("| IMP-0003 | 2026-06-13 | a | cli | low | triaged | five false positives | — |")
    after = _table("| IMP-0003 | 2026-06-13 | a | cli | low | triaged | SIX false positives, reverified | — |")

    BACKLOG.import_legacy(before, store)
    BACKLOG.import_legacy(after, store)

    entry = BACKLOG.load_entry(store, "IMP-0003")
    assert entry["detail"] == "SIX false positives, reverified"
    assert len(list(store.glob("*.json"))) == 1, "the rerun forked a second copy"


def test_import_reports_rows_it_could_not_take(tmp_path):
    store = tmp_path / "backlog"
    text = _table(
        "| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |",
        "| IMP-0002 | 2026-06-13 | broken |",
    )

    result = BACKLOG.import_legacy(text, store)

    assert result["imported"] == 1
    assert len(result["problems"]) == 1
    assert result["problems"][0]["id"] == "IMP-0002"


def test_import_does_not_delete_entries_absent_from_the_table(tmp_path):
    """An APP entry filed through the CLI must not be wiped by a later import
    of the IMP table."""
    store = tmp_path / "backlog"
    BACKLOG.add_entry(
        store,
        stream="APP",
        date="2026-08-05",
        source="dogfood",
        category="ux",
        severity="med",
        status="open",
        detail="reader loses scroll position on rotate",
    )
    BACKLOG.import_legacy(
        _table("| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |"), store
    )

    assert len(BACKLOG.list_entries(store, stream="APP")) == 1


# ---------------------------------------------------------------------------
# 3. round trip — the actual acceptance condition
# ---------------------------------------------------------------------------

def test_render_round_trips_every_field(tmp_path):
    store = tmp_path / "backlog"
    text = _table(
        "| IMP-0001 | 2026-06-13 | review gate | doc | low | fixed | it lied | `7c95a02` |",
        r"| IMP-0023 | 2026-07-09 | backup | cli | med | open | wrap it in `\|\| true` | — |",
        "| IMP-0052 | 2026-08-04 | probe | tool | high | wont-fix | flag went missing | reasoned away |",
    )
    BACKLOG.import_legacy(text, store)

    rendered = BACKLOG.render_view(store, verified_against="deadbeef")
    reparsed, problems = BACKLOG.parse_legacy_table(rendered)

    assert problems == []
    original, _ = BACKLOG.parse_legacy_table(text)
    assert {r["id"]: r for r in reparsed} == {r["id"]: r for r in original}


def test_render_is_deterministic(tmp_path):
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(
        _table(
            "| IMP-0002 | 2026-06-14 | b | cli | med | open | second | — |",
            "| IMP-0001 | 2026-06-13 | a | doc | low | fixed | first | — |",
        ),
        store,
    )
    assert BACKLOG.render_view(store, verified_against="x") == BACKLOG.render_view(
        store, verified_against="x"
    )


def _lint_valid_tiers() -> set[str]:
    """Read the tier vocabulary out of docs_lint.sh itself rather than
    restating it. A second hand-written copy of a vocabulary is the exact shape
    of IMP-0041/IMP-0055 — it drifts, and nothing notices."""
    text = (ROOT / "ops" / "docs_lint.sh").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("VALID_TIERS="):
            return set(line.split("=", 1)[1].strip().strip('"').split())
    raise AssertionError("could not find VALID_TIERS in ops/docs_lint.sh")


def test_render_emits_doc_meta_the_lint_requires(tmp_path):
    """docs_lint.sh demands tier/authority/update_trigger/scope/verified_against
    on every docs/**/*.md. The generated view is one of those."""
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(
        _table("| IMP-0001 | 2026-06-13 | a | doc | low | fixed | first | — |"), store
    )
    rendered = BACKLOG.render_view(store, verified_against="abc1234")

    head = rendered.split("-->")[0]
    assert head.startswith("<!-- doc-meta")
    for field in ("tier:", "authority:", "update_trigger:", "scope:", "verified_against:"):
        assert field in head, f"generated view is missing {field}, docs_lint will reject it"
    assert "verified_against: abc1234" in head

    # `generated` is a registry *kind*, not a doc tier — docs_lint.sh:112 would
    # reject it. The precedent is ios_baseline.md: tier: snapshot in the
    # frontmatter, kind: generated in the registry.
    tier = next(l.split(":", 1)[1].strip() for l in head.splitlines() if l.startswith("tier:"))
    assert tier in _lint_valid_tiers(), (
        f"tier {tier!r} is not in docs_lint.sh's VALID_TIERS; the generated view "
        f"would be rejected by the docs gate"
    )


def test_render_says_it_is_generated(tmp_path):
    """Anyone opening the file to hand-edit a row needs to find out here, not
    after their edit is silently overwritten by the next render."""
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(
        _table("| IMP-0001 | 2026-06-13 | a | doc | low | fixed | first | — |"), store
    )
    rendered = BACKLOG.render_view(store, verified_against="abc1234")
    assert "ops/backlog.py" in rendered
    body = rendered.split("-->", 1)[1]
    assert "GENERATED" in body.upper()


def test_app_entries_render_in_their_own_section(tmp_path):
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(
        _table("| IMP-0001 | 2026-06-13 | a | doc | low | fixed | first | — |"), store
    )
    BACKLOG.add_entry(
        store,
        stream="APP",
        date="2026-08-05",
        source="dogfood",
        category="ux",
        severity="high",
        status="open",
        detail="tapping a word mid-layout selects the wrong token",
        surface="reader",
    )

    rendered = BACKLOG.render_view(store, verified_against="abc1234")
    assert "tapping a word mid-layout" in rendered
    # The two streams have different owners and different triage queues, so they
    # must not be interleaved into one table.
    imp_pos = rendered.index("IMP-0001")
    app_pos = rendered.index("tapping a word mid-layout")
    assert imp_pos < app_pos


# ---------------------------------------------------------------------------
# 3b. verdict stamps promoted to first-class fields
# ---------------------------------------------------------------------------
#
# The 2026-08-05 re-verification sweep encoded its results as a convention
# inside the resolution cell:
#
#   —(YYYY-MM-DD 驗證 <VERDICT>;落點 `file:line`,成本 <S|M|L>,測試…)
#
# Promoting those to real fields is the point of having a store at all. But the
# extraction is ADDITIVE and LOSSLESS: `resolution` keeps the original text
# verbatim and stays authoritative, so a stamp the parser does not recognise
# costs an empty field and a named report — never a lost sentence.


def test_verdict_and_date_are_extracted():
    stamp = "—(2026-08-05 驗證 CONFIRMED-OPEN;成本 M=純文編排)"
    fields, misses = BACKLOG.extract_verdict_fields(stamp)

    assert fields["verified_at"] == "2026-08-05"
    assert fields["verdict"] == "CONFIRMED-OPEN"
    assert fields["cost"] == "M"
    assert misses == []


@pytest.mark.parametrize("sep", [";", ",", ":"])
def test_verdict_survives_all_three_separators_seen_in_the_data(sep):
    """The sweep used `;`, `,` and `:` interchangeably after the verdict —
    CONFIRMED-OPEN;候選, CONFIRMED-OPEN,detail 兩處失準, PARTIAL:症狀真."""
    fields, _ = BACKLOG.extract_verdict_fields(f"—(2026-08-05 驗證 PARTIAL{sep}症狀真)")
    assert fields["verdict"] == "PARTIAL"


def test_en_dash_cost_range_is_kept_whole():
    """`成本 S–M` uses an EN DASH, not a hyphen. Splitting on `-` would report
    cost `S` and silently halve the estimate."""
    fields, _ = BACKLOG.extract_verdict_fields("—(2026-08-05 驗證 CONFIRMED-OPEN;成本 S–M——M 的部分是…)")
    assert fields["cost"] == "S–M"


def test_duplicate_verdict_keeps_the_id_it_points_at():
    fields, _ = BACKLOG.extract_verdict_fields("—(2026-08-05 驗證 DUPLICATE-OF-IMP-0042)")
    assert fields["verdict"] == "DUPLICATE-OF-IMP-0042"
    assert fields["duplicate_of"] == "IMP-0042"


def test_fix_site_is_taken_only_when_it_is_a_backticked_token():
    fields, misses = BACKLOG.extract_verdict_fields(
        "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 `ops_world_export.py:140` 上方加模組級 X)"
    )
    assert fields["fix_site"] == "ops_world_export.py:140"
    assert misses == []


def test_unbackticked_fix_site_is_reported_not_guessed():
    """`落點` followed by free prose has no delimiter that can be trusted.
    Guessing where it ends would put arbitrary prose into a field that later
    readers treat as a path."""
    fields, misses = BACKLOG.extract_verdict_fields(
        "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 大概在 export 那一帶,成本 S)"
    )
    assert "fix_site" not in fields
    assert any(m["field"] == "fix_site" for m in misses)
    assert fields["cost"] == "S", "one unparseable field must not abort the others"


def test_stamp_is_found_when_it_starts_with_prose():
    """IMP-0029's real shape. The date is regular relative to 驗證, not to the
    opening bracket — anchoring on `—(` silently loses the date on entries whose
    resolution opens with a note."""
    fields, misses = BACKLOG.extract_verdict_fields(
        "—(by-design,待產品決策;2026-08-05 驗證 CONFIRMED-OPEN,範圍由 1 擴為 4 surface;決策成本 S)"
    )
    assert fields["verified_at"] == "2026-08-05"
    assert fields["verdict"] == "CONFIRMED-OPEN"


def test_prose_mentioning_the_word_is_not_treated_as_a_stamp():
    """Three real entries (IMP-0018/0054/0056) mention 驗證 in prose without
    carrying a stamp. Gating on the bare keyword reported all three as having
    unreadable stamps — a keyword standing in for the structure, which is the
    same proxy error the module refuses to make elsewhere."""
    fields, misses = BACKLOG.extract_verdict_fields(
        "`330b87fad`。reviewer 用兩-tick 探針實測驗證出回滾不 recreate,故改走 force-recreate。"
    )
    assert fields == {}
    assert misses == [], f"prose mention produced noise: {misses}"


def test_no_stamp_extracts_nothing_and_reports_nothing():
    """Resolutions that are plain commit hashes are the majority; they must not
    generate noise."""
    fields, misses = BACKLOG.extract_verdict_fields("`8aeb9e54b`。裁定：reconciler 是例行部署 SoT")
    assert fields == {}
    assert misses == []


def test_extraction_never_mutates_the_resolution(tmp_path):
    """The lossless half of the contract."""
    store = tmp_path / "backlog"
    original = "—(2026-08-05 驗證 PARTIAL:症狀真、機制原述為錯已改寫;落點 `ios_test.sh:790`,成本 S)"
    BACKLOG.import_legacy(
        _table(f"| IMP-0030 | 2026-07-10 | sweep | tool | med | open | a false green | {original} |"),
        store,
    )

    entry = BACKLOG.load_entry(store, "IMP-0030")
    assert entry["resolution"] == original, "resolution must survive verbatim"
    assert entry["verdict"] == "PARTIAL"
    assert entry["fix_site"] == "ios_test.sh:790"


def test_needs_test_is_deliberately_not_extracted():
    """`測試` appears in free prose with no consistent encoding. Deriving a
    boolean from the presence of the word would be a proxy standing in for the
    property — the exact shape that survived three review rounds in IMP-0047.
    The prose stays in `resolution`; no field is invented."""
    fields, _ = BACKLOG.extract_verdict_fields(
        "—(2026-08-05 驗證 CONFIRMED-OPEN;成本 S,測試加在 `ops/test_ios_ops.sh:375-378`)"
    )
    assert "needs_test" not in fields


# ---------------------------------------------------------------------------
# 4. against the real ledger currently in the repo
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_real_ledger_parses_with_no_losses(tmp_path):
    """The migration's fidelity gate. Every row in the shipped ledger must
    parse; a single unparsed row is an entry that would vanish."""
    text = LEGACY_DOC.read_text(encoding="utf-8")
    rows, problems = BACKLOG.parse_legacy_table(text)

    lost = [p for p in problems if p["kind"] == "malformed-row"]
    assert lost == [], f"rows the importer could not take: {lost}"
    assert len(rows) >= 59, f"expected the full ledger, parsed {len(rows)}"

    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids in the source ledger"

    # Recovery, if it happens at all, must be NAMED rather than silent. The
    # hand-maintained table needed it (IMP-0017 wrote `|| true` where IMP-0023
    # wrote `\|\| true`, so that row was silently ten columns wide for as long
    # as the table existed). Once the file is generated, `render` escapes cells
    # and recovery should never fire again — so this asserts the invariant, not
    # the transient fact, and holds on both sides of the migration.
    for problem in problems:
        assert problem["kind"] == "recovered-row", f"unexpected problem: {problem}"
        assert problem.get("id"), "a recovery must name the row it repaired"


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_generated_view_needs_no_recovery():
    """The post-migration invariant: a rendered view is escaped correctly, so
    round-tripping it is clean. If this ever goes red, `render` has started
    re-creating the damage the importer was built to repair."""
    text = LEGACY_DOC.read_text(encoding="utf-8")
    if "GENERATED" not in text.upper():
        pytest.skip("ledger has not been migrated to the generated view yet")

    _, problems = BACKLOG.parse_legacy_table(text)
    assert problems == [], f"the generated view does not round-trip cleanly: {problems}"


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_real_ledger_survives_a_full_round_trip(tmp_path):
    store = tmp_path / "backlog"
    text = LEGACY_DOC.read_text(encoding="utf-8")

    BACKLOG.import_legacy(text, store)
    rendered = BACKLOG.render_view(store, verified_against="deadbeef")

    original, _ = BACKLOG.parse_legacy_table(text)
    reparsed, problems = BACKLOG.parse_legacy_table(rendered)

    assert problems == []
    assert {r["id"]: r for r in reparsed} == {r["id"]: r for r in original}


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_real_ledger_entries_pass_validation(tmp_path):
    """Catches vocabulary drift in the source: a category or status in the table
    that the store does not know about would otherwise be imported and only fail
    much later."""
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(LEGACY_DOC.read_text(encoding="utf-8"), store)

    assert BACKLOG.validate_store(store) == []

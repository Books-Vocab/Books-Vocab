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

# FROZEN corpus, not the live view. These tests exercise `import_legacy`, whose job
# since IMP-20260805-3df783 is reading HISTORICAL 8-column ledgers — so their input
# must be a historical 8-column ledger. Pointing them at
# docs/runbook/improvement_backlog.md was always a latent bug: that file is a
# generated artifact, and the moment IMP-20260805-355016 widened it to 12 columns
# five of these tests failed for a reason that had nothing to do with the parser.
# The fixture is the real ledger as of main@0d4d4d1c3 (141 IMP + 9 APP rows of real
# prose and CJK), byte-identical to that commit's generated view.
#
# WHAT IT CANNOT SEE, stated because an earlier version of this comment claimed the
# opposite: it contains ZERO unescaped pipes inside cells. Measured — 141 IMP rows
# carry exactly 9x141 = 1269 unescaped pipes (pure delimiters) and 9 APP rows exactly
# 12x9 = 108; all 40 content pipes are already `\|`. It is a RENDERED artifact, so
# every cell was escaped on the way out. The genuine hand-written pre-migration
# ledgers do contain an unescaped pipe (IMP-0017, present in 30 historical versions),
# and that is exactly the input the over-wide branch now refuses. This fixture cannot
# exercise that path. A fixture easier than the input it stands for is a check kinder
# than the thing it guards; saying so is cheaper than pretending otherwise.
LEGACY_DOC = ROOT / "ops" / "tests" / "fixtures" / "legacy_ledger_8col.md"


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

def test_render_no_longer_round_trips_and_says_so(tmp_path):
    """The view is deliberately NOT importable any more (IMP-20260805-355016).

    This test used to assert the opposite. It is inverted rather than deleted
    because the property was load-bearing for a year and its absence must be
    asserted, not merely un-asserted: a silent return to an importable view would
    otherwise go unnoticed until someone re-imported a 12-column table and got
    the mangled rows that motivated retiring `_recover_overflowing_row`.

    What replaces it as the safety net: entries are one-file-per-entry in the
    store, and `view_entry_ids` (NOT `parse_legacy_table`) is what the render
    drop-guard reads.
    """
    store = tmp_path / "backlog"
    text = _table(
        "| IMP-0001 | 2026-06-13 | review gate | doc | low | fixed | it lied | `7c95a02` |",
        r"| IMP-0023 | 2026-07-09 | backup | cli | med | open | wrap it in `\|\| true` | — |",
    )
    BACKLOG.import_legacy(text, store)
    rendered = BACKLOG.render_view(store, verified_against="deadbeef")

    reparsed, problems = BACKLOG.parse_legacy_table(rendered)
    assert reparsed == [], "the view became importable again — see the docstring"
    assert {p["kind"] for p in problems} == {"malformed-row"}
    assert "NOT importable" in problems[0]["note"], problems[0]

    # the ids are still readable, by the reader that is actually used
    assert BACKLOG.view_entry_ids(rendered) == {"IMP-0001", "IMP-0023"}


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
    # reject it. The precedent was ios_baseline.md (tier: snapshot in the
    # frontmatter, kind: generated in the registry) until IMP-20260808-b63206
    # unversioned that artifact; the registry now has no `kind: generated` entry.
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
        "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 `ops_world_export.py:140` 上方加模組級 X,成本 S)"
    )
    assert fields["fix_site"] == "ops_world_export.py:140"
    # Stays a GLOBAL assertion. A first attempt narrowed it to fix_site so the
    # new cost report would not trip it — and a review then constructed a
    # verdict-vocabulary regression that the narrowed form sails past while
    # `misses == []` catches it. The fixture states a cost instead; that keeps
    # the assertion able to see every field, which is most of its value.
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


REAL_STORE = ROOT / "docs" / "runbook" / "backlog"


@pytest.mark.skipif(not REAL_STORE.exists(), reason="store not present")
def test_render_escapes_every_cell_in_the_real_store():
    """`_cell`'s pipe escaping, asserted against the LIVE store.

    This replaces the round-trip that used to guard it. Widening the view retired
    `parse_legacy_table` as the view's reader, and that quietly took the escaping
    guard with it: deleting `.replace("|", "\\|")` from `_cell` left the whole
    suite green (measured: 112 passed), while 19 cells across the real store carry
    a raw pipe — including `IMP-0003.fix_site`, which literally contains
    `| IMP-0003 |`. The damage is silent end to end: `render --commit` writes it,
    `render --check` then calls it up to date, `validate` reports 0 problems, and
    a dozen-odd rows of the human-facing artifact are shifted.

    Escaping is MORE load-bearing after the widening, not less — `fix_site` is a
    new column and it is one of the pipe carriers.

    Deliberately reads the real store rather than a fixture: a fixture would have
    to reproduce the pipes to be worth anything, and the frozen 8-column fixture
    demonstrably does not (all 40 of its content pipes are already escaped).
    """
    view = BACKLOG.render_view(REAL_STORE, verified_against="0" * 9)
    checked = 0
    for line in view.splitlines():
        if line.startswith("| IMP-"):
            expected = len(BACKLOG.VIEW_IMP_COLUMNS)
        elif line.startswith("| APP-"):
            expected = len(BACKLOG.APP_COLUMNS)
        else:
            continue
        cells = BACKLOG._split_row_raw(line)
        assert len(cells) == expected, (
            f"{cells[0].strip()} rendered {len(cells)} cells, expected {expected} — "
            "an unescaped pipe shifts every field after it"
        )
        checked += 1
    # Anti-vacuity: a render that emitted nothing would satisfy the loop above.
    assert checked >= 100, f"only {checked} rows checked — the probe, not the tree"


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="fixture not present")
def test_frozen_fixture_still_round_trips_without_recovery():
    """The 8-column fixture is what `import` still claims to read; it must parse
    with zero problems. Note what this canNOT see: the fixture's content pipes are
    all escaped, so it cannot exercise the unescaped-pipe path that `IMP-0017`
    exercises in the genuine pre-migration ledger."""
    _, problems = BACKLOG.parse_legacy_table(LEGACY_DOC.read_text(encoding="utf-8"))
    assert problems == [], f"the frozen fixture does not parse cleanly: {problems}"


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_real_ledger_import_still_works_even_though_render_does_not(tmp_path):
    """The half of the property that is KEPT: `import` still reads the historical
    8-column ledger. Only the render direction was given up.

    Without this, retiring the round-trip tests would have quietly retired the
    importer's real regression coverage too.
    """
    store = tmp_path / "backlog"
    text = LEGACY_DOC.read_text(encoding="utf-8")

    result = BACKLOG.import_legacy(text, store)
    original, orig_problems = BACKLOG.parse_legacy_table(text)

    assert orig_problems == [], f"the historical ledger stopped parsing: {orig_problems}"
    assert original, "parsed zero rows from the real ledger — the probe is broken"
    stored = {e["id"] for e in BACKLOG.list_entries(store)}
    assert {r["id"] for r in original} <= stored


@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_real_ledger_entries_pass_validation(tmp_path):
    """Catches vocabulary drift in the source: a category or status in the table
    that the store does not know about would otherwise be imported and only fail
    much later."""
    store = tmp_path / "backlog"
    BACKLOG.import_legacy(LEGACY_DOC.read_text(encoding="utf-8"), store)

    # Traceability is excluded, not ignored: this fixture is the FROZEN 8-column
    # table, whose `fixed` rows predate `fixed_by` and can never carry one. The
    # assertion still fails on anything else, and asserting that the remainder is
    # *only* traceability keeps this from quietly becoming a weaker test.
    problems = BACKLOG.validate_store(store)
    traceability = {"fixed-without-fixed-by", "fixed-by-orphaned",
                    "fixed-by-unresolvable", "fixed-by-not-a-sha", "no-next-action"}
    assert [p for p in problems if p["kind"] not in traceability] == []


# ---------------------------------------------------------------------------
# 5. the CLI layer — where "reported, never silent" actually reaches an operator
# ---------------------------------------------------------------------------
#
# Every one of these was a surviving mutation before it existed. The module's
# whole promise is that problems get REPORTED, and the place a report becomes
# actionable is the exit code — problems printed to stdout with rc=0 are not
# reported, they are decoration.


def _write_table(tmp_path, *rows) -> Path:
    doc = tmp_path / "ledger.md"
    doc.write_text(_table(*rows), encoding="utf-8")
    return doc


def test_import_exits_nonzero_when_a_row_was_lost(tmp_path, capsys):
    doc = _write_table(
        tmp_path,
        "| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |",
        "| IMP-0002 | 2026-06-13 | broken |",
    )
    rc = BACKLOG.main(["import", "--store", str(tmp_path / "s"), "--from", str(doc), "--commit"])
    assert rc == 2, "a lost row exited 0 — the operator has no signal at all"


def test_import_exits_zero_on_a_clean_table(tmp_path):
    """The green direction. Without it the exit code could be hardwired to 2."""
    doc = _write_table(tmp_path, "| IMP-0001 | 2026-06-13 | ok | doc | low | fixed | fine | — |")
    assert BACKLOG.main(["import", "--store", str(tmp_path / "s"), "--from", str(doc), "--commit"]) == 0


def test_import_reports_a_row_the_store_refused(tmp_path):
    """The `rejected-row` path — add_entry raising — had no test reaching it at
    all, and it is the only backstop for a row whose columns passed the anchor
    check but whose values the store rejects."""
    doc = _write_table(
        tmp_path, "| IMP-0001 | 2026/06/13 | ok | doc | low | fixed | fine | — |"
    )
    result = BACKLOG.import_legacy(doc.read_text(encoding="utf-8"), tmp_path / "s")
    assert any(p["kind"] == "rejected-row" for p in result["problems"]), result["problems"]


def test_validate_cli_exit_codes(tmp_path):
    store = tmp_path / "s"
    BACKLOG.add_entry(
        store, stream="IMP", date="2026-08-05", source="t", category="cli",
        severity="med", status="open", detail="d", resolution="",
    )
    assert BACKLOG.main(["validate", "--store", str(store)]) == 0

    entry = next(store.glob("*.json"))
    payload = json.loads(entry.read_text(encoding="utf-8"))
    payload["status"] = "done"
    entry.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert BACKLOG.main(["validate", "--store", str(store)]) == 2


def test_validate_cli_flags_a_store_that_is_not_there(tmp_path):
    """A typo'd --store used to be a green gate pointed at nothing."""
    assert BACKLOG.main(["validate", "--store", str(tmp_path / "typo")]) == 2


def test_update_dry_run_does_not_write(tmp_path, monkeypatch):
    """The headline contract of the update commit, previously asserted by no
    test: making dry-run write left the whole suite green."""
    store = tmp_path / "s"
    entry = BACKLOG.add_entry(
        store, stream="IMP", date="2026-08-05", source="t", category="cli",
        severity="med", status="open", detail="d", resolution="",
    )
    path = store / f"{entry['id']}.json"
    before = path.read_bytes()

    # status=fixed now owes a fixed_by, and update resolves it for real. Stub
    # the resolver so this test keeps asserting what it is named for instead of
    # becoming a test about the host repo's history.
    monkeypatch.setattr(BACKLOG, "make_commit_state", lambda: lambda sha: "ok")
    argv = ["update", "--store", str(store), entry["id"], "--status", "fixed",
            "--fixed-by", "abc1234"]

    assert BACKLOG.main(argv) == 0
    assert path.read_bytes() == before, "dry-run wrote to the store"

    assert BACKLOG.main(argv + ["--commit"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "fixed"


def test_show_cli_reports_a_missing_entry(tmp_path):
    store = tmp_path / "s"
    BACKLOG.add_entry(
        store, stream="IMP", date="2026-08-05", source="t", category="cli",
        severity="med", status="open", detail="d", resolution="",
    )
    assert BACKLOG.main(["show", "--store", str(store), "IMP-0404"]) == 1


# ---------------------------------------------------------------------------
# 6. an anchor that does not go through the parser
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LEGACY_DOC.exists(), reason="ledger not present")
def test_row_count_matches_a_count_taken_without_the_parser():
    """The round-trip test compares parse(original) with parse(render(import)).
    Both sides run through the SAME parser, so anything the parser drops is
    dropped on both sides and the comparison still passes. This counts the rows
    by hand instead, which is the one check the parser cannot satisfy by being
    consistently wrong."""
    text = LEGACY_DOC.read_text(encoding="utf-8")
    by_hand = sum(1 for line in text.splitlines() if line.strip().startswith("| IMP-"))
    rows, _ = BACKLOG.parse_legacy_table(text)
    assert len(rows) == by_hand, f"parser produced {len(rows)} rows for {by_hand} IMP lines"


def test_a_row_whose_id_is_malformed_is_reported_not_skipped():
    """`_ID_RE` used to decide both 'is this a data row' and 'is this id valid',
    so a bolded, mistyped, lowercased or link-wrapped id took the whole row with
    it — detail and all — without a word."""
    for bad_id in ("**IMP-0009**", "imp-0009", "IMP-9", "[IMP-0009](#x)"):
        text = _table(f"| {bad_id} | 2026-06-13 | s | doc | low | open | real content | — |")
        rows, problems = BACKLOG.parse_legacy_table(text)
        assert rows == [], bad_id
        assert [p["kind"] for p in problems] == ["unrecognised-id"], f"{bad_id}: {problems}"


def test_the_date_must_sit_next_to_the_verdict():
    """The adjacency is the entire reason the stamp regex is shaped as it is,
    and loosening it left the suite green."""
    fields, _ = BACKLOG.extract_verdict_fields(
        "問題自 2026-06-13 起存在;後於 2026-08-05 驗證 CONFIRMED-OPEN"
    )
    assert fields["verified_at"] == "2026-08-05", "picked up a date from unrelated prose"


def test_render_anchor_survives_a_rebase(tmp_path, monkeypatch):
    """`verified_against` must not be minted from HEAD.

    Rebasing this branch to add review trailers orphaned every sha it had
    minted, and docs_lint rejected the generated view for an unreachable
    anchor — IMP-0038's exact shape, produced by the tool itself. The anchor is
    now the merge-base with main, which survives both rebase and squash merge.
    """
    import subprocess as sp
    head = BACKLOG._doc_anchor()
    if head == "unknown":
        pytest.skip("no git")
    # The anchor must be an ancestor of HEAD — the property docs_lint enforces.
    rc = sp.run(["git", "merge-base", "--is-ancestor", head, "HEAD"],
                cwd=BACKLOG.ROOT, capture_output=True).returncode
    assert rc == 0, f"render would stamp an anchor unreachable from HEAD: {head}"


def test_doc_anchor_is_reachable_from_origin_main():
    """The positive control the previous two anchor fixes both lacked.

    docs_lint only checks reachability from HEAD, which every wrong answer
    satisfies — a branch-local sha, local main's tip, HEAD itself. The property
    that actually matters is reachability from ORIGIN, because that is what
    IMP-0038 is about and what fails in CI rather than locally. Without this
    assertion any value render produces looks equally correct.
    """
    import subprocess as sp
    anchor = BACKLOG._doc_anchor()
    if anchor == "unknown":
        pytest.skip("no git")
    if sp.run(["git", "rev-parse", "--verify", "origin/main"],
              cwd=BACKLOG.ROOT, capture_output=True).returncode != 0:
        pytest.skip("no origin/main")
    rc = sp.run(["git", "merge-base", "--is-ancestor", anchor, "origin/main"],
                cwd=BACKLOG.ROOT, capture_output=True).returncode
    assert rc == 0, f"anchor {anchor} is not reachable from origin/main — IMP-0038's shape"


def _app_row(**overrides) -> str:
    """One rendered APP row, in the generated view's 11-column APP shape."""
    cells = {
        "id": "APP-20260101-abcdef",
        "date": "2026-01-01",
        "source": "review",
        "surface": "vocabulary",
        "category": "correctness",
        "severity": "med",
        "status": "open",
        "detail": "browsing the public catalogue must not log anyone out",
        "repro": "open Explore with an expired token",
        "build": "—",
        "resolution": "—",
    }
    cells.update(overrides)
    return "| " + " | ".join(cells[c] for c in BACKLOG.APP_COLUMNS) + " |"


def test_app_row_from_generated_view_is_skipped_not_reported():
    """An APP row is not a malformed IMP row.

    The APP table carries three extra columns (surface/repro/build), so its
    controlled-vocabulary anchors sit at different indices than the IMP table's.
    `_anchors_ok` is IMP-shaped, so an APP row can never satisfy it — which made
    the `APP-` skip that sits behind that gate unreachable, and reported the
    first APP entry ever written as a malformed row.
    """
    rows, problems = BACKLOG.parse_legacy_table(_app_row())
    assert problems == [], f"a well-formed APP row was reported: {problems}"
    assert rows == [], "an APP row must not be imported into the IMP table"


def test_malformed_app_row_is_still_reported():
    """Skipping APP rows must not become a silent drop.

    The parser's whole discipline is that a row it cannot read is REPORTED, never
    dropped. A blanket `startswith("APP-")` skip would satisfy the test above
    while quietly swallowing a genuinely broken APP row.
    """
    broken = _app_row(severity="nonsense")
    rows, problems = BACKLOG.parse_legacy_table(broken)
    assert rows == []
    assert [p["kind"] for p in problems] == ["malformed-row"]
    assert problems[0]["id"] == "APP-20260101-abcdef"


def test_a_stamp_that_states_no_cost_at_all_is_reported(tmp_path):
    """Absence has to be visible, or "24 of 25 have a cost" means nothing.

    `_COST_PRESENT_RE` tests for the WORD 成本, not for "does this text state a
    cost", so a stamp stating its cost some other way produced no field AND no
    report — an empty column indistinguishable from every other empty column.

    The three unreadable shapes get ONE reason on purpose. Splitting "written
    unreadably" from "not written" needs a discriminator, and the only one
    available is that same keyword test: a first attempt used it and handed
    `各 S` — IMP-0048's real stamp — "no cost stated in the stamp", which is a
    confident wrong answer replacing an honest silence. Twice now this entry has
    been mis-measured by a detector rather than read: the commit that added the
    keyword check asserted IMP-0048 stated no cost ("checked, not assumed" —
    what it checked was the keyword), and the commit that removed it asserted
    `各 S` no longer existed (a regex needing 40 trailing characters, against a
    match 11 from the end).
    """
    readable = "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 `ops/x.py:10`,成本 S)"
    fields, misses = BACKLOG.extract_verdict_fields(readable)
    assert fields["cost"] == "S"
    assert [m for m in misses if m["field"] == "cost"] == []

    unreadable = "—(2026-08-05 驗證 CONFIRMED-OPEN;成本 高)"
    absent = "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 `ops/x.py:10`)"
    keywordless = "—(2026-08-05 驗證 CONFIRMED-OPEN;落點 `ops/x.py:10`,各 S)"
    for stamp in (unreadable, absent, keywordless):
        fields, misses = BACKLOG.extract_verdict_fields(stamp)
        assert "cost" not in fields, stamp
        # ONE reason for all three. Splitting them needs a discriminator, and
        # the only one available is the keyword test this rule rejects: it
        # labelled `各 S` — IMP-0048's real stamp, a cost stated without the
        # word — as "no cost stated", which is a confident wrong answer where
        # there used to be an honest silence.
        assert [m["reason"] for m in misses if m["field"] == "cost"] == [
            "stamp states no cost this module can read"], stamp

    # Not owed a cost: the verdict token was never recognised, so the stamp has
    # not been understood at all; and a DUPLICATE-OF entry's cost lives on its
    # target. Reporting cost on either is noise on a legitimate shape.
    for legitimate in ("—(2026-08-05 驗證 PENDING;等上游)",
                       "—(2026-08-05 驗證 DUPLICATE-OF-IMP-0042)"):
        _fields, misses = BACKLOG.extract_verdict_fields(legitimate)
        assert [m for m in misses if m["field"] == "cost"] == [], legitimate

    # No stamp at all is not a miss — most resolutions are a bare commit hash,
    # and reporting those would bury the real ones.
    _fields, misses = BACKLOG.extract_verdict_fields("`8aeb9e54b` 修好了")
    assert misses == []


def test_a_retired_status_is_still_a_row_and_gets_mapped_forward(tmp_path):
    """Narrowing the vocabulary broke the READER, and the failure was silent loss.

    `_anchors_ok` uses the closed vocabularies to decide "is this line a data row".
    When `in-progress` was retired (IMP-20260808-439594), the three rows carrying it
    in the frozen 8-column fixture stopped looking like rows at all — reported as
    `malformed-row`, i.e. three entries that would have vanished on import. The
    migration's own fidelity gate caught it, which is what that gate is for.

    Reading old data and writing new data are different questions. `PARSEABLE_
    STATUSES` answers the first, `STATUSES` the second, and `import_legacy` maps
    between them — reporting each rewrite rather than doing it quietly, because a
    migration that changes values without saying so is indistinguishable from one
    that corrupts them.
    """
    table = (
        "| id | date | source | category | severity | status | detail | resolution |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| IMP-0900 | 2026-01-01 | t | tool | low | in-progress | a thing | — next: x |\n"
    )
    rows, problems = BACKLOG.parse_legacy_table(table)
    assert [p for p in problems if p["kind"] == "malformed-row"] == [], (
        "a retired status made the row unrecognisable — that is entry loss")
    assert [r["status"] for r in rows] == ["in-progress"], "the parser must not rewrite"

    store = tmp_path / "s"
    result = BACKLOG.import_legacy(table, store)
    assert result["imported"] == 1
    assert BACKLOG.load_entry(store, "IMP-0900")["status"] == "triaged"
    migrated = [p for p in result["problems"] if p["kind"] == "status-migrated"]
    assert migrated and migrated[0]["from"] == "in-progress" and migrated[0]["to"] == "triaged", (
        "the rewrite must be reported; a silent one cannot be told from corruption")

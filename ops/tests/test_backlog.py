"""Tests for ops/backlog.py — the one-file-per-entry backlog store.

Why this store exists (the failure modes it is built against, all observed):

  1. The predecessor was a single markdown table. Two agents in two worktrees
     cannot both append to it without a textual conflict, and the file had grown
     to 54KB — every agent that wanted to file one entry had to read all of it.
  2. Sequential ids (IMP-0001, IMP-0002, ...) collide. IMP-0017's own detail
     records colliding twice WITHOUT parallelism. Across worktrees a counter
     cannot work even in principle: the files are invisible to each other until
     merge, so two agents necessarily allocate the same next number.
  3. A schema migration is only safe if the importer is re-runnable, because the
     source file keeps being edited while the migration is in flight.

So the contracts asserted here are, in order of importance:

  - one file per entry, disjoint paths (git merges disjoint new files cleanly)
  - ids are content-derived, never a counter: distinct content => distinct id in
    stores that cannot see each other, and identical content => identical id, so
    `add` and `import` are idempotent
  - the id inside the file and the filename cannot drift apart unnoticed
  - writes are atomic (crash cannot leave a half-written entry)

Tests are stdlib-only on purpose: the `ops/**.py` cutover gate runs them under a
sandbox `uv run --no-project --with pytest`, which has no PyYAML and no project
dependencies. Anything imported here must be in the standard library.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("backlog", ROOT / "ops" / "backlog.py")
assert SPEC and SPEC.loader
BACKLOG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BACKLOG
SPEC.loader.exec_module(BACKLOG)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

DEFAULT_CATEGORY = {"IMP": "cli", "APP": "ux"}


def _entry_kwargs(**overrides):
    stream = overrides.get("stream", "IMP")
    base = dict(
        stream=stream,
        date="2026-08-05",
        source="test",
        # The two streams have disjoint category vocabularies, so the default
        # has to follow the stream or every APP case below would be rejected
        # for using an IMP category.
        category=DEFAULT_CATEGORY[stream],
        severity="med",
        status="open",
        detail="a tool reports success while doing nothing",
        resolution="",
    )
    base.update(overrides)
    return base


def _add(store: Path, **overrides) -> dict:
    return BACKLOG.add_entry(store, **_entry_kwargs(**overrides))


# --------------------------------------------------------------------------
# 1. store layout: one file per entry
# --------------------------------------------------------------------------

def test_each_entry_is_its_own_file(tmp_path):
    store = tmp_path / "backlog"
    a = _add(store, detail="first problem")
    b = _add(store, detail="second problem")

    files = sorted(p.name for p in store.glob("*.json"))
    assert len(files) == 2, f"expected one file per entry, got {files}"
    assert f"{a['id']}.json" in files
    assert f"{b['id']}.json" in files
    # The whole point: the two writes touch disjoint paths, so two worktrees
    # doing this independently produce a conflict-free merge.
    assert a["id"] != b["id"]


def test_reading_one_entry_does_not_require_reading_the_others(tmp_path):
    store = tmp_path / "backlog"
    target = _add(store, detail="the one I want")
    for i in range(20):
        _add(store, detail=f"noise {i}")

    loaded = BACKLOG.load_entry(store, target["id"])
    assert loaded["detail"] == "the one I want"


# --------------------------------------------------------------------------
# 2. ids: content-derived, never a counter
# --------------------------------------------------------------------------

def test_distinct_content_gets_distinct_ids_in_stores_that_cannot_see_each_other(tmp_path):
    """The cross-worktree case that kills a counter.

    Two stores, neither able to observe the other (as two git worktrees cannot
    before they merge). A counter allocates the same next number in both. A
    content-derived id must not.
    """
    store_a = tmp_path / "worktree-a" / "backlog"
    store_b = tmp_path / "worktree-b" / "backlog"

    a = _add(store_a, detail="gate is green for the wrong reason")
    b = _add(store_b, detail="importer drops entries added mid-flight")

    assert a["id"] != b["id"], (
        "two isolated stores allocated the same id — this is exactly the "
        "collision a counter produces across worktrees"
    )


def test_identical_content_is_idempotent_not_duplicated(tmp_path):
    """`import` is re-run against a file that is still being edited, so filing
    the same entry twice must converge rather than fork."""
    store = tmp_path / "backlog"
    first = _add(store, detail="same text")
    second = _add(store, detail="same text")

    assert first["id"] == second["id"]
    assert len(list(store.glob("*.json"))) == 1


def test_id_is_not_sequential(tmp_path):
    """Guards against a well-meaning future change back to a counter."""
    store = tmp_path / "backlog"
    ids = [_add(store, detail=f"problem {i}")["id"] for i in range(5)]

    suffixes = [i.rsplit("-", 1)[-1] for i in ids]
    assert not all(s.isdigit() for s in suffixes), (
        f"ids look like a counter again: {ids}"
    )
    assert len(set(ids)) == 5


def test_same_text_on_different_dates_are_different_entries(tmp_path):
    store = tmp_path / "backlog"
    a = _add(store, detail="recurring symptom", date="2026-08-05")
    b = _add(store, detail="recurring symptom", date="2026-09-01")
    assert a["id"] != b["id"]


def test_new_ids_carry_their_stream_and_date(tmp_path):
    store = tmp_path / "backlog"
    imp = _add(store, stream="IMP", date="2026-08-05", detail="tooling friction")
    app = _add(store, stream="APP", date="2026-08-05", detail="reader loses scroll position")

    assert imp["id"].startswith("IMP-20260805-")
    assert app["id"].startswith("APP-20260805-")


# --------------------------------------------------------------------------
# 3. legacy ids survive migration
# --------------------------------------------------------------------------

def test_explicit_legacy_id_is_preserved(tmp_path):
    """The existing table cross-references ids in prose ("see IMP-0052").
    Renumbering on migration would break every one of those references."""
    store = tmp_path / "backlog"
    entry = BACKLOG.add_entry(store, entry_id="IMP-0052", **_entry_kwargs())

    assert entry["id"] == "IMP-0052"
    assert (store / "IMP-0052.json").exists()


# --------------------------------------------------------------------------
# 4. the id inside the file cannot drift from the filename
# --------------------------------------------------------------------------

def test_validate_catches_id_filename_drift(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)
    path = store / f"{entry['id']}.json"

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["id"] = "IMP-9999"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    problems = BACKLOG.validate_store(store)
    assert any(p["kind"] == "id-filename-drift" for p in problems), problems


@pytest.mark.parametrize(
    "field,bad_value,kind",
    [
        ("status", "done", "bad-status"),
        ("severity", "critical", "bad-severity"),
        ("category", "misc", "bad-category"),
        ("stream", "OPS", "bad-stream"),
    ],
)
def test_validate_rejects_out_of_vocabulary_values(tmp_path, field, bad_value, kind):
    store = tmp_path / "backlog"
    entry = _add(store)
    path = store / f"{entry['id']}.json"

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = bad_value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    problems = BACKLOG.validate_store(store)
    assert any(p["kind"] == kind for p in problems), problems


def test_validate_reports_missing_required_field(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)
    path = store / f"{entry['id']}.json"

    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["detail"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    problems = BACKLOG.validate_store(store)
    assert any(p["kind"] == "missing-field" and p["field"] == "detail" for p in problems), problems


def test_validate_is_clean_on_a_healthy_store(tmp_path):
    """The green direction. Without this the validator could reject everything
    and still pass every test above — a gate that can only go red is as useless
    as one that can only go green (IMP-0044)."""
    store = tmp_path / "backlog"
    for i in range(3):
        _add(store, detail=f"problem {i}")

    assert BACKLOG.validate_store(store) == []


def test_validate_reports_unparseable_entry_rather_than_crashing(tmp_path):
    store = tmp_path / "backlog"
    _add(store)
    (store / "IMP-0001.json").write_text("{ not json", encoding="utf-8")

    problems = BACKLOG.validate_store(store)
    assert any(p["kind"] == "unparseable" for p in problems), problems


# --------------------------------------------------------------------------
# 5. writes are atomic
# --------------------------------------------------------------------------

def test_entry_write_is_atomic(tmp_path, monkeypatch):
    """A crash between open() and the final bytes must not leave a truncated
    entry behind. Simulated by making the rename step fail."""
    store = tmp_path / "backlog"
    _add(store, detail="pre-existing good entry")
    before = {p.name: p.read_bytes() for p in store.glob("*.json")}

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("simulated crash during publish")

    monkeypatch.setattr(BACKLOG.os, "replace", boom)
    with pytest.raises(OSError):
        _add(store, detail="entry that dies mid-write")
    monkeypatch.setattr(BACKLOG.os, "replace", real_replace)

    after = {p.name: p.read_bytes() for p in store.glob("*.json")}
    assert after == before, "a failed write left residue in the store"


# --------------------------------------------------------------------------
# 6. list / show
# --------------------------------------------------------------------------

def test_list_filters_by_status(tmp_path):
    store = tmp_path / "backlog"
    _add(store, detail="still broken", status="open")
    _add(store, detail="already handled", status="fixed")

    open_ids = [e["id"] for e in BACKLOG.list_entries(store, status="open")]
    assert len(open_ids) == 1
    assert BACKLOG.load_entry(store, open_ids[0])["detail"] == "still broken"


def test_list_filters_by_stream(tmp_path):
    store = tmp_path / "backlog"
    _add(store, stream="IMP", detail="tooling friction")
    _add(store, stream="APP", detail="reader loses scroll position")

    app = BACKLOG.list_entries(store, stream="APP")
    assert [e["detail"] for e in app] == ["reader loses scroll position"]


def test_list_filters_compose(tmp_path):
    store = tmp_path / "backlog"
    _add(store, stream="APP", severity="high", status="open", detail="data loss on sync")
    _add(store, stream="APP", severity="low", status="open", detail="label truncated")
    _add(store, stream="IMP", severity="high", status="open", detail="gate false green")

    hits = BACKLOG.list_entries(store, stream="APP", severity="high")
    assert [e["detail"] for e in hits] == ["data loss on sync"]


def test_list_is_deterministically_ordered(tmp_path):
    """Ordering must not depend on filesystem enumeration order, or the
    generated view churns between machines."""
    store = tmp_path / "backlog"
    for i in range(6):
        _add(store, detail=f"problem {i}", date=f"2026-08-0{i + 1}")

    once = [e["id"] for e in BACKLOG.list_entries(store)]
    twice = [e["id"] for e in BACKLOG.list_entries(store)]
    assert once == twice
    assert once == sorted(once, key=BACKLOG.entry_sort_key_by_id(store))


def test_list_on_empty_store_returns_empty(tmp_path):
    assert BACKLOG.list_entries(tmp_path / "does-not-exist") == []


def test_load_entry_raises_for_unknown_id(tmp_path):
    store = tmp_path / "backlog"
    _add(store)
    with pytest.raises(KeyError):
        BACKLOG.load_entry(store, "IMP-0404")


# --------------------------------------------------------------------------
# 7. APP stream carries the fields an app-usage report actually needs
# --------------------------------------------------------------------------

def test_app_entries_accept_surface_and_repro(tmp_path):
    store = tmp_path / "backlog"
    entry = BACKLOG.add_entry(
        store,
        **_entry_kwargs(
            stream="APP",
            category="ux",
            detail="tapping a word while the page is still laying out selects the wrong token",
            surface="reader",
            repro="open a 400-page EPUB, jump to chapter 12, tap within 200ms of the jump",
            build="ios 2.0.1 (build 14)",
        ),
    )

    loaded = BACKLOG.load_entry(store, entry["id"])
    assert loaded["surface"] == "reader"
    assert loaded["repro"].startswith("open a 400-page EPUB")
    assert loaded["build"] == "ios 2.0.1 (build 14)"


def test_imp_entries_reject_app_only_fields(tmp_path):
    """Keeping the two streams' vocabularies apart is the reason they are
    separate streams at all."""
    store = tmp_path / "backlog"
    with pytest.raises(ValueError):
        BACKLOG.add_entry(store, **_entry_kwargs(stream="IMP", surface="reader"))


def test_app_stream_uses_its_own_categories(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, stream="APP", category="ux", detail="confusing empty state")
    assert BACKLOG.load_entry(store, entry["id"])["category"] == "ux"

    with pytest.raises(ValueError):
        BACKLOG.add_entry(store, **_entry_kwargs(stream="APP", category="cli"))


# --------------------------------------------------------------------------
# 8. update: the one mutation that overwrites, so dry-run by default
# --------------------------------------------------------------------------

def test_update_changes_status_and_resolution(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, status="open")

    BACKLOG.update_entry(store, entry["id"], status="fixed", resolution="`abc1234`")

    loaded = BACKLOG.load_entry(store, entry["id"])
    assert loaded["status"] == "fixed"
    assert loaded["resolution"] == "`abc1234`"


def test_update_does_not_change_the_id(tmp_path):
    """The id digest covers only the fields that identify WHICH problem this is.
    If triaging an entry moved its id, every cross-reference to it would rot and
    the store would accumulate a fresh file per status change."""
    store = tmp_path / "backlog"
    entry = _add(store, status="open")

    BACKLOG.update_entry(store, entry["id"], status="in-progress")

    assert BACKLOG.load_entry(store, entry["id"])["id"] == entry["id"]
    assert len(list(store.glob("*.json"))) == 1


def test_update_leaves_untouched_fields_alone(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, detail="the original finding", severity="high")

    BACKLOG.update_entry(store, entry["id"], status="triaged")

    loaded = BACKLOG.load_entry(store, entry["id"])
    assert loaded["detail"] == "the original finding"
    assert loaded["severity"] == "high"


def test_update_rejects_an_out_of_vocabulary_value_without_writing(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, status="open")
    before = (store / f"{entry['id']}.json").read_bytes()

    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], status="done")

    assert (store / f"{entry['id']}.json").read_bytes() == before, (
        "a rejected update still touched the file"
    )


def test_update_raises_for_unknown_id(tmp_path):
    store = tmp_path / "backlog"
    _add(store)
    with pytest.raises(KeyError):
        BACKLOG.update_entry(store, "IMP-0404", status="fixed")


def test_update_can_set_verdict_fields(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)

    BACKLOG.update_entry(store, entry["id"], verdict="CONFIRMED-OPEN", cost="M")

    loaded = BACKLOG.load_entry(store, entry["id"])
    assert loaded["verdict"] == "CONFIRMED-OPEN"
    assert loaded["cost"] == "M"


def test_update_rejects_unknown_fields(tmp_path):
    """Typos must not silently create a field nobody reads."""
    store = tmp_path / "backlog"
    entry = _add(store)
    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], statuss="fixed")


def test_update_refuses_a_digest_field_instead_of_silently_dropping_it(tmp_path, capsys):
    """`--detail` parsed, printed in --help, and did nothing. Exit 0.

    `detail` is a digest input, so its absence from MUTABLE_FIELDS is correct.
    The bug was that `_cmd_update` derives its change set from MUTABLE_FIELDS
    and therefore never read `args.detail` — the flag was accepted, ignored,
    and the command reported success with a changes dict that simply omitted
    it. Three separate entries were filed for this (IMP-20260805-24146e /
    -1be2c6 / -dd35f8) and a groom plan that leaned on the flag was rejected
    three times before anyone checked whether the flag worked at all.

    A no-op that exits 0 is worse than an error: the caller's next move is to
    verify something else. So the refusal must be loud, must name the flag, and
    must say where a correction actually belongs.
    """
    store = tmp_path / "backlog"
    entry = _add(store, detail="the original wording", status="open")

    rc = BACKLOG.main(
        [
            "update", entry["id"],
            "--store", str(store),
            "--status", "fixed",
            "--detail", "a rewording nobody asked for",
            "--commit",
        ]
    )

    # 64, not merely non-zero: this file's usage-error convention, and the
    # fragmented exit-code families (IMP-0042) are exactly why the flag was
    # kept and refused rather than deleted. Pin the contract the change claims.
    assert rc == 64, f"passing --detail should be a usage error, got rc={rc}"
    err = capsys.readouterr().err
    assert "--detail" in err, f"the refusal does not name the flag: {err!r}"
    assert "--resolution" in err, f"the refusal does not name the way out: {err!r}"

    # Refused as a unit: the mutable half must not land either, or the caller
    # is left with a half-applied command that also printed an error.
    after = BACKLOG.load_entry(store, entry["id"])
    assert after["detail"] == "the original wording"
    assert after["status"] == "open"


def test_refused_update_fields_are_exactly_the_digest_inputs_the_cli_exposes():
    """The refusal list is not an opinion — it is the digest signature.

    `make_entry_id` hashes stream/date/source/detail, so those are the fields
    an update can never touch. Anything the CLI refuses must be one of them,
    and nothing in that set may also be mutable, or the id would decouple from
    the content it is derived from.
    """
    assert set(BACKLOG.REFUSED_UPDATE_FIELDS) <= set(BACKLOG.DIGEST_FIELDS)
    assert not set(BACKLOG.DIGEST_FIELDS) & set(BACKLOG.MUTABLE_FIELDS)


def test_every_field_named_in_digest_fields_actually_changes_the_id():
    """DIGEST_FIELDS is read off the signature, and a signature is a proxy.

    What actually decides the id is the join inside `make_entry_id`'s body, so
    a parameter that is declared but not hashed would leave DIGEST_FIELDS
    naming it anyway — and the refusal message would then assert it is "an
    input make_entry_id hashes" in the one message whose entire job is to
    explain that invariant. Adding such a parameter passes every name-level
    check, so the name-level checks cannot be what guards this.

    Perturbing each named field and demanding the id move pins the behaviour
    rather than the spelling: it catches a field that drifts out of the digest
    just as well as one that was never in it.
    """
    base = {"stream": "IMP", "date": "2026-08-05", "source": "test", "detail": "a problem"}
    baseline = BACKLOG.make_entry_id(**base)

    for field in BACKLOG.DIGEST_FIELDS:
        perturbed = {**base, field: f"{base.get(field, '')}-perturbed"}
        assert BACKLOG.make_entry_id(**perturbed) != baseline, (
            f"{field!r} is named in DIGEST_FIELDS but the digest ignores it"
        )


# --------------------------------------------------------------------------
# 8. groom stamp: "this entry has been worked out, not just filed"
#
# The ledger accumulated two different kinds of confidence under one stamp:
# a re-verification sweep ("the claim still holds") and an entry born from a
# deep dive ("this was investigated at birth"). Both wrote the same
# verdict/verified_at, so the one question the owner actually asks — which of
# these has someone worked out how to fix? — was unanswerable from the data.
#
# The groom stamp answers it, and is deliberately expensive to claim: an entry
# is groomed only when it carries a fix plan concrete enough to hand to a small
# model, the acceptance command that must flip, and the site to change. A badge
# whose preconditions nobody checks is the "reason field nobody reads" failure
# this repo has already been bitten by.
# --------------------------------------------------------------------------


def _groom_kwargs(**overrides):
    base = dict(
        plan="1. open ops/x.py:10  2. replace the whitelist with the tuple  3. run the test",
        acceptance="pytest -q ops/tests/test_x.py::test_y",
        fix_site="ops/x.py:10",
        groomed_at="2026-08-05",
        groomed_by="workflow:groom@v1",
    )
    base.update(overrides)
    return base


def test_a_fully_groomed_entry_validates(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs())
    assert BACKLOG.validate_store(store) == []


@pytest.mark.parametrize("missing", ["plan", "acceptance", "fix_site"])
def test_groom_stamp_is_refused_without_the_work_it_claims(tmp_path, missing):
    """Claiming groomed without the artifact that makes it groomed is the lie
    this field exists to prevent."""
    store = tmp_path / "backlog"
    entry = _add(store)
    before = (store / f"{entry['id']}.json").read_bytes()

    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(**{missing: ""}))

    assert (store / f"{entry['id']}.json").read_bytes() == before


def test_groom_stamp_needs_a_named_groomer_and_a_real_date(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)
    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(groomed_by=""))
    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(groomed_at="5 Aug"))


def test_validate_catches_a_groom_claim_written_straight_into_the_file(tmp_path):
    """The store is a directory of JSON; a hand-edit can bypass update()."""
    store = tmp_path / "backlog"
    entry = _add(store)
    path = store / f"{entry['id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["groomed_by"] = "me, honest"
    payload["groomed_at"] = "2026-08-05"
    path.write_text(json.dumps(payload), encoding="utf-8")

    kinds = {p["kind"] for p in BACKLOG.validate_store(store)}
    assert "groom-claim-without-plan" in kinds


def test_list_ungroomed_is_the_queue_of_entries_nobody_has_worked_out(tmp_path):
    store = tmp_path / "backlog"
    raw = _add(store, detail="filed in a hurry")
    done = _add(store, detail="worked out end to end")
    BACKLOG.update_entry(store, done["id"], **_groom_kwargs())

    ungroomed = [e["id"] for e in BACKLOG.list_entries(store, ungroomed=True)]
    assert ungroomed == [raw["id"]]

    groomed = [e["id"] for e in BACKLOG.list_entries(store, groomed=True)]
    assert groomed == [done["id"]]


def test_ungroomed_filter_composes_with_the_others(tmp_path):
    store = tmp_path / "backlog"
    _add(store, detail="low one", severity="low")
    wanted = _add(store, detail="high one", severity="high")
    hits = BACKLOG.list_entries(store, ungroomed=True, severity="high")
    assert [e["id"] for e in hits] == [wanted["id"]]


# Every flag on `update` must actually reach the field it names. A flag whose
# dest is filtered out by the collection whitelist is accepted and then
# discarded: `--detail X --status Y --commit` exits 0 having dropped X.
#
# This carried two exemptions for the two known holes (IMP-20260805-1be2c6),
# on the theory that deleting an exemption is how the fix proves itself. Both
# are now deleted: `--detail` is a declared refusal rather than an unwired
# flag, and surface/repro/build/duplicate_of have flags. What is left is the
# contract with no escape hatch — the right-hand sides are read from the module
# rather than restated, so a new exemption cannot be smuggled in as a literal.
_UPDATE_PLUMBING = {"id", "store", "commit", "json", "help"}


def test_every_update_flag_reaches_a_field_and_every_field_has_a_flag():
    sub = BACKLOG.build_parser()._subparsers._group_actions[0].choices["update"]
    dests = {a.dest for a in sub._actions} - _UPDATE_PLUMBING
    mutable = set(BACKLOG.MUTABLE_FIELDS)

    assert dests - mutable == set(BACKLOG.REFUSED_UPDATE_FIELDS), (
        "a flag on `update` neither writes a mutable field nor is refused by name"
    )
    assert mutable - dests == set(), "a mutable field has no way in"


def test_import_carries_forward_every_field_the_legacy_table_does_not_own(tmp_path):
    """A re-import must not erase work done through `update`.

    The table owns eight columns; anything else on disk is there because a
    maintainer put it there. This was fixed once for surface/repro/build and
    then reintroduced for the groom fields — carrying a hand-listed set of
    field names is the shape of the bug, so the contract is stated as
    "everything the table does not own" rather than as another list.
    """
    store = tmp_path / "backlog"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], verdict="PARTIAL", **_groom_kwargs())

    rendered = BACKLOG.render_view(store, verified_against="deadbeef")
    BACKLOG.import_legacy(rendered, store)

    loaded = BACKLOG.load_entry(store, entry["id"])
    for field in BACKLOG.GROOM_FIELDS + ("verdict",):
        assert loaded.get(field), f"{field} was erased by a re-import"

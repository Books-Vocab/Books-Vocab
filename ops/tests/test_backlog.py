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
import subprocess
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


@pytest.fixture(autouse=True)
def _fake_object_database(monkeypatch):
    """Every well-formed sha exists; nothing else does.

    Most tests in this file predate `fixed_by` and only touch `status` in
    passing, but `update` now resolves shas for real. Pointing them at the host
    repo's actual history would make their verdict a property of this machine.
    A test that needs orphan / unresolvable behaviour injects `commit_state`
    into `validate_entry` directly, and one test below drives the REAL resolver
    so this stub cannot hide a broken one.
    """
    monkeypatch.setattr(
        BACKLOG, "make_commit_state",
        lambda: lambda sha: "ok" if BACKLOG._SHA_RE.match(sha) else "unknown",
    )


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

    BACKLOG.update_entry(store, entry["id"], status="fixed", resolution="`abc1234`",
                         fixed_by=["abc1234"])

    loaded = BACKLOG.load_entry(store, entry["id"])
    assert loaded["status"] == "fixed"
    assert loaded["resolution"] == "`abc1234`"


def test_update_does_not_change_the_id(tmp_path):
    """The id digest covers only the fields that identify WHICH problem this is.
    If triaging an entry moved its id, every cross-reference to it would rot and
    the store would accumulate a fresh file per status change."""
    store = tmp_path / "backlog"
    entry = _add(store, status="open")

    BACKLOG.update_entry(store, entry["id"], status="in-progress",
                         plan="claiming a status that says someone looked owes a next action")

    assert BACKLOG.load_entry(store, entry["id"])["id"] == entry["id"]
    assert len(list(store.glob("*.json"))) == 1


def test_update_leaves_untouched_fields_alone(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, detail="the original finding", severity="high")

    BACKLOG.update_entry(store, entry["id"], status="triaged",
                         plan="claiming a status that says someone looked owes a next action")

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
        BACKLOG.update_entry(store, "IMP-0404", status="fixed", fixed_by=["abc1234"])


def test_update_can_set_verdict_fields(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store)

    # The date rides along: a verdict with no date can never go stale, so
    # validate refuses the pair being split.
    BACKLOG.update_entry(store, entry["id"], verdict="CONFIRMED-OPEN", cost="M",
                         verified_at="2026-08-07")

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
    BACKLOG.update_entry(store, entry["id"], verdict="PARTIAL", verified_at="2026-08-07",
                         verified_by="agent:test", **_groom_kwargs())

    rendered = BACKLOG.render_view(store, verified_against="deadbeef")
    BACKLOG.import_legacy(rendered, store)

    loaded = BACKLOG.load_entry(store, entry["id"])
    # The verification stamp is in this set for the same reason the groom fields
    # are: the table does not own it, so a re-import that drops it is erasing
    # work. Adding fields to the module and not to this assertion is how the
    # original bug came back the second time.
    for field in BACKLOG.GROOM_FIELDS + ("verdict", "verified_at", "verified_by"):
        assert loaded.get(field), f"{field} was erased by a re-import"


# --------------------------------------------------------------------------
# 9. render: the view is an output, but it is not a blank slate
#
# The measured incident (IMP-20260806-e06150): a branch forked before the
# store migration carried IMP-0060/0061/0062 as table rows only. The file
# conflicted on rebase, the conflict was "resolved" by regenerating the view,
# and all three entries were deleted — rc=0, stderr empty, byte count of the
# same order, docs_lint 0 ERROR, cutover gate green. `_cmd_render` never read
# its own --out, so "the store is the SoT" silently meant "anything the store
# has not heard of does not exist".
# --------------------------------------------------------------------------

_VIEW_ONLY_IMP_ROW = (
    "| IMP-0060 | 2026-06-01 | pre-migration branch | tool | high | open "
    "| only ever existed as a table row | — |\n"
)
_VIEW_ONLY_APP_ROW = (
    "| APP-20260601-aaaaaa | 2026-06-01 | pre-migration branch | reader | ux | high "
    "| open | only ever existed as a table row | — | — | — |\n"
)
# Not a duplicate of the two above: this id IS in the store. What it is missing
# from is the text render is about to write. See the diff-base test below.
_UNRENDERED_IMP_ROW = (
    "| IMP-0099 | 2026-06-01 | a newer tool sharing this store | tool | high | open "
    "| in the store, in the view, and not in what render emits | — |\n"
)


def _render_argv(store: Path, out: Path, *extra: str) -> list[str]:
    # --verified-against is pinned so the command never shells out to git for
    # the doc anchor; the anchor is not what these tests are about.
    return [
        "render", "--store", str(store), "--out", str(out),
        "--verified-against", "deadbeef", *extra,
    ]


@pytest.mark.parametrize(
    "row,lost_id",
    [
        (_VIEW_ONLY_IMP_ROW, "IMP-0060"),
        # Not a duplicate of the IMP case: `parse_legacy_table` skips every
        # APP- row by design (it returns 129 rows for the real ledger's 138
        # entries), so a guard built on the parser that is already in this file
        # passes the IMP case and is blind to the entire APP stream.
        (_VIEW_ONLY_APP_ROW, "APP-20260601-aaaaaa"),
    ],
)
def test_render_refuses_to_delete_an_entry_that_only_exists_in_the_outgoing_view(
    tmp_path, capsys, row, lost_id
):
    store = tmp_path / "backlog"
    _add(store, detail="an entry that does live in the store")
    out = tmp_path / "improvement_backlog.md"

    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    capsys.readouterr()

    out.write_text(out.read_text(encoding="utf-8") + row, encoding="utf-8")
    before = out.read_bytes()

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    err = capsys.readouterr().err

    # Byte equality, not `lost_id in out.read_text()`: what has to be proven is
    # that NOTHING was written, not that one substring happened to survive.
    assert out.read_bytes() == before, f"{lost_id} was silently deleted from the view"
    assert rc == 2, f"render exited {rc} after refusing to drop {lost_id}"
    assert lost_id in err, f"the refusal does not name the lost entry: {err!r}"


def test_render_refusal_names_what_disappears_and_only_that(tmp_path, capsys):
    """Row counts are not the check; id SETS are.

    In the incident the row count stayed plausible. Here the outgoing view and
    the new text have the SAME number of rows — one entry left, one arrived —
    so a length comparison, or a `!=` on the text, cannot tell the two apart.
    """
    store = tmp_path / "backlog"
    survivor = _add(store, detail="present in both")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW, encoding="utf-8")
    capsys.readouterr()

    arrival = _add(store, detail="filed after that view was rendered")

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    err = capsys.readouterr().err

    assert rc == 2
    assert "IMP-0060" in err
    # The discriminating half: an id that is arriving is not an id that is
    # leaving. A message that lists every id it saw would satisfy the assertion
    # above while proving nothing about the comparison.
    assert arrival["id"] not in err, f"the refusal blames an incoming entry: {err!r}"
    assert survivor["id"] not in err, f"the refusal blames a surviving entry: {err!r}"


def test_render_writes_when_the_same_entries_come_out_different(tmp_path, capsys):
    """A view that changes without losing an id is the normal case.

    This is what separates an id-set guard from `old_text != new_text`: the
    file must still be regenerated after `update` edits a row in place.
    """
    store = tmp_path / "backlog"
    entry = _add(store, detail="before the update", status="open")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    before = out.read_bytes()

    BACKLOG.update_entry(store, entry["id"], status="fixed", resolution="abc1234",
                         fixed_by=["abc1234"])
    capsys.readouterr()

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    err = capsys.readouterr().err

    assert rc == 0, f"render refused a view that loses nothing: {err!r}"
    assert out.read_bytes() != before, "render did not regenerate the view"
    assert "fixed" in out.read_text(encoding="utf-8")
    assert err == "", f"render complained about a lossless rewrite: {err!r}"


def test_render_writes_when_the_store_has_grown(tmp_path, capsys):
    store = tmp_path / "backlog"
    _add(store, detail="the first one")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    _add(store, detail="the second one")
    capsys.readouterr()

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    assert rc == 0, f"render refused a superset: {capsys.readouterr().err!r}"


def test_render_writes_when_there_is_no_outgoing_view_to_lose(tmp_path, capsys):
    store = tmp_path / "backlog"
    _add(store, detail="bootstrapping a fresh view")
    out = tmp_path / "nested" / "improvement_backlog.md"
    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    assert rc == 0, f"render refused to create a view: {capsys.readouterr().err!r}"
    assert out.exists()


def test_allow_drop_authorises_only_the_ids_it_names(tmp_path, capsys):
    """The escape hatch has to exist — the store has no `delete`, so removing
    an entry means `rm`-ing its file, and without a hatch every later render
    would be refused forever.

    It is a named list rather than a bare `--allow-drop` on purpose: the whole
    entry is about a deletion nobody had to state out loud, and a blanket
    bypass flag is the same silence one flag later. Naming the ids costs a
    copy-paste from the refusal message, which is exactly the reading the
    incident skipped.
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    out.write_text(
        out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW + _VIEW_ONLY_APP_ROW,
        encoding="utf-8",
    )
    before = out.read_bytes()
    capsys.readouterr()

    # Authorising one of the two is not authorising both.
    rc = BACKLOG.main(_render_argv(store, out, "--commit", "--allow-drop", "IMP-0060"))
    err = capsys.readouterr().err
    assert rc == 2, "a partial authorisation let an unnamed entry through"
    assert out.read_bytes() == before
    assert "APP-20260601-aaaaaa" in err
    # Scoped to the REFUSED header, not the whole stream. At whole-stderr
    # granularity this assertion forbids the authorised id from appearing in
    # the remedy line too — i.e. it pins the remedy to printing a flag that
    # drops the authorisation you just gave (the loop measured in D1 of the
    # review of IMP-20260806-e06150). What has to be true is narrower: the
    # sentence that says what is REFUSED must not blame an authorised id.
    header = err.splitlines()[0]
    assert "IMP-0060" not in header, f"an authorised id is still being refused: {header!r}"

    rc = BACKLOG.main(
        _render_argv(
            store, out, "--commit", "--allow-drop", "IMP-0060", "APP-20260601-aaaaaa"
        )
    )
    err = capsys.readouterr().err
    assert rc == 0, f"the escape hatch did not open: {err!r}"
    assert "IMP-0060" not in out.read_text(encoding="utf-8"), "the drop was not applied"
    # Authorised is not the same as unremarked: the defect being fixed is
    # silence, so the taken path still says what it took.
    assert "IMP-0060" in err and "APP-20260601-aaaaaa" in err, (
        f"--allow-drop deleted entries without naming them: {err!r}"
    )


def _remedy_flag_ids(err: str) -> list[str]:
    """The ids the refusal's own remedy line tells you to pass to --allow-drop.

    Read out of the message rather than reconstructed from the test's own
    knowledge: the thing under test is what the operator is TOLD to type, so
    building the flag from the ids the test happens to know would test nothing.
    """
    marker = "--allow-drop "
    for line in err.splitlines():
        if marker in line:
            return line.split(marker, 1)[1].split()
    raise AssertionError(f"the refusal printed no --allow-drop remedy at all: {err!r}")


def test_following_the_remedy_line_converges_instead_of_ping_ponging(tmp_path, capsys):
    """`--allow-drop`'s help says the ids are named on stderr, copy them here.
    So the remedy line has to print the COMPLETE flag, not the remainder.

    Printing only the not-yet-authorised ids makes the documented workflow a
    closed loop: authorise A, get told to authorise B, do that, and B's run has
    dropped A's authorisation, so it tells you to authorise A again. Measured on
    the shipped code as a 3-step cycle. This drives the loop instead of matching
    a string: it types what it was told to type and asserts the second attempt
    lands.
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    out.write_text(
        out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW + _VIEW_ONLY_APP_ROW,
        encoding="utf-8",
    )
    before = out.read_bytes()
    capsys.readouterr()

    # Step 1: the operator authorises one of the two, as an operator reading a
    # refusal that names one id would.
    assert BACKLOG.main(_render_argv(store, out, "--commit", "--allow-drop", "IMP-0060")) == 2
    told_to_type = _remedy_flag_ids(capsys.readouterr().err)
    assert out.read_bytes() == before

    # Step 2: type exactly that. One step, not a cycle.
    rc = BACKLOG.main(_render_argv(store, out, "--commit", "--allow-drop", *told_to_type))
    err = capsys.readouterr().err

    assert rc == 0, (
        f"the remedy line said `--allow-drop {' '.join(told_to_type)}` and following it "
        f"was refused again — the advice does not converge: {err!r}"
    )
    # The artifact, not the exit code: both rows really left.
    written = out.read_text(encoding="utf-8")
    assert "IMP-0060" not in written and "APP-20260601-aaaaaa" not in written


def test_the_refusal_does_not_offer_a_recovery_that_cannot_work(tmp_path, capsys):
    """A refusal that hands out a broken recovery command is the same defect
    one layer down: `import` reads the legacy IMP table and skips every APP
    row, so "recover it with `import`" would have the operator run a command
    that exits 0 and brings nothing back.
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_APP_ROW, encoding="utf-8")
    capsys.readouterr()

    # Measured here rather than assumed from the docstring of the parser: the
    # advice is only wrong if `import` really cannot bring this row back.
    BACKLOG.import_legacy(out.read_text(encoding="utf-8"), store)
    with pytest.raises(KeyError):
        BACKLOG.load_entry(store, "APP-20260601-aaaaaa")

    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 2
    err = capsys.readouterr().err
    # `backlog.py import`, not the bare word "import": the message is allowed
    # to say WHY the importer cannot do it, and matching "importer" would have
    # this assertion fail on the sentence that makes it true.
    assert "backlog.py import" not in err, f"the refusal offers `import` for an APP row: {err!r}"
    assert "ops/backlog.py add" in err, f"the refusal offers no way back at all: {err!r}"

    # The other half of the routing: an IMP row IS importable, so the same
    # message must offer it. Without this, deleting the IMP branch entirely
    # would still pass.
    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW, encoding="utf-8")
    capsys.readouterr()
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 2
    err = capsys.readouterr().err
    assert f"backlog.py import --from {out} --commit" in err, (
        f"the refusal does not offer the recovery that does work: {err!r}"
    )


def test_render_dry_run_warns_without_failing(tmp_path, capsys):
    """Dry-run cannot lose anything — it writes nothing — so it reports and
    exits 0, keeping `render` usable as a generator whose stdout can be diffed
    against the file on disk (that comparison is IMP-20260805-462d28's job).
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW, encoding="utf-8")
    before = out.read_bytes()
    capsys.readouterr()

    rc = BACKLOG.main(_render_argv(store, out))
    captured = capsys.readouterr()

    assert rc == 0
    assert out.read_bytes() == before, "a dry-run wrote to --out"
    assert "IMP-0060" in captured.err, "dry-run hid the divergence it can see"
    assert captured.out.startswith("<!-- doc-meta"), "dry-run stopped emitting the view"


def test_render_json_reports_that_it_wrote_nothing(tmp_path, capsys):
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit", "--json")) == 0
    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW, encoding="utf-8")
    capsys.readouterr()

    rc = BACKLOG.main(_render_argv(store, out, "--commit", "--json"))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["written"] is False
    # `dropped` is what this run DELETED, and a refusal deleted nothing.
    # Carrying the at-risk ids under that key made the payload contradict
    # itself: `written:false` next to `dropped:["IMP-0060"]` reads as a
    # deletion that happened.
    assert payload["dropped"] == [], "a refusal reported a deletion it did not perform"
    assert payload["refused"] == ["IMP-0060"], "the refusal payload does not say what stopped it"
    assert "bytes" not in payload, "a refusal reported a size for a file it did not write"


def test_the_json_refusal_hands_back_the_whole_flag_not_the_remainder(tmp_path, capsys):
    """The machine channel needs the same complete `--allow-drop` set the stderr
    remedy line prints; otherwise a machine caller authorising one id at a time
    walks the same cycle as a human (see the remedy-line test above).

    `refused` and `would_drop` are therefore different questions: what blocked
    this run, and the full set a write would delete.
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit", "--json")) == 0
    out.write_text(
        out.read_text(encoding="utf-8") + _VIEW_ONLY_IMP_ROW + _VIEW_ONLY_APP_ROW,
        encoding="utf-8",
    )
    capsys.readouterr()

    rc = BACKLOG.main(
        _render_argv(store, out, "--commit", "--json", "--allow-drop", "IMP-0060")
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert payload["refused"] == ["APP-20260601-aaaaaa"]
    assert payload["would_drop"] == ["APP-20260601-aaaaaa", "IMP-0060"], (
        "the JSON refusal reports only the remainder, so authorising from it cannot converge"
    )

    # Drive it: the set the payload handed back is the set that works.
    rc = BACKLOG.main(
        _render_argv(store, out, "--commit", "--json", "--allow-drop", *payload["would_drop"])
    )
    assert rc == 0, "following the JSON payload's own would_drop was refused again"


def test_json_records_the_deletion_it_was_authorised_to_perform(tmp_path, capsys):
    """An authorised deletion must not be invisible in the machine channel.

    The contract is one machine-readable JSON object on stdout with progress on
    stderr, so a caller that reads only stdout is a supported caller. Emitting a
    payload shape-identical to a clean render after permanently deleting rows
    re-creates the exact defect IMP-20260806-e06150 is about — silence — in the
    channel designated as authoritative.
    """
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit", "--json")) == 0
    clean = json.loads(capsys.readouterr().out)

    out.write_text(out.read_text(encoding="utf-8") + _VIEW_ONLY_APP_ROW, encoding="utf-8")
    capsys.readouterr()

    rc = BACKLOG.main(
        _render_argv(store, out, "--commit", "--json", "--allow-drop", "APP-20260601-aaaaaa")
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    # The premise, measured: the deletion really happened, so there is
    # something for the payload to be silent about.
    assert "APP-20260601-aaaaaa" not in out.read_text(encoding="utf-8")

    assert payload["dropped"] == ["APP-20260601-aaaaaa"], (
        "a permanent deletion left no record in the machine-authoritative channel"
    )
    assert clean["dropped"] == [], "a clean render claimed to have deleted something"
    # The distinguishing half: a key that only appears when it has news is the
    # same silence one level down — a reader with no reason to look for it
    # never learns it exists. The two write payloads must be the same shape and
    # differ in the VALUE.
    assert set(clean) == set(payload), (
        f"the deleting render and the clean render are not the same shape: "
        f"{sorted(set(clean) ^ set(payload))}"
    )


def test_render_names_an_unreadable_out_instead_of_a_traceback(tmp_path, capsys):
    """The guard reads --out, so --out can now fail to be read. A caller who
    pointed --out at something that is not a view gets a named error, not a
    UnicodeDecodeError escaping through main()."""
    store = tmp_path / "backlog"
    _add(store, detail="stays in the store")
    out = tmp_path / "not-a-view.bin"
    out.write_bytes(b"\xff\xfe\x00\x01")

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    err = capsys.readouterr().err

    assert rc == 64, "an unreadable --out is a usage error, not a data-loss refusal"
    assert str(out) in err
    assert out.read_bytes() == b"\xff\xfe\x00\x01", "render wrote over a file it could not read"


def test_the_guard_diffs_against_the_text_it_will_write_not_the_store(tmp_path, capsys):
    """The one load-bearing choice in the guard, made falsifiable.

    `dropped` is `view_entry_ids(outgoing) - view_entry_ids(text)`. The obvious
    alternative is `... - {e["id"] for e in list_entries(store)}`, and on today's
    ledger the two sets agree, so the wrong one looks right. They come apart
    wherever `render_view` declines to emit something the store holds: it asks
    for `stream="IMP"` and `stream="APP"` only, while an unfiltered
    `list_entries` returns everything on disk.

    Such an entry — here, one filed under a stream this version does not render,
    which is what a store shared with a newer tool looks like from here — is in
    the store and NOT in the outgoing text. Diffed against the store it is not
    at risk and the row is deleted with rc=0 and an empty stderr: the original
    incident exactly. Diffed against the text, the row is what has to survive.

    Stated rather than hidden: `validate` calls this store unhealthy, and that
    is the point rather than a flaw in the setup. On a store every entry of
    which renders, the two diff bases agree — which is exactly why the wrong
    one looks right. A guard against data loss earns its keep in the states the
    happy path does not produce, so it has to hold while the store is in one.
    """
    store = tmp_path / "backlog"
    _add(store, detail="an entry both diff bases agree about")
    out = tmp_path / "improvement_backlog.md"
    assert BACKLOG.main(_render_argv(store, out, "--commit")) == 0
    capsys.readouterr()

    BACKLOG.entry_path(store, "IMP-0099").write_text(
        json.dumps(
            {
                "id": "IMP-0099",
                "stream": "OPS",  # not in STREAMS, so render_view never asks for it
                "date": "2026-06-01",
                "source": "a newer tool sharing this store",
                "category": "cli",
                "severity": "high",
                "status": "open",
                "detail": "in the store, in the view, and not in what render emits",
                "resolution": "",
            }
        ),
        encoding="utf-8",
    )
    out.write_text(out.read_text(encoding="utf-8") + _UNRENDERED_IMP_ROW, encoding="utf-8")
    before = out.read_bytes()

    # The premise, measured rather than asserted from this docstring: the two
    # candidate diff bases really do disagree about IMP-0099. Without this the
    # test could pass on a store where they agree and prove nothing.
    assert "IMP-0099" in {entry["id"] for entry in BACKLOG.list_entries(store)}
    assert "IMP-0099" not in BACKLOG.view_entry_ids(
        BACKLOG.render_view(store, verified_against="deadbeef")
    ), "render_view emits this stream after all; pick another entry render will not emit"
    # And the honesty check on the paragraph above: this store IS one `validate`
    # rejects. Measured here so nobody has to take the docstring's word for it.
    assert [p for p in BACKLOG.validate_store(store) if p.get("kind") == "bad-stream"]

    rc = BACKLOG.main(_render_argv(store, out, "--commit"))
    err = capsys.readouterr().err

    assert out.read_bytes() == before, "IMP-0099 was silently deleted from the view"
    assert rc == 2, f"render exited {rc} on a row only the outgoing text protects"
    assert "IMP-0099" in err, f"the refusal does not name the row it saved: {err!r}"


def test_view_entry_ids_sees_both_streams(tmp_path):
    """The helper the guard is built on, asserted directly.

    `parse_legacy_table` is the tempting reuse and it is the wrong one: it
    returns rows for IMP only. Rendering a store with one entry of each stream
    and asking the two functions the same question makes that divergence a
    test rather than a comment.
    """
    store = tmp_path / "backlog"
    imp = _add(store, stream="IMP", detail="a tool problem")
    app = _add(store, stream="APP", detail="a reader problem", surface="reader")
    text = BACKLOG.render_view(store, verified_against="deadbeef")

    assert BACKLOG.view_entry_ids(text) == {imp["id"], app["id"]}

    # `parse_legacy_table` now reads NOTHING out of the current view: the view
    # renders more columns than the legacy table it parses (IMP-20260805-355016).
    # That answers this test's original question — view_entry_ids does not merely
    # still need to exist separately, it is now the ONLY reader of the view, which
    # is why the render drop-guard was built on it rather than on the parser.
    rows, _ = BACKLOG.parse_legacy_table(text)
    assert rows == [], (
        "parse_legacy_table can read the current view again; if that is intended, "
        "re-check the drop-guard, which assumes view_entry_ids is the only reader"
    )


# ---------------------------------------------------------------------------
# IMP-20260805-355016 — the view carries the re-verification fields
# ---------------------------------------------------------------------------
def test_view_shows_the_reverification_fields(tmp_path):
    """The four first-class fields the ruling names were invisible in the table.

    They were withheld for one reason, stated in render_view's own comment: keep
    the view importable. The executive ruling of 2026-08-05 abandoned that
    property outright ("表格需要加欄就加"), on the grounds that it was already
    half-broken — the APP half of the render has never been importable
    (IMP-20260805-f4ec99, measured rc=2) — and that the importer only ever reads
    files this module itself produced.

    `plan`/`acceptance` deliberately stay OUT: the largest plan in the real store
    is 57KB, and a table cell is not where that belongs. The groom counter in the
    footer already answers "how many have a plan".
    """
    store = tmp_path / "s"
    store.mkdir()
    BACKLOG.add_entry(
        store, stream="IMP", date="2026-01-01", source="probe", category="tool",
        severity="med", detail="a probe entry", status="open",
    )
    eid = next(iter(BACKLOG.list_entries(store)))["id"]
    BACKLOG.update_entry(store, eid, verdict="CONFIRMED-OPEN",
                         verified_at="2026-01-02", cost="M",
                         fix_site="ops/backlog.py:1")
    view = BACKLOG.render_view(store, verified_against="deadbeef")

    # Assert against the rendered TABLE, never `field in view`: _VIEW_HEADER already
    # prints all four field names as schema prose, and interpolates the VERDICTS
    # vocabulary — so `"verdict" in view` and `"CONFIRMED-OPEN" in view` are both
    # satisfied by the module's own explanatory text with the table empty. Measured:
    # dropping `verdict` or `cost` from VIEW_IMP_COLUMNS left the whole suite green.
    header = next(line for line in view.splitlines()
                  if line.startswith("| id ") and "detail" in line)
    for field in BACKLOG.VIEW_IMP_COLUMNS:
        assert f"| {field} " in header, (
            f"{field} is not a column of the rendered table (header: {header})")
    assert "plan" not in header and "acceptance" not in header, (
        f"plan/acceptance must stay out of the table: {header}")

    row = next(line for line in view.splitlines() if line.startswith(f"| {eid} "))
    cells = [c.strip() for c in BACKLOG._split_row_raw(row)]
    by_col = dict(zip(BACKLOG.VIEW_IMP_COLUMNS, cells))
    assert by_col["verdict"] == "CONFIRMED-OPEN", by_col
    assert by_col["verified_at"] == "2026-01-02", by_col
    assert by_col["cost"] == "M", by_col
    assert by_col["fix_site"] == "ops/backlog.py:1", by_col


def test_import_requires_an_explicit_from():
    """`--from` became required with IMP-20260805-3df783.

    It used to default to the generated view. After the widening that default can
    only fail, and failing on a default nobody typed is the kind of red that gets
    read as "the tool is broken" rather than "you pointed it at the wrong file".
    Untested until now: restoring `default=DEFAULT_VIEW` left the suite green.
    """
    parser = BACKLOG.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "--commit"])
    args = parser.parse_args(["import", "--from", "x.md"])
    assert str(args.source_doc) == "x.md"   # argparse type=Path, not str


def test_import_refuses_the_widened_view_instead_of_recovering_it(tmp_path):
    """Widening the view gave `_recover_overflowing_row` an input it must not touch.

    Measured before this guard: parsing a rendered 12-column view produced ONE row
    with kind `recovered-row` — `detail` had swallowed resolution/verdict/
    verified_at/cost, and `resolution` had become the fix_site. A `problems` entry
    was emitted, but `import_legacy` still had a row to write, so a re-import would
    have overwritten good entries with mangled prose.

    Recovery existed to rescue hand-written tables containing an unescaped pipe.
    After the 2026-08-05 rulings the importer's only input is this module's own
    machine-escaped output, so that input surface is gone (IMP-20260805-3df783),
    and the same heuristic now actively corrupts the one file it will ever see.
    A refusal that names the file is the only safe answer: too many columns is not
    a row to be repaired, it is a file from the wrong era.
    """
    store = tmp_path / "s"
    store.mkdir()
    BACKLOG.add_entry(store, stream="IMP", date="2026-01-01", source="probe",
                      category="tool", severity="med",
                      detail="detail with | a pipe", status="open")
    eid = next(iter(BACKLOG.list_entries(store)))["id"]
    BACKLOG.update_entry(store, eid, verdict="CONFIRMED-OPEN",
                         verified_at="2026-01-02", cost="M",
                         fix_site="ops/backlog.py:1")
    view = BACKLOG.render_view(store, verified_against="deadbeef")

    rows, problems = BACKLOG.parse_legacy_table(view)
    assert rows == [], f"a widened-view row was parsed anyway: {rows}"
    kinds = {p.get("kind") for p in problems}
    assert "recovered-row" not in kinds, "the widened view was 'recovered' into a mangled row"
    assert kinds, "the row vanished with no problem reported — silence is the defect"


def test_schema_section_blames_rebase_not_squash():
    """The doctrine this pins was wrong for a month and cost two entries their audit trail.

    It named PR squash-merge as what invalidates a resolution hash. This repo has
    no PR merge path; what rewrites sha is the `git rebase` that `cmd_cutover`
    runs before its `merge --ff-only`. IMP-0063 and IMP-20260805-dd35f8 both sat
    waiting for a squash that could never arrive, and both branches are now gone.

    Prose corrections rot back. Every site the correction touched is asserted
    here so re-introducing the old mechanism name goes red.
    """
    header = BACKLOG._VIEW_HEADER
    assert "squash" not in header
    assert "rebase" in header

    view = (ROOT / "docs" / "runbook" / "improvement_backlog.md").read_text(encoding="utf-8")
    # Header段 only: entry rows quote the old doctrine verbatim as evidence and
    # must not be caught by this.
    assert "squash" not in view.split("## IMP")[0]

    sync = (ROOT / "docs" / "sop" / "doc_sync.md").read_text(encoding="utf-8")
    invariant = [ln for ln in sync.splitlines() if "SHA 不被改寫" in ln]
    assert len(invariant) == 1
    assert "rebase" in invariant[0]
    assert "PR branch" not in sync

    steward = (ROOT / ".claude" / "agents" / "docs-steward.md").read_text(encoding="utf-8")
    desc = [ln for ln in steward.splitlines() if "KG 文檔管家" in ln]
    assert len(desc) == 1
    assert "PR 開出前" not in desc[0]
    assert "cutover" in desc[0]

    # Two always-on surfaces carried the same instruction and were missed by the
    # first pass: CLAUDE.md is loaded every session, tech_index.md is a SoT.
    # A grep boundary that skipped docs/reference/ is why. Pin both.
    root_guide = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "開 PR" not in root_guide
    assert "PR 開出前" not in root_guide

    tech_index = (ROOT / "docs" / "reference" / "tech_index.md").read_text(encoding="utf-8")
    assert "PR 開出前" not in tech_index


# --------------------------------------------------------------------------
# traceability: fixed_by (IMP-20260805-9a51e9)
# --------------------------------------------------------------------------
#
# `resolution` is prose, and prose can only be checked by position heuristics.
# Measured on the real store: position-0 sha was right for 49 of 63 fixed
# entries and wrong for 14, and one of the 49 (IMP-0063) was an *incidental*
# hash — a commit the resolution mentions for an unrelated reason. A heuristic
# that reads "the fix is the first sha in the paragraph" cannot tell those apart,
# so the answer moves into a field that only ever holds landing commits.
#
# The reference is "reachable from HEAD **or** main", not one of them:
#   * HEAD alone accepts a branch-local sha, which is correct at gate time —
#     the fix has not been cut over yet — but says nothing once it lands.
#   * main alone rejects that same legitimate sha on every single cutover, and a
#     gate that reds on the normal path is a gate that gets muted.
# Reachable from neither means the rebase inside cutover rewrote it. That is a
# real defect with a mechanical repair (`reanchor`), so it is an ERROR that names
# the repair, not a warning nobody acts on.

def _payload(**overrides):
    """A validate-ready entry dict, without touching a store.

    These rules are pure functions of one entry, so the tests are too: going
    through `add_entry` would drag in the filesystem and the creation-path
    exemption, and then the thing under test would not be the thing asserted.
    """
    base = _entry_kwargs(**overrides)
    return dict(base, id="IMP-20260807-000001", schema="kg.backlog.entry.v1")


def _traced(state_by_sha):
    """A commit_state seam so these stay stdlib-only and repo-independent."""
    return lambda sha: state_by_sha.get(sha, "unknown")


def test_fixed_entry_without_fixed_by_is_a_problem():
    entry = _payload(status="fixed", resolution="修好了")
    problems = BACKLOG.validate_entry(entry, commit_state=_traced({}))
    assert "fixed-without-fixed-by" in {p["kind"] for p in problems}


def test_fixed_by_reachable_from_head_or_main_is_clean():
    entry = _payload(status="fixed")
    entry["fixed_by"] = ["aaaaaaa", "bbbbbbb"]
    problems = BACKLOG.validate_entry(
        entry, commit_state=_traced({"aaaaaaa": "ok", "bbbbbbb": "ok"})
    )
    assert problems == [], problems


def test_fixed_by_orphaned_and_unresolvable_are_distinct_problems():
    entry = _payload(status="fixed")
    entry["fixed_by"] = ["0ffffff", "badbadb"]
    problems = BACKLOG.validate_entry(
        entry, commit_state=_traced({"0ffffff": "orphan", "badbadb": "unknown"})
    )
    kinds = {p["kind"] for p in problems}
    # Two different causes with two different repairs: an orphan has a
    # mechanical fix (find the patch-id-equal commit), a fabricated hash does
    # not. Collapsing them into one "bad sha" would send the reader of the
    # second one hunting for a rebase that never happened. IMP-0005 carried
    # `813356b1`, a hash that exists in no object database at all.
    assert "fixed-by-orphaned" in kinds
    assert "fixed-by-unresolvable" in kinds


def test_unfinished_entry_must_not_carry_fixed_by():
    for status in ("open", "triaged", "in-progress"):
        entry = _payload(status=status, plan="x", acceptance="y")
        entry["fixed_by"] = ["aaaaaaa"]
        kinds = {p["kind"] for p in BACKLOG.validate_entry(
            entry, commit_state=_traced({"aaaaaaa": "ok"}))}
        assert "fixed-by-on-unfinished-entry" in kinds, status


def test_triaged_needs_a_next_action_but_open_does_not():
    """`open` means filed-not-yet-triaged, and that is an honest state.

    The first design required a next action on every unfinished entry. Measured
    against the real store that would have turned 40 entries red on the day it
    landed — the convention it assumed (26 of 27 unfinished entries carried a
    dash-prefixed next action) had decayed as filing volume grew. A gate that
    reds 40 entries at once gets muted, and forcing a next action onto an
    untriaged entry buys a fabricated plan, which is worse than an empty one.
    `triaged` and `in-progress` are different: both CLAIM someone looked.
    """
    bare = _payload(status="open", resolution="")
    assert BACKLOG.validate_entry(bare, commit_state=_traced({})) == []

    claimed = _payload(status="triaged", resolution="")
    kinds = {p["kind"] for p in BACKLOG.validate_entry(claimed, commit_state=_traced({}))}
    assert "no-next-action" in kinds

    with_plan = dict(claimed, plan="改 foo.py 的 bar()，把 X 換成 Y")
    assert BACKLOG.validate_entry(with_plan, commit_state=_traced({})) == []


def test_wont_fix_needs_a_reason_that_is_not_a_bare_sha():
    empty = _payload(status="wont-fix", resolution="")
    assert "wont-fix-without-reason" in {
        p["kind"] for p in BACKLOG.validate_entry(empty, commit_state=_traced({}))}

    sha_only = dict(empty, resolution="  9a8209a4c  ")
    assert "wont-fix-reason-is-a-sha" in {
        p["kind"] for p in BACKLOG.validate_entry(sha_only, commit_state=_traced({}))}

    real = dict(empty, resolution="正常行為,快取後即解;不修")
    assert BACKLOG.validate_entry(real, commit_state=_traced({})) == []


def test_verdict_outside_the_closed_vocabulary_is_a_problem():
    """VERDICTS was declared closed but only ever enforced in the extractor.

    Measured before this landed: `update <id> --verdict TOTALLY-BOGUS --commit`
    exited 0, the value landed in the file, and `validate` reported 0 problems.
    A vocabulary nothing checks is a comment.
    """
    entry = _payload()
    entry["verdict"] = "TOTALLY-BOGUS"
    assert "bad-verdict" in {p["kind"] for p in BACKLOG.validate_entry(entry)}

    for good in BACKLOG.VERDICTS:
        ok_entry = dict(entry, verdict=good)
        assert "bad-verdict" not in {p["kind"] for p in BACKLOG.validate_entry(ok_entry)}

    dup = dict(entry, verdict="DUPLICATE-OF-IMP-0007", duplicate_of="IMP-0007")
    assert "bad-verdict" not in {p["kind"] for p in BACKLOG.validate_entry(dup)}


def test_update_writes_fixed_by(tmp_path, monkeypatch):
    """`--fixed-by` reaches the file, and `update` refuses a sha it cannot reach.

    The resolver is stubbed rather than pointed at real commits: a test whose
    green depends on which shas exist in the host repo is a property of the
    host, not of this code — the same rule test_gate_can_fail.sh states for its
    own fixture.
    """
    store = tmp_path / "store"
    store.mkdir()
    entry = _add(store)
    monkeypatch.setattr(BACKLOG, "make_commit_state",
                        lambda: lambda sha: "ok" if sha == "deadbee" else "unknown")

    rc = BACKLOG.main([
        "update", entry["id"], "--store", str(store),
        "--status", "fixed", "--fixed-by", "deadbee", "--commit",
    ])
    assert rc == 0
    written = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert written["fixed_by"] == ["deadbee"]

    # A sha nobody can resolve is refused at write time, so the defect never
    # reaches the store for `validate` to find later and blame on nobody.
    assert BACKLOG.main([
        "update", entry["id"], "--store", str(store),
        "--fixed-by", "badbadb", "--commit",
    ]) == 64
    reread = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert reread["fixed_by"] == ["deadbee"], "a refused update wrote anyway"


def test_the_real_commit_resolver_answers_from_git(monkeypatch):
    """A positive control for make_commit_state, which every other test stubs.

    Without this, `_fake_object_database` above would keep the suite green even
    if the real resolver were wired to nothing — a guard whose silence proves
    nothing. Both directions are asserted against facts true of any git repo:
    HEAD resolves and is reachable from itself; an all-zero sha resolves nowhere.
    """
    monkeypatch.undo()  # drop the fake odb for this test only
    state = BACKLOG.make_commit_state()
    assert state is not None, "tests must run inside a git repo"
    assert state("HEAD") == "ok"
    assert state("0000000") == "unknown"


def _force_fixed_by(store, entry_id, shas):
    """Bypass `update` to plant a state `update` is built to refuse."""
    path = store / f"{entry_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(status="fixed", resolution="landed", fixed_by=shas)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _git_repo(path):
    """A throwaway repo carrying the exact shape reanchor exists for."""
    def g(*args, **kw):
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
             *args],
            cwd=path, capture_output=True, text=True, check=kw.get("check", True),
        )
    path.mkdir(parents=True, exist_ok=True)
    g("init", "-b", "main", "-q")
    (path / "base.txt").write_text("base\n")
    g("add", "base.txt"); g("commit", "-qm", "base")

    # The change, minted on a branch — this is the sha an entry would record.
    g("checkout", "-qb", "feat")
    (path / "fix.txt").write_text("the fix\n")
    g("add", "fix.txt"); g("commit", "-qm", "the fix")
    orphan = g("rev-parse", "HEAD").stdout.strip()

    # main moves, then the same change is replayed onto it — exactly what the
    # rebase inside cutover does. Different sha, identical patch-id.
    g("checkout", "-q", "main")
    (path / "other.txt").write_text("meanwhile\n")
    g("add", "other.txt"); g("commit", "-qm", "meanwhile")
    g("cherry-pick", "feat")
    landed = g("rev-parse", "HEAD").stdout.strip()
    g("branch", "-qD", "feat")  # now unreachable from main, still in the odb
    # One more commit on top, so `landed` is NOT main's tip. Without it a
    # --search-depth of 1 would still find the answer and the bounded-search
    # test would pass for the wrong reason.
    (path / "after.txt").write_text("after\n")
    g("add", "after.txt"); g("commit", "-qm", "after")
    return orphan, landed


def test_reanchor_moves_an_orphan_onto_its_patch_id_equal_commit(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real resolver, on a real repo
    repo = tmp_path / "repo"
    orphan, landed = _git_repo(repo)
    monkeypatch.chdir(repo)

    store = repo / "store"
    entry = _add(store, detail="reanchor fixture")
    # Written straight to disk on purpose: `update` REFUSES an orphaned sha, so
    # the broken state cannot be created through it. That is not a gap in the
    # fixture — it is how the state actually arises. The sha is valid when
    # written and the rebase orphans it afterwards, with nobody in the loop.
    _force_fixed_by(store, entry["id"], [orphan])
    assert BACKLOG.make_commit_state()(orphan) == "orphan", "fixture did not orphan the commit"

    dry = BACKLOG.reanchor_store(store)
    assert dry["plan"][0]["moves"] == {orphan: landed[:9]}
    # A dry run must not touch the store; the whole point of the primitive is
    # that a wrong mapping is a wrong audit trail.
    assert json.loads((store / f"{entry['id']}.json").read_text())["fixed_by"] == [orphan]

    assert BACKLOG.main(["reanchor", "--store", str(store), "--commit", "--json"]) == 0
    assert json.loads((store / f"{entry['id']}.json").read_text())["fixed_by"] == [landed[:9]]
    assert BACKLOG.validate_store(store) == []


def test_reanchor_refuses_to_guess_when_no_patch_id_matches(tmp_path, monkeypatch):
    """One real case (IMP-0062) had a patch-id that differed because the rebase
    resolved a conflict differently. A matcher that fell back to "closest" would
    have silently written a neighbouring commit into the audit trail."""
    monkeypatch.undo()
    repo = tmp_path / "repo"
    orphan, _landed = _git_repo(repo)
    monkeypatch.chdir(repo)

    store = repo / "store"
    entry = _add(store, detail="unmatchable fixture")
    _force_fixed_by(store, entry["id"], [orphan])

    # Window of 1 cannot reach the equivalent commit. The answer must be "not
    # found in the window I searched", never a guess.
    result = BACKLOG.reanchor_store(store, search_depth=1)
    item = result["plan"][0]
    assert item["moves"] == {}
    assert [u["sha"] for u in item["unmatched"]] == [orphan]
    assert result["searched"] == 1, "the bound must be reported, not silently applied"
    assert json.loads((store / f"{entry['id']}.json").read_text())["fixed_by"] == [orphan]


# --------------------------------------------------------------------------
# re-verification as a mechanism, not a ritual (IMP-20260805-2834b2)
# --------------------------------------------------------------------------
#
# A sweep on 2026-08-05 re-derived 25 entries from current code and rewrote 11
# of them — a measured 11/25 error rate in first-hand descriptions. It left no
# mechanism behind: no way to ask what has never been checked, no verifier
# identity, no evidence. One day later, 7 of 30 unfinished entries had never
# been verified; two days later the number is 99 of 159, and 42 of those are
# `fixed`. That last figure is the structural blind spot — a sweep aimed at
# unfinished entries can never see it, and closure is exactly when an audit
# trail starts to rot (the branch gets deleted, the sha gets rebased).

def test_list_unverified_includes_closed_entries(tmp_path):
    store = tmp_path / "s"
    _add(store, detail="never checked, still open")
    checked = _add(store, detail="checked once")
    closed = _add(store, detail="closed but never re-checked")
    BACKLOG.update_entry(store, checked["id"], verified_at="2026-08-01",
                         verdict="CONFIRMED-OPEN", verified_by="agent:sweep")
    BACKLOG.update_entry(store, closed["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="done")

    unverified = {e["id"] for e in BACKLOG.select_entries(store, unverified=True)}
    assert checked["id"] not in unverified
    # The whole point: a `fixed` entry with no verification record is IN the
    # queue. Filtering the queue to unfinished work reproduces the blind spot
    # this exists to close.
    assert closed["id"] in unverified


def test_list_stale_is_measured_from_verified_at(tmp_path):
    store = tmp_path / "s"
    old = _add(store, detail="verified long ago")
    fresh = _add(store, detail="verified recently")
    BACKLOG.update_entry(store, old["id"], verified_at="2026-01-01",
                         verdict="CONFIRMED-OPEN", verified_by="agent:sweep")
    BACKLOG.update_entry(store, fresh["id"], verified_at="2026-08-06",
                         verdict="CONFIRMED-OPEN", verified_by="agent:sweep")

    stale = {e["id"] for e in BACKLOG.select_entries(store, stale_days=30, today="2026-08-07")}
    assert stale == {old["id"]}
    # Never-verified entries are NOT stale — they are unverified. Merging the
    # two would let "run the staleness query" read as full coverage while 99
    # entries that were never looked at sit outside both answers.
    never = _add(store, detail="never verified")
    assert never["id"] not in {
        e["id"] for e in BACKLOG.select_entries(store, stale_days=30, today="2026-08-07")}


def test_verify_records_who_checked_and_with_what(tmp_path):
    store = tmp_path / "s"
    entry = _add(store, detail="needs re-derivation")

    rc = BACKLOG.main([
        "verify", entry["id"], "--store", str(store), "--verdict", "CONFIRMED-OPEN",
        "--by", "agent:platform-steward", "--evidence", "grep -n foo ops/bar.py",
        "--at", "2026-08-07", "--commit",
    ])
    assert rc == 0
    written = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert written["verdict"] == "CONFIRMED-OPEN"
    assert written["verified_at"] == "2026-08-07"
    assert written["verified_by"] == "agent:platform-steward"
    # The command is kept because a verdict with no evidence cannot be re-run,
    # and a claim nobody can re-run is the "reason field nobody reads" failure
    # this repo has already paid for.
    assert written["verified_evidence"] == "grep -n foo ops/bar.py"


def test_verify_refuses_a_verdict_outside_the_vocabulary(tmp_path):
    store = tmp_path / "s"
    entry = _add(store)
    assert BACKLOG.main([
        "verify", entry["id"], "--store", str(store), "--verdict", "LOOKS-FINE",
        "--by", "me", "--commit",
    ]) != 0
    assert "verdict" not in json.loads((store / f"{entry['id']}.json").read_text())


def test_a_verdict_must_carry_a_date_it_can_go_stale_from():
    """Symmetric with _check_groom: a badge whose preconditions nobody checks
    decays into decoration, and a verdict with no date can never go stale.

    Deliberately NOT also requiring `verified_by`: 60 entries carry a
    `verified_at` written before that field existed, and turning them all red
    would buy one loud day and then a muted check. `verify` writes it from now
    on, and `list --unverified` is where the backlog of unattributed claims
    stays visible."""
    dated = _payload(verdict="CONFIRMED-OPEN", verified_at="2026-08-07",
                     verified_by="agent:x")
    assert BACKLOG.validate_entry(dated) == []

    undated = _payload(verdict="CONFIRMED-OPEN", verified_by="agent:x")
    assert "verdict-without-date" in {p["kind"] for p in BACKLOG.validate_entry(undated)}

    bad_date = _payload(verdict="CONFIRMED-OPEN", verified_at="last tuesday",
                        verified_by="agent:x")
    assert "verdict-without-date" in {p["kind"] for p in BACKLOG.validate_entry(bad_date)}

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

import datetime
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import time
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKLOG_PATH = ROOT / "ops" / "backlog.py"
SPEC = importlib.util.spec_from_file_location("backlog", BACKLOG_PATH)
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

    `repo=None` is not decoration: the real `make_commit_state` takes an optional
    repo and ONE caller passes it (`reanchor_store`). The stub used to be a bare
    `lambda:`, i.e. NARROWER than the thing it replaces, so every test that reached
    `reanchor` under this fixture died on a TypeError instead of exercising it —
    which is to say no test did, until one tried. A double whose signature does not
    match its subject cannot be a stand-in for it; `test_the_commit_state_stub_
    matches_the_real_signature` pins the two together.
    """
    monkeypatch.setattr(
        BACKLOG, "make_commit_state",
        lambda repo=None: lambda sha: "ok" if BACKLOG._SHA_RE.match(sha) else "unknown",
    )


def test_the_commit_state_stub_matches_the_real_signature():
    """The autouse double above must accept exactly what the real function accepts.

    Signature drift in a test double is invisible by construction: the tests that
    use the double keep passing, and the ones that would have caught the mismatch
    are precisely the ones the mismatch prevents from running.
    """
    real = inspect.signature(BACKLOG.make_commit_state)
    stub = inspect.signature(
        lambda repo=None: lambda sha: "ok" if BACKLOG._SHA_RE.match(sha) else "unknown")
    assert list(real.parameters) == list(stub.parameters), (
        f"real{real} vs stub{stub} — the double is not a stand-in for the subject")
    for name, param in real.parameters.items():
        assert stub.parameters[name].default == param.default, name


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


def _stamp_queue(queue: Path, entry_id: str, sha: str) -> None:
    """What `cutover` does after the ff: mark the row as actually landed."""
    rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for row in rows:
        if row["id"] == entry_id:
            row["landed_sha"] = sha
    queue.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                     encoding="utf-8")


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
# 7b. the APP stream through the CLI — the path the routing docs actually name
#
# Every APP assertion above calls add_entry() directly. That left the CLI half
# of the stream — argparse wiring for --surface/--repro/--build, and the two
# read-back commands — asserted nowhere, while the schema, the categories and
# the owner were all in place. IMP-20260805-7ac60d is the routing half of that
# same shape: nothing in CLAUDE.md, agent_org.md, kg-router or the two Line
# agent files told anyone the stream existed, so it had no callers to break.
#
# It has callers now: .claude/agents/{ios,backend}-engineer.md hand agents this
# flag set, and .claude/skills/kg-receipt/SKILL.md makes filing mandatory. A doc
# that routes work into an unasserted code path is the routing gap with an extra
# step, so these tests type the same flags those files print. (Not byte-identical
# argv: the agent files show an elided form without --json, which these tests add
# to read the id back. Both land on the same handler before the output branch.)
#
# main() rather than subprocess: it is this file's existing convention (the
# --detail refusal test above), it keeps the suite stdlib-only for the sandbox
# uv run, and it still crosses the whole parser -> handler -> disk boundary.
# --------------------------------------------------------------------------

_APP_SURFACE = "reader"
_APP_REPRO = "open a 400-page EPUB, jump to chapter 12, tap within 200ms of the jump"
_APP_BUILD = "ios 2.0.1 (build 14)"


def _app_add_argv(store: Path, *extra: str) -> list[str]:
    """The flag set .claude/agents/ios-engineer.md tells an agent to type."""
    return [
        "add",
        "--store", str(store),
        "--stream", "APP",
        "--date", "2026-08-07",
        "--source", "ios-engineer",
        "--category", "correctness",
        "--severity", "med",
        "--detail", "tapping a word mid-layout selects the wrong token",
        "--surface", _APP_SURFACE,
        "--repro", _APP_REPRO,
        "--build", _APP_BUILD,
        *extra,
    ]


def test_cli_add_round_trips_every_app_only_field(tmp_path, capsys):
    """The three APP-only flags must reach disk unchanged, all three of them.

    Pinned per-field, not as a set: a flag that parses and is then dropped on
    the floor is this CLI's already-observed failure (`--detail` on `update`
    parsed, did nothing, exited 0, and cost three duplicate entries). Reading
    the raw file rather than load_entry() keeps the module's own reader out of
    the round trip — otherwise a symmetric bug on both sides cancels out.
    """
    store = tmp_path / "backlog"

    rc = BACKLOG.main(_app_add_argv(store, "--json"))
    assert rc == 0, f"filing an APP entry via the CLI failed with rc={rc}"

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "kg.backlog.add.v1"
    entry_id = payload["entry"]["id"]
    assert entry_id.startswith("APP-"), f"APP entry got a non-APP id: {entry_id}"

    on_disk = json.loads((store / f"{entry_id}.json").read_text(encoding="utf-8"))
    assert on_disk["stream"] == "APP"
    assert on_disk["surface"] == _APP_SURFACE
    assert on_disk["repro"] == _APP_REPRO
    assert on_disk["build"] == _APP_BUILD


def test_cli_show_hands_back_the_app_only_fields(tmp_path, capsys):
    """A field the writer lands and the reader cannot return is still lost.

    `show` is how the owning department reads an entry someone else filed, so
    the write path being correct is only half of the round trip.
    """
    store = tmp_path / "backlog"
    assert BACKLOG.main(_app_add_argv(store, "--json")) == 0
    entry_id = json.loads(capsys.readouterr().out)["entry"]["id"]

    assert BACKLOG.main(["show", entry_id, "--store", str(store), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)["entry"]
    assert (shown["surface"], shown["repro"], shown["build"]) == (
        _APP_SURFACE,
        _APP_REPRO,
        _APP_BUILD,
    )

    # Human output too: `show` without --json is what an agent reads first, and
    # it prints a hand-maintained field order that APP fields can fall out of.
    #
    # Spelled out rather than looped over BACKLOG.APP_ONLY_FIELDS: `_cmd_show`
    # builds its field order from that same constant, so driving the assertion
    # from it lets the two shrink together — drop `build` from the constant and
    # it silently leaves the human output with the test still green.
    assert BACKLOG.main(["show", entry_id, "--store", str(store)]) == 0
    human = capsys.readouterr().out
    for field in ("surface", "repro", "build"):
        assert field in human, f"`show` omits {field!r} from its human output"


def test_cli_list_stream_app_is_the_inbox_the_agent_files_name(tmp_path, capsys):
    """`list --stream APP` is printed verbatim in both Line agent files.

    If it did not filter, the department's inbox would be the whole ledger —
    which is the mixing the two-stream split exists to prevent.
    """
    store = tmp_path / "backlog"
    assert BACKLOG.main(_app_add_argv(store, "--json")) == 0
    app_id = json.loads(capsys.readouterr().out)["entry"]["id"]
    _add(store, stream="IMP", detail="a tool exits 0 while doing nothing")

    assert BACKLOG.main(["list", "--store", str(store), "--stream", "APP", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)["entries"]

    assert [entry["id"] for entry in listed] == [app_id]


def test_cli_refuses_an_app_field_on_an_imp_entry_and_files_nothing(tmp_path, capsys):
    """The one machine-checkable half of the "which stream?" question.

    kg-receipt's checklist decides the stream by where the fix lands, and prose
    cannot be enforced. This can: an APP-only field on an IMP entry is refused
    at the CLI, with the usage-error code, before anything is written. Pinning
    "files nothing" matters more than the code — a refusal that still leaves an
    entry on disk means the next `validate` fails for a command that reported
    an error, and the caller has no reason to go look.
    """
    store = tmp_path / "backlog"

    rc = BACKLOG.main(
        [
            "add",
            "--store", str(store),
            "--stream", "IMP",
            "--date", "2026-08-07",
            "--source", "test",
            "--category", "cli",
            "--severity", "low",
            "--detail", "an app problem misfiled into the tooling stream",
            "--surface", _APP_SURFACE,
        ]
    )

    assert rc == 64, f"expected the usage-error code, got rc={rc}"

    # The problem *kind*, not just the word "surface". `add_entry` has a second
    # ValueError path (the already-exists refusal, ops/backlog.py:383-387) whose
    # message lists differing field names and would therefore also contain
    # "surface" — so asserting the bare word cannot tell "refused for the right
    # reason" from "refused for some other one".
    err = capsys.readouterr().err
    assert "app-field-on-imp-entry" in err, f"refused, but not for this reason: {err!r}"
    assert "surface" in err, f"the refusal does not name the offending field: {err!r}"

    assert list(store.glob("*.json")) == [], "a refused add still wrote an entry"


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

    BACKLOG.update_entry(store, entry["id"], status="triaged",
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


# The two human-facing sentences. Defined here rather than beside the tests that
# scrutinise them (section 24) because `_groom_kwargs` needs them: stamping the
# badge demands plain language at write time whatever date is being written, so
# "a fully groomed entry" cannot be expressed without them any more.
BRIEF_TEXT = "有一份自動產生的統計報告已經爛掉，但檢查程式只確認它有人負責產生就放行。"
SCOPE_TEXT = "改一支檢查腳本、加一道比對，連帶要重生一份報告。"


def _groom_kwargs(**overrides):
    base = dict(
        plan="1. open ops/x.py:10  2. replace the whitelist with the tuple  3. run the test",
        # Part of the badge since BRIEF_REQUIRED_SINCE — see section 24. Carried by
        # the shared fixture because `update_entry` refuses to stamp a groom badge
        # without them, so every groomed fixture in this file needs them to exist
        # at all; the tests that assert the RULE override them explicitly.
        brief=BRIEF_TEXT,
        scope=SCOPE_TEXT,
        acceptance="pytest -q ops/tests/test_x.py::test_y",
        # The EXECUTABLE half. `acceptance` above is prose and nothing reads it;
        # this is what `anchor --commit` actually runs before closing the entry.
        acceptance_cmd="true",
        acceptance_expect_rc=0,
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


# --------------------------------------------------------------------------
# 8b. list --grep — "has this already been filed?"
#
# Every other filter here answers a question about an entry's METADATA, and
# none of them answer the one question an agent has before starting work. The
# store is 170 entries and growing in waves of 10-20; the observed cost of not
# being able to ask it was a full rebuild of a spec that was already written
# AND already groomed (IMP-20260807-c66d97 rebuilt IMP-20260807-5bff5e), plus
# two throwaway python scripts written the same day to scan the store by hand.
#
# It is a filter on `list` rather than a `search` subcommand on purpose: the
# question is almost never "does this text appear anywhere", it is "does this
# text appear in something still OPEN" or "...in something already groomed".
# A separate subcommand cannot stack, so it would have to re-grow every flag
# `list` already has, and until it did, every caller would go back to the
# throwaway script.
# --------------------------------------------------------------------------


def test_list_grep_keeps_only_the_entries_whose_text_matches(tmp_path):
    store = tmp_path / "backlog"
    hit = _add(store, detail="macOS ships openrsync; a push exits 0 and copies nothing")
    _add(store, detail="the gate reads green with no tests run")
    _add(store, detail="ios build picks the wrong scheme")

    assert [e["id"] for e in BACKLOG.list_entries(store, grep="openrsync")] == [hit["id"]]
    # The empty answer has to be reachable and has to be EMPTY. If a miss
    # returned the whole store, "nobody has filed this" and "the filter did
    # nothing" would be the same observation — and the second one is the
    # reading that makes an agent rebuild a spec that already exists.
    assert BACKLOG.list_entries(store, grep="nfs-over-carrier-pigeon") == []


@pytest.mark.parametrize("field", ["resolution", "plan", "fix_site"])
def test_list_grep_reads_the_fix_fields_not_only_detail(tmp_path, field):
    """`detail` says what broke; plan / fix_site / resolution say where and how.

    An agent about to touch `ops/foo.py` is asking "is there a neighbour ticket
    on this file", and that string lives in `fix_site` — an entry can be a
    perfect match for the work about to start while its `detail` never names
    the file at all. A detail-only grep answers "no" on exactly those.
    """
    store = tmp_path / "backlog"
    entry = _add(store, detail="a tool reports success while doing nothing")
    _add(store, detail="an unrelated neighbour", date="2026-08-06")
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(**{field: "ops/openrsync_probe.py:42"}))

    hits = [e["id"] for e in BACKLOG.list_entries(store, grep="openrsync")]
    assert hits == [entry["id"]], f"--grep never looked at `{field}`"


def test_list_grep_intersects_the_other_filters_rather_than_replacing_them(tmp_path):
    """AND, not OR, and not "the last filter wins".

    A union would return every groomed entry plus every textual match, which
    reads as a plausible answer and is the wrong set. The assertions below pin
    the intersection from both sides: each predicate alone is strictly wider
    than the two together.
    """
    store = tmp_path / "backlog"
    groomed_hit = _add(store, detail="openrsync push exits 0 and copies nothing")
    BACKLOG.update_entry(store, groomed_hit["id"], **_groom_kwargs())
    raw_hit = _add(store, detail="openrsync ignores --delete without saying so")
    groomed_other = _add(store, detail="the gate reads green with no tests run")
    BACKLOG.update_entry(store, groomed_other["id"], **_groom_kwargs())

    assert [e["id"] for e in BACKLOG.list_entries(store, grep="openrsync", groomed=True)] \
        == [groomed_hit["id"]]
    assert {e["id"] for e in BACKLOG.list_entries(store, grep="openrsync")} \
        == {groomed_hit["id"], raw_hit["id"]}
    assert {e["id"] for e in BACKLOG.list_entries(store, groomed=True)} \
        == {groomed_hit["id"], groomed_other["id"]}

    # Same statement against a metadata filter that partitions the store
    # differently, so the AND is not an accident of the groom badge.
    BACKLOG.update_entry(store, raw_hit["id"], status="wont-fix",
                         resolution="not worth it")
    assert [e["id"] for e in BACKLOG.list_entries(store, grep="openrsync", status="open")] \
        == [groomed_hit["id"]]


def test_list_grep_does_not_match_across_field_boundaries(tmp_path):
    """Each field is searched on its own, not as one concatenated blob.

    Joining the four fields with "\\n" and searching once is a line shorter and
    wrong: `alpha\\s+beta` then matches an entry whose detail ends in "alpha"
    and whose plan begins with "beta", because the separator IS whitespace. The
    caller asked whether one field contains that phrase and got back an entry
    where no field does — a false positive in a tool whose entire job is
    answering "has this already been filed".
    """
    store = tmp_path / "backlog"
    entry = _add(store, detail="the tool reports alpha")
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(plan="beta lives here"))

    assert BACKLOG.list_entries(store, grep=r"alpha\s+beta") == []
    assert BACKLOG.list_entries(store, grep=r"(?s)alpha.*beta") == []
    # ...while each field on its own still matches, i.e. the fix is a boundary,
    # not a narrowing.
    assert [e["id"] for e in BACKLOG.list_entries(store, grep="alpha")] == [entry["id"]]
    assert [e["id"] for e in BACKLOG.list_entries(store, grep="beta lives")] == [entry["id"]]


def test_list_grep_is_case_insensitive_and_takes_a_regex(tmp_path):
    store = tmp_path / "backlog"
    entry = _add(store, detail="OpenRsync silently drops the push")
    _add(store, detail="the gate reads green with no tests run")

    assert [e["id"] for e in BACKLOG.list_entries(store, grep="openrsync")] == [entry["id"]]
    assert [e["id"] for e in BACKLOG.list_entries(store, grep=r"open.?rsync")] == [entry["id"]]


def test_list_grep_refuses_a_broken_pattern_by_name(tmp_path, capsys):
    """A typo'd bracket is a refusal, not a stack trace.

    `main()` only catches (BacklogError, ValueError, EntryNotFound); letting
    `re.error` out would print a traceback whose top line is about `sre_parse`,
    i.e. it would blame this tool's internals for the caller's pattern. That is
    the defect IMP-20260807-68715b was filed for, one command over.
    """
    store = tmp_path / "backlog"
    _add(store)

    rc = BACKLOG.main(["list", "--store", str(store), "--grep", "["])

    # 64 is this CLI's documented "cannot carry out this invocation" (see the
    # code ladder in `main()`), which is what a malformed pattern is.
    assert rc == 64
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and "Traceback" not in captured.out
    assert "--grep" in captured.err, captured.err


def test_list_grep_is_reachable_from_argv(tmp_path, capsys):
    """Every other test here calls `list_entries()` directly, so deleting the
    parser line would leave all of them green while `--grep` is an
    `unrecognized arguments` error at the only place anyone types it."""
    store = tmp_path / "backlog"
    hit = _add(store, detail="openrsync push exits 0 and copies nothing")
    _add(store, detail="the gate reads green with no tests run")

    assert BACKLOG.main(
        ["list", "--store", str(store), "--grep", "openrsync", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in payload["entries"]] == [hit["id"]]


def test_list_grep_gets_no_file_twin(tmp_path):
    """`--grep` is a query, not prose on its way into the store.

    `_add_file_twins` derives a `--<flag>-file` twin for every flag whose dest
    is in FILE_TWIN_FIELDS. That set is a whitelist of STORE FIELDS: the twin
    exists so prose reaches the store unedited by a shell that eats backticks.
    `--grep` writes nothing, so there is no stored text for a twin to protect.

    Note the tempting-but-wrong version of this argument — "a mangled query is
    harmless because you would see it in the results". You would not: a pattern
    the shell narrowed returns FEWER rows, and zero rows reads as "nobody has
    filed this", which is the exact failure this flag was added to remove.

    The neighbouring `--acceptance-manual` is the precedent, and it shows the
    cost concretely: it shares a dest with a free-text field, so it got a twin,
    and that twin was a flag that could never succeed (default `False` is not
    None, so the mutual-exclusion branch fired on every call). A filter with a
    twin is a broken flag, not a safer one. `--grep` stays on the right side by
    having a dest of its own, and this test is what keeps that true.
    """
    parser = BACKLOG.build_parser()
    flags = {opt for action in BACKLOG._subcommands(parser)["list"]._actions
             for opt in action.option_strings}

    assert "--grep" in flags
    assert "--grep-file" not in flags
    assert "grep" not in BACKLOG.FILE_TWIN_FIELDS


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
    # `--X-file` twins are plumbing too: they are folded into `--X` before any
    # handler runs, so the field they reach is X's. Derived from the same module
    # constant the twins themselves come from — restating them as literals here
    # would be the smuggled exemption this test's comment warns about.
    dests -= {f"{f}_file" for f in BACKLOG.FILE_TWIN_FIELDS}
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
                         verified_by="agent:test", verified_evidence="pytest -k x",
                         **_groom_kwargs())

    before = BACKLOG.load_entry(store, entry["id"])
    rendered = BACKLOG.render_view(store, verified_against="deadbeef")
    BACKLOG.import_legacy(rendered, store)
    after = BACKLOG.load_entry(store, entry["id"])

    # BEFORE/AFTER, not a list of field names. The docstring above already says the
    # contract is "everything the table does not own", and the first version then
    # spelled out a list anyway — which broke the moment new groom fields landed,
    # for the honest reason that `acceptance_manual` is mutually exclusive with
    # `acceptance_cmd` and is CORRECTLY absent here. A list cannot express that;
    # "nothing that had a value lost it" can, and it covers fields nobody has
    # invented yet.
    lost = {k: v for k, v in before.items()
            if v not in (None, "", [], {}) and after.get(k) != v}
    assert not lost, f"a re-import erased work: {lost}"
    # ...and the pin that makes the above non-vacuous: these WERE set going in, so
    # a fixture that quietly stopped setting them cannot make this test pass by
    # having nothing to lose.
    for field in ("plan", "acceptance", "acceptance_cmd", "groomed_by",
                  "verdict", "verified_at", "verified_by", "verified_evidence",
                  # The view's table is locked to 8 columns, so these two are
                  # carried ONLY by the "everything the table does not own" path
                  # — exactly the path that silently dropped the groom fields once.
                  *BACKLOG.BRIEF_FIELDS):
        assert before.get(field), f"{field} was never set — this test proves nothing"


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
    assert "backlog.py import --from" not in err, (
        f"the refusal offers the dead rendered-view recovery: {err!r}"
    )
    assert "git checkout <sha> -- docs/runbook/backlog/<id>.json" in err, (
        f"the refusal does not offer the git recovery path: {err!r}"
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

    # RENDERED here, not read off disk. The view left version control
    # (IMP-20260807-b9526c) and is produced on demand, so a machine that has never
    # run `render` has no such file — and the property being pinned belongs to the
    # GENERATOR, not to whether a local artifact happens to exist. Reading the file
    # made this test's verdict depend on the reader's shell history.
    view = BACKLOG.render_view(BACKLOG.DEFAULT_STORE, verified_against="test")
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
    # DERIVED from the live vocabulary, not a hand-copied list. The literal version
    # named `in-progress`, which was retired — a hardcoded list of statuses goes
    # stale in exactly the direction that stops testing anything, because a removed
    # status silently drops out of coverage while the test keeps passing on the rest.
    unfinished = [s for s in BACKLOG.STATUSES if s not in ("fixed", "wont-fix")]
    assert unfinished, "every status is terminal — this test now covers nothing"
    for status in unfinished:
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
    `triaged` is different: it CLAIMS someone looked.
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


def test_reachable_from_main_but_not_head_still_counts_as_ok(tmp_path, monkeypatch):
    """The `or main` half of the reference frame, which nothing else observes.

    Caught by mutation, not by reading: deleting that branch of the OR
    (`elif has_main and merge-base…main` -> `elif False`) left the whole suite
    green. Every other test that touches the resolver either stubs it or only
    exercises the HEAD side, so the single most-argued decision in this design
    was the one a refactor could silently remove.

    The case that needs a witness is exactly the one the design paragraph is
    about: a commit ON main, with HEAD parked behind it. That is what `validate`
    sees when it runs from a worktree whose branch forked before the fix landed.
    """
    monkeypatch.undo()
    repo = tmp_path / "repo"

    def g(*args):
        return subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
             *args],
            cwd=repo, capture_output=True, text=True, check=True,
        )
    repo.mkdir()
    g("init", "-b", "main", "-q")
    (repo / "a.txt").write_text("a\n")
    g("add", "a.txt"); g("commit", "-qm", "base")
    behind = g("rev-parse", "HEAD").stdout.strip()
    (repo / "b.txt").write_text("b\n")
    g("add", "b.txt"); g("commit", "-qm", "later")
    ahead = g("rev-parse", "HEAD").stdout.strip()
    g("checkout", "-q", behind)  # detached, parked behind main

    # The repo is passed, not stood in: cwd is no longer a way to aim this
    # resolver, because cwd was also a way to disarm it.
    state = BACKLOG.make_commit_state(repo)
    # `behind` is reachable from BOTH arms, so asserting `ok` on it does not
    # witness the HEAD arm — under a mutation that drops the HEAD arm's `repo=`,
    # the main arm answers for it and the label lies. Delete main first, and the
    # only arm left is the one this line claims to be testing.
    g("branch", "-D", "main")
    assert BACKLOG.make_commit_state(repo)(behind) == "ok", "reachable from HEAD"
    g("branch", "main", ahead)
    # The witness: unreachable from HEAD, reachable from main. Only the `or main`
    # branch can answer `ok` here, so removing it turns this red.
    assert state(ahead) == "ok", "reachable from main but not HEAD"


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
    # The CLI deliberately has no --repo flag: `reanchor` repairs the ledger of
    # the checkout it ships in, and a flag would re-open the "which repo is this
    # answering about" question the cwd fix just closed. So the fixture repo is
    # made to BE that checkout for this test — but only for the CLI half, below.
    # Pointing GIT_REPO straight at `repo` was the first attempt and it QUIETLY
    # destroyed this test's best property: with the fallback equal to the right
    # answer, dropping `repo=` from any threading site became unobservable, and
    # a mutation that this very test had already caught once survived green.

    store = repo / "store"
    entry = _add(store, detail="reanchor fixture")
    # Written straight to disk on purpose: `update` REFUSES an orphaned sha, so
    # the broken state cannot be created through it. That is not a gap in the
    # fixture — it is how the state actually arises. The sha is valid when
    # written and the rebase orphans it afterwards, with nobody in the loop.
    _force_fixed_by(store, entry["id"], [orphan])
    assert BACKLOG.make_commit_state(repo)(orphan) == "orphan", "fixture did not orphan the commit"

    # A decoy: any site that falls back to GIT_REPO instead of using the passed
    # `repo` now answers from a repo where none of these shas exist.
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=decoy, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "-q", "--allow-empty", "-m", "decoy"], cwd=decoy, check=True,
                   capture_output=True)
    monkeypatch.setattr(BACKLOG, "GIT_REPO", decoy)

    dry = BACKLOG.reanchor_store(store, repo=repo)
    assert dry["plan"][0]["moves"] == {orphan: landed[:9]}
    # A dry run must not touch the store; the whole point of the primitive is
    # that a wrong mapping is a wrong audit trail.
    assert json.loads((store / f"{entry['id']}.json").read_text())["fixed_by"] == [orphan]

    # Only now does the fixture repo become "the checkout this ships in", which
    # is the CLI's only frame of reference.
    monkeypatch.setattr(BACKLOG, "GIT_REPO", repo)
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

    store = repo / "store"
    entry = _add(store, detail="unmatchable fixture")
    _force_fixed_by(store, entry["id"], [orphan])

    # Window of 1 cannot reach the equivalent commit. The answer must be "not
    # found in the window I searched", never a guess. (The window walks HEAD,
    # not main: the rewritten commit lands on the branch first, and searching
    # main alone returned 8-of-8 UNMATCHED on this tool's first real run.)
    result = BACKLOG.reanchor_store(store, search_depth=1, repo=repo)
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
        "--by", "me", "--evidence", "cmd", "--at", "2026-08-07", "--commit",
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


def test_verify_can_close_an_entry_in_the_same_act(tmp_path, monkeypatch):
    """`verify --status fixed` without `--fixed-by` was a dead end.

    Hit while closing this batch: the traceability rule refuses a `fixed` entry
    with no landing commit, so the natural closing act failed with an error
    naming a flag `verify` did not have. Rule 9 — the entry point was wrong, not
    the caller.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="closing act")
    monkeypatch.setattr(BACKLOG, "make_commit_state", lambda: lambda sha: "ok")

    rc = BACKLOG.main([
        "verify", entry["id"], "--store", str(store), "--verdict", "CONFIRMED-FIXED",
        "--by", "agent:test", "--evidence", "pytest -k closing", "--at", "2026-08-07",
        "--status", "fixed", "--fixed-by", "abc1234", "--commit",
    ])
    assert rc == 0
    written = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert written["status"] == "fixed"
    assert written["fixed_by"] == ["abc1234"]
    assert written["verified_by"] == "agent:test"


def test_unverified_means_no_attributable_verification(tmp_path):
    """A date with no verifier is not a verification, and the first cut let 60
    of them sit outside both the gate and the queue.

    That design justified skipping the gate by pointing at this queue; measured,
    the queue's hit rate on exactly those entries was 0 of 60 — `not verified_at`
    is their complement by construction. A safety net whose catch is provably
    empty is worse than no net, because it ends an argument.
    """
    store = tmp_path / "s"
    dated_only = _add(store, detail="date but nobody")
    BACKLOG.update_entry(store, dated_only["id"], verified_at="2026-08-01")
    attributed = _add(store, detail="properly verified")
    BACKLOG.update_entry(store, attributed["id"], verified_at="2026-08-01",
                         verdict="CONFIRMED-OPEN", verified_by="agent:x")

    unverified = {e["id"] for e in BACKLOG.select_entries(store, unverified=True)}
    assert dated_only["id"] in unverified
    assert attributed["id"] not in unverified


def test_unverified_and_stale_together_are_refused(tmp_path):
    """Their intersection is empty by construction, and an empty result reads as
    'both queues are clear'. The neighbouring --groomed/--ungroomed pair already
    refuses its own contradiction."""
    with pytest.raises(BACKLOG.BacklogError):
        BACKLOG.select_entries(tmp_path, unverified=True, stale_days=30)


def test_half_a_verification_stamp_cannot_hide_an_entry(tmp_path):
    """`--verified-at n/a` alone used to walk through every net at once.

    validate passed it (no verdict, so the old single-sided trigger never
    fired), `--unverified` skipped it (field non-empty), `--stale` skipped it
    (unparseable date). One flag removed an entry from the whole mechanism.
    """
    store = tmp_path / "s"
    entry = _add(store)
    with pytest.raises(ValueError):
        BACKLOG.update_entry(store, entry["id"], verified_at="n/a")

    planted = dict(_payload(), verified_at="n/a")
    assert "verdict-without-date" in {p["kind"] for p in BACKLOG.validate_entry(planted)}
    assert planted["id"] in {
        e["id"] for e in [planted] if not str(planted.get("verified_by") or "").strip()}


@pytest.mark.parametrize("bad", ["2026-13-45", "9999-99-99", "0000-00-00", "2099-01-01"])
def test_a_date_shaped_string_is_not_a_date(tmp_path, bad):
    """`^\\d{4}-\\d{2}-\\d{2}$` is a shape. All four of these landed in the store
    through `--at`, and the last two break the rule that was checking them:
    `9999-99-99` and any future date are verdicts that can never go stale, which
    is the exact thing `verdict-without-date` exists to prevent."""
    store = tmp_path / "s"
    entry = _add(store)
    rc = BACKLOG.main([
        "verify", entry["id"], "--store", str(store), "--verdict", "CONFIRMED-OPEN",
        "--by", "agent:x", "--evidence", "cmd", "--at", bad, "--commit",
    ])
    assert rc == 64, f"{bad} was accepted as a date"
    assert "verified_at" not in json.loads((store / f"{entry['id']}.json").read_text())


def test_verify_overwrites_evidence_rather_than_inheriting_it(tmp_path):
    """Measured before `--evidence` became required: a second verifier's
    CONFIRMED-FIXED carried the first verifier's command. Evidence that re-runs
    to the previous verdict is worse than none, because it looks like it has
    some."""
    store = tmp_path / "s"
    entry = _add(store)
    BACKLOG.main(["verify", entry["id"], "--store", str(store), "--verdict", "CONFIRMED-OPEN",
                  "--by", "agent:alice", "--evidence", "pytest -k alpha",
                  "--at", "2026-08-01", "--commit"])
    BACKLOG.main(["verify", entry["id"], "--store", str(store), "--verdict", "PARTIAL",
                  "--by", "agent:bob", "--evidence", "pytest -k beta",
                  "--at", "2026-08-02", "--commit"])
    written = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert written["verified_by"] == "agent:bob"
    assert written["verified_evidence"] == "pytest -k beta"

    # And it cannot be omitted at all: optional evidence in an "atomic" act
    # means evidence is not in the atom.
    with pytest.raises(SystemExit):
        BACKLOG.main(["verify", entry["id"], "--store", str(store), "--verdict", "PARTIAL",
                      "--by", "agent:carol", "--commit"])


def test_the_ratchet_blocks_closing_without_verifying(tmp_path, monkeypatch):
    """The [prompt] -> [machine] step, and the reason it is keyed on CLOSED.

    The queue alone had zero automatic callers — its only caller anywhere was a
    bullet in an agent file. `validate` was already a block gate at cutover, so
    riding that rail costs nothing. Keyed on every entry it would red on `add`,
    which punishes filing; keyed on closure it cannot, and closure is when the
    audit trail starts to rot.
    """
    store = tmp_path / "s"
    baseline = tmp_path / "baseline.txt"
    monkeypatch.setenv("KG_BACKLOG_BASELINE", str(baseline))
    monkeypatch.setattr(BACKLOG, "make_commit_state", lambda: lambda sha: "ok")

    grandfathered = _add(store, detail="closed long ago, nobody checked")
    BACKLOG.update_entry(store, grandfathered["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="done")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline"]) == 0
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 0

    # Filing does NOT move the ratchet.
    _add(store, detail="freshly filed, no verification yet")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 0

    # Closing without verifying does.
    fresh = _add(store, detail="closed today without checking")
    BACKLOG.update_entry(store, fresh["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="done")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 2

    # Closing WITH an attributable verification does not. All four fields:
    # date + verifier alone used to be enough, which let `update` apply through
    # the side door the two flags `verify` bundles.
    BACKLOG.update_entry(store, fresh["id"], verified_at="2026-08-07",
                         verdict="CONFIRMED-FIXED", verified_by="agent:x",
                         verified_evidence="pytest ops/tests/test_backlog.py")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 0


def test_the_ratchet_cannot_be_disarmed_by_standing_somewhere_else(tmp_path, monkeypatch):
    """The store and the baseline must name the same checkout.

    Measured on the real ledger: `cd /tmp/elsewhere && <worktree>/ops/backlog.py
    validate --baseline-check` printed `0 problems`, rc=0, while forgiving all
    160 ids — because `DEFAULT_STORE` is ROOT-anchored and the baseline default
    was cwd-anchored. A mismatched pair fails OPEN whenever the foreign baseline
    is the larger one, and the gate reads green from a directory rather than
    from the ledger. Same shape as IMP-0049 (`review_audit.sh` silently auditing
    whichever repo the caller happened to stand in).

    An explicit env override is still honoured as given: that one has a caller
    who meant it.
    """
    foreign = tmp_path / "elsewhere"
    (foreign / "ops").mkdir(parents=True)
    (foreign / "ops" / "backlog_closed_unverified_baseline.txt").write_text(
        "IMP-FOREIGN-PREFORGIVEN\n", encoding="utf-8")
    monkeypatch.delenv("KG_BACKLOG_BASELINE", raising=False)
    monkeypatch.chdir(foreign)

    assert BACKLOG._baseline_path() == BACKLOG.ROOT / "ops" / "backlog_closed_unverified_baseline.txt"
    allowed = BACKLOG._read_baseline(BACKLOG._baseline_path())
    # Positive control on the FILE, not on its contents: this ratchet's whole
    # purpose is to reach zero (ops/i18n_baseline.txt already has), and a
    # non-empty assertion would red on the day the system arrives.
    assert BACKLOG._baseline_path().exists(), "positive control: the repo's own baseline must be findable from here"
    assert "IMP-FOREIGN-PREFORGIVEN" not in allowed

    # An absolute override is honoured as given...
    absolute = tmp_path / "explicit.txt"
    absolute.write_text("IMP-EXPLICIT\n", encoding="utf-8")
    monkeypatch.setenv("KG_BACKLOG_BASELINE", str(absolute))
    assert BACKLOG._read_baseline(BACKLOG._baseline_path()) == {"IMP-EXPLICIT"}

    # ...and a RELATIVE one resolves against the repo root, not against cwd.
    # Absolute values make all three candidate semantics (as-given / ROOT-joined
    # / cwd-joined) identical, so only this arm can tell them apart. The choice
    # follows the sister contract already documented for KG_INJECTION_BASELINE
    # in docs/reference/tech_index.md: two baseline env vars in one repo with
    # opposite relative-path rules is a trap laid for whoever reads one first.
    monkeypatch.setenv("KG_BACKLOG_BASELINE", "ops/backlog_closed_unverified_baseline.txt")
    assert BACKLOG._baseline_path() == BACKLOG.ROOT / "ops" / "backlog_closed_unverified_baseline.txt"


def test_the_commit_resolver_answers_about_this_repo_not_the_callers_directory(tmp_path, monkeypatch):
    """`_git` inherited the caller's cwd, so `validate` had a second cwd disarm.

    Measured on the real ledger, one command, only cwd varying, entry carrying
    the unresolvable sha 813356b1:

        cwd=repo root   rc=2  ['fixed-by-unresolvable']
        cwd=/tmp        rc=0  []                          <- fail-open
        cwd=other repo  rc=2  ['fixed-by-unresolvable']   <- false red on a good sha

    `make_commit_state` returned None outside a repo and the consumer read that
    as "ok" for every sha. Pinning git to ROOT makes the answer a property of
    the ledger's own checkout, which is the only repo the shas can mean.
    """
    monkeypatch.undo()  # drop the fake odb; this test drives the real resolver
    here = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKLOG.ROOT,
                          capture_output=True, text=True).stdout.strip()

    monkeypatch.chdir(tmp_path)  # not a git repo at all
    state = BACKLOG.make_commit_state()
    assert state is not None, "the resolver must not go blind because of the caller's cwd"
    assert state(here) == "ok"
    assert state("0000000") == "unknown"

    # A *different* git repo is the other half: it must not become the frame of
    # reference either, or a perfectly good sha reads as unresolvable.
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(cmd, cwd=foreign, check=True, capture_output=True)
    monkeypatch.chdir(foreign)
    assert BACKLOG.make_commit_state()(here) == "ok"


def test_validate_says_the_check_did_not_run_rather_than_saying_ok(tmp_path, monkeypatch):
    """The consumer contradicted the producer's docstring.

    `make_commit_state` returns None "so the caller can say the check did not
    run instead of printing a clean bill of health it never earned" — and its
    only caller wrote `commit_state(sha) if commit_state else "ok"`, i.e. it
    printed exactly that clean bill. An enumerated hole beats an anonymous one:
    absence of evidence has to have its own name in the output.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="carries a sha nobody can resolve")
    BACKLOG.update_entry(store, entry["id"], status="fixed",
                         fixed_by=["813356b1"], resolution="done")

    monkeypatch.setattr(BACKLOG, "make_commit_state", lambda: None)
    kinds = {p["kind"] for p in BACKLOG.validate_store(store)}
    assert "commit-state-unavailable" in kinds
    assert BACKLOG.main(["validate", "--store", str(store)]) == 2


def test_asking_for_the_gate_and_the_rewrite_at_once_is_refused(tmp_path, monkeypatch):
    """`--baseline` returned early, so it silently ATE `--baseline-check`.

    Measured on a copy of the real ledger, one entry closed without
    verification and outside the baseline:

        validate --baseline-check              -> rc=2, 1 problems
        validate --baseline-check --baseline   -> rc=0, "wrote base.txt (70 entries)"
        validate --baseline-check              -> rc=0, 0 problems

    So passing the gate flag produced a green light AND permanently widened the
    watermark by one, with no line of output saying the requested check had not
    run. Nothing machine-driven passes both (`worktree_orchestrate` hardcodes
    the argv), which is exactly why only a human or an agent typing it would
    ever be hurt by it.

    The refusal is argparse's, matching the three sister lints
    (ui_token / plain_deadzone / injection) and this file's own two precedents
    — one of which (`--unverified` / `--stale`) was added by the same commit
    that added these two flags, with the same argument: a quiet empty result
    reads like a pass.
    """
    store = tmp_path / "s"
    _add(store, detail="anything")
    monkeypatch.setenv("KG_BACKLOG_BASELINE", str(tmp_path / "b.txt"))
    with pytest.raises(SystemExit) as exc:
        BACKLOG.main(["validate", "--store", str(store), "--baseline-check", "--baseline"])
    assert exc.value.code == 2


def test_empty_evidence_is_not_evidence(tmp_path, monkeypatch):
    """`required=True` proves the flag was typed, not that it says anything.

    `verify ... --evidence ''` exited 0 and stored `''`, which satisfies the
    ratchet and leaves the re-verification queue — the whole apparatus cleared
    by a stamp that records no command at all.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="probe")
    BACKLOG.update_entry(store, entry["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="landed")
    for hollow in ("", "   ", "\t\n"):
        assert BACKLOG.main(["verify", entry["id"], "--store", str(store),
                             "--verdict", "CONFIRMED-FIXED", "--by", "agent:x",
                             "--evidence", hollow, "--commit"]) == 64  # EX_USAGE, as every refusal here
    stored = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert not stored.get("verified_evidence")


def test_a_half_written_stamp_does_not_clear_the_ratchet(tmp_path, monkeypatch):
    """`update --verified-at X --verified-by Y` walked straight through it.

    The ratchet asked only for a date and a name, so the two flags `verify`
    exists to bundle could still be applied piecemeal through `update`, landing
    a closed entry with NO verdict and NO evidence that the gate then called
    verified. Measured: rc=2 before, rc=0 after, verdict=None evidence=None.

    Attributable has to mean the whole stamp — who, when, what they concluded,
    and what they ran. Strengthening the predicate reds exactly the same 69
    entries it did before (measured against the real store), so this costs no
    new debt; it only closes the side door.
    """
    store = tmp_path / "s"
    baseline = tmp_path / "b.txt"
    monkeypatch.setenv("KG_BACKLOG_BASELINE", str(baseline))
    monkeypatch.setattr(BACKLOG, "make_commit_state", lambda *a, **k: lambda sha: "ok")

    entry = _add(store, detail="probe")
    BACKLOG.update_entry(store, entry["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="landed")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline"]) == 0
    fresh = _add(store, detail="closed today")
    BACKLOG.update_entry(store, fresh["id"], status="fixed",
                         fixed_by=["abc1234"], resolution="landed")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 2

    # Half a stamp: the two fields the old predicate asked for, nothing else.
    BACKLOG.update_entry(store, fresh["id"], verified_at="2026-08-07", verified_by="agent:x")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 2

    # The whole stamp clears it.
    BACKLOG.update_entry(store, fresh["id"], verdict="CONFIRMED-FIXED",
                         verified_evidence="pytest ops/tests/test_backlog.py")
    assert BACKLOG.main(["validate", "--store", str(store), "--baseline-check"]) == 0


def test_wont_fix_does_not_launder_a_broken_fixed_by(tmp_path):
    """One status flip made an unresolvable sha disappear from the verdict.

    `_check_traceability` only resolved shas under `status == "fixed"`, so
    measured: fixed + fixed_by=['813356b1'] -> rc=2 fixed-by-unresolvable;
    change nothing but the status to wont-fix -> rc=0, 0 problems. The sha is no
    less broken for the entry having been closed a different way, and "flip the
    status" is a repair anyone reaching for a green gate would find.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="probe")
    _force_fixed_by(store, entry["id"], ["813356b1"])
    path = store / f"{entry['id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "wont-fix"
    payload["resolution"] = "decided against it after discussion"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    kinds = {p["kind"] for p in BACKLOG.validate_store(
        store, commit_state=lambda sha: "unknown")}
    assert "fixed-by-unresolvable" in kinds


def test_reanchor_searches_the_frame_the_detector_accepts(tmp_path, monkeypatch):
    """The search frame was still narrower than the acceptance frame.

    `make_commit_state` calls a sha `ok` when it is reachable from HEAD **or**
    from main, and both halves are argued for. The repair walked HEAD alone —
    first cut walked main alone and returned 8-of-8 UNMATCHED, so the frame was
    moved rather than widened. The case left uncovered is the mirror image and
    just as ordinary: HEAD parked behind main, which is what a worktree looks
    like when the fix landed on main after the branch forked. A repair tool
    whose search space is narrower than its own detector's acceptance can only
    report `not guessed`, which reads like care rather than like looking in the
    wrong place.
    """
    monkeypatch.undo()
    repo = tmp_path / "repo"
    orphan, landed = _git_repo(repo)

    def g(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, check=True)
    root_commit = g("rev-list", "--max-parents=0", "main").stdout.strip()
    g("checkout", "-q", root_commit)  # detached, parked behind main
    assert BACKLOG.make_commit_state(repo)(landed) == "ok", \
        "fixture check: landed is reachable from main, which the detector accepts"

    store = repo / "store"
    entry = _add(store, detail="orphan whose replacement is on main only")
    _force_fixed_by(store, entry["id"], [orphan])
    result = BACKLOG.reanchor_store(store, repo=repo)
    assert result["plan"][0]["moves"] == {orphan: landed[:9]}


def test_json_mode_stays_json_when_the_answer_is_a_refusal(tmp_path):
    """A machine channel that turns into prose exactly when something goes wrong.

    Measured: `verify ... --verdict STILL-PRESENT --json` (a value not in VERDICTS)
    printed `ERROR invalid update: [{'kind': 'bad-verdict', ...}]` to stderr and
    NOTHING to stdout, so a consumer doing `json.load(proc.stdout)` gets
    `JSONDecodeError: Expecting value: line 1 column 1`. Refusals are the outcome an
    automated caller most needs to read — ten agents driving this CLI will meet
    `fixed-without-fixed-by` far more often than they meet success.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="probe")
    proc = subprocess.run(
        [sys.executable, str(BACKLOG_PATH), "update", entry["id"], "--store", str(store),
         "--verdict", "NOT-A-REAL-VERDICT", "--commit", "--json"],
        capture_output=True, text=True)
    assert proc.returncode == 64
    payload = json.loads(proc.stdout)          # must not raise
    assert payload["ok"] is False
    assert payload["schema"].startswith("kg.backlog.")
    assert "bad-verdict" in json.dumps(payload, ensure_ascii=False)


def test_every_mutation_returns_the_entry_it_wrote(tmp_path):
    """`update --json` answered with `changes` but not the resulting entry.

    That is what made `d.get('entry')` print `None` after a write that had in fact
    succeeded — the caller could not tell "no entry in the payload" from "the write
    did nothing", and had to re-query to find out. `add` and `show` already return
    `entry`; the write paths are the ones where it matters most.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="probe")
    for argv in (["update", entry["id"], "--severity", "high"],
                 ["verify", entry["id"], "--verdict", "CONFIRMED-OPEN",
                  "--by", "agent:x", "--evidence", "ran the thing"]):
        proc = subprocess.run(
            [sys.executable, str(BACKLOG_PATH), *argv, "--store", str(store),
             "--commit", "--json"], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert "entry" in payload, (argv[0], sorted(payload))
        assert payload["entry"]["id"] == entry["id"]


def test_no_mutation_writes_the_view(tmp_path, monkeypatch):
    """The store is the SoT; the view is an optional local convenience.

    Every mutation used to re-render the view, and that one line of convenience was
    the most expensive thing in this module. Measured on the real 179-entry store:
    one render is 118–232 ms and it is O(entries), so serialising it behind a lock
    capped mutations at ~8/sec and made a burst of n filings O(n²) — 32 filings in
    3.5 s, 64 in 7.2 s, 128 in 16.2 s. It also made a 291 KB tracked file the one
    thing concurrent branches provably collide on, which is what `_view_lock`, the
    entry-loss guard on the refresh path, the registry `check:` gate, cutover's
    render-repair step, catchup's conflict resolver and `review_audit.sh`'s
    path-scoped exemption all existed to survive.

    None of that bought anything a reader wanted: the inventory of every pointer to
    the file across CLAUDE.md, the skills, the agent files and the registry found
    SIX, and **not one of them tells anybody to read it** — they all say "generated,
    do not hand-edit" or "this is what your rebase will conflict on". So the file is
    gitignored now and `render` produces it on demand.

    Driven through `main()` for every mutating subcommand, because the defect was
    never in the helpers — it was that the CLI did a second, expensive thing its
    caller did not ask for.
    """
    store = tmp_path / "backlog"; store.mkdir()
    view = tmp_path / "view.md"
    # `reanchor` refuses outside a git repo (it resolves shas), so this cannot be a
    # bare tmp dir — and it is one of the six call sites removed, so leaving it out
    # would leave a removal unwitnessed.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(BACKLOG, "DEFAULT_STORE", store)
    monkeypatch.setattr(BACKLOG, "DEFAULT_VIEW", view)
    monkeypatch.setattr(BACKLOG, "_doc_anchor", lambda: "deadbeef")

    assert BACKLOG.main(["add", "--store", str(store), "--stream", "IMP",
                         "--date", "2026-08-08", "--source", "an agent",
                         "--category", "tool", "--severity", "low",
                         "--detail", "filed by an agent"]) == 0
    entry_id = next(p.stem for p in store.glob("*.json"))
    assert not view.exists(), "`add` rendered the view"

    assert BACKLOG.main(["update", entry_id, "--store", str(store),
                         "--resolution", "— still open", "--commit"]) == 0
    assert not view.exists(), "`update --commit` rendered the view"

    assert BACKLOG.main(["verify", entry_id, "--store", str(store),
                         "--verdict", "CONFIRMED-OPEN", "--by", "x",
                         "--evidence", "ran it", "--commit"]) == 0
    assert not view.exists(), "`verify --commit` rendered the view"

    assert BACKLOG.main(["reanchor", "--store", str(store), "--commit"]) == 0
    assert not view.exists(), "`reanchor --commit` rendered the view"

    # ...and the explicit command still does the job, unchanged.
    assert BACKLOG.main(["render", "--store", str(store), "--out", str(view),
                         "--commit"]) == 0
    text = view.read_text(encoding="utf-8")
    assert entry_id in text and "deadbeef" in text


def test_render_still_refuses_to_drop_a_row_the_outgoing_view_carried(
        tmp_path, monkeypatch):
    """The entry-loss guard belongs to `render`, and survives the refresh's removal.

    IMP-20260806-e06150: three entries once vanished in a re-render with rc=0, empty
    stderr, a plausible row count and a green gate. That guard was duplicated onto
    the automatic path; deleting the automatic path must not take the original with
    it, which is a thing a purely subtractive change can do silently.
    """
    store = tmp_path / "backlog"; store.mkdir()
    view = tmp_path / "view.md"
    monkeypatch.setattr(BACKLOG, "_doc_anchor", lambda: "deadbeef")

    doomed = BACKLOG.add_entry(store, **_entry_kwargs(detail="present in the view"))
    keeper = BACKLOG.add_entry(store, **_entry_kwargs(detail="the other one"))
    assert BACKLOG.main(["render", "--store", str(store), "--out", str(view),
                         "--commit"]) == 0
    assert doomed["id"] in view.read_text(encoding="utf-8")

    # The store loses an entry behind the tool's back — a bad merge, a stray rm.
    (store / f"{doomed['id']}.json").unlink()
    BACKLOG.main(["render", "--store", str(store), "--out", str(view), "--commit"])

    surviving = view.read_text(encoding="utf-8")
    assert doomed["id"] in surviving, "render silently deleted a row from the view"
    assert keeper["id"] in surviving


def test_the_rendered_view_carries_no_global_aggregate(tmp_path):
    """The view used to end in `<!-- N IMP + M APP entries -->` and a groom counter.

    Those two lines re-created inside the artifact the exact defect this store's
    shape was chosen to escape — "every append targets the same trailing region, so
    two worktrees appending concurrently conflict by construction". Measured on a
    clone of the real repo, ten branches filing 1-3 entries each and landing in turn:
    with the counters, 4 of 10 landed and the final view was STALE; without them,
    7 of 10 landed and the view was consistent.
    """
    store = tmp_path / "backlog"; store.mkdir()
    BACKLOG.add_entry(store, **_entry_kwargs(detail="one"))
    BACKLOG.add_entry(store, **_entry_kwargs(detail="two"))
    text = BACKLOG.render_view(store, verified_against="cafe1234")

    tail = [ln for ln in text.strip().splitlines()[-3:]]
    assert not any("entries -->" in ln for ln in tail), tail
    assert not any(ln.startswith("<!-- groom:") for ln in tail), tail
    # a count of anything at all is the shape being banned, not those two strings
    assert not re.search(r"<!--[^>]*\b\d+\s*(IMP|APP|of|/)\b", text.split("|")[0])


def test_render_reports_the_counts_it_no_longer_writes_down(tmp_path, monkeypatch, capsys):
    """Removing the footer must not remove the information. It moves to where a
    number costs nothing — stdout — instead of a merge conflict per branch."""
    store = tmp_path / "backlog"; store.mkdir()
    out = tmp_path / "view.md"
    BACKLOG.add_entry(store, **_entry_kwargs(detail="unresolved and ungroomed"))
    monkeypatch.setattr(BACKLOG, "_doc_anchor", lambda: "cafe1234")
    rc = BACKLOG.main(["render", "--store", str(store), "--out", str(out), "--commit"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "1 IMP + 0 APP entries" in printed, printed
    assert "groom: 0/1" in printed, printed
    assert "list --ungroomed" in printed, printed


def test_the_atomic_write_does_not_collide_with_a_concurrent_one(tmp_path):
    """The temp name used to be a fixed `.{name}.tmp`, which is safe only while
    nothing writes the same path twice at once. Auto-refresh made that false: two
    writers raced, the first `os.replace` moved the shared temp away, and the second
    died with FileNotFoundError inside the helper whose job is to make writing safe.
    """
    import threading
    target = tmp_path / "view.md"
    errors: list[BaseException] = []
    payloads = [f"payload-{i}\n" * 200 for i in range(8)]

    def write(text: str) -> None:
        try:
            for _ in range(20):
                BACKLOG._write_atomic(target, text)
        except BaseException as exc:  # noqa: BLE001 — the point is to see it at all
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    # and every reader saw a WHOLE payload, never a spliced one
    assert target.read_text(encoding="utf-8") in payloads
    assert not list(tmp_path.glob(".*tmp*")), "temp files leaked"


def test_the_atomic_write_does_not_quietly_change_a_files_permissions(tmp_path):
    """`tempfile.mkstemp` creates 0600 and `os.replace` carries that onto the target.

    This one had already happened: after `_write_atomic` moved off `write_text`, the
    280KB ledger view on disk was `-rw-------` while its sibling entry files were
    still `-rw-r--r--`. git tracks only the exec bit, so nothing in any diff, any
    gate or any review would ever have mentioned it — every mutation would just keep
    demoting whatever it touched.
    """
    target = tmp_path / "view.md"
    target.write_text("first\n", encoding="utf-8")
    os.chmod(target, 0o644)
    BACKLOG._write_atomic(target, "second\n")
    assert oct(target.stat().st_mode & 0o777) == "0o644"

    # a file it CREATES follows the umask, exactly as an ordinary create would
    fresh = tmp_path / "fresh.md"
    umask = os.umask(0o022)
    os.umask(umask)
    BACKLOG._write_atomic(fresh, "new\n")
    assert fresh.stat().st_mode & 0o777 == (0o666 & ~umask)


# --------------------------------------------------------------------------
# 14. a mistyped id is a refusal, not a crash — in every subcommand
# --------------------------------------------------------------------------

def test_an_id_that_is_not_there_is_refused_by_every_command_that_loads_one(tmp_path, capsys):
    """`show` and `update` each grew their own try/except; `verify` never did.

    Per-command handling is the wrong shape for this. Three call sites into the
    same loader, two of which remembered, means the third's users met a Python
    traceback for the most ordinary mistake there is — and `--json` met one too,
    which is the single channel whose caller provably cannot read it (json.load
    raises on a traceback, so the refusal arrives as a second, different error).

    Asserted over all three because they are the three that load an entry today.
    What actually stops a FOURTH command from reintroducing this is `main`'s single
    handler, not this list — these argv are hand-written and nothing derives them
    from the source, so a new subcommand that catches the error itself and answers
    something else would not turn anything here red.
    """
    store = tmp_path / "s"
    _add(store)  # a populated store: the failure under test is the id, not the dir
    missing = "IMP-20260101-abcdef"
    argvs = (
        ["show", missing, "--store", str(store)],
        ["update", missing, "--store", str(store), "--severity", "high"],
        ["verify", missing, "--store", str(store), "--verdict", "CONFIRMED-OPEN",
         "--by", "probe", "--evidence", "ran the thing"],
    )
    for argv in argvs:
        rc = BACKLOG.main(list(argv))
        captured = capsys.readouterr()
        # The SAME code from all three. Not just non-zero: this CLI separates 1
        # ("your question was fine, the answer is no" — `render --check` STALE)
        # from 64 ("the call is malformed"), and a missing id has to land on one
        # side of that line for every command, not a different side per command.
        assert rc == 1, f"{argv[0]} answered {rc} for an id that is not in the store"
        assert f"no such entry: {missing}" in captured.err, (
            f"{argv[0]} did not name the missing id: {captured.err!r}"
        )

    for argv in argvs:
        rc = BACKLOG.main([*argv, "--json"])
        out = capsys.readouterr().out
        # The assertion is that this parses at all. A traceback goes to stderr and
        # leaves stdout empty, so json.loads is what actually distinguishes the two.
        payload = json.loads(out)
        assert payload["ok"] is False
        assert missing in payload["error"]


def test_the_missing_entry_refusal_is_narrower_than_a_bare_key_error(tmp_path):
    """The refusal has to be narrower than `except KeyError`.

    A bare KeyError handler around a whole command body would also swallow a real
    dict-lookup bug inside it and report it as "no such entry" — turning a defect
    into a reassuring message. So the loader raises its own type, and that type is
    what the CLI answers to. It stays a KeyError as well, because three tests and
    one recovery path in `import_legacy` already read it that way; and a BacklogError so
    that deleting `main`'s specific clause degrades to the generic refusal rather
    than to a traceback.
    """
    store = tmp_path / "s"
    _add(store)
    with pytest.raises(BACKLOG.EntryNotFound) as caught:
        BACKLOG.load_entry(store, "IMP-20260101-abcdef")
    assert isinstance(caught.value, KeyError)
    assert isinstance(caught.value, BACKLOG.BacklogError)
    # str() is what `main` prints. KeyError's own __str__ would repr the id and
    # produce `ERROR 'IMP-...'`, which names nothing.
    assert str(caught.value) == "no such entry: IMP-20260101-abcdef"


# --------------------------------------------------------------------------
# 15. one search depth, not two
# --------------------------------------------------------------------------

def test_the_reanchor_search_depth_has_one_default_and_not_two(tmp_path):
    """The CLI searched 2000 commits and a direct call searched 800.

    Both are doors into the same function, and `reanchor` is the one command whose
    only silent failure is "found nothing" — with two depths there was no way to
    read that answer, because "nothing matched" and "the window ended early" look
    identical and the window was a different size depending on how you got in.

    Compares the two real sources against each other rather than against a literal,
    so the test cannot be satisfied by re-typing the same number in both places.
    """
    parsed = BACKLOG.build_parser().parse_args(["reanchor"])
    from_signature = inspect.signature(
        BACKLOG.reanchor_store).parameters["search_depth"].default
    assert parsed.search_depth == from_signature, (
        f"CLI default {parsed.search_depth} != library default {from_signature}"
    )


# --------------------------------------------------------------------------
# 16. `show` returns the field that says which commit fixed it
# --------------------------------------------------------------------------

def test_show_prints_the_commits_that_closed_the_entry(tmp_path, capsys):
    """`fixed_by` exists so a closed entry can be traced to the commit that closed it.

    The human output built its field order by hand and left TRACE_FIELDS out, so
    the one field a reader opens a fixed entry to see was the one field `show`
    would not print — while `--json` had it all along. A field that is stored,
    validated and invisible is, to the reader, a field that was never added.
    """
    store = tmp_path / "s"
    entry = _add(store)
    shas = ["8e9d1ca49", "6b278c33d"]
    assert BACKLOG.main([
        "verify", entry["id"], "--store", str(store), "--verdict", "CONFIRMED-FIXED",
        "--by", "probe", "--evidence", "re-ran the acceptance command",
        "--status", "fixed", "--fixed-by", *shas, "--commit",
    ]) == 0
    capsys.readouterr()

    assert BACKLOG.main(["show", entry["id"], "--store", str(store)]) == 0
    human = capsys.readouterr().out
    # ONE assertion over the label AND the values on the SAME LINE. Two separate
    # `in human` checks looked equivalent and were not: `resolution` is by
    # definition the authoritative narrative and in practice almost always names
    # the landing commits, so a real entry satisfies both halves from two
    # different fields while `show` prints no fixed_by line at all. Measured
    # against the unfixed code with `resolution="landed in 8e9d1ca49 and
    # 6b278c33d"` and evidence mentioning the words "fixed_by": both assertions
    # passed, green, with the bug fully present. This test was only red today
    # because its own fixture happens to set `resolution=""`.
    assert re.search(rf"^fixed_by\s+.*{shas[0]}.*{shas[1]}", human, re.M), (
        f"`show` has no fixed_by line carrying both shas:\n{human}"
    )


def test_show_can_print_every_field_update_can_write(tmp_path):
    """The reader has to cover the writer, or a new field is invisible by default.

    `fixed_by` was added to MUTABLE_FIELDS and not to `show`'s field order, and it
    stayed that way through the whole feature: stored, validated by `validate`,
    required by the ratchet, and absent from the only human view of an entry. No
    test could go red, because both lists were hand-maintained and neither
    mentioned the other.
    """
    missing = sorted(set(BACKLOG.MUTABLE_FIELDS) - set(BACKLOG.SHOW_FIELD_ORDER))
    assert not missing, f"`update` can write fields `show` will never print: {missing}"


def test_staging_a_closure_writes_no_store_and_no_view(tmp_path, capsys):
    """The whole point of the queue.

    Every store write from a hunter's branch rewrites the 280KB generated view,
    which is the one file parallel branches provably collide on, and it does it
    once per hunter — the O(entries) render that measured 8 mutations/sec. `stage`
    records the SAME closure the hunter would have written, in a gitignored
    append-only file, and the store is touched once per wave instead.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    before = (store / f"{entry['id']}.json").read_bytes()

    assert BACKLOG.main([
        "stage", entry["id"], "--store", str(store), "--queue", str(queue),
        "--verdict", "CONFIRMED-FIXED", "--by", "agent:hunter",
        "--evidence", "uv run pytest ops/tests/test_x.py -q",
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["staged"]["id"] == entry["id"]
    assert payload["staged"]["landed_sha"] is None   # cutover has not run yet

    assert (store / f"{entry['id']}.json").read_bytes() == before, "stage wrote the store"
    rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1
    # The hunter's own evidence travels with it. An integrator who has to invent
    # the evidence at wave end is writing the reason field nobody checked.
    assert rows[0]["evidence"] == "uv run pytest ops/tests/test_x.py -q"
    assert rows[0]["by"] == "agent:hunter"


def test_staging_refuses_bad_verdicts_evidence_and_ids_exactly_as_verify_does(tmp_path):
    """The three refusals `stage` shares with `verify`, and only those.

    Named for what it covers. The previous name claimed `stage` refuses "the same
    things verify refuses", which oversold it: the two commands differ on exactly
    one axis — traceability — and this test never went near it. That axis is now
    closed by construction instead (`stage` pins `status=fixed`, so the rules the
    relaxed check drops all guard statuses it cannot emit); see the anchor-side
    guard in `test_anchor_refuses_a_row_whose_status_is_not_fixed`.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    assert BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                         "--verdict", "TOTALLY-BOGUS", "--by", "x", "--evidence", "y"]) == 64
    assert BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                         "--verdict", "CONFIRMED-FIXED", "--by", "x", "--evidence", "   "]) == 64
    assert BACKLOG.main(["stage", "IMP-20260101-abcdef", "--store", str(store),
                         "--queue", str(queue), "--verdict", "CONFIRMED-FIXED",
                         "--by", "x", "--evidence", "y"]) == 1
    assert not queue.exists() or queue.read_text(encoding="utf-8").strip() == ""


def test_stage_has_no_status_flag_at_all(tmp_path):
    """Pinning the status is what makes anchor's unconditional `fixed_by` honest.

    While `--status` took the whole vocabulary, `stage --status wont-fix` ran green
    from end to end: `_cmd_anchor` hangs `fixed_by=[landed_sha]` on every row it
    replays, so the entry ended up a wont-fix carrying a commit hash — and
    `validate` reported 0 problems, because no rule forbids `fixed_by` on a
    wont-fix. `_check_traceability`'s own docstring says a wont-fix decision is
    "a reason, not a hash".

    A wave exists because the landing commit does not exist yet, and `fixed` is the
    only status that needs one, so there is nothing to express here.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    # argparse EXITS on an unrecognized flag rather than returning; that is the
    # shape of "this flag does not exist", and it is what we want asserted.
    with pytest.raises(SystemExit) as exc:
        BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                      "--verdict", "CONFIRMED-FIXED", "--by", "x", "--evidence", "y",
                      "--status", "wont-fix"])
    assert exc.value.code == 2, "argparse should not know --status"
    assert BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                         "--verdict", "CONFIRMED-FIXED", "--by", "x",
                         "--evidence", "y"]) == 0
    rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [r["status"] for r in rows] == [BACKLOG.STAGED_STATUS] == ["fixed"]


def test_anchor_refuses_a_row_whose_status_is_not_fixed(tmp_path, capsys):
    """The defence for rows `stage` did not write.

    The queue is a plain gitignored jsonl and `unstage` is the sanctioned way in,
    so a hand-written or pre-rule row can still carry any status. Anchor must not
    replay it: the write below attaches `fixed_by` unconditionally, and on any
    other status that is a claim the status contradicts.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    queue.write_text(json.dumps({
        "id": entry["id"], "verdict": "CONFIRMED-FIXED", "by": "x", "evidence": "y",
        "status": "wont-fix", "at": "2026-08-08", "branch": "b",
        "landed_sha": "abc1234",
    }) + "\n", encoding="utf-8")

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] == []
    assert "only 'fixed' can be anchored" in payload["problems"][0]["error"]
    after = json.loads((store / f"{entry['id']}.json").read_text(encoding="utf-8"))
    assert after["status"] == "open" and not after.get("fixed_by")


def test_staging_one_id_twice_refuses_rather_than_replacing_the_first_evidence(tmp_path):
    """Two rows for one entry used to be accepted in silence.

    `anchor` applied both, the second overwrote the first, and `applied` listed the
    id twice. The first hunter's evidence was gone with no warning — and evidence
    silently replaced by someone else's is worse than none, because it still reads
    as attributable to whoever the row now names.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    base = ["stage", entry["id"], "--store", str(store), "--queue", str(queue),
            "--verdict", "CONFIRMED-FIXED"]
    assert BACKLOG.main([*base, "--by", "agent:first", "--evidence", "first cmd"]) == 0
    assert BACKLOG.main([*base, "--by", "agent:second", "--evidence", "second cmd"]) == 64

    rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1 and rows[0]["by"] == "agent:first"

    assert BACKLOG.main([*base, "--by", "agent:second", "--evidence", "second cmd",
                         "--replace"]) == 0
    rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1 and rows[0]["by"] == "agent:second", (
        "--replace must swap the row, not append a second one")


def test_unstage_is_the_way_past_a_row_that_blocks_the_whole_wave(tmp_path, capsys):
    """`anchor` is all-or-nothing, so one unusable row stops everyone.

    Without an escape verb the only way out is hand-editing the queue file, and
    this module's standing policy is that the ledger is reached through this CLI.
    An all-or-nothing gate with no way past does not get rows fixed; it gets the
    file edited, and nothing constrains what else changes in there.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    good, bad = _add(store, detail="keeps"), _add(store, detail="blocks")
    for entry in (good, bad):
        assert BACKLOG.main(["stage", entry["id"], "--store", str(store),
                             "--queue", str(queue), "--verdict", "CONFIRMED-FIXED",
                             "--by", "x", "--evidence", "y"]) == 0
    _stamp_queue(queue, good["id"], "aaaaaaa11")
    _stamp_queue(queue, bad["id"], "bbbbbbb22")
    (store / f"{bad['id']}.json").unlink()          # whatever makes it unusable

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit"]) == 2
    capsys.readouterr()

    assert BACKLOG.main(["unstage", bad["id"], "--queue", str(queue), "--json"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["mode"] == "dry-run" and len(dry["dropped"]) == 1
    assert len([ln for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 2, \
        "a dry-run unstage must not touch the queue"

    assert BACKLOG.main(["unstage", bad["id"], "--queue", str(queue), "--commit"]) == 0
    assert BACKLOG.main(["unstage", bad["id"], "--queue", str(queue), "--commit"]) == 64
    capsys.readouterr()
    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == [good["id"]]


def test_a_malformed_queue_line_is_named_rather_than_swallowed(tmp_path, capsys):
    """The queue has two readers and they used to have two policies.

    `worktree_orchestrate._read_anchor_queue` swallows a bad file and returns `[]`,
    which is right for a step that has already moved the trunk. `anchor` has moved
    nothing, so it must say what is wrong and where — and the recovery has to be
    stated, because this is the one ledger file policy allows a human to edit.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    queue.write_text('{"id": "IMP-0001", "verdict": "CONFIRMED-FIXED"\n', encoding="utf-8")
    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue)]) == 64
    err = capsys.readouterr().err
    assert f"{queue}:1" in err, "the error must name the file and the line"
    assert "delete the bad line" in err, "the error must state the recovery"


def test_the_queue_lock_is_the_same_file_in_both_modules(tmp_path):
    """Two spellings of the lock name would be two locks and no serialization.

    `backlog.py` guards the queue with its own `_queue_lock`; `worktree_orchestrate
    ._stamp_anchor_queue` reaches the same file through `worktree_registry
    ._ledger_lock`. Both must resolve to the identical path — `with_suffix('.lock')`
    instead of `with_name(name + '.lock')` strips `.jsonl` and yields a different
    file, at which point each process holds its own lock, every test still passes,
    and the rows go on disappearing. Nothing else in the suite would notice.
    """
    import importlib.util

    def _load(name):
        spec = importlib.util.spec_from_file_location(name, ROOT / "ops" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(name, mod)
        spec.loader.exec_module(mod)
        return mod

    registry = _load("worktree_registry")
    queue = tmp_path / ".cache" / "backlog_anchor_queue.jsonl"

    with BACKLOG._queue_lock(queue):
        locks = list((tmp_path / ".cache").glob("*.lock"))
    assert len(locks) == 1, f"expected exactly one lock file, got {locks}"

    with registry._ledger_lock(queue):
        pass
    assert sorted(p.name for p in (tmp_path / ".cache").glob("*.lock")) == \
        [locks[0].name], "the two modules lock different files"


def test_two_concurrent_stages_cannot_lose_each_others_row(tmp_path):
    """Real OS processes, and the read->write gap widened on purpose.

    `read_queue` + append + `write_queue` is a read-modify-write of one shared file.
    `_write_atomic` makes each WRITE all-or-nothing and does nothing for the gap
    between them. Measured before the lock, staging distinct ids concurrently:

        N=2 → rows lost in 6 of 6 rounds     N=24 → 16/19/21/18/19 of 24 survived

    and every loser printed `[staged]` and exited 0. Nothing downstream notices — no
    row means `cutover` never stamps it, so `resolve` cannot mention it, so the store
    still reads the entry as open, with the work that closed it nowhere on disk.

    The gap is widened rather than raced at speed because "it did not happen at N=4"
    is not "it cannot happen": a slower disk or a bigger store brings it back. Widening
    it INSIDE the critical section is also the sharper test — a lock that only works
    when the section is short is not a lock.

    The sleep goes into a COPY of the module, so nothing in the shipped file exists
    only to make a test pass.
    """
    repo = tmp_path / "repo"
    (repo / "docs" / "runbook" / "backlog").mkdir(parents=True)
    (repo / "ops").mkdir()
    src = BACKLOG_PATH.read_text(encoding="utf-8")
    anchor = "        clash = [r for r in rows if r.get(\"id\") == args.id]"
    assert src.count(anchor) == 1, "the stage RMW moved; re-anchor this probe"
    (repo / "ops" / "backlog.py").write_text(
        src.replace(anchor,
                    "        __import__('time').sleep(float(os.environ.get("
                    "'KG_TEST_STAGE_DELAY', '0')))\n" + anchor),
        encoding="utf-8")
    # The module imports `lib.streaming_command` (the heartbeat runner both readers
    # of `acceptance_cmd` go through), so a copy of the FILE is not a copy of the
    # TOOL. Copied rather than made lazy on purpose: a lazy import would let this
    # probe pass against a checkout where the real command dies halfway through a
    # sweep, which moves the failure from setup time to the middle of a gate.
    shutil.copytree(BACKLOG_PATH.parent / "lib", repo / "ops" / "lib")
    assert (repo / "ops" / "lib" / "streaming_command.py").exists(), (
        "the probe stopped shipping the module's own dependency")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    store, queue = repo / "s", repo / "q.jsonl"
    tool = str(repo / "ops" / "backlog.py")
    ids = []
    for tag in ("alpha", "beta"):
        out = subprocess.run(
            [sys.executable, tool, "add", "--stream", "IMP", "--date", "2026-08-08",
             "--source", tag, "--category", "tool", "--severity", "low",
             "--detail", f"concurrent stage probe {tag}", "--store", str(store),
             "--json"], cwd=repo, text=True, capture_output=True)
        assert out.returncode == 0, out.stderr
        ids.append(json.loads(out.stdout)["entry"]["id"])

    def stage(entry_id, who, delay="0"):
        return subprocess.run(
            [sys.executable, tool, "stage", entry_id, "--store", str(store),
             "--queue", str(queue), "--verdict", "CONFIRMED-FIXED", "--by", who,
             "--evidence", f"{who} ran it"],
            cwd=repo, text=True, capture_output=True,
            env={**os.environ, "KG_TEST_STAGE_DELAY": delay})

    import threading
    results = {}
    thread = threading.Thread(
        target=lambda: results.update(slow=stage(ids[0], "agent:slow", delay="3")))
    thread.start()
    time.sleep(0.6)                     # let the slow stager get past its read
    results["fast"] = stage(ids[1], "agent:fast")
    thread.join(timeout=60)

    assert results["slow"].returncode == 0, results["slow"].stderr
    assert results["fast"].returncode == 0, results["fast"].stderr

    rows = {r["id"]: r for r in
            (json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines()
             if ln.strip())}
    assert set(rows) == set(ids), (
        f"a staged row was lost: queued {sorted(rows)}, staged {sorted(ids)} — "
        f"the queue's read-modify-write is not serialized")


def test_a_stage_that_cannot_take_the_lock_refuses_instead_of_appending(tmp_path):
    """Fail-closed, and the opposite of `_view_lock`'s policy on purpose.

    `_view_lock` proceeds unlocked when it cannot acquire, because by then the
    mutation has landed and refusing would not unmake it. Here nothing has been
    written yet, and an unlocked append is exactly how rows vanish in silence — so
    the honest answer is to refuse and say why.
    """
    store = tmp_path / "s"
    queue = tmp_path / "nowhere" / "q.jsonl"
    entry = _add(store)
    (tmp_path / "nowhere").write_text("a file where the lock's directory should be\n")

    with pytest.raises(BACKLOG.BacklogError) as exc:
        with BACKLOG._queue_lock(queue):
            pass
    assert "refusing to stage" in str(exc.value)

    assert BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue",
                         str(queue), "--verdict", "CONFIRMED-FIXED", "--by", "x",
                         "--evidence", "y"]) == 64
    assert not queue.exists()


def test_anchor_will_not_close_an_entry_on_a_commit_that_never_landed(tmp_path, capsys):
    """An unstamped row is a branch that was staged and then abandoned.

    Closing it would put a `fixed` status on work that is on no trunk at all, and
    `fixed_by` would have nothing to point at. The row is reported, not applied,
    and not silently dropped either.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                  "--verdict", "CONFIRMED-FIXED", "--by", "x", "--evidence", "ran it"])
    capsys.readouterr()

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] == []
    assert payload["unstamped"] == [entry["id"]]
    assert BACKLOG.load_entry(store, entry["id"])["status"] == "open"
    # still queued: an unstamped row is waiting for its cutover, not garbage
    assert queue.read_text(encoding="utf-8").strip() != ""


def test_anchor_closes_the_whole_wave_in_one_pass(tmp_path, capsys):
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    a = _add(store, detail="first wave entry")
    b = _add(store, detail="second wave entry")
    for entry, sha in ((a, "aaaaaaa11"), (b, "bbbbbbb22")):
        BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                      "--verdict", "CONFIRMED-FIXED", "--by", "agent:hunter",
                      "--evidence", f"ran the acceptance for {entry['id']}"])
        _stamp_queue(queue, entry["id"], sha)
    capsys.readouterr()

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["applied"]) == sorted([a["id"], b["id"]])

    for entry, sha in ((a, "aaaaaaa11"), (b, "bbbbbbb22")):
        written = BACKLOG.load_entry(store, entry["id"])
        assert written["status"] == "fixed"
        assert written["fixed_by"] == [sha]
        assert written["verdict"] == "CONFIRMED-FIXED"
        assert written["verified_by"] == "agent:hunter"
        assert entry["id"] in written["verified_evidence"]
    # consumed rows leave the queue, so a re-run is a no-op rather than a re-close
    assert queue.read_text(encoding="utf-8").strip() == ""
    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == []


def test_a_dry_run_anchor_changes_nothing(tmp_path, capsys):
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    entry = _add(store)
    BACKLOG.main(["stage", entry["id"], "--store", str(store), "--queue", str(queue),
                  "--verdict", "CONFIRMED-FIXED", "--by", "x", "--evidence", "ran it"])
    _stamp_queue(queue, entry["id"], "ccccccc33")
    before_entry = (store / f"{entry['id']}.json").read_bytes()
    before_queue = queue.read_bytes()
    capsys.readouterr()

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert (store / f"{entry['id']}.json").read_bytes() == before_entry
    assert queue.read_bytes() == before_queue


def test_anchor_refuses_the_whole_wave_rather_than_closing_half_of_it(tmp_path, capsys):
    """One bad row must not leave the store half-migrated.

    The queue is the only record of what a wave closed. If anchor applied rows
    until one failed, the consumed prefix would be gone from the queue and the
    rest would still be there, and nobody could tell from either side which
    entries had been dealt with.
    """
    store = tmp_path / "s"
    queue = tmp_path / "q.jsonl"
    good = _add(store, detail="a closable entry")
    BACKLOG.main(["stage", good["id"], "--store", str(store), "--queue", str(queue),
                  "--verdict", "CONFIRMED-FIXED", "--by", "x", "--evidence", "ran it"])
    _stamp_queue(queue, good["id"], "ddddddd44")
    # a row naming an entry that has since been dropped from the store
    with queue.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "IMP-20260101-abcdef", "verdict": "CONFIRMED-FIXED",
                             "by": "x", "evidence": "ran it", "status": "fixed",
                             "at": "2026-08-07", "branch": "feat/gone",
                             "landed_sha": "eeeeeee55"}) + "\n")
    before = (store / f"{good['id']}.json").read_bytes()
    capsys.readouterr()

    rc = BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                       "--commit", "--json"])
    assert rc != 0
    payload = json.loads(capsys.readouterr().out)
    assert "IMP-20260101-abcdef" in str(payload)
    # The refusal payload must not claim it applied the rows it did not apply. It
    # returns before the write loop, so `applied` is a field computed on a path that
    # never wrote — easy to leave optimistic, and a machine caller reading it would
    # record closures that are not in the store.
    assert payload["applied"] == [], f"refusal claims it applied {payload['applied']}"
    assert payload["would_apply"] == [good["id"]]
    assert (store / f"{good['id']}.json").read_bytes() == before, "a refused wave still wrote"
    assert len(queue.read_text(encoding="utf-8").strip().splitlines()) == 2


# --------------------------------------------------------------------------
# 18. acceptance stops being write-only (IMP-20260808-9f3838)
# --------------------------------------------------------------------------

def _stage_and_stamp(store, queue, entry_id, capsys=None, sha="aaaaaaa11"):
    """Stage a closure and mark it landed, draining stdout on the way out.

    `capsys` is drained because `stage` prints a human line and the tests below
    parse `anchor`'s JSON out of the same buffer — leaving it in makes
    `json.loads` fail on the FIRST test that adds a stage, which reads as a bug in
    anchor rather than in the fixture.
    """
    assert BACKLOG.main(["stage", entry_id, "--store", str(store), "--queue", str(queue),
                         "--verdict", "CONFIRMED-FIXED", "--by", "agent:hunter",
                         "--evidence", "ran the suite"]) == 0
    _stamp_queue(queue, entry_id, sha)
    if capsys is not None:
        capsys.readouterr()


def test_anchor_runs_the_acceptance_command_before_closing(tmp_path, capsys):
    """The one step that asks whether the defect is actually GONE.

    Everything else `anchor` checks is about the closure being well-formed.
    `status: fixed` with a reachable `fixed_by` proves a commit exists — not that
    the problem it claims to fix stopped happening. `acceptance` was supposed to
    close that gap and was write-only: `GROOM_REQUIRES` checked it was non-empty
    and no line of code ever read it again (measured: of 17 entries both groomed
    and closed, at most 9 shared any 4+ character token with their closure text,
    and token overlap is not evidence a command ran).
    """
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    marker = tmp_path / "it-ran"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd=f"touch {marker} && true"))
    _stage_and_stamp(store, queue, entry["id"], capsys)

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert marker.exists(), "the acceptance command was never actually run"
    assert payload["applied"] == [entry["id"]]
    ran = payload["acceptance"]["ran"]
    assert [r["id"] for r in ran] == [entry["id"]]
    assert ran[0]["ok"] is True and ran[0]["rc"] == 0
    assert BACKLOG.load_entry(store, entry["id"])["status"] == "fixed"


def test_anchor_refuses_the_wave_when_the_acceptance_does_not_hold(tmp_path, capsys):
    """A closure whose own nominated proof fails is not a closure.

    All-or-nothing, same as every other anchor refusal: the failing entry takes the
    wave down rather than letting the others through, because a wave that lands
    around a false closure has already published the wrong answer.
    """
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    good, bad = _add(store, detail="really fixed"), _add(store, detail="not really")
    BACKLOG.update_entry(store, good["id"], **_groom_kwargs(acceptance_cmd="true"))
    BACKLOG.update_entry(store, bad["id"], **_groom_kwargs(acceptance_cmd="false"))
    for e in (good, bad):
        _stage_and_stamp(store, queue, e["id"], capsys)

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] == []
    assert any(p["id"] == bad["id"] and "acceptance did not hold" in p["error"]
               for p in payload["problems"]), payload["problems"]
    # the innocent one is untouched AND still queued — nothing was half-applied
    assert BACKLOG.load_entry(store, good["id"])["status"] == "open"
    assert len([ln for ln in queue.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 2


def test_anchor_honours_an_inverted_acceptance(tmp_path, capsys):
    """`expect_rc` is not decoration.

    Measured on the real store: IMP-20260805-afc14b's acceptance is a DETECTOR —
    "exit 1 = the phenomenon this entry describes still holds". Demanding rc 0
    would grade every such entry backwards, which is worse than not checking:
    a check that is wrong in a known direction gets switched off, and takes the
    correct ones with it.
    """
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd="false", acceptance_expect_rc=1))
    _stage_and_stamp(store, queue, entry["id"], capsys)

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["acceptance"]["ran"][0]["ok"] is True
    assert payload["acceptance"]["ran"][0]["rc"] == 1


def test_anchor_counts_what_it_could_not_check(tmp_path, capsys):
    """The unverifiable set is a NUMBER, reported at the moment of closing.

    `acceptance_manual` is not a loophole and the difference is where the count
    shows up: an absence is invisible, a declared exemption is queryable
    (`list --acceptance-manual`) and appears in the wave's own payload. The failure
    this replaces was silence — nobody could have said how many closures rested on
    nothing, because nothing recorded it.
    """
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    checked = _add(store, detail="machine-checkable")
    declared = _add(store, detail="needs a device")
    silent = _add(store, detail="groomed before the rule existed")
    BACKLOG.update_entry(store, checked["id"], **_groom_kwargs(acceptance_cmd="true"))
    BACKLOG.update_entry(store, declared["id"], **_groom_kwargs(
        acceptance_cmd=None, acceptance_expect_rc=None,
        acceptance_manual="needs a physical device on a live backend"))
    BACKLOG.update_entry(store, silent["id"], **_groom_kwargs(
        acceptance_cmd=None, acceptance_expect_rc=None))
    for e in (checked, declared, silent):
        _stage_and_stamp(store, queue, e["id"], capsys)

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--commit", "--json"]) == 0
    acc = json.loads(capsys.readouterr().out)["acceptance"]
    assert [r["id"] for r in acc["ran"]] == [checked["id"]]
    assert acc["manual"] == [declared["id"]]
    assert acc["unproven"] == [silent["id"]], (
        "an entry with neither proof must be counted, not quietly lumped in with "
        "the ones that declared why")

    manual = BACKLOG.list_entries(store, acceptance_manual=True)
    assert [p["id"] for p in manual] == [declared["id"]]


def test_a_dry_run_anchor_does_not_run_acceptance_commands(tmp_path, capsys):
    """These are real commands with real side effects. A dry-run that ran them
    would not be one — and the store's acceptance strings include `rm`, container
    restarts and network calls."""
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    marker = tmp_path / "should-not-exist"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd=f"touch {marker}"))
    _stage_and_stamp(store, queue, entry["id"], capsys)

    assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                         "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert not marker.exists(), "a dry-run executed the acceptance command"
    assert payload["acceptance"]["ran"] == []
    assert payload["would_apply"] == [entry["id"]]


def test_new_grooming_must_carry_a_proof_and_old_grooming_is_grandfathered(tmp_path):
    """Ratcheted by DATE, and the choice is load-bearing.

    `groomed_at` is written at groom time, so re-grooming an old entry stamps
    today's date and the rule binds it. An id baseline would forgive that entry
    forever — the opposite of what a ratchet is for. Turning all 49 pre-existing
    groomed entries red on day one would have made the rule the thing to route
    around; 39 already carry a runnable command, 5 need a device, 5 are prose no
    command expresses.

    The rule is asserted on constructed payloads because `update_entry` validates
    BEFORE writing, so a violation cannot be persisted through it — which is the
    stronger guarantee, and gets its own assertion at the end rather than being
    assumed.
    """
    store = tmp_path / "s"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs())
    groomed = BACKLOG.load_entry(store, entry["id"])
    no_proof = {**groomed, "acceptance_cmd": "", "acceptance_expect_rc": None,
                "acceptance_manual": ""}

    old = {**no_proof, "groomed_at": "2026-07-01"}
    assert BACKLOG.validate_entry(old) == [], "pre-existing grooming was not grandfathered"

    fresh = {**no_proof, "groomed_at": BACKLOG.ACCEPTANCE_PROOF_SINCE}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(fresh)]
    assert "groom-claim-without-acceptance-proof" in kinds, kinds

    # either proof satisfies it
    assert BACKLOG.validate_entry({**fresh, "acceptance_manual": "needs a device"}) == []
    assert BACKLOG.validate_entry({**fresh, "acceptance_cmd": "true",
                                   "acceptance_expect_rc": 0}) == []
    # both together do not: two contradictory claims about the same question, one
    # saying a machine settles it and one saying nothing can
    both = {**fresh, "acceptance_cmd": "true", "acceptance_expect_rc": 0,
            "acceptance_manual": "needs a device"}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(both)]
    assert "groom-claim-with-conflicting-acceptance-proof" in kinds, kinds

    # and the stronger half: the violation cannot be written through the CLI path
    with pytest.raises(ValueError, match="groom-claim-without-acceptance-proof"):
        BACKLOG.update_entry(store, entry["id"],
                             groomed_at=BACKLOG.ACCEPTANCE_PROOF_SINCE,
                             acceptance_cmd="", acceptance_manual="")


def test_the_acceptance_expectation_is_shape_checked(tmp_path):
    """`anchor` compares `rc == expect_rc` with `==`, so a string `"0"` from a
    hand-edited entry would never match the int a subprocess returns — refusing
    every wave that carried it, and blaming the fix rather than the field.

    `bool` is rejected by NAME rather than coerced: `True` is an `int` in Python
    and `True == 1`, so a JSON `true` would silently mean "expect exit 1".
    """
    store = tmp_path / "s"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs())
    payload = BACKLOG.load_entry(store, entry["id"])

    for value, kind in ((True, "acceptance-expect-rc-not-an-int"),
                        ("0", "acceptance-expect-rc-not-an-int"),
                        (300, "acceptance-expect-rc-out-of-range"),
                        (-1, "acceptance-expect-rc-out-of-range")):
        probe = {**payload, "acceptance_expect_rc": value}
        kinds = [p["kind"] for p in BACKLOG.validate_entry(probe)]
        assert kind in kinds, f"{value!r} was accepted as an exit code: {kinds}"

    orphan = {**payload, "acceptance_cmd": "", "acceptance_expect_rc": 0,
              "acceptance_manual": "x"}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(orphan)]
    assert "acceptance-expect-rc-without-cmd" in kinds, (
        "an expectation with nothing to expect it of would never be read")


# --------------------------------------------------------------------------
# 19. in-progress is derived, not stored (IMP-20260808-439594)
# --------------------------------------------------------------------------

def _ledger(anchor: Path, *records) -> Path:
    (anchor / ".cache").mkdir(parents=True, exist_ok=True)
    path = anchor / ".cache" / "worktree_registry.json"
    path.write_text(json.dumps({"records": list(records)}), encoding="utf-8")
    return path


def test_in_progress_is_retired_and_the_refusal_says_what_replaced_it(tmp_path):
    """It never had mechanical behaviour of its own.

    Every rule in `_check_traceability` that named `triaged` named `in-progress`
    too, in the same set — two status values, one set of obligations. What removed
    it is that the claim plane made the same fact real: the ledger records which
    worktree holds which ticket, so "somebody is working on this" is derivable, and
    a stored copy of a derivable fact is a copy that drifts.

    Named separately from `bad-status`: "a value that never existed" and "a value
    that was retired, and here is its replacement" are different problems with
    different fixes, and a generic refusal would send the reader hunting a typo.
    """
    assert "in-progress" not in BACKLOG.STATUSES
    store = tmp_path / "s"
    entry = _add(store)
    stale = {**BACKLOG.load_entry(store, entry["id"]), "status": "in-progress"}

    problems = BACKLOG.validate_entry(stale)
    retired = [p for p in problems if p["kind"] == "retired-status"]
    assert retired, [p["kind"] for p in problems]
    assert retired[0]["use_instead"] == "triaged"
    assert not [p for p in problems if p["kind"] == "bad-status"], (
        "a retired value must not ALSO read as a typo")

    # still LOADABLE — a hard removal turns a cleanup into an outage for every
    # pre-existing entry and every branch that predates this
    assert stale["status"] == "in-progress"


def test_a_released_claim_disappears_from_the_derived_view(tmp_path):
    """The case the stored status could never handle, and the reason for the change.

    `cmd_resolve` changes the ledger record's status and never looks at the entry,
    so an abandoned worktree left its ticket `in-progress` forever with nothing to
    notice. Measured the day this landed: the store's single `in-progress` entry
    named an owner and a branch (`debug/ios-lock-wait-heartbeat`) that no longer
    existed, while the ledger's only active claim was on a completely different
    ticket. Derivation makes that state unrepresentable.
    """
    anchor = tmp_path / "repo"
    active = {"status": "active", "branch": "feat/x", "path": "/wt/x",
              "backlog": ["IMP-0001"], "claimed_at": "2026-08-08T00:00:00Z"}
    _ledger(anchor, active)
    assert set(BACKLOG.held_tickets(anchor)) == {"IMP-0001"}

    _ledger(anchor, {**active, "status": "merged"})
    assert BACKLOG.held_tickets(anchor) == {}, (
        "a resolved worktree still showed as holding its ticket")


def test_the_derived_claim_is_fail_soft(tmp_path):
    """A ledger problem must not make the backlog unreadable.

    This is a convenience column on a READ command. No ledger (a fresh clone),
    a corrupt one, and one from an older schema all mean the same thing to a
    reader — "cannot say" — and none of them is a reason to refuse to list.
    """
    anchor = tmp_path / "repo"
    (anchor / ".cache").mkdir(parents=True)
    assert BACKLOG.held_tickets(anchor) == {}                    # missing

    (anchor / ".cache" / "worktree_registry.json").write_text("{oh no", encoding="utf-8")
    assert BACKLOG.held_tickets(anchor) == {}                    # corrupt

    (anchor / ".cache" / "worktree_registry.json").write_text('{"v": 1}', encoding="utf-8")
    assert BACKLOG.held_tickets(anchor) == {}                    # no `records`

    _ledger(anchor, {"status": "active", "branch": "b", "backlog": None})
    assert BACKLOG.held_tickets(anchor) == {}                    # active, claims nothing


def test_list_says_the_claim_column_is_per_machine(tmp_path, capsys, monkeypatch):
    """Empty here means "nobody on THIS machine", not "nobody".

    The ledger is gitignored and describes this checkout's worktrees. Rendering an
    empty column without saying so would rebuild the same false confidence the
    stored status produced, one layer down — an agent on the other machine would
    read "free" and take a ticket somebody is already holding.
    """
    store = tmp_path / "s"
    held_entry, free_entry = _add(store, detail="someone has it"), _add(store, detail="free")
    monkeypatch.setattr(BACKLOG, "held_tickets", lambda *a, **k: {
        held_entry["id"]: {"branch": "feat/x", "path": "/wt/x",
                           "claimed_at": "2026-08-08T00:00:00Z"}})

    assert BACKLOG.main(["list", "--store", str(store)]) == 0
    human = capsys.readouterr().out
    assert "feat/x" in human, "the holder's branch is not shown"
    assert "per-machine" in human or "THIS MACHINE" in human, (
        "an empty column that does not state its scope reads as 'nobody is on it'")

    assert BACKLOG.main(["list", "--store", str(store), "--held", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in payload["entries"]] == [held_entry["id"]]
    assert payload["held_scope"] == "this machine's worktrees only"
    # alongside the entries, NOT merged into them: a caller that round-tripped this
    # into the store would be re-inventing the field this change removed
    assert "held" not in payload["entries"][0]


def test_an_acceptance_command_that_cannot_parse_is_refused(tmp_path):
    """An unparseable command is not a criterion.

    Stored without this floor it runs at anchor time and exits 2 — which reads as
    "the defect is back" and sends whoever is closing the entry to debug the FIX
    rather than the field. Measured twice in one session while transcribing agent
    output into the store: a dropped closing quote and a mangled `&&` both landed
    silently, and only surfaced when the whole batch was re-run and reconciled
    against the exit codes the agents had reported.

    A SYNTAX floor, deliberately not a semantic one: `bash -n` can say a shell
    could read the command, never that it measures the right thing.
    """
    store = tmp_path / "s"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs())
    payload = BACKLOG.load_entry(store, entry["id"])

    broken = {**payload, "acceptance_cmd": 'grep -q "unterminated ops/x.py'}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(broken)]
    assert "acceptance-cmd-does-not-parse" in kinds, kinds

    # and the write path refuses it too, so a broken criterion cannot reach the store
    with pytest.raises(ValueError, match="acceptance-cmd-does-not-parse"):
        BACKLOG.update_entry(store, entry["id"],
                             acceptance_cmd='echo "still open')

    # a well-formed one still passes — the floor must not reject shell it simply
    # finds unusual (process substitution, subshells, non-ASCII in strings)
    ok = {**payload, "acceptance_cmd":
          'bash -c \'set -e; test "$(echo 中文)" = "中文"\' && ! grep -q x /dev/null'}
    assert [p for p in BACKLOG.validate_entry(ok)
            if p["kind"].startswith("acceptance-cmd")] == []


def test_add_refuses_groom_flags_by_name_and_says_where_they_belong(tmp_path, capsys):
    """argparse says the flag is wrong; it never says where the correction goes.

    Measured: the same mistake three times in ONE session, by someone who had
    already filed an entry about it. That is not carelessness — the flags read as
    if they should work, because filing and grooming feel like one act right up
    until the tool disagrees.

    The separation itself stays: merging grooming into `add` would make "pretend
    you worked it out at filing time" free, and being non-free is the entire value
    of the badge. What changes is that the refusal names the flag and the route.

    Every groom-only flag is covered by iterating the module's own list, so a flag
    added to `update` and forgotten here is caught by the same test rather than by
    a fourth incident.
    """
    store = tmp_path / "s"
    base = ["add", "--store", str(store), "--stream", "IMP", "--date", "2026-08-08",
            "--source", "t", "--category", "tool", "--severity", "low",
            "--detail", "probe"]
    for flag in BACKLOG.GROOM_ONLY_FLAGS:
        value = "0" if flag.endswith("-rc") else "x"
        assert BACKLOG.main([*base, flag, value]) == 64, flag
        err = capsys.readouterr().err
        assert flag in err, f"{flag} was refused without being named: {err}"
        assert "update" in err, f"{flag}'s refusal does not say where it belongs: {err}"
    # nothing was written on any of those refusals
    assert not list(store.glob("*.json")) if store.exists() else True
    # ...and the ordinary path still works
    assert BACKLOG.main([*base, "--json"]) == 0
    capsys.readouterr()
    assert len(list(store.glob("*.json"))) == 1


# --------------------------------------------------------------------------
# 21. one acceptance gate, every door to `fixed` (IMP-20260808-3646f3)
#
# `acceptance_cmd` is the only field that makes `fixed` mean something a machine
# checked, and section 18 wired it into exactly ONE of the three ways an entry
# reaches that status. `update --status fixed` and `verify --status fixed` both
# wrote it while checking only traceability — "a commit exists" — which is not
# the same claim. Worse, the two kinds of `fixed` were indistinguishable in the
# store afterwards, so nobody could have counted how many closures rested on
# nothing.
#
# The tests below are written against the DOORS, not against the helper, and one
# of them asserts that a single implementation serves all three: three copies of
# this check would be three things to forget next time, which is how the hole
# got here.
# --------------------------------------------------------------------------


def _groomed(store, cmd="true", expect_rc=0, **overrides):
    entry = _add(store, **overrides)
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd=cmd,
                                         acceptance_expect_rc=expect_rc))
    return entry


def test_update_acceptance_cmd_selector_count_is_printed(tmp_path, capsys):
    """Writing a pytest ``-k`` criterion exposes how many tests it selects."""
    store = tmp_path / "s"
    tests = tmp_path / "test_selector_probe.py"
    tests.write_text(
        "def test_needlealpha_first(): pass\n"
        "def test_needlealpha_second(): pass\n"
        "def test_other(): pass\n",
        encoding="utf-8",
    )
    entry = _add(store)
    cmd = (
        "uv run --no-project --python 3.13 --with pytest pytest -q "
        f"-p no:cacheprovider {tests} -k needlealpha"
    )

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--acceptance-cmd", cmd, "--commit", "--json"]) == 0
    err = capsys.readouterr().err
    assert "selector-count" in err and "selected=2" in err, err
    assert BACKLOG.load_entry(store, entry["id"])["acceptance_cmd"] == cmd


def test_update_acceptance_cmd_zero_selector_count_is_visible_but_nonblocking(
        tmp_path, capsys):
    """A zero-selection probe is evidence for the author, not a write refusal."""
    store = tmp_path / "s"
    tests = tmp_path / "test_selector_probe.py"
    tests.write_text("def test_other(): pass\n", encoding="utf-8")
    entry = _add(store)
    cmd = (
        "uv run --no-project --python 3.13 --with pytest pytest -q "
        f"-p no:cacheprovider {tests} -k needle_never_matches"
    )

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--acceptance-cmd", cmd, "--commit", "--json"]) == 0
    err = capsys.readouterr().err
    assert "selector-count" in err and "selected=0" in err, err
    assert BACKLOG.load_entry(store, entry["id"])["acceptance_cmd"] == cmd


def test_update_acceptance_cmd_selector_count_unavailable_probe_is_nonblocking(
        tmp_path, capsys, monkeypatch):
    """A missing probe executable must not abort the criterion write."""
    store = tmp_path / "s"
    entry = _add(store)
    cmd = "pytest -q -k needlealpha"

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("pytest")

    monkeypatch.setattr(BACKLOG, "run_streamed_command", unavailable)
    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--acceptance-cmd", cmd, "--commit", "--json"]) == 0
    err = capsys.readouterr().err
    assert "selected=unavailable" in err and "non-blocking" in err, err
    assert BACKLOG.load_entry(store, entry["id"])["acceptance_cmd"] == cmd


def test_update_refuses_to_close_when_the_acceptance_is_red(tmp_path, capsys):
    """The door most likely to be used by hand, and it checked nothing.

    A backfill, a re-verification, a single ticket closed by an agent that never
    went through the wave — all of them arrive here, and all of them could write
    `fixed` over a criterion that fails today.
    """
    store = tmp_path / "s"
    entry = _groomed(store, cmd="false")

    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--status", "fixed", "--fixed-by", "aaaaaaa11",
                       "--commit", "--json"])

    assert rc != 0, "a red acceptance closed the entry anyway"
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "acceptance did not hold" in payload["error"], payload["error"]
    # Nothing half-written: the refusal happens before the store is touched.
    after = BACKLOG.load_entry(store, entry["id"])
    assert after["status"] == "open" and not after.get("fixed_by")


def test_verify_refuses_to_close_when_the_acceptance_is_red(tmp_path, capsys):
    """`verify --status fixed` is documented in its own parser as "the natural
    closing act". It has to answer the same question as the wave does."""
    store = tmp_path / "s"
    entry = _groomed(store, cmd="false")

    rc = BACKLOG.main(["verify", entry["id"], "--store", str(store),
                       "--verdict", "CONFIRMED-FIXED", "--by", "probe",
                       "--evidence", "ran the suite", "--status", "fixed",
                       "--fixed-by", "aaaaaaa11", "--commit", "--json"])

    assert rc != 0, "a red acceptance closed the entry anyway"
    payload = json.loads(capsys.readouterr().out)
    assert "acceptance did not hold" in payload["error"], payload["error"]
    assert BACKLOG.load_entry(store, entry["id"])["status"] == "open"


def test_the_refusal_names_the_rc_and_shows_what_the_command_said(tmp_path, capsys):
    """A refusal that says only "it failed" sends the reader to debug the fix.

    The two facts that tell them where to look instead are the exit code (was it
    the criterion or the harness?) and the command's own last words.

    The probe COMPUTES its output rather than echoing a literal, and that detail is
    the test. The first version ran `echo 'the regression is back' >&2` and asserted
    that phrase appeared — which it did, from the refusal quoting the COMMAND back.
    Deleting the output_tail line entirely left that version green: the assertion had
    two possible producers and could not name which one satisfied it.
    """
    store = tmp_path / "s"
    entry = _groomed(store, cmd="awk 'BEGIN{print 6*7}' >&2; exit 3")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--fixed-by", "aaaaaaa11",
                         "--commit", "--json"]) != 0
    error = json.loads(capsys.readouterr().out)["error"]
    assert "exited 3" in error, error
    assert "42" in error, (
        f"only the command could have produced '42' — its text does not contain "
        f"it, so this proves the output reached the reader: {error}")


def test_update_runs_the_acceptance_and_says_so_in_the_payload(tmp_path, capsys):
    """Green closes, and the closure carries its own evidence grade.

    Without the payload block, a machine reading the store back could not tell a
    `fixed` a command proved from a `fixed` somebody asserted — which is the half
    of this defect that survives after the refusal is in place.
    """
    store = tmp_path / "s"
    marker = tmp_path / "it-ran"
    entry = _groomed(store, cmd=f"touch {marker} && true")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--fixed-by", "aaaaaaa11",
                         "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert marker.exists(), "the acceptance command was never actually run"
    assert payload["acceptance"]["kind"] == "ran"
    assert payload["acceptance"]["ok"] is True and payload["acceptance"]["rc"] == 0
    assert BACKLOG.load_entry(store, entry["id"])["status"] == "fixed"


def test_a_dry_run_update_does_not_run_acceptance_commands(tmp_path, capsys):
    """Same contract as `anchor`'s dry run, for the same reason: the real store's
    acceptance strings include `rm`, container restarts and network calls."""
    store = tmp_path / "s"
    marker = tmp_path / "should-not-exist"
    entry = _groomed(store, cmd=f"touch {marker}")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--fixed-by", "aaaaaaa11",
                         "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert not marker.exists(), "a dry-run executed the acceptance command"
    assert payload["acceptance"]["kind"] == "would-run"
    assert payload["acceptance"]["cmd"].startswith("touch ")


def test_closing_without_a_proof_is_allowed_and_counted_not_silent(tmp_path, capsys):
    """The unverifiable closure is not forbidden — it is LABELLED.

    Forbidding it would only move the work outside the tool; there are real
    entries whose acceptance needs a physical device. What must not happen is
    the two kinds arriving in the store looking identical.
    """
    store = tmp_path / "s"
    declared = _add(store, detail="needs a device")
    BACKLOG.update_entry(store, declared["id"], **_groom_kwargs(
        acceptance_cmd=None, acceptance_expect_rc=None,
        acceptance_manual="needs a physical device on a live backend"))
    silent = _add(store, detail="never groomed at all")

    for entry, kind in ((declared, "manual"), (silent, "unproven")):
        assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                             "--status", "fixed", "--fixed-by", "aaaaaaa11",
                             "--commit", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["acceptance"]["kind"] == kind


def test_updating_a_field_that_is_not_the_status_runs_nothing(tmp_path, capsys):
    """The gate fires on the ACT of closing, not on touching a closed entry.

    Otherwise every later correction to a `fixed` entry — a resolution reworded,
    a `fixed_by` re-pointed after a rebase — would re-run a full pytest suite,
    and `reanchor`'s repair loop would become unusable.
    """
    store = tmp_path / "s"
    marker = tmp_path / "should-not-exist"
    entry = _groomed(store, cmd=f"touch {marker}")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--severity", "low", "--commit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert not marker.exists(), "a non-closing update ran the acceptance command"
    assert "acceptance" not in payload


def test_all_three_doors_go_through_one_acceptance_implementation(tmp_path, capsys):
    """The point of the fix, asserted structurally.

    Section 18 closed the wave door and left two open. If each door grows its own
    copy of the check, the next door added closes the same gap a third time — and
    the copies drift, which is the failure that produced this entry. So: one
    function, and all three callers observably route through it.
    """
    store, queue = tmp_path / "s", tmp_path / "q.jsonl"
    seen: list[str] = []
    real = BACKLOG._acceptance_gate

    def spy(entry, commit):
        seen.append(entry["id"])
        return real(entry, commit)

    BACKLOG._acceptance_gate = spy
    try:
        via_update = _groomed(store, detail="closed by update")
        assert BACKLOG.main(["update", via_update["id"], "--store", str(store),
                             "--status", "fixed", "--fixed-by", "aaaaaaa11",
                             "--commit", "--json"]) == 0

        via_verify = _groomed(store, detail="closed by verify")
        assert BACKLOG.main(["verify", via_verify["id"], "--store", str(store),
                             "--verdict", "CONFIRMED-FIXED", "--by", "probe",
                             "--evidence", "ran it", "--status", "fixed",
                             "--fixed-by", "aaaaaaa11", "--commit", "--json"]) == 0

        via_anchor = _groomed(store, detail="closed by the wave")
        _stage_and_stamp(store, queue, via_anchor["id"], capsys)
        assert BACKLOG.main(["anchor", "--store", str(store), "--queue", str(queue),
                             "--commit", "--json"]) == 0
    finally:
        BACKLOG._acceptance_gate = real

    assert seen == [via_update["id"], via_verify["id"], via_anchor["id"]], (
        f"a door reached `fixed` without going through the shared gate: {seen}")


# --------------------------------------------------------------------------
# 22. the acceptance command runs under the shell that vetted it
#     (IMP-20260808-c4bbb3)
# --------------------------------------------------------------------------

def test_acceptance_runs_under_bash_the_same_shell_that_vets_it(tmp_path, capsys):
    """The syntax floor and the executor must be the same shell.

    `_check_acceptance_cmd` parses with `bash -n`; the executor used `shell=True`,
    which is `/bin/sh` — bash 3.2 in POSIX mode here, dash on a Linux runner. So
    the floor certified a property of a shell that would never run the command.
    Measured: `bash -n -c '[[ 1 == 1 ]]'` exits 0, `dash -c '[[ 1 == 1 ]]'` exits
    127. A grooming agent had already started writing every acceptance in POSIX
    sh to route around this, which costs the criteria their expressiveness.

    The command asks the SHELL TO NAME ITSELF rather than using bash-only syntax,
    and that choice is the whole test. Measured on this machine: `shell=True` runs
    `/bin/sh`, which here IS bash 3.2, so `[[ -n x ]]` exits 0 under both — a test
    built on bash-only syntax passes with the defect still in place and only reds
    on a Linux runner, which is the worst possible place to find out. `$0` is `bash`
    under `["bash", "-c", …]` and `/bin/sh` under `shell=True`, on every platform.
    """
    store = tmp_path / "s"
    names_its_shell = 'case "$0" in *bash) exit 0 ;; *) exit 1 ;; esac'

    entry = _groomed(store, cmd=names_its_shell)
    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--fixed-by", "aaaaaaa11",
                         "--commit", "--json"]) == 0, (
        "the acceptance ran under a shell that does not call itself bash — "
        "the floor vets these strings with `bash -n`, so the executor must be bash")
    assert json.loads(capsys.readouterr().out)["acceptance"]["rc"] == 0

    # And the consequence the criteria authors actually feel: bash-only syntax is
    # legal at BOTH ends, so nobody has to downgrade a criterion to POSIX sh.
    bash_only = "[[ -n x ]] && test 1 -eq 1"
    assert BACKLOG._check_acceptance_cmd(
        {"acceptance_cmd": bash_only, "acceptance_expect_rc": 0}) == []
    assert BACKLOG._run_acceptance("probe", bash_only, 0)["ok"] is True


# --------------------------------------------------------------------------
# 23. free text does not pass through a shell (IMP-20260808-1aed9f)
#
# Backticks inside a double-quoted shell string are command substitution: the
# text is rewritten before this process ever sees it, and neither the store nor
# git records that anything was removed. Three occurrences in one day — a lost
# sentence in a `detail`, a lost phrase in a commit message, a dropped quote that
# stored an unparseable acceptance command. No in-tool detection is possible:
# by the time argv arrives the information is gone. The only fix is a channel
# the shell does not touch.
# --------------------------------------------------------------------------

HOSTILE_TEXT = ("run `ops/backlog.py show` and note $HOME plus a \\backslash\n"
                "\n"
                "  an indented second paragraph, with a trailing space   ")


def test_free_text_read_from_a_file_arrives_verbatim(tmp_path, capsys):
    """Byte-for-byte, minus only the newline every editor adds and nobody means.

    Interior blank lines, indentation and trailing spaces all survive: a channel
    that tidies its input is a channel that edits it, which is the defect being
    fixed, only politer.
    """
    store = tmp_path / "s"
    src = tmp_path / "detail.txt"
    src.write_text(HOSTILE_TEXT + "\n", encoding="utf-8")

    assert BACKLOG.main(["add", "--store", str(store), "--stream", "IMP",
                         "--date", "2026-08-08", "--source", "probe",
                         "--category", "tool", "--severity", "med",
                         "--detail-file", str(src), "--json"]) == 0
    entry = json.loads(capsys.readouterr().out)["entry"]

    assert entry["detail"] == HOSTILE_TEXT, (
        "the file channel must deliver the bytes on disk, minus only the "
        f"editor's trailing newline: {entry['detail']!r}")


def test_a_flag_and_its_file_twin_together_are_refused_by_name(tmp_path, capsys):
    """Silently preferring one would be the same class of defect: a write whose
    content is not the content the caller believes they supplied."""
    store = tmp_path / "s"
    src = tmp_path / "plan.txt"
    src.write_text("from the file", encoding="utf-8")
    entry = _add(store)

    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--plan", "from the flag", "--plan-file", str(src),
                       "--commit"])

    assert rc == 64
    err = capsys.readouterr().err
    # `--plan` is a PREFIX of `--plan-file`, so `"--plan" in err` has two possible
    # producers and is satisfied by the twin's own name. Measured: rewriting the
    # message to say `--plan-file` twice left the old assertion green — the refusal
    # could stop naming the bare flag, which is the entire content of "by name".
    assert re.search(r"--plan(?!-file)", err), err
    assert "--plan-file" in err, err
    assert BACKLOG.load_entry(store, entry["id"]).get("plan", "") == ""


def test_a_missing_file_is_a_named_refusal_not_a_traceback(tmp_path, capsys):
    store = tmp_path / "s"
    entry = _add(store)
    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--resolution-file", str(tmp_path / "nope.txt"), "--commit"])
    assert rc == 64
    assert "nope.txt" in capsys.readouterr().err


def test_the_file_twin_of_a_refused_flag_is_refused_the_same_way(tmp_path, capsys):
    """`update --detail` is refused because `detail` is a digest input. Routing the
    same value through a file must not become a way around that."""
    store = tmp_path / "s"
    src = tmp_path / "detail.txt"
    src.write_text("a reworded problem statement", encoding="utf-8")
    entry = _add(store)

    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--detail-file", str(src), "--commit"])

    assert rc == 64
    assert "--resolution" in capsys.readouterr().err, "the refusal lost its repair hint"
    assert BACKLOG.load_entry(store, entry["id"])["detail"] != "a reworded problem statement"


def test_every_free_text_flag_that_can_carry_a_backtick_has_a_file_twin():
    """The bidirectional invariant, so the next free-text flag added is caught.

    A hand-kept list of twins is exactly the shape that drifts — the same reason
    `update`'s change map is derived from MUTABLE_FIELDS rather than typed twice.
    """
    commands = BACKLOG.build_parser()._subparsers._group_actions[0].choices
    checked, broken = [], []
    for name, sub in commands.items():
        by_dest = {a.dest: a for a in sub._actions}
        for dest in sorted(set(by_dest) & set(BACKLOG.FILE_TWIN_FIELDS)):
            if by_dest[dest].nargs == 0:
                # store_true FILTERS share a dest with a free-text field
                # (`list --acceptance-manual`). A twin there is a flag that can
                # never succeed — its default `False` is not None, so the
                # mutual-exclusion branch fires on every call. See _add_file_twins.
                assert f"{dest}_file" not in by_dest, (
                    f"{name} --{dest.replace('_', '-')} takes no value; its twin "
                    f"could only ever refuse")
                continue
            if f"{dest}_file" not in by_dest:
                broken.append(f"{name} --{dest.replace('_', '-')} (no twin)")
                continue
            checked.append(f"{name}.{dest}")
    assert not broken, (
        "free-text flags reachable only through argv, where a backtick is "
        f"command substitution: {broken}")
    # Presence alone is near-tautological — it mirrors the predicate the generator
    # uses to create them, so it can only fail if the generator is never called.
    # Drive one twin through the parser and assert the VALUE lands on the twin dest
    # while the bare flag stays unset.
    assert "update.plan" in checked, checked
    args = BACKLOG.build_parser().parse_args(
        ["update", "IMP-0001", "--plan-file", "/dev/null"])
    assert args.plan_file == "/dev/null" and args.plan is None


# --------------------------------------------------------------------------
# 24. what the first cut of section 21 did NOT pin
#
# Every test below was written because a mutation SURVIVED the suite as first
# written. They are grouped rather than scattered so the next reader can see the
# shape they share: each one is a guard whose docstring carried the whole design
# rationale while nothing asserted the behaviour.
# --------------------------------------------------------------------------

def test_add_status_fixed_is_a_door_too_and_reports_an_unproven_closure(tmp_path, capsys):
    """`add --status fixed` writes the status directly and ran no gate at all.

    A new entry cannot carry a criterion — grooming is a separate act — so the only
    honest grade is `unproven`. The point is that it now SAYS so: before this, a
    `fixed` born here was indistinguishable in the store from one a command proved.
    """
    store = tmp_path / "s"
    assert BACKLOG.main(["add", "--store", str(store), "--stream", "IMP",
                         "--date", "2026-08-08", "--source", "probe",
                         "--category", "tool", "--severity", "low",
                         "--status", "fixed", "--detail", "born closed",
                         "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance"]["kind"] == "unproven"


def test_import_cannot_close_a_live_entry_over_a_red_acceptance(tmp_path, capsys):
    """The fifth door, and the only one that OVERWRITES.

    `import_legacy` calls `add_entry(overwrite=True, status=row["status"])`, so a
    one-row legacy table could flip a groomed, open entry to `fixed` while its own
    nominated command failed — reproduced by review at rc=0, silent.
    """
    store = tmp_path / "s"
    entry = _add(store, detail="import door probe")
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(acceptance_cmd="false"))
    table = tmp_path / "legacy.md"
    table.write_text(
        "| id | date | source | category | severity | status | detail | resolution |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| {entry['id']} | 2026-06-01 | probe | tool | high | fixed | "
        f"import door probe | closed by the table |\n", encoding="utf-8")

    rc = BACKLOG.main(["import", "--store", str(store), "--from", str(table),
                       "--commit", "--json"])
    capsys.readouterr()
    assert rc != 0, "a legacy table closed a live entry over a failing criterion"
    assert BACKLOG.load_entry(store, entry["id"])["status"] == "open"


def test_closing_cannot_rewrite_the_criterion_it_is_judged_by(tmp_path, capsys):
    """The gate must not read the command supplied by the act it is gating.

    Reproduced: `update <id> --status fixed --acceptance-cmd true` replaced a red
    criterion, ran the replacement, and the payload recorded `kind: ran, ok: true`.
    That is a gate satisfiable by its own input.
    """
    store = tmp_path / "s"
    entry = _groomed(store, cmd="false")
    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--status", "fixed", "--acceptance-cmd", "true",
                       "--fixed-by", "aaaaaaa11", "--commit", "--json"])
    assert rc != 0
    err = json.loads(capsys.readouterr().out)["error"]
    assert "one act" in err, err
    after = BACKLOG.load_entry(store, entry["id"])
    assert after["status"] == "open" and after["acceptance_cmd"] == "false"


def test_editing_an_already_closed_entry_runs_nothing(tmp_path, capsys):
    """Keyed on the CHANGE, not on the resulting state.

    The first version of `test_updating_a_field_that_is_not_the_status_runs_nothing`
    used an `open` entry, so `changes.get("status")` and `{**entry, **changes}
    .get("status")` agreed and the difference was invisible. On a `fixed` entry they
    disagree, and the merged reading re-runs a full suite on every later correction —
    which would make `reanchor`'s repair loop unusable.
    """
    store = tmp_path / "s"
    marker = tmp_path / "should-not-exist"
    entry = _groomed(store, cmd=f"touch {marker}")
    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--fixed-by", "aaaaaaa11",
                         "--commit"]) == 0
    capsys.readouterr()
    marker.unlink()                       # the closing act legitimately ran it

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--resolution", "reworded afterwards", "--commit"]) == 0
    assert not marker.exists(), (
        "editing an entry that is ALREADY fixed re-ran its acceptance command")


def test_a_dry_run_verify_does_not_run_acceptance_commands(tmp_path, capsys):
    """`update` had this test; `verify` did not, and its guard deleted cleanly."""
    store = tmp_path / "s"
    marker = tmp_path / "should-not-exist"
    entry = _groomed(store, cmd=f"touch {marker}")

    assert BACKLOG.main(["verify", entry["id"], "--store", str(store),
                         "--verdict", "CONFIRMED-FIXED", "--by", "probe",
                         "--evidence", "ran it", "--status", "fixed",
                         "--fixed-by", "aaaaaaa11", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert not marker.exists(), "a dry-run verify executed the acceptance command"
    assert payload["acceptance"]["kind"] == "would-run"


def test_whitespace_is_not_a_command(tmp_path, capsys):
    """`bash -c "   "` exits 0. Without the strip, a criterion of three spaces
    grades `ran / ok: true` — a green machine-checked badge produced by nothing,
    which is the exact artefact this whole section exists to abolish."""
    # Asserted on the gate directly: `update_entry` will not persist a
    # whitespace-only criterion (the groom rule strips too), so the store cannot
    # reach this state through the CLI — but `_acceptance_gate` is also called with
    # entries read straight off disk, which anyone can hand-edit.
    blank = {"id": "IMP-0001", "acceptance_cmd": "   ", "acceptance_expect_rc": 0}
    assert BACKLOG._acceptance_gate(blank, commit=True)["kind"] == "unproven"
    assert BACKLOG._acceptance_gate(blank, commit=False)["kind"] == "unproven"


def test_a_bad_sha_is_refused_before_the_acceptance_suite_runs(tmp_path, capsys):
    """Validation first, gate second — the order `verify` already used.

    Reversed, a typo'd `--fixed-by` ran the entry's whole acceptance command and
    only then refused on traceability. On a real entry that is a 15-minute pytest
    run thrown away for a typo.
    """
    store = tmp_path / "s"
    marker = tmp_path / "should-not-exist"
    entry = _groomed(store, cmd=f"touch {marker}")
    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--status", "fixed", "--fixed-by", "not-a-sha!",
                       "--commit", "--json"])
    capsys.readouterr()
    assert rc != 0
    assert not marker.exists(), (
        "the acceptance suite ran before the closure was checked for well-formedness")


def test_a_refused_digest_flag_is_named_as_the_caller_typed_it(tmp_path, capsys):
    """`--detail-file <missing path>` used to report the file error — a true
    statement about the wrong problem, since `update` can never write `detail` at
    all. The refusal must name the flag that was actually typed."""
    store = tmp_path / "s"
    entry = _add(store)
    rc = BACKLOG.main(["update", entry["id"], "--store", str(store),
                       "--detail-file", str(tmp_path / "nope.txt"), "--commit"])
    assert rc == 64
    err = capsys.readouterr().err
    assert "--detail-file" in err, err
    assert "--resolution" in err, "the digest refusal lost its repair hint"


# --------------------------------------------------------------------------
# 24. brief / scope — the two fields written for the HUMAN sorting the board
#     (IMP-20260808-1785b0)
#
# The phone board renders the first 400 characters of `detail`, which is
# technical prose addressed to whoever will execute the entry. The three actions
# the board offers — pin / reorder / defer — all need a different question
# answered in seconds: "what is broken and will I feel it" and "how big is this".
# Measured consequence: with 122 unresolved entries the write surface existed and
# was functionally inert, because nothing on a card supported the only decisions
# it could make.
#
# `fix_site` cannot double as this. It is a CODE ANCHOR (`ops/docs_lint.sh:180`)
# for the executor; different reader, different register, different precision.
#
# The rule binds by DATE for the same reason ACCEPTANCE_PROOF_SINCE does, and the
# cutoff is asserted against the shipped store below rather than assumed.
# --------------------------------------------------------------------------

def _briefed(**overrides):
    """A groom stamp that satisfies the new rule, dated ON the cutoff.

    (`BRIEF_TEXT` / `SCOPE_TEXT` live beside `_groom_kwargs` in section 8, which
    now needs them: the badge cannot be stamped without them at all.)
    """
    base = dict(_groom_kwargs(), groomed_at=BACKLOG.BRIEF_REQUIRED_SINCE)
    base.update(overrides)
    return base


@pytest.mark.parametrize("field", ["brief", "scope"])
def test_grooming_stamped_from_the_cutoff_on_must_speak_plain_language(tmp_path, field):
    """Grooming now means "worked out AND explained", and the second half is
    checkable the same way the first is: by its precondition being non-empty."""
    store = tmp_path / "s"
    entry = _add(store)

    payload = {**BACKLOG.load_entry(store, entry["id"]), **_briefed(**{field: ""})}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(payload)]
    assert f"groom-claim-without-{field}" in kinds, kinds

    # and the whole stamp, complete, is clean — otherwise the test above could be
    # passing off some unrelated defect as the finding
    assert BACKLOG.validate_entry({**payload, field: BRIEF_TEXT}) == []

    # the stronger half: the violation cannot be written through the CLI path
    with pytest.raises(ValueError, match=f"groom-claim-without-{field}"):
        BACKLOG.update_entry(store, entry["id"], **_briefed(**{field: ""}))


def test_grooming_from_before_the_cutoff_is_grandfathered(tmp_path):
    """THE POSITIVE CONTROL for the date guard.

    Without this, "the rule only binds new grooming" is a sentence in a comment
    and nothing distinguishes it from a rule that binds everything — the store
    would just be red, and the fix would look like backfilling 121 entries under
    time pressure rather than a guard that was never written.

    Grandfathered by DATE, not by a baseline of ids, for the reason
    ACCEPTANCE_PROOF_SINCE states: `groomed_at` is stamped at groom time, so
    re-grooming an old entry writes today's date and the rule binds it by itself.
    An id whitelist would forgive that entry forever.
    """
    store = tmp_path / "s"
    entry = _add(store)
    old = _briefed(brief="", scope="", groomed_at="2026-07-01")
    payload = {**BACKLOG.load_entry(store, entry["id"]), **old}

    assert BACKLOG.validate_entry(payload) == [], (
        "grooming that predates the rule was turned red by it")

    # and it really is the DATE doing the forgiving: move the same payload forward
    # and both problems appear
    fresh = {**payload, "groomed_at": BACKLOG.BRIEF_REQUIRED_SINCE}
    kinds = {p["kind"] for p in BACKLOG.validate_entry(fresh)}
    assert {"groom-claim-without-brief", "groom-claim-without-scope"} <= kinds, kinds


def test_the_cutoff_forgives_every_groom_stamp_already_in_the_shipped_store():
    """The cutoff is a MEASUREMENT against this repo's ledger, not a guess.

    A cutoff of "today" reads as the obvious choice and is wrong here: the
    2026-08-08 grooming wave had already stamped 96 entries before this rule was
    written, so `>= today` would have turned 95 of them red (all but this ticket,
    whose prose this very commit writes) and taken
    `./ops/backlog.py validate` — this entry's own acceptance command — down with
    them. The rule must land ahead of the newest stamp that exists; the backfill
    wave is what clears the debt, and `list --missing-brief` is what counts it.

    Asserted over the real store because that is the thing that would break, and
    a tmp_path fixture cannot know what date the last wave stamped.

    The assertion is the PROPERTY ("the rule reds nothing that already exists"),
    not the proxy that first suggested it ("the cutoff is later than every stamp
    in the store"). The proxy is true today and stops being true the first time
    somebody legitimately grooms on or after the cutoff WITH both fields — so a
    test written that way would turn red on correct behaviour, which is how a
    gate teaches people to ignore it.
    """
    groomed = [p for p in BACKLOG._iter_entries(BACKLOG.DEFAULT_STORE)
               if str(p.get("groomed_at") or "").strip()]
    assert groomed, "no groomed entries in the store — this test would be vacuous"

    wanted = {f"groom-claim-without-{f}" for f in BACKLOG.BRIEF_FIELDS}
    red = sorted(p["id"] for p in groomed
                 if wanted & {q["kind"] for q in BACKLOG._check_groom(p)})
    assert not red, (
        f"BRIEF_REQUIRED_SINCE={BACKLOG.BRIEF_REQUIRED_SINCE} binds grooming that "
        f"was stamped before the rule existed, so `./ops/backlog.py validate` is "
        f"red on {len(red)} entry(s) nobody can fix except by backfilling prose "
        f"under time pressure: {red[:5]}")

    # The other side of the same constant, and it needs its own assertion: the
    # test above only stops the cutoff being set too EARLY. Nothing stopped it
    # being pushed out — set it to 2099-01-01 and the whole suite stays green
    # while `validate` silently stops judging hand-edited groom stamps forever.
    # This bound does not decay, because legitimate new grooming raises `newest`
    # along with it.
    newest = max(str(p.get("groomed_at") or "") for p in groomed)
    day_after = (datetime.date.fromisoformat(newest)
                 + datetime.timedelta(days=1)).isoformat()
    assert BACKLOG.BRIEF_REQUIRED_SINCE <= day_after, (
        f"BRIEF_REQUIRED_SINCE={BACKLOG.BRIEF_REQUIRED_SINCE} is more than one day "
        f"past the newest stamp in the store ({newest}), so `validate` is inert "
        f"over a window nobody declared")


@pytest.mark.parametrize("field", ["brief", "scope"])
def test_brief_and_scope_travel_by_file_because_they_are_free_text(tmp_path, capsys, field):
    """Both are prose a human wrote, so both need the channel the shell cannot
    edit — a backtick in argv is command substitution and the loss is silent."""
    store = tmp_path / "s"
    entry = _add(store)
    src = tmp_path / f"{field}.txt"
    hostile = f"`ops/backlog.py show` 這支工具的輸出對排序者不可用，$HOME 也是\n"
    src.write_text(hostile, encoding="utf-8")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         f"--{field}-file", str(src), "--commit"]) == 0
    capsys.readouterr()
    assert BACKLOG.load_entry(store, entry["id"])[field] == hostile.rstrip("\n")


def test_brief_and_scope_are_reachable_on_add_as_well_as_update(tmp_path, capsys):
    """Filing and explaining are the same act when the filer already knows; only
    GROOMING is the separate one. An `add` that cannot carry them would send every
    author through a second command to say the one thing the board displays."""
    assert BACKLOG.main(["add", "--store", str(tmp_path / "s"), "--stream", "IMP",
                         "--date", "2026-08-08", "--source", "probe",
                         "--category", "tool", "--severity", "med",
                         "--detail", "a tool reports success while doing nothing",
                         "--brief", BRIEF_TEXT, "--scope", SCOPE_TEXT,
                         "--json"]) == 0
    entry = json.loads(capsys.readouterr().out)["entry"]
    assert entry["brief"] == BRIEF_TEXT and entry["scope"] == SCOPE_TEXT


def test_list_missing_brief_is_the_backfill_queue_not_the_dispatch_queue(tmp_path):
    """Two properties, and the second is the one that makes the number honest.

    It counts UNRESOLVED entries only: a closed entry never reaches the board, so
    counting it would inflate the debt with work nobody can do anything about.
    """
    store = tmp_path / "s"
    bare = _add(store, detail="no plain language anywhere")
    half = _add(store, detail="brief but no scope")
    BACKLOG.update_entry(store, half["id"], brief=BRIEF_TEXT)
    done = _add(store, detail="both fields written")
    BACKLOG.update_entry(store, done["id"], brief=BRIEF_TEXT, scope=SCOPE_TEXT)
    closed = _add(store, detail="closed and never shown on the board", status="fixed")

    hits = [e["id"] for e in BACKLOG.list_entries(store, missing_brief=True)]
    assert bare["id"] in hits and half["id"] in hits
    assert done["id"] not in hits, "an entry carrying both fields is not backfill debt"
    assert closed["id"] not in hits, "a closed entry never reaches the board"


def test_missing_brief_intersects_the_other_filters_rather_than_replacing_them(tmp_path):
    store = tmp_path / "s"
    _add(store, detail="low severity, no brief", severity="low")
    wanted = _add(store, detail="high severity, no brief", severity="high")
    hits = BACKLOG.list_entries(store, missing_brief=True, severity="high")
    assert [e["id"] for e in hits] == [wanted["id"]]


def test_list_missing_brief_is_reachable_from_argv(tmp_path, capsys):
    store = tmp_path / "s"
    bare = _add(store, detail="no plain language anywhere")
    done = _add(store, detail="both fields written")
    BACKLOG.update_entry(store, done["id"], brief=BRIEF_TEXT, scope=SCOPE_TEXT)

    assert BACKLOG.main(["list", "--store", str(store), "--missing-brief", "--json"]) == 0
    ids = [e["id"] for e in json.loads(capsys.readouterr().out)["entries"]]
    assert ids == [bare["id"]], ids


def test_show_prints_the_human_fields_ahead_of_the_technical_prose(tmp_path, capsys):
    """Order is the feature. `detail` is 400+ characters of prose addressed to the
    executor; a `brief` printed after it is a `brief` nobody reaches."""
    store = tmp_path / "s"
    entry = _add(store)
    BACKLOG.update_entry(store, entry["id"], brief=BRIEF_TEXT, scope=SCOPE_TEXT)

    assert BACKLOG.main(["show", entry["id"], "--store", str(store)]) == 0
    human = capsys.readouterr().out
    positions = {}
    for field in ("brief", "scope", "detail"):
        match = re.search(rf"^{field}\s+\S", human, re.M)
        assert match, f"`show` printed no {field} line:\n{human}"
        positions[field] = match.start()
    assert positions["brief"] < positions["detail"], (
        f"the one-line summary is printed after the prose it summarises:\n{human}")
    assert positions["scope"] < positions["detail"], human


def test_stamping_a_groom_badge_demands_plain_language_whatever_the_date(tmp_path):
    """The date ratchet grandfathers DATA; it must not grandfather ACTS.

    `BRIEF_REQUIRED_SINCE` had to land ahead of the newest stamp in the store
    (see the cutoff test above), which left a window in which grooming could
    still be stamped with no plain language at all — measured, not theorised.
    Closing it with an earlier date is impossible without reddening 95 existing
    entries, and closing it with a list of exempt ids is the whitelist this
    design refuses. So the two questions are answered in the two places they
    belong: `validate` judges STORED DATA and forgives what predates the rule,
    while claiming or refreshing the badge is an ACT happening now and is held
    to today's standard regardless of the date being written.
    """
    store = tmp_path / "s"
    entry = _add(store)
    before = (store / f"{entry['id']}.json").read_bytes()

    # A date the ratchet forgives, so ONLY the write-time gate can refuse this
    stale = "2026-08-01"
    assert stale < BACKLOG.BRIEF_REQUIRED_SINCE
    with pytest.raises(ValueError, match="groom-claim-without-brief"):
        BACKLOG.update_entry(store, entry["id"],
                             **_groom_kwargs(groomed_at=stale, brief="", scope=""))
    assert (store / f"{entry['id']}.json").read_bytes() == before

    # ... and the same act with the sentences written is accepted
    BACKLOG.update_entry(store, entry["id"], **_groom_kwargs(groomed_at=stale))
    assert BACKLOG.load_entry(store, entry["id"])["brief"] == BRIEF_TEXT


def test_editing_a_grandfathered_entry_that_is_not_re_grooming_is_untouched(tmp_path):
    """THE POSITIVE CONTROL for the write-time gate, and the reason it is keyed
    on the CHANGE SET rather than on the merged entry.

    133 entries in the shipped store carry a groom stamp and no plain language.
    A gate that fired on "the entry being written is groomed and has no brief"
    would freeze every one of them: `update <id> --status fixed`, `--resolution`,
    `verify`, `anchor` — none of which are grooming, all of which would start
    demanding prose their caller was never asked for. The gate must fire on the
    act of stamping the badge, and on nothing else.
    """
    store = tmp_path / "s"
    entry = _add(store)
    # A legacy shape: groomed before the rule, no brief, written straight to disk
    # because `update_entry` is exactly what refuses to create it now.
    path = store / f"{entry['id']}.json"
    payload = {**json.loads(path.read_text(encoding="utf-8")),
               **_groom_kwargs(groomed_at="2026-07-01")}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert BACKLOG.validate_store(store) == [], "the fixture itself is already red"

    # every non-grooming edit still works
    BACKLOG.update_entry(store, entry["id"], severity="high")
    BACKLOG.update_entry(store, entry["id"], resolution="— 之後再說")
    assert BACKLOG.load_entry(store, entry["id"])["severity"] == "high"


@pytest.mark.parametrize("status", ["fixed", "wont-fix"])
def test_missing_brief_refuses_a_closed_status_instead_of_answering_empty(tmp_path, status):
    """Same rule the two neighbouring pairs already follow, applied where it was
    missing.

    `--missing-brief` means "unresolved and unexplained", so pairing it with a
    closed status is empty BY CONSTRUCTION — and an empty result reads as "there
    is no such debt", which is the opposite of true: 96 closed entries carry no
    brief today. `--groomed/--ungroomed` and `--unverified/--stale` are both
    refused by name for exactly this reason, and the refusal has to name the
    contradiction rather than let the caller believe the queue is clear.
    """
    store = tmp_path / "s"
    # `wont-fix` carries a reason because `add` now enforces that (section 27);
    # the fixture had been filing an entry `validate` rejects, which is the very
    # defect that rule closes.
    _add(store, status=status, detail="closed and unexplained",
         resolution="not worth the complexity")
    with pytest.raises(BACKLOG.BacklogError, match="--missing-brief"):
        BACKLOG.list_entries(store, missing_brief=True, status=status)


def test_missing_brief_still_composes_with_the_open_statuses(tmp_path):
    """The refusal above must not become a blanket ban on --status."""
    store = tmp_path / "s"
    wanted = _add(store, status="triaged", detail="triaged, no brief",
                  resolution="— 下一步:先量測")
    _add(store, status="open", detail="open, no brief")
    hits = BACKLOG.list_entries(store, missing_brief=True, status="triaged")
    assert [e["id"] for e in hits] == [wanted["id"]]


def test_the_groom_refusal_names_each_defect_once_and_says_how_to_repair_it(tmp_path):
    """Two gates ask the same question of a groom stamp, so once the date binds
    they BOTH fire and the caller sees each missing field twice — four problems
    for two defects, distinguishable only by an internal key.

    And these two kinds are the only ones whose repair is fully determined, which
    makes them the last that should arrive as a bare defect name. The enclosing
    function already carries hints for `fixed_by` under a comment that says "Name
    the repair, not just the defect"; this is that rule applied where it was
    missing.
    """
    store = tmp_path / "s"
    entry = _add(store)
    bound = BACKLOG.BRIEF_REQUIRED_SINCE  # both gates active

    with pytest.raises(ValueError) as excinfo:
        BACKLOG.update_entry(store, entry["id"],
                             **_groom_kwargs(groomed_at=bound, brief="", scope=""))
    message = str(excinfo.value)

    for field in BACKLOG.BRIEF_FIELDS:
        assert message.count(f"groom-claim-without-{field}") == 1, (
            f"{field} is reported more than once — both gates fired and nothing "
            f"deduped them:\n{message}")
        # The repair, not just the defect. Asserted as the flag the caller has to
        # type, because "write a brief" is not a command anybody can run.
        #
        # Scoped to the hint line and given a word boundary, for the two reasons
        # the sibling assertion in test_worktree_orchestrate.py was just narrowed:
        # `--brief` is a prefix of `--brief-file`, and a substring test over the
        # WHOLE message is satisfied by the flag appearing anywhere — including
        # the defect list it is supposed to be the answer to.
        hint = next((ln for ln in message.splitlines()
                     if "add to the command you just ran" in ln), "")
        assert hint, f"the refusal carries no repair line:\n{message}"
        assert re.search(rf"--{field}(?=[\s=]|$)", hint), (
            f"the repair line never says how to fix {field}:\n{hint}")


def test_deduping_the_refusal_does_not_swallow_distinct_defects(tmp_path):
    """The dedupe above exists because TWO GATES ask one question; it must not
    collapse ONE gate reporting N different things.

    Three kinds are emitted per-item with a discriminator the caller needs:
    `app-field-on-imp-entry` per field, `missing-field` per field, and the
    `fixed-by-*` family per sha (`--fixed-by` is nargs="+"). Keying the dedupe on
    `kind` alone made each of them report the first item only — so the caller
    fixes it, is refused again, and learns the tool drips defects one at a time.
    That is the same "name the whole repair" failure the surrounding code was
    written against, reintroduced by the fix for a neighbouring one.
    """
    store = tmp_path / "s"
    entry = _add(store)

    # One gate, two fields
    with pytest.raises(ValueError) as excinfo:
        BACKLOG.update_entry(store, entry["id"], surface="reader", repro="tap it")
    message = str(excinfo.value)
    for field in ("surface", "repro"):
        assert f"'field': '{field}'" in message, (
            f"only one app-field defect survived the dedupe; {field} is missing:\n{message}")

    # One gate, two shas
    with pytest.raises(ValueError) as excinfo:
        BACKLOG.update_entry(store, entry["id"], status="fixed",
                             fixed_by=["zzzz111", "qqqq222"])
    message = str(excinfo.value)
    for sha in ("zzzz111", "qqqq222"):
        assert sha in message, (
            f"only one bad sha survived the dedupe; {sha} is missing:\n{message}")


# --------------------------------------------------------------------------
# 25. `dispatch` — the queue the operating constitution already names
#     (IMP-20260808-573a09)
#
# CLAUDE.md nominalises `dispatch` in three places ("take one from `dispatch`",
# "an ungroomed entry stays on the board but not in `dispatch`", "groom -> into
# `dispatch` -> taken"), and the subcommand did not exist: the FIRST command the
# 2026-08-08 dogfood batch typed was `./ops/backlog.py dispatch --json`, which
# exited 2 with `invalid choice`. What a session does instead is scan the whole
# list by hand, which is exactly the failure the groomed/held guards exist to
# prevent — hand out an id somebody already holds, or one with no fix plan.
# --------------------------------------------------------------------------

def _groomed_ticket(store, *, status=None, fixed_by=None, resolution=None, **overrides):
    """An entry carrying a real groom badge, optionally moved on from `open`."""
    entry = _add(store, **overrides)
    changes = dict(_groom_kwargs())
    if status is not None:
        changes["status"] = status
    if fixed_by is not None:
        changes["fixed_by"] = fixed_by
    if resolution is not None:
        changes["resolution"] = resolution
    return BACKLOG.update_entry(store, entry["id"], **changes)


def _dispatch_store(tmp_path):
    """One store carrying a member of every class the three clauses discriminate."""
    store = tmp_path / "s"
    takeable = _groomed_ticket(store, detail="groomed, unresolved, free — the only takeable one")
    ungroomed = _add(store, detail="nobody has worked out how to fix this")
    closed = _groomed_ticket(store, detail="already fixed", status="fixed", fixed_by=["abc1234"])
    refused = _groomed_ticket(store, detail="decided against", status="wont-fix",
                       resolution="not worth the complexity")
    claimed = _groomed_ticket(store, detail="somebody is already on this one")
    return store, dict(takeable=takeable, ungroomed=ungroomed, closed=closed,
                       refused=refused, claimed=claimed)


def test_dispatch_is_the_intersection_of_three_clauses_each_with_its_own_negative(tmp_path):
    """Groomed AND unresolved AND unclaimed — and each clause is load-bearing.

    Asserted as three separate absences against ONE positive control in the same
    store, because a filter that returns the empty set satisfies every negative
    assertion at once and would read as three passing tests.
    """
    store, e = _dispatch_store(tmp_path)
    held = {e["claimed"]["id"]: {"branch": "feat/x", "path": "/wt/x",
                                 "claimed_at": "2026-08-08T00:00:00Z"}}

    ids = [p["id"] for p in BACKLOG.list_entries(store, dispatch=True, held=held)]

    assert ids == [e["takeable"]["id"]], ids
    assert e["ungroomed"]["id"] not in ids, "an entry with no fix plan was handed out"
    assert e["closed"]["id"] not in ids, "a closed entry was handed out"
    assert e["refused"]["id"] not in ids, "a wont-fix entry was handed out"
    assert e["claimed"]["id"] not in ids, "an id another worktree holds was handed out"


def test_dispatch_intersects_with_the_ordinary_filters_rather_than_replacing_them(tmp_path):
    """`--stream` / `--severity` / `--grep` must still narrow it.

    A dispatch queue that ignores the filters beside it forces the caller back to
    the hand-rolled scan this subcommand exists to delete.
    """
    store = tmp_path / "s"
    wanted = _groomed_ticket(store, detail="the ops wrapper drops its exit code", severity="high")
    _groomed_ticket(store, detail="an unrelated high-severity problem", severity="high")
    _groomed_ticket(store, detail="the ops wrapper is also slow", severity="low")

    hits = BACKLOG.list_entries(store, dispatch=True, held={},
                                severity="high", grep="drops its exit code")
    assert [p["id"] for p in hits] == [wanted["id"]], hits


def test_dispatch_hands_out_the_worst_thing_first(tmp_path):
    """severity high->low, then oldest first — a queue with no order is a list.

    `list`'s own order is (date, id), which puts a年-old `low` ahead of today's
    `high`. That is right for an inventory and wrong for a queue somebody takes
    the top of.
    """
    store = tmp_path / "s"
    low = _groomed_ticket(store, detail="cosmetic", severity="low", date="2026-08-01")
    high_new = _groomed_ticket(store, detail="data loss", severity="high", date="2026-08-07")
    high_old = _groomed_ticket(store, detail="silent corruption", severity="high", date="2026-08-02")
    med = _groomed_ticket(store, detail="confusing help", severity="med", date="2026-08-03")

    ids = [p["id"] for p in BACKLOG.list_entries(store, dispatch=True, held={})]
    assert ids == [high_old["id"], high_new["id"], med["id"], low["id"]], ids


def test_the_dispatch_subcommand_and_list_dispatch_return_the_same_ids(tmp_path, capsys,
                                                                      monkeypatch):
    """Two doors, ONE implementation — pinned by the answer, not by the source.

    The subcommand exists because the constitution uses that noun and an agent
    that has read it types `dispatch`; the flag exists because it is a filter like
    every other filter. Two hand-written queues would drift, and the drift would
    be invisible: both doors would keep returning *a* list.
    """
    store, e = _dispatch_store(tmp_path)
    monkeypatch.setattr(BACKLOG, "held_tickets", lambda *a, **k: {
        e["claimed"]["id"]: {"branch": "feat/x", "path": "/wt/x",
                             "claimed_at": "2026-08-08T00:00:00Z"}})

    assert BACKLOG.main(["list", "--store", str(store), "--dispatch", "--json"]) == 0
    via_flag = json.loads(capsys.readouterr().out)
    assert BACKLOG.main(["dispatch", "--store", str(store), "--json"]) == 0
    via_noun = json.loads(capsys.readouterr().out)

    flag_ids = [p["id"] for p in via_flag["entries"]]
    noun_ids = [p["id"] for p in via_noun["entries"]]
    # Positive control FIRST: two empty lists are also equal, and an equality that
    # holds because both doors are broken is the one this test must not pass on.
    assert flag_ids == [e["takeable"]["id"]], flag_ids
    assert noun_ids == flag_ids, f"{noun_ids} != {flag_ids}"

    # ...and the shared flags reach the shared implementation from both doors
    assert BACKLOG.main(["dispatch", "--store", str(store), "--severity", "low",
                         "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["entries"] == []


def test_every_list_filter_is_reachable_from_the_dispatch_door():
    """One implementation means one flag set; a subset is a second implementation.

    A filter added to `list` and forgotten on `dispatch` cannot be caught by
    comparing results — the caller simply cannot express the question through the
    door the constitution tells them to use.
    """
    commands = BACKLOG._subcommands(BACKLOG.build_parser())
    assert "dispatch" in commands, "the constitution's first command still does not exist"
    on_list = {o for a in commands["list"]._actions for o in a.option_strings}
    on_dispatch = {o for a in commands["dispatch"]._actions for o in a.option_strings}

    assert on_list - on_dispatch == {"--dispatch"}, (
        "a `list` filter cannot be expressed through the `dispatch` door")
    assert on_dispatch - on_list == set(), (
        "`dispatch` grew a flag `list --dispatch` cannot reach")


def test_dispatch_says_what_it_cannot_see(tmp_path, capsys, monkeypatch):
    """Two blind spots, both stated: the claim ledger is per-machine, snooze is elsewhere.

    `held` is derived from THIS checkout's gitignored worktree ledger, so on the
    other machine the queue is optimistic — it will offer an id somebody is
    already holding. Board deferrals live in `~/kg-board-state/overlay.json`,
    deliberately outside this repo, so a snoozed entry is offered too. A queue
    that presents itself as authoritative about either is worse than one that
    admits it: the caller has no other way to learn it.
    """
    store, e = _dispatch_store(tmp_path)
    monkeypatch.setattr(BACKLOG, "held_tickets", lambda *a, **k: {})

    assert BACKLOG.main(["dispatch", "--store", str(store), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    scope = payload["dispatch"]
    assert scope["clauses"] == ["groomed", "unresolved", "unclaimed"], scope
    assert "optimistic" in scope["held_scope"].lower(), scope["held_scope"]
    assert "overlay.json" in scope["snooze_scope"], scope["snooze_scope"]

    assert BACKLOG.main(["dispatch", "--store", str(store)]) == 0
    human = capsys.readouterr().out
    assert "optimistic" in human.lower(), human
    assert "snooze" in human.lower(), human


def test_dispatch_refuses_the_combinations_that_are_empty_by_construction(tmp_path, capsys):
    """An empty dispatch queue reads as "no work available" — the worst false read here.

    Same treatment, and the same reason, as --groomed/--ungroomed,
    --unverified/--stale and --missing-brief + a closed status: each of these
    intersects dispatch's own clauses to nothing, so the result would be a
    confident empty answer to a question that was never asked.
    """
    store, _ = _dispatch_store(tmp_path)
    for extra in (["--ungroomed"], ["--held"], ["--status", "fixed"],
                  ["--status", "wont-fix"]):
        assert BACKLOG.main(["list", "--store", str(store), "--dispatch", *extra]) == 64, extra
        err = capsys.readouterr().err
        assert "--dispatch" in err, f"{extra} was refused without naming the conflict: {err}"
        # The whole value of these refusals is naming WHICH flag conflicts. Without
        # this half, one message saying "--dispatch conflicts with something"
        # satisfies all four cases and the caller still has to guess.
        assert extra[0] in err, (
            f"the refusal does not name the other side of the conflict: {err}")
    # ...and a combination that is NOT empty by construction still works
    assert BACKLOG.main(["list", "--store", str(store), "--dispatch",
                         "--status", "open", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["entries"], (
        "--dispatch --status open is a legitimate narrowing and returned nothing")


# --------------------------------------------------------------------------
# 26. `fixed_elsewhere` — a second, countable form of traceability
#     (IMP-20260808-ddf494)
#
# `status=fixed` demanded `fixed_by`, every element had to match `_SHA_RE`, and
# every sha had to resolve in THIS repo. Three rules with one unstated premise:
# every entry's fix lands in this git repository. Two entries in the live store
# have a `fix_site` under `~/butler/kg-board/`, and `~/butler` deliberately does
# not use git (Syncthing since 2026-06-16) — there is no sha and there never will
# be one. The shape is `acceptance_manual`'s, exactly: when the machine-checkable
# form does not exist, DECLARE it and keep the declaration countable.
# --------------------------------------------------------------------------

ELSEWHERE = ("~/butler/kg-board/server.py:_dispatch — re-run: "
             "`cd ~/butler/kg-board && uv run python -m pytest tests/test_dispatch.py`")


def _closable(store, **overrides):
    return BACKLOG.load_entry(store, _add(store, **overrides)["id"])


def test_closing_needs_exactly_one_of_fixed_by_and_fixed_elsewhere(tmp_path):
    """Neither is a claim with no audit trail; both are two contradictory ones.

    The "both" half is not pedantry: it is the same defect
    `groom-claim-with-conflicting-acceptance-proof` names one field family over.
    One says the fix is a commit in this repo, the other says it is not — and a
    reader has no way to tell which one the closer meant.
    """
    payload = _closable(tmp_path / "s")

    neither = {**payload, "status": "fixed", "resolution": "done"}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(neither)]
    assert "fixed-without-fixed-by" in kinds, kinds

    both = {**neither, "fixed_by": ["abc1234"], "fixed_elsewhere": ELSEWHERE}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(both)]
    assert "fixed-with-conflicting-traceability" in kinds, kinds
    assert "fixed-without-fixed-by" not in kinds, (
        "both-at-once must not ALSO read as none-at-all")


def test_fixed_elsewhere_closes_an_entry_and_skips_the_sha_rules_entirely(tmp_path):
    """The whole point: a fix with no sha, closed, and clean under `validate`.

    `IMP-20260808-47f7b4` is the measured case — fixed, self-tested, red/green
    evidence written down, and unclosable: `--status fixed` alone gave
    `fixed-without-fixed-by`, and `--fixed-by external:butler/kg-board` gave
    `fixed-by-not-a-sha`. There was no third door.
    """
    store = tmp_path / "s"
    entry = _closable(store)
    closed = BACKLOG.update_entry(store, entry["id"], status="fixed",
                                  fixed_elsewhere=ELSEWHERE, resolution="landed in butler")

    assert closed["fixed_elsewhere"] == ELSEWHERE
    problems = BACKLOG.validate_entry(closed, entry_id=closed["id"])
    assert problems == [], problems


def test_the_sha_rules_are_skipped_only_for_a_closure_that_declares_no_sha(tmp_path):
    """The skip has to be OBSERVED, which means the loop has to be reachable.

    The first cut of this asserted "no `fixed-by-*` problem" on an entry with no
    `fixed_by` at all: the loop ran zero times either way, so deleting the skip
    entirely left the whole suite green. An assertion about a branch that cannot
    be entered is not an assertion about the branch.

    The second case is the defect that found: the skip used to be keyed on
    `fixed_elsewhere` alone, while both exactly-one-of rules are keyed on `fixed`.
    A `wont-fix` carrying a broken sha AND this field therefore got NEITHER —
    validated clean, one CLI call away, on exactly the entries `reanchor` exists
    for. `validate --baseline-check` is the cutover block gate, so that was a path
    to a green light.
    """
    payload = _closable(tmp_path / "s")

    # `fixed` + both: the CONFLICT is the finding. Complaining about the sha too
    # would bury it under the field that should not be there.
    both = {**payload, "status": "fixed", "resolution": "done",
            "fixed_by": ["zzzzzzz"], "fixed_elsewhere": ELSEWHERE}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(both)]
    assert kinds == ["fixed-with-conflicting-traceability"], kinds

    # `wont-fix` + both: no conflict rule applies here, so the sha must still be
    # judged. Nothing about a decision not to fix makes a broken hash acceptable.
    refused = {**both, "status": "wont-fix"}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(refused)]
    assert "fixed-by-not-a-sha" in kinds, (
        f"a broken sha vanished by flipping the status — the exact repair anyone "
        f"hunting a green gate would find: {kinds}")


def test_fixed_elsewhere_on_an_unfinished_entry_is_refused_like_fixed_by_is(tmp_path):
    """`fixed_by` on an open entry was already refused; the new field owes the same.

    Otherwise the field is a way to write "this is fixed" while the status keeps
    saying it is not — the shape that lets finished work look open forever, which
    is what `fixed-by-on-unfinished-entry` was added for.
    """
    payload = _closable(tmp_path / "s")
    for status in ("open", "triaged"):
        entry = {**payload, "status": status, "plan": "step 1",
                 "fixed_elsewhere": ELSEWHERE}
        kinds = [p["kind"] for p in BACKLOG.validate_entry(entry)]
        assert "fixed-elsewhere-on-unfinished-entry" in kinds, (status, kinds)


def test_list_fixed_elsewhere_keeps_the_declared_exceptions_countable(tmp_path, capsys):
    """`list --fixed-elsewhere`, for the same reason `--acceptance-manual` exists.

    An escape hatch nobody can count is a loophole; one with a number attached is
    an exception list somebody can look at and argue with.
    """
    store = tmp_path / "s"
    away = _closable(store, detail="fixed in the board repo")
    home = _closable(store, detail="fixed right here")
    BACKLOG.update_entry(store, away["id"], status="fixed", fixed_elsewhere=ELSEWHERE,
                         resolution="landed in butler")
    BACKLOG.update_entry(store, home["id"], status="fixed", fixed_by=["abc1234"],
                         resolution="landed here")

    assert BACKLOG.main(["list", "--store", str(store), "--fixed-elsewhere", "--json"]) == 0
    ids = [p["id"] for p in json.loads(capsys.readouterr().out)["entries"]]
    assert ids == [away["id"]], ids


def test_reanchor_leaves_a_fixed_elsewhere_entry_alone(tmp_path, monkeypatch):
    """There is no sha to re-point, so it must not appear in the plan at all.

    A DERIVED property, not an implementation: `reanchor_store` selects targets by
    `fixed_by`, and the exactly-one-of rule means a `fixed_elsewhere` entry has
    none, so nothing in `reanchor` had to be taught about the new field. The
    docstring says so because no mutation of the code under review can redden this
    — a reader who assumed it covers a skip in `reanchor` would be wrong about
    what protects them. What it does pin is that the derivation stays true if
    either side moves.

    Paired with a positive control in the SAME store: a genuine orphan still gets
    mapped, so "the plan is empty" cannot be what makes this pass.
    """
    monkeypatch.undo()  # the real resolver, on a real repo
    repo = tmp_path / "repo"
    orphan, landed = _git_repo(repo)
    store = repo / "store"

    orphaned = _add(store, detail="fixed here, then rebased")
    _force_fixed_by(store, orphaned["id"], [orphan])
    away = _add(store, detail="fixed in a repo that has no shas")
    path = store / f"{away['id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(status="fixed", resolution="landed in butler", fixed_elsewhere=ELSEWHERE)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = BACKLOG.reanchor_store(store, repo=repo)
    touched = [item["id"] for item in result["plan"]]
    assert touched == [orphaned["id"]], touched
    assert result["plan"][0]["moves"] == {orphan: landed[:9]}


def test_verify_can_close_an_entry_that_is_fixed_elsewhere(tmp_path, capsys):
    """`verify --status fixed` is advertised as the natural closing act.

    It grew `--fixed-by` because without it that act was a dead end — the exact
    same dead end reappears for a fix with no sha unless the second form is
    reachable from the same door.
    """
    store = tmp_path / "s"
    entry = _closable(store)
    assert BACKLOG.main(["verify", entry["id"], "--store", str(store),
                         "--verdict", "CONFIRMED-FIXED", "--by", "agent:ops-engineer",
                         "--evidence", "cd ~/butler/kg-board && uv run python -m pytest",
                         "--status", "fixed", "--fixed-elsewhere", ELSEWHERE,
                         "--commit", "--json"]) == 0
    capsys.readouterr()
    stored = BACKLOG.load_entry(store, entry["id"])
    assert stored["status"] == "fixed" and stored["fixed_elsewhere"] == ELSEWHERE
    assert BACKLOG.validate_entry(stored, entry_id=stored["id"]) == []


# --------------------------------------------------------------------------
# 27. `add` cannot write what `validate` will refuse (IMP-20260808-f2bcc1)
#
# `add --status triaged` wrote an entry `validate` rejects with `no-next-action`,
# and the thing that reported it was the cutover gate of a LATER, unrelated
# branch. Five filed in one session on 2026-08-08; all five surfaced in
# `feat/backlog-list-grep`'s `land`.
#
# Root cause, and it is not "add forgot to validate": `add_entry` already calls
# `validate_entry`, with `check_traceability=False`. That switch exists to forgive
# the SHA rules (history is full of `fixed` rows whose landing commit was never
# written down) — and `no-next-action` / `wont-fix-without-reason` /
# `wont-fix-reason-is-a-sha` were sitting inside the same function, mentioning no
# sha and needing no repo. `_cmd_stage` says so in its own comment. So the repair
# is to stop calling them traceability, not to bolt a second rule set onto `add`.
# --------------------------------------------------------------------------

_ADD = ["--stream", "IMP", "--date", "2026-08-08", "--source", "dogfood batch 1",
        "--category", "cli", "--severity", "med",
        "--detail", "a tool writes an entry its own validator rejects"]


def test_add_refuses_a_triaged_entry_with_no_next_action_and_leaves_no_file(tmp_path, capsys):
    """The refusal has to arrive here, not in somebody else's `land`.

    `triaged` claims a next step has been decided, so the entry owes one. `add`
    offering it as a bare `--status` choice while `validate` refuses the result is
    the tool disagreeing with itself, and the disagreement is settled by whichever
    unrelated branch runs the gate next.
    """
    store = tmp_path / "s"
    assert BACKLOG.main(["add", "--store", str(store), *_ADD, "--status", "triaged"]) == 64
    err = capsys.readouterr().err
    assert "no-next-action" in err, err
    # ...and it says the ways out, both of which have to be reachable FROM `add`.
    assert "--resolution" in err, err
    assert "--status open" in err, err
    # `add` refuses the groom flags by name, so a hint that offers `--plan` without
    # saying it belongs to `update` sends the caller straight into a second refusal.
    for line in err.splitlines():
        if "--plan" in line:
            assert "update" in line, (
                f"a hint offers --plan, which `add` refuses, without routing it "
                f"through `update`: {line}")
    assert not (store.exists() and list(store.glob("*.json"))), (
        "a refused add left half an entry behind")


def test_add_is_silent_on_an_ordinary_new_open_entry(tmp_path, capsys):
    """The positive control, and the reason the check is per-kind rather than blanket.

    A freshly filed entry legitimately has no plan, no acceptance and no landing
    commit. If this pre-check red-lined that, the repair would be a tool nobody
    can file with — a strictly worse failure than the one it fixes.
    """
    store = tmp_path / "s"
    assert BACKLOG.main(["add", "--store", str(store), *_ADD, "--json"]) == 0
    entry = json.loads(capsys.readouterr().out)["entry"]
    assert entry["status"] == "open"
    assert (store / f"{entry['id']}.json").exists()
    # The real assertion: the two now agree about the same entry. `add` writing
    # something `validate` refuses is the whole defect, so this is what has to hold.
    assert BACKLOG.main(["validate", "--store", str(store)]) == 0
    capsys.readouterr()


def test_add_still_accepts_a_triaged_entry_that_carries_its_next_action(tmp_path, capsys):
    """The rule is "triaged owes a next action", not "triaged is banned".

    `_next_action` accepts a resolution opening with an em-dash, the convention
    that predates `plan`. Filing straight into `triaged` stays possible for
    somebody who has actually decided the next step.
    """
    store = tmp_path / "s"
    assert BACKLOG.main(["add", "--store", str(store), *_ADD, "--status", "triaged",
                         "--resolution", "— 下一步:把 choices 收窄,並在落檔前跑同一份檢查",
                         "--json"]) == 0
    entry = json.loads(capsys.readouterr().out)["entry"]
    assert entry["status"] == "triaged"
    assert BACKLOG.main(["validate", "--store", str(store)]) == 0
    capsys.readouterr()


def test_add_refuses_a_wont_fix_with_no_reason(tmp_path, capsys):
    """The sibling rule, exempted by the same switch and for no better reason.

    A decision not to fix is an argument; `wont-fix` with an empty resolution is
    the shape of an entry closed by reflex, and `add` could write it.
    """
    store = tmp_path / "s"
    assert BACKLOG.main(["add", "--store", str(store), *_ADD, "--status", "wont-fix"]) == 64
    assert "wont-fix-without-reason" in capsys.readouterr().err
    assert not (store.exists() and list(store.glob("*.json")))


def test_creation_still_forgives_the_rules_that_need_a_repo(tmp_path):
    """The exemption `check_traceability=False` was actually for, kept intact.

    `import` exists to represent HISTORY, and history is full of `fixed` rows
    whose landing commit was never written down. Refusing them at creation would
    mean the only way to migrate the ledger is to first solve the audit problem
    the migration exists to expose. Measured against the frozen 8-column fixture
    when this landed: 0 of 141 rows are affected by the rules that DID move.
    """
    store = tmp_path / "s"
    entry = BACKLOG.add_entry(store, **_entry_kwargs(status="fixed",
                                                     resolution="landed long ago"))
    assert entry["status"] == "fixed" and "fixed_by" not in entry


def test_importing_history_keeps_a_triaged_row_the_new_rule_would_refuse(tmp_path):
    """The regression this rule caused on its way in, pinned so it cannot come back.

    The legacy table's empty-resolution marker is a bare em-dash, so a historical
    `triaged` row with nothing decided has no next action by today's rule. With the
    check applied to `import` as well, `add_entry` raised, `import_legacy` recorded
    a `rejected-row` and carried on — and the entry was GONE. A migration is not a
    place to enforce a rule invented after the data: the only way to satisfy it is
    to invent a plan for work nobody triaged, and the alternative the importer
    actually takes is to drop the row.

    So the exemption is named at the ONE call site that has a reason for it, and
    `validate` still reports the row afterwards — this forgives the moment of
    writing, not the finding.
    """
    store = tmp_path / "s"
    entry = BACKLOG.add_entry(store, historical=True,
                              **_entry_kwargs(status="triaged", resolution=""))
    assert (store / f"{entry['id']}.json").exists(), "a historical row was dropped"

    # ...and it is still VISIBLE as a problem, so nothing was swept under the rug
    kinds = [p["kind"] for p in BACKLOG.validate_store(store, commit_state=None)]
    assert "no-next-action" in kinds, kinds

    # ...while the interactive door, which has no such reason, still refuses it
    with pytest.raises(ValueError, match="no-next-action"):
        BACKLOG.add_entry(store, **_entry_kwargs(status="triaged", resolution="",
                                                 detail="filed by hand today"))


def test_the_historical_exemption_forgives_only_what_it_names(tmp_path):
    """An exemption whose bound nothing checks is not an exemption, it is an off switch.

    Written because a mutation proved it: widening the forgiven set to "every
    problem this payload has" survived the whole suite green. `import` would then
    write anything the legacy parser handed it — including shapes `validate` is
    about to refuse over the entire store — which is the same "turned a check off
    wider than the reason required" defect as the one this section exists for, one
    caller along.

    `app-field-on-imp-entry` is the probe because it is reachable through
    `add_entry`'s own keywords and is emitted by a check the exemption does not
    name.
    """
    store = tmp_path / "s"
    with pytest.raises(ValueError, match="app-field-on-imp-entry"):
        BACKLOG.add_entry(store, historical=True,
                          **_entry_kwargs(stream="IMP", surface="reader"))
    assert not (store.exists() and list(store.glob("*.json")))


def test_fixed_elsewhere_is_reachable_through_a_channel_the_shell_cannot_edit(tmp_path):
    """The field most likely to carry a backtick, driven through its twin for real.

    Its value is a path plus the command that re-derives the fix — `~` and
    backticks, i.e. exactly what a shell rewrites before this process sees argv.
    The generic twin test intersects with `FILE_TWIN_FIELDS` itself, so it goes
    quiet the moment a field leaves that constant: it can prove the twin exists,
    never that this field still has one. This drives the value end to end.
    """
    store = tmp_path / "s"
    entry = _closable(store)
    payload = tmp_path / "elsewhere.txt"
    payload.write_text(ELSEWHERE + "\n", encoding="utf-8")

    assert BACKLOG.main(["update", entry["id"], "--store", str(store),
                         "--status", "fixed", "--resolution", "landed in butler",
                         "--fixed-elsewhere-file", str(payload), "--commit"]) == 0
    stored = BACKLOG.load_entry(store, entry["id"])
    assert stored["fixed_elsewhere"] == ELSEWHERE, (
        "the backtick-bearing text did not survive the file channel verbatim")
    assert "`" in stored["fixed_elsewhere"], "the fixture stopped testing the hazard"


# --------------------------------------------------------------------------
# 28. `audit-criteria` — running the criteria themselves (IMP-20260808-09dd3b)
#
# An entry that is still OPEN says the defect is still there. Its
# `acceptance_cmd` says what "gone" looks like. So on an open entry that command
# should be RED today, and a green one has exactly two readings, both bad:
#
#   1. the entry is already fixed and nobody closed it — it will be dispatched
#      again and the next agent redoes finished work;
#   2. the criterion does not test what its prose claims. That one is worse,
#      because `_acceptance_gate` RUNS this command at closing time and lets the
#      closure through: a defect nobody fixed gets stamped machine-verified.
#
# Reading 2 has a confirmed case. IMP-20260805-958999's criterion ended in
# `! grep -qF "…" docs/snapshot/ios_baseline.md`; that file left version control
# with IMP-20260808-b63206, `grep` on a missing file exits 2, and the leading `!`
# turns that into a pass. Green, for a reason that has nothing to do with the
# subject.
#
# Every test below names `criteria` on purpose: the entry's own acceptance is
# `pytest … -k criteria`, and a `-k` that selects nothing exits 5, not 0 —
# measured before writing any of this. A test outside that filter is a test this
# entry cannot be closed on.
# --------------------------------------------------------------------------

def _criteria_target(store, *, detail, cmd, **overrides):
    """A groomed, unresolved entry carrying `cmd` as its executable criterion."""
    entry = _add(store, detail=detail)
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd=cmd, **overrides))
    return entry["id"]


def _criteria_audit(store, *extra, expect_rc=0, capsys=None):
    """Run the sweep and return (payload, stderr).

    `--all` unless the caller narrows: a bare invocation is refused on purpose (the
    command executes stored free text), and every test here is about what the sweep
    REPORTS rather than about that guard, which has its own test.
    """
    narrowed = any(a in ("--filter", "--limit", "--all", "--dry-run") for a in extra)
    argv = ["audit-criteria", "--store", str(store), "--json",
            *([] if narrowed else ["--all"]), *extra]
    rc = BACKLOG.main(argv)
    captured = capsys.readouterr()
    assert rc == expect_rc, f"rc={rc}; stderr={captured.err[-800:]}"
    return json.loads(captured.out), captured.err


def test_audit_criteria_flags_a_criterion_that_is_green_on_an_open_entry(tmp_path, capsys):
    """The whole product of this command: the suspect list."""
    store = tmp_path / "s"
    suspect = _criteria_target(store, detail="claims to be open", cmd="true")

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["green"]] == [suspect]
    assert payload["green"][0]["rc"] == 0 and payload["green"][0]["expect_rc"] == 0
    assert payload["green"][0]["cmd"] == "true"


def test_audit_criteria_leaves_a_red_criterion_in_the_uninteresting_bucket(tmp_path, capsys):
    """Red is the HEALTHY answer here, and inverting that would make the tool useless."""
    store = tmp_path / "s"
    healthy = _criteria_target(store, detail="genuinely still broken", cmd="false")

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["red"]] == [healthy]
    assert payload["green"] == []


def test_audit_criteria_names_the_last_clause_of_a_silent_failure(tmp_path, capsys):
    """A silent && chain must expose the failed clause, not just rc=1."""
    store = tmp_path / "s"
    silent = _criteria_target(store, detail="silent clause", cmd="true && test 1 = 2 && true")

    payload, _ = _criteria_audit(store, capsys=capsys)

    row = payload["red"][0]
    assert row["id"] == silent
    assert "test 1 = 2" in row["failing_clause"], row


def test_failed_acceptance_keeps_output_tail_and_adds_failing_clause(capsys):
    """The closure gate's shared executor reports output and attribution separately."""
    result = BACKLOG._run_acceptance(
        "probe", "printf 'visible\\n'; printf '+ input echo\\n' >&2; false", 0)

    assert result["ok"] is False
    assert "visible" in result["output_tail"]
    assert "+ input echo" in result["output_tail"]
    assert "false" in result["failing_clause"]
    assert "input echo" not in result["failing_clause"]
    capsys.readouterr()


def test_audit_criteria_keeps_shell_failure_in_error_without_attribution(tmp_path, capsys):
    """A command the shell cannot start is an error, not a named failed clause."""
    store = tmp_path / "s"
    broken = _criteria_target(store, detail="missing command", cmd="kg-no-such-command-failing-clause")

    payload, _ = _criteria_audit(store, capsys=capsys)

    row = payload["error"][0]
    assert row["id"] == broken
    assert row["rc"] == 127
    assert row["failing_clause"] == ""
    assert payload["red"] == []


def test_audit_criteria_does_not_trace_a_timeout_twice(tmp_path, capsys):
    """Timeout means no answer; diagnostic replay must not repeat the command."""
    store = tmp_path / "s"
    marker = tmp_path / "runs"
    hanging = _criteria_target(
        store, detail="timeout is not a mismatch", cmd=f"printf x >> {marker}; sleep 30")

    payload, _ = _criteria_audit(store, "--timeout-seconds", "1", capsys=capsys)

    assert [row["id"] for row in payload["timeout"]] == [hanging], payload
    assert marker.read_text(encoding="utf-8") == "x"


def test_audit_criteria_separates_a_broken_command_from_a_red_criterion(tmp_path, capsys):
    """THE test. A command that could not run has said nothing about the defect.

    `exit 127` is the shell saying it never found what you named. Filing that
    under `red` means "the defect is still there, carry on" — which is the exact
    misreading this command exists to destroy, arriving through the back door of
    the command that hunts for it.
    """
    store = tmp_path / "s"
    broken = _criteria_target(store, detail="criterion names a tool nobody has",
                              cmd="kg-no-such-command-9f3838")

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["error"]] == [broken], payload
    assert payload["red"] == [], "a command that never ran was graded as a red criterion"
    assert payload["error"][0]["rc"] == 127
    assert payload["error"][0]["reason"] == "command-not-found"
    # The shell says WHY on stderr and nowhere else. A tail that captured only
    # stdout would report this row with an empty explanation, which is the one
    # field telling the reader whether to go fix the entry or fix their machine.
    assert "kg-no-such-command-9f3838" in payload["error"][0]["output_tail"], payload


def test_audit_criteria_reports_a_hanging_criterion_as_a_timeout(tmp_path, capsys):
    """Neither green nor red: it did not answer."""
    store = tmp_path / "s"
    hanging = _criteria_target(store, detail="criterion waits forever", cmd="sleep 30")

    payload, _ = _criteria_audit(store, "--timeout-seconds", "1", capsys=capsys)

    assert [row["id"] for row in payload["timeout"]] == [hanging], payload
    assert payload["green"] == [] and payload["red"] == [] and payload["error"] == []
    assert payload["timeout"][0]["timeout_seconds"] == 1


def test_audit_criteria_does_not_read_a_124_exit_as_a_timeout(tmp_path, capsys):
    """`124` is what the runner writes when IT killed the child — and also a number
    a child may exit with on its own, immediately.

    Keying the timeout bucket on the return code alone makes the two
    indistinguishable, which is this entry's own defect (an assertion satisfied
    by something other than its subject) reproduced inside the auditor.
    """
    store = tmp_path / "s"
    quick = _criteria_target(store, detail="criterion exits 124 at once", cmd="exit 124")

    payload, _ = _criteria_audit(store, "--timeout-seconds", "30", capsys=capsys)

    assert payload["timeout"] == [], "an instant exit was reported as a timeout"
    assert [row["id"] for row in payload["red"]] == [quick]


def test_audit_criteria_does_not_execute_a_criterion_that_cannot_parse(tmp_path, capsys):
    """A string no shell can read is not a criterion, and bash's syntax-error `2`
    is indistinguishable from a hundred tools' "I found the problem"."""
    store = tmp_path / "s"
    good = _criteria_target(store, detail="fine", cmd="false")
    # Hand-edited on purpose: `update` refuses this shape, so the only way it
    # reaches the store is somebody editing the JSON — which is how the two
    # measured cases got there.
    broken_id = _criteria_target(store, detail="mangled while transcribing", cmd="false")
    path = store / f"{broken_id}.json"
    payload_on_disk = json.loads(path.read_text(encoding="utf-8"))
    payload_on_disk["acceptance_cmd"] = 'grep -q "unterminated ops/x.py'
    path.write_text(json.dumps(payload_on_disk, indent=2, ensure_ascii=False),
                    encoding="utf-8")

    payload, err = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["error"]] == [broken_id], payload
    assert payload["error"][0]["reason"] == "does-not-parse"
    # Proof of NON-EXECUTION has to come from something other than this module: the
    # `rc: None` in that row is written by the very branch under test, so asserting
    # it only says the code did what the code does (measured — running the command
    # before the early return left an earlier version of this test green).
    # `run_streamed_command` prints `phase=start` unconditionally the moment it is
    # called, so its ABSENCE is a fact produced by the other module.
    assert f"entry={broken_id} phase=start" not in err, err
    assert f"entry={good} phase=start" in err, "the fixture stopped running anything"
    assert [row["id"] for row in payload["red"]] == [good]


def test_audit_criteria_writes_nothing_to_the_store(tmp_path, capsys):
    """Read-only by construction — there is no `--commit` and no write path."""
    store = tmp_path / "s"
    _criteria_target(store, detail="green one", cmd="true")
    _criteria_target(store, detail="red one", cmd="false")
    before = {p.name: p.read_bytes() for p in sorted(store.glob("*.json"))}

    _criteria_audit(store, capsys=capsys)

    after = {p.name: p.read_bytes() for p in sorted(store.glob("*.json"))}
    assert after == before, "the audit modified the store it was reading"
    flags = {opt
             for action in BACKLOG._subcommands(BACKLOG.build_parser())["audit-criteria"]._actions
             for opt in action.option_strings}
    assert "--commit" not in flags, "a read-only audit grew a write door"


def test_audit_criteria_keeps_progress_on_stderr_and_json_on_stdout(tmp_path, capsys):
    """82 entries × one command each is a multi-minute sweep, so silence is not an
    option — and the JSON channel must survive the noise (iron law 5)."""
    store = tmp_path / "s"
    first = _criteria_target(store, detail="one", cmd="true")
    second = _criteria_target(store, detail="two", cmd="false")

    payload, err = _criteria_audit(store, capsys=capsys)

    assert payload["schema"] == "kg.backlog.audit-criteria.v1"
    for entry_id in (first, second):
        # The PREFIX is asserted, not just the phase fields: it is the grep handle
        # an operator watching a 30-minute sweep uses, and `entry=… phase=…` alone
        # is a shape any hand-rolled print could imitate — measured, renaming the
        # prefix left an earlier version of this test green.
        assert f"[backlog][audit] entry={entry_id} phase=start" in err, err
        assert re.search(rf"\[backlog\]\[audit\] entry={entry_id} phase=done .*rc=",
                         err), err
    # Position in the sweep, which the runner cannot know: without it "slow" and
    # "stuck" look identical from the outside.
    assert "[backlog][audit] 2/2 entry=" in err, err


def test_audit_criteria_runs_only_what_the_filter_selects(tmp_path, capsys):
    """This command executes free text out of the store. Running the whole store
    by reflex is how a sweep opens a simulator or calls a network."""
    store = tmp_path / "s"
    ran = tmp_path / "ran"
    skipped = tmp_path / "skipped"
    wanted = _criteria_target(store, detail="the one I asked for", cmd=f"touch {ran}")
    other = _criteria_target(store, detail="the one I did not", cmd=f"touch {skipped}")

    payload, _ = _criteria_audit(store, "--filter", wanted, capsys=capsys)

    assert ran.exists(), "the selected criterion never ran"
    assert not skipped.exists(), "--filter ran a command it did not select"
    assert payload["selected"] == 1
    assert other not in json.dumps(payload)


def test_audit_criteria_names_what_the_limit_left_unrun(tmp_path, capsys):
    """A truncated sweep whose gaps are invisible reads as a clean bill of health."""
    store = tmp_path / "s"
    _criteria_target(store, detail="high one", cmd="true", severity="high")
    low = _criteria_target(store, detail="low one", cmd="true", severity="low")

    payload, _ = _criteria_audit(store, "--limit", "1", capsys=capsys)

    assert payload["ran"] == 1
    # The ID, not the count. The help and the payload comment both promise the unrun
    # entries are NAMED, and a length assertion is satisfied by a list of the right
    # size holding anything at all — measured, filling it with a placeholder string
    # left an earlier version of this test green.
    assert payload["skipped_by_limit"] == [low], payload
    # Worst-first, like `dispatch`: a limit that took the low one first would be
    # a different command than the one the help describes.
    assert payload["green"][0]["detail"].startswith("high")


def test_audit_criteria_honours_a_named_exemption_without_running_it(tmp_path, capsys):
    """Green is a CANDIDATE, not a verdict — some criteria are green by design.

    The answer is `acceptance_manual`'s: not a quieter check, a DECLARED
    exception somebody can count. Reported with its reason and never run, so the
    bucket is a list of declarations rather than a measurement pretending to be one.
    """
    store = tmp_path / "s"
    marker = tmp_path / "exempt-ran"
    exempt = _criteria_target(
        store, detail="a negative assertion, green forever", cmd=f"touch {marker}",
        acceptance_green_expected="this criterion asserts an absence; it is green "
                                  "until the defect is REintroduced")
    # A second, NON-exempt entry, so the ledger filter below has something to
    # exclude. Without it the store has one entry and an unfiltered list returns
    # the same single id — the assertion would be satisfied by the store's size
    # rather than by the filter (measured: making the filter a no-op left this
    # test green).
    _criteria_target(store, detail="an ordinary criterion", cmd="false")

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert not marker.exists(), "an exempt criterion was executed anyway"
    assert [row["id"] for row in payload["exempt"]] == [exempt]
    assert "asserts an absence" in payload["exempt"][0]["reason"]
    assert [row["id"] for row in payload["green"]] == [], (
        "the exemption did not keep it out of the suspect list")
    # Countable from the ledger too, exactly like --acceptance-manual.
    assert [p["id"] for p in BACKLOG.list_entries(store, acceptance_green_expected=True)] \
        == [exempt]


def test_a_criteria_exemption_with_no_command_to_exempt_is_refused():
    """An exemption from running a command that does not exist exempts nothing."""
    payload = {**_entry_kwargs(), "id": "IMP-0001", "schema": BACKLOG.SCHEMA,
               "plan": "x", "acceptance": "y", "fix_site": "ops/x.py:1",
               "brief": BRIEF_TEXT, "scope": SCOPE_TEXT,
               "groomed_at": "2026-08-05", "groomed_by": "workflow:groom@v1",
               "acceptance_manual": "needs a device",
               "acceptance_green_expected": "green by design"}
    kinds = [p["kind"] for p in BACKLOG.validate_entry(payload)]
    assert "acceptance-green-expected-without-cmd" in kinds, kinds


def test_audit_criteria_looks_at_groomed_unresolved_entries_only(tmp_path, capsys):
    """The premise is "this entry says the defect is still there". A closed entry
    says the opposite, and an ungroomed one has no criterion worth believing."""
    store = tmp_path / "s"
    live = _criteria_target(store, detail="open and groomed", cmd="true")
    closed = _criteria_target(store, detail="already closed", cmd="true")
    BACKLOG.update_entry(store, closed, status="wont-fix",
                         resolution="decided against it")
    ungroomed = _add(store, detail="nobody has worked this out")["id"]

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["green"]] == [live]
    blob = json.dumps(payload)
    assert closed not in blob and ungroomed not in blob


def test_audit_criteria_counts_the_entries_it_could_not_run(tmp_path, capsys):
    """An absence nobody counts is how `acceptance` spent its whole life write-only."""
    store = tmp_path / "s"
    declared = _add(store, detail="needs a physical device")["id"]
    BACKLOG.update_entry(store, declared, **_groom_kwargs(
        acceptance_cmd=None, acceptance_expect_rc=None,
        acceptance_manual="needs a device on a live backend"))
    silent = _add(store, detail="groomed before the rule existed")["id"]
    BACKLOG.update_entry(store, silent, **_groom_kwargs(
        acceptance_cmd=None, acceptance_expect_rc=None))

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert [row["id"] for row in payload["manual"]] == [declared]
    assert [row["id"] for row in payload["unproven"]] == [silent]


def test_audit_criteria_says_green_is_a_candidate_not_a_verdict(tmp_path, capsys):
    """The output is a work queue for a human. A tool that reports "these entries
    are zombies" would be making the second claim this entry is about.

    Two halves, and only one of them is evidence. The substring check is a constant
    read against itself — it can fail only if somebody edits `AUDIT_CAVEAT` into a
    verdict, which is exactly the regression worth a tripwire but is not a test of
    behaviour. The half that IS behaviour is the plumbing: the caveat has to reach
    the human channel too, and nothing else in this section drives the non-JSON
    path at all.
    """
    store = tmp_path / "s"
    _criteria_target(store, detail="suspect", cmd="true")

    payload, _ = _criteria_audit(store, capsys=capsys)
    assert "candidate" in payload["caveat"].lower(), payload["caveat"]
    assert "red` is not a clean bill of health" in payload["caveat"], (
        "the caveat stopped admitting the blind spot on the red side")

    assert BACKLOG.main(["audit-criteria", "--store", str(store), "--all"]) == 0
    human = capsys.readouterr().out
    assert BACKLOG.AUDIT_CAVEAT in human, "the human channel dropped the caveat"
    assert "green (1)" in human, human


def test_audit_criteria_help_admits_it_executes_stored_free_text():
    """No static safety judgement is offered anywhere, because none is possible —
    so the help has to say what the caller is about to do instead."""
    sub = BACKLOG._subcommands(BACKLOG.build_parser())["audit-criteria"]
    text = sub.format_help().lower()

    assert "execut" in text, text
    assert "acceptance_cmd" in text
    assert "--filter" in text and "--limit" in text


def test_audit_criteria_filter_does_not_match_across_the_seam(tmp_path, capsys):
    """`--filter` searches the id and the command SEPARATELY.

    Joining them and searching the blob is the bug `--grep` already shipped once:
    with a `"\n".join` the separator IS whitespace, so `alpha\\s+beta` matches an
    entry whose id ends in "alpha" and whose command starts with "beta" — a string
    neither field contains. Here the cost would be running a command the caller did
    not select, on a subcommand whose entire safety story is "you choose what runs".
    """
    store = tmp_path / "s"
    ran = tmp_path / "seam-ran"
    entry = BACKLOG.add_entry(store, **_entry_kwargs(
        entry_id="IMP-0091-ALPHA",
        detail="an entry whose id ends where the command begins"))
    BACKLOG.update_entry(store, entry["id"],
                         **_groom_kwargs(acceptance_cmd=f"BETA=1; touch {ran}"))

    payload, _ = _criteria_audit(store, "--filter", r"ALPHA\s+BETA", capsys=capsys)

    assert payload["selected"] == 0, payload
    assert not ran.exists(), "a pattern that matches neither field selected the entry"
    # Positive control: the filter is not simply broken. Same store, a pattern that
    # really is in the id, selects it.
    payload, _ = _criteria_audit(store, "--filter", "ALPHA", capsys=capsys)
    assert payload["selected"] == 1 and ran.exists()


@pytest.mark.parametrize("expect_rc", [126, 127])
def test_audit_criteria_never_grades_a_criterion_green_on_a_shell_failure(
        tmp_path, capsys, expect_rc):
    """An entry may not buy a green by expecting the code the shell writes when it
    could not run the command at all.

    126/127 come from the SHELL, not from the program the criterion names, so they
    are not evidence about the defect in either direction. The ordering inside
    `_audit_one` is what enforces that, and without this the claim was prose: no
    entry in the suite had an expectation in that range, so moving the check after
    the comparison changed nothing that was measured.
    """
    store = tmp_path / "s"
    entry = _criteria_target(store, detail="expects the shell to keep failing",
                             cmd="kg-no-such-command-h2c65", acceptance_expect_rc=expect_rc)

    payload, _ = _criteria_audit(store, capsys=capsys)

    assert payload["green"] == [], "a shell failure was graded as the criterion holding"
    assert [row["id"] for row in payload["error"]] == [entry], payload
    assert payload["error"][0]["rc"] == 127


def test_audit_criteria_refuses_to_sweep_the_whole_store_unasked(tmp_path, capsys):
    """The default must not execute every stored command.

    Measured on the live ledger the day this landed: the population's commands
    include a `curl` at another host, an `ios_ops.sh catalog` run that drives a
    simulator, and several infra probes. None of that is visible in the flag list,
    so a bare invocation is a sweep somebody did not know they were starting.
    """
    store = tmp_path / "s"
    marker = tmp_path / "unasked"
    _criteria_target(store, detail="has side effects", cmd=f"touch {marker}")

    assert BACKLOG.main(["audit-criteria", "--store", str(store), "--json"]) == 64
    out, err = capsys.readouterr().out, capsys.readouterr().err
    assert not marker.exists(), "the refusal still ran the command"
    payload = json.loads(out)
    assert payload["ok"] is False
    for way_out in ("--dry-run", "--filter", "--limit", "--all"):
        assert way_out in payload["error"], payload["error"]


def test_audit_criteria_contradictory_narrowing_is_refused(tmp_path, capsys):
    """`--all` says "no narrowing" and `--filter`/`--limit` narrow. Letting one win
    silently would run a set the caller did not describe."""
    store = tmp_path / "s"
    _criteria_target(store, detail="whatever", cmd="true")

    for extra in (["--all", "--filter", "IMP"], ["--all", "--limit", "1"]):
        assert BACKLOG.main(["audit-criteria", "--store", str(store), *extra]) == 64
        assert "contradicts" in capsys.readouterr().err


def test_audit_criteria_dry_run_executes_nothing_and_says_the_buckets_are_empty(
        tmp_path, capsys):
    """Consent needs a way to read the commands first — the same reason `anchor` has
    a dry run. And an empty `green` from a dry run is byte-identical to a clean
    sweep's, so the payload has to carry the difference or a machine reader will
    take the one for the other."""
    store = tmp_path / "s"
    marker = tmp_path / "dry-ran"
    entry = _criteria_target(store, detail="would have run", cmd=f"touch {marker}")

    payload, err = _criteria_audit(store, "--dry-run", capsys=capsys)

    assert not marker.exists(), "--dry-run executed the criterion"
    assert "phase=start" not in err, err
    assert payload["dry_run"] is True and payload["ran"] == 0
    assert [row["id"] for row in payload["would_run"]] == [entry]
    assert payload["would_run"][0]["cmd"] == f"touch {marker}"
    assert payload["green"] == [] and payload["red"] == []


def test_audit_criteria_asks_for_progress_inside_the_twenty_second_contract(tmp_path):
    """Iron law 5 is a NUMBER, and nothing was holding this one.

    The runner's default happens to be 20s, so the sweep satisfied the contract by
    inheritance — measured, injecting `heartbeat_interval=600.0` into the call left
    all 32 criteria/acceptance tests green. The interval is read back off the call
    itself, with the runner's own defaults applied, so this holds whether the value
    is passed explicitly or inherited.
    """
    seen = {}
    original = BACKLOG.run_streamed_command
    # Bound against the REAL signature, captured before the patch. Reading
    # `signature(BACKLOG.run_streamed_command)` inside the spy reads the spy's own
    # `(command, **kwargs)` — the assertion would then be inspecting the double
    # rather than the call it stands in for, which is this section's whole subject.
    signature = inspect.signature(original)

    def spy(command, **kwargs):
        bound = signature.bind(command, **kwargs)
        bound.apply_defaults()
        seen.update(bound.arguments)
        result = subprocess.CompletedProcess(command, 0, "", "")
        result.timed_out = False
        return result

    store = tmp_path / "s"
    _criteria_target(store, detail="anything", cmd="true")
    BACKLOG.run_streamed_command = spy
    try:
        assert BACKLOG.main(["audit-criteria", "--store", str(store), "--all"]) == 0
    finally:
        BACKLOG.run_streamed_command = original

    assert seen, "the sweep never reached the streaming runner"
    assert seen["heartbeat_interval"] <= 20.0, (
        f"heartbeat every {seen['heartbeat_interval']}s breaks the <=20s contract")
    assert seen["timeout_seconds"] == BACKLOG.AUDIT_TIMEOUT_SECONDS

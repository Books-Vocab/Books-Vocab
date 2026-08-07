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
import inspect
import json
import os
import re
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
                         verified_by="agent:test", verified_evidence="pytest -k x",
                         **_groom_kwargs())

    rendered = BACKLOG.render_view(store, verified_against="deadbeef")
    BACKLOG.import_legacy(rendered, store)

    loaded = BACKLOG.load_entry(store, entry["id"])
    # The verification stamp is in this set for the same reason the groom fields
    # are: the table does not own it, so a re-import that drops it is erasing
    # work. Adding fields to the module and not to this assertion is how the
    # original bug came back the second time.
    for field in BACKLOG.GROOM_FIELDS + ("verdict", "verified_at", "verified_by",
                                        "verified_evidence"):
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

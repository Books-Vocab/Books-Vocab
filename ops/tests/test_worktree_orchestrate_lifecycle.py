"""Behavior-group collector for worktree_orchestrate (lifecycle)."""

from worktree_orchestrate_support import *  # noqa: F401,F403


@gitmark
def test_cutover_refuses_required_tier_metadata_drift(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "tier-drift.json")
    wt = _open_wt(state, slug="tier-drift")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, gate
    record_path = MODULE._gate_record_path(state, wt)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["required_tier"] = "S3"
    record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rc, cut = _run_json(
        ["cutover", "--worktree", wt, "--state", state, "--commit", "--json"]
    )
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert "required tier" in cut["error"]
    assert "notes.txt" not in _local_main_files(repo)

@gitmark
def test_open_cutover_resolve_roundtrip_leaves_no_residue(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    # --- open: worktree add + registry register ---
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "reader-crash",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    assert opened["branch"] == "debug/reader-crash"
    wt = opened["path"]
    assert Path(wt).is_dir()
    scratch_dir = Path(opened["scratch_dir"])
    assert scratch_dir.is_dir()
    assert scratch_dir.parent == Path(wt) / ".cache"
    _git(["check-ignore", "-q", "--", str(scratch_dir)], wt)
    assert "reader-crash" in {r["branch"].split("/")[-1] for r in
                              json.loads(Path(state).read_text())["records"]}

    # --- mock work: a commit touching a NEUTRAL file (matches no impact gate) ---
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)

    # --- gate: neutral change -> no impact gates -> verdict pass ---
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["schema"] == "kg.worktree.gate.v1"
    # Contract update (2026-08-03): the fixture's file is routed to no gate, so
    # the always-planned coverage gate warns. `warn` still lands; what changed is
    # that "nothing was checked" is now visible instead of reading as pass.
    assert gate["verdict"] == "warn"
    assert [g["name"] for g in gate["gates"] if g["status"] == "warn"] == ["coverage"]
    # Only the coverage bookkeeping gate runs; an empty gate list is no longer
    # reachable, which is the point (see test_plan_is_never_empty).
    assert [g["name"] for g in gate["gates"]] == ["coverage"]
    assert "notes.txt" in gate["changed_files"]
    # gate wrote a verdict cache beside the ledger (nit3 will strike it on resolve).
    gate_cache = MODULE._gate_record_path(state, wt)
    assert gate_cache.exists()
    # A failed gate ALSO leaves an output log beside that cache (IMP-20260808-c47253).
    # This run is green so there is none; plant one so the residue assertion below has
    # something to be about. Planted through the real path helper — a hand-spelled
    # filename would still pass while resolve cleaned a directory nobody writes to.
    stray_log = MODULE._gate_log_path(gate_cache, "ops-shell:test_devops.sh")
    stray_log.write_text("✗ some assertion\n", encoding="utf-8")

    # --- cutover: rebase onto local main + ff the primary's local main (--commit) ---
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["landed"] is True
    # local main now carries the work
    assert "notes.txt" in _local_main_files(repo)

    # --- resolve: teardown worktree + branch, close the ledger ---
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK

    # NO residue: worktree gone, local branch gone, gate-record cache struck (nit3)
    assert not Path(wt).exists()
    assert not scratch_dir.exists()
    assert "debug/reader-crash" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()
    assert not stray_log.exists(), (
        "a failed gate's output log outlives the worktree it describes unless resolve "
        "strikes it too — same residue rule as the verdict cache")
    # ledger record struck to merged
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs["debug/reader-crash"]["status"] == "merged"
    assert recs["debug/reader-crash"]["resolved_at"] is not None

@gitmark
def test_delegated_worktree_is_marked_and_cutover_refuses_before_gate(scratch):
    """A delegated child must be refused before a gate verdict is required."""
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    wt = None
    try:
        rc, opened = _run_json([
            "open", "--intent", "delegated child", "--slug", "delegated-child",
            "--delegated", "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_OK, opened
        wt = opened["path"]
        records = json.loads(Path(state).read_text())["records"]
        assert next(r for r in records if r["path"] == wt)["delegated"] is True

        rc, refusal = _run_json([
            "cutover", "--worktree", wt, "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_BLOCK, refusal
        assert refusal["refusal"] == "delegated"
    finally:
        if wt and Path(wt).exists():
            MODULE.main([
                "resolve", "--worktree", wt, "--state", state,
                "--force", "--commit", "--json",
            ])


def test_open_work_mode_requires_scope_or_ticket_claim(scratch):
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "work-mode.json")
    rc, refusal = _run_json([
        "open", "--intent", "direct child", "--slug", "mode-direct",
        "--work-mode", "direct-assignment", "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_USAGE
    assert refusal["reason"] == "invalid-work-mode"

    scope = json.dumps({"files": [{"path": "notes.txt", "operation": "add"}]})
    rc, opened = _run_json([
        "open", "--intent", "direct child", "--slug", "mode-direct-ok",
        "--work-mode", "direct-assignment", "--scope", scope,
        "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_OK
    record = next(r for r in json.loads(Path(state).read_text())["records"]
                  if r["branch"] == opened["branch"])
    assert record["work_mode"] == "direct-assignment"
    MODULE.main([
        "resolve", "--worktree", opened["path"], "--state", state,
        "--force", "--commit", "--json",
    ])

@gitmark
def test_two_open_worktrees_get_distinct_scratch_dirs_and_resolve_removes_them(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")

    opened = []
    for slug in ("scratch-alpha", "scratch-beta"):
        rc, payload = _run_json([
            "open", "--intent", "isolate agent scratch", "--slug", slug,
            "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_OK
        scratch_dir = Path(payload["scratch_dir"])
        assert scratch_dir.is_dir()
        _git(["check-ignore", "-q", "--", str(scratch_dir)], payload["path"])
        (scratch_dir / "same-name.log").write_text(slug, encoding="utf-8")
        opened.append((payload["path"], scratch_dir))

    assert opened[0][1] != opened[1][1]
    assert (opened[0][1] / "same-name.log").read_text(encoding="utf-8") == "scratch-alpha"
    assert (opened[1][1] / "same-name.log").read_text(encoding="utf-8") == "scratch-beta"

    for wt, scratch_dir in opened:
        rc, resolved = _run_json([
            "resolve", "--worktree", wt, "--state", state,
            "--force", "--commit", "--json",
        ])
        assert rc == MODULE.EXIT_OK, resolved
        assert not scratch_dir.exists()
        assert not Path(wt).exists()

@gitmark
def test_open_forks_from_local_main_not_origin(scratch):
    # local-centric: a commit that exists only on LOCAL main (origin never saw it) must
    # be present in a freshly opened worktree — proving the fork point is local, offline.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_local_main(repo, "localwork")
    assert "localwork.txt" not in _origin_main_files(remote)   # origin is behind
    rc, opened = _run_json(["open", "--intent", "build on local work",
                            "--slug", "on-local", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    assert (Path(wt) / "localwork.txt").exists()               # forked from local main
    assert opened["base"] == "main"

@gitmark
def test_cutover_advances_local_main_and_leaves_origin_untouched(scratch):
    # the defining property of the local-centric model: cutover lands on LOCAL main,
    # origin is NOT pushed (deploy is a separate step).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert "notes.txt" in _local_main_files(repo)              # local trunk advanced
    assert "notes.txt" not in _origin_main_files(remote)       # origin UNTOUCHED

@gitmark
def test_cutover_refused_when_primary_is_dirty(scratch):
    # cutover ff's the primary's checked-out main, which updates its working tree — so
    # a dirty primary (tracked changes) must refuse rather than clobber.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "doit",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    (repo / "f").write_text("dirtied the primary\n")            # tracked, uncommitted
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "dirty" in json.dumps(cut)
    assert cut["landed"] is False
    assert "notes.txt" not in _local_main_files(repo)          # trunk not advanced
    _git(["checkout", "--", "f"], repo)                         # clean up → now it lands
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True

@gitmark
def test_a_dirty_primary_broadcast_names_the_blocked_branch_and_the_files(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "bcast",
                            "--state", state, "--json"])
    wt, branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    assert not mailbox.exists()
    (repo / "f").write_text("someone else's uncommitted work\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK and cut["landed"] is False

    posted = mailbox.read_text()
    assert branch in posted, "a notice nobody can attribute is worse than none"
    # the dirty LINE, parsed — not a substring search over the whole record. `f` is one
    # character, and the 16-hex marker contains an `f` about 64% of the time, so the
    # loose version's discriminating power was a coin flip on the slug and the wording.
    line = next(ln for ln in posted.splitlines() if ln.startswith("dirty: "))
    assert [c.strip("`") for c in line.removeprefix("dirty: ").split(", ")] == ["f"]
    assert wt in posted, "the reader has to be able to find the blocked session"
    # the refusal itself is unchanged, and now says where it wrote
    assert "dirty" in cut["error"]
    assert "broadcast.md" in cut["error"]
    assert cut["broadcast"] == str(mailbox)

@gitmark
def test_a_dirty_primary_broadcast_is_not_repeated_for_the_same_block(scratch):
    """Polling is the expected usage — the refusal literally says "re-run cutover once
    the primary is clean". If each attempt appended, the mailbox other humans read would
    be flooded by the one participant that is a program."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "bcast-idem",
                            "--state", state, "--json"])
    wt, branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    (repo / "f").write_text("dirty\n")
    for _ in range(3):
        rc, _cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                              "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
    assert mailbox.read_text().count(branch) == 1

    # but a DIFFERENT block is genuinely new information and must be posted.
    # `add g`, NOT `add -A`: the scratch fixture ships no .gitignore, so `-A` would
    # sweep in the tool's OWN mailbox and lock file and report them as someone's
    # uncommitted work — the exact inverse of production, where `.cache/` is ignored
    # (that is the premise the whole best-effort argument rests on).
    (repo / "g").write_text("a second dirty file\n")
    _git(["add", "g"], repo)
    rc, _cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                          "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert mailbox.read_text().count(branch) == 2

@gitmark
@pytest.mark.parametrize("break_it, which", [
    # a DIRECTORY where the file goes: read_text() raises before any write is attempted
    (lambda mb: (mb.parent.mkdir(parents=True, exist_ok=True), mb.mkdir()), "read"),
    # a read-only FILE: everything succeeds until `open("a")` — the write path itself.
    # Without this case the guard never reaches the append, and an implementation whose
    # write sits OUTSIDE the try/except passes anyway. Verified: moving the `open("a")`
    # block out of the `except OSError` arm leaves the directory case green and turns
    # this one red with a PermissionError traceback. Found by review of the first
    # version of this test, which had only the directory case.
    (lambda mb: (mb.parent.mkdir(parents=True, exist_ok=True),
                 mb.write_text("# mailbox\n"), mb.chmod(0o444)), "write"),
])
def test_a_dirty_primary_broadcast_failure_never_becomes_the_refusal(
        scratch, break_it, which):
    """`.cache/` is gitignored scratch, not a source of truth. If posting the notice
    fails, the operator must still be told the real reason — swapping a coordination
    courtesy in for the diagnosis would be strictly worse than not having it."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", f"bcast-ro-{which}",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    break_it(mailbox)
    try:
        (repo / "f").write_text("dirty\n")
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert cut["landed"] is False
        assert "dirty" in cut["error"], "the diagnosis must survive a failed courtesy"
        assert "f" in cut["dirty_files"]
        assert "broadcast.md" not in cut["error"], \
            "do not point at a file that was not written"
        assert cut.get("broadcast") is None
        assert "notes.txt" not in _local_main_files(repo)
    finally:
        if mailbox.is_file():
            mailbox.chmod(0o644)

def test_a_dirty_primary_broadcast_keys_on_every_file_not_just_the_shown_ten(
        tmp_path, monkeypatch):
    """The record shows ten paths but the key must cover all of them: an 11th file
    changing is a different block, and suppressing it would make the docs' claim
    ("idempotent per branch + dirty set") false for exactly the diffs big enough to
    matter. Same reason the join is NUL rather than newline — `_c_unquote` returns real
    filenames, and a newline separator collides `["a\\nb"]` with `["a", "b"]`.
    Found by review of IMP-20260806-42d183."""
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL
    twelve = [f"f{i}.txt" for i in range(12)]

    # the day is part of the key, so a real clock makes this flake when UTC midnight
    # lands between two of the six calls below
    class _Fixed:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(MODULE, "datetime", _Fixed)

    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve)
    assert mailbox.read_text().count("kg-cutover-block") == 1
    # same input again: still one
    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve)
    assert mailbox.read_text().count("kg-cutover-block") == 1
    # the 12th file changes — invisible in the shown ten, but a different block
    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve[:11] + ["other.txt"])
    assert mailbox.read_text().count("kg-cutover-block") == 2
    # separator collision: these two dirty sets must not share a key
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["a\nb"])
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["a", "b"])
    assert mailbox.read_text().count("kg-cutover-block") == 4
    # the paths go into markdown a human reads, so they are backtick-quoted and their
    # newlines escaped: unquoted, `a\nb` splits the record's own dirty line in two and a
    # leading `#` renders as a heading. test_cutover_dirty_refusal_unquotes_special_paths
    # proves this path really does receive names like that.
    lines = mailbox.read_text().splitlines()
    assert "dirty: `a\\nb`" in lines
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["#h.txt", "-i.txt"])
    assert "dirty: `#h.txt`, `-i.txt`" in mailbox.read_text().splitlines()

    # and a branch we could not determine is named as such rather than guessed
    assert MODULE._broadcast_cutover_block(primary, None, ["z.txt"])
    assert "(unknown)" in mailbox.read_text()

def test_a_dirty_primary_broadcast_marker_expires_with_the_day(tmp_path, monkeypatch):
    """Nobody deletes these. The record asks the reader to remove it when handled; the
    real mailbox is 694 lines going back to 2026-08-05 with not one entry removed. So a
    marker that never expires means the same branch blocked by the same file next week —
    slugs repeat, and the recurring dirty file is the same `ops/release.sh` — posts
    NOTHING, and the second block is invisible. The day is part of the key for that
    reason, and this is the only test that can see it. Found by review."""
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL

    class _FrozenClock:
        stamp = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.stamp

    monkeypatch.setattr(MODULE, "datetime", _FrozenClock)
    same = ("feat/x", ["ops/release.sh"])
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 1, "same day: one notice"

    # a later time on the SAME day is still the same block
    _FrozenClock.stamp = datetime(2026, 8, 8, 23, 59, tzinfo=timezone.utc)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 1

    # the next day it is news again
    _FrozenClock.stamp = datetime(2026, 8, 9, 0, 1, tzinfo=timezone.utc)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 2

def test_a_dirty_primary_broadcast_names_the_blocked_worktree(tmp_path):
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL

    assert MODULE._broadcast_cutover_block(
        primary, "feat/x", ["a.txt"], worktree="/w/tr ee\nX")
    branch_lines = [line for line in mailbox.read_text().splitlines()
                    if line.startswith("被擋的分支")]
    assert branch_lines == ["被擋的分支:`feat/x` (worktree `/w/tr ee\\nX`)"]

    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["b.txt"])
    branch_lines = [line for line in mailbox.read_text().splitlines()
                    if line.startswith("被擋的分支")]
    assert branch_lines[-1] == "被擋的分支:`feat/x`"

@gitmark
def test_cutover_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "doit2",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _git(["checkout", "-q", "-b", "sidetrack"], repo)           # primary leaves main
    try:
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(cut) and cut["landed"] is False
        # every refusal names its next step — here: put the primary back on main.
        assert "re-run cutover" in cut["error"]
    finally:
        _git(["checkout", "-q", "main"], repo)

@gitmark
def test_cutover_dirty_refusal_is_actionable(scratch):
    # a dirty-primary refusal must be ACTIONABLE for a concurrent-session agent:
    # name the dirty files (machine-readable `dirty_files` + in-message list) and
    # carry coordination guidance (find the co-tenant session, or evacuate your own
    # residue) instead of a bare "dirty" that leaves the agent dead-waiting.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "alpha.txt").write_text("base\n")
    (repo / "beta.txt").write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track alpha/beta"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-ux",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    (repo / "alpha.txt").write_text("another session's edit\n")
    (repo / "beta.txt").write_text("another session's edit\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK and cut["landed"] is False
    assert sorted(cut["dirty_files"]) == ["alpha.txt", "beta.txt"]  # machine-readable
    err = cut["error"]
    assert "alpha.txt" in err and "beta.txt" in err                 # named in message
    for cue in ("list_sessions", "send_message", "commit",          # coordination path
                "gate verdict", "re-run cutover"):                  # verdict stays valid
        assert cue in err, f"missing guidance cue {cue!r} in: {err}"

@gitmark
def test_cutover_dirty_refusal_caps_message_list_at_ten(scratch):
    # the message stays readable (first 10 + "… and N more"); the JSON carries ALL.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    names = [f"trk{i:02d}.txt" for i in range(12)]
    for n in names:
        (repo / n).write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track 12 files"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-cap",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    for n in names:
        (repo / n).write_text("dirty\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert sorted(cut["dirty_files"]) == sorted(names)   # JSON: complete list
    assert cut["error"].count("trk") == 10               # message: capped at 10
    assert "and 2 more" in cut["error"]

@gitmark
def test_cutover_dirty_refusal_unquotes_special_paths(scratch):
    # git porcelain C-quotes unusual paths (`"my file.txt"`; octal-escaped UTF-8 for
    # non-ASCII under default core.quotePath=true). dirty_files must carry the REAL
    # paths — a literal-quoted/escaped entry is unusable to both machines and humans.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    names = ["my file.txt", "中文檔.txt"]
    for n in names:
        (repo / n).write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track special names"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-quote",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    for n in names:
        (repo / n).write_text("dirty\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert sorted(cut["dirty_files"]) == sorted(names)   # unquoted, decoded paths
    assert not any('"' in f or "\\" in f for f in cut["dirty_files"])

@gitmark
def test_cutover_merge_in_flight_refusal_names_next_step(scratch):
    # non-dirty refusals keep their reason but must also point at the next step.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "merge-flight",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    # stage a merge-in-progress in the primary (MERGE_HEAD set)
    _git(["checkout", "-q", "-b", "side"], repo)
    (repo / "side.txt").write_text("side\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "side"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--no-commit", "--no-ff", "side"], repo)
    try:
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "merge is in progress" in cut["error"]
        assert "re-run cutover" in cut["error"]
    finally:
        _git(["merge", "--abort"], repo)
        _git(["branch", "-qD", "side"], repo)

@gitmark
def test_cutover_refused_without_a_passing_gate(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "add share sheet", "--slug", "share-sheet",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("x\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work"], wt)

    # cutover WITHOUT running gate first -> refused (no verdict on file)
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    # local main did NOT advance
    assert "notes.txt" not in _local_main_files(repo)

@gitmark
def test_cutover_refused_when_gate_verdict_is_stale(scratch):
    # a gate pass recorded against an OLD head must not authorize a cutover of NEW
    # (ungated) commits.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "fix thing", "--slug", "thing", "--state", state, "--json"]
    )
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("v1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "v1"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    # Contract update (2026-08-03): the fixture's file is routed to no gate, so
    # the always-planned coverage gate warns. `warn` still lands; what changed is
    # that "nothing was checked" is now visible instead of reading as pass.
    assert gate["verdict"] == "warn"
    assert [g["name"] for g in gate["gates"] if g["status"] == "warn"] == ["coverage"]

    # a NEW commit after the gate ran -> verdict is now stale
    (Path(wt) / "more.txt").write_text("v2\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "v2"], wt)

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False

@gitmark
def test_cutover_lands_with_warn_verdict(scratch):
    # nit1: a WARN verdict is advisory — the driving agent owns its disposition, the
    # tool must not hard-refuse it. A backend-src-only change (no targeted test in the
    # diff) plans a WARN advisory gate; cutover --commit must LAND it and record the
    # warning ("landed with warnings: <gate>").
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    rc, opened = _run_json(
        ["open", "--intent", "add backend endpoint", "--slug", "backend-ep",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    src = Path(wt) / "backend" / "src" / "kg" / "app.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x = 1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "backend src"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "warn"
    assert "backend-tests-advisory" in {g["name"] for g in gate["gates"]}

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["landed"] is True
    assert cut["verdict"] == "warn"
    assert "backend-tests-advisory" in cut["warnings"]
    # the work actually landed on LOCAL main
    assert "backend/src/kg/app.py" in _local_main_files(repo)

@gitmark
def test_cutover_refused_when_gate_verdict_is_block(scratch):
    # nit1 (the other edge): a BLOCK verdict must STILL refuse cutover. A docs change
    # with a conflict marker -> docs-conflict-markers blocks -> verdict block -> refused.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # seed a no-op docs_lint.sh into base so the docs-lint shell gate can run cleanly
    # (the conflict-marker internal gate is what supplies the block).
    lint = repo / "ops" / "docs_lint.sh"
    lint.parent.mkdir(parents=True, exist_ok=True)
    lint.write_text("#!/bin/sh\nexit 0\n")
    lint.chmod(0o755)
    _git(["add", "-A"], repo); _git(["commit", "-qm", "seed docs_lint"], repo)
    _git(["push", "-q", "origin", "main"], repo)

    rc, opened = _run_json(
        ["open", "--intent", "update the reader doc", "--slug", "reader-doc",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    doc = Path(wt) / "docs" / "reference" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("intro\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "doc with conflict"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert gate["verdict"] == "block"

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert "docs/reference/x.md" not in _local_main_files(repo)

@gitmark
def test_cutover_refuses_while_a_gate_was_left_inconclusive(scratch):
    """An inconclusive gate folds the VERDICT to warn, and a warn LANDS — so on its own
    the fold turns "this red could not be attributed" into "shipped with a note". That
    is the disarm direction, and it is reachable without any tag surgery: every
    concurrent `preflight` / `catchup` / `sync` / `deploy` runs `git fetch --prune`,
    which imports new origin tags and moves the snapshot under an unrelated gate.

    The summary already told the operator to re-run the gate; nothing made that happen.
    cutover now refuses, which costs one gate re-run and makes the instruction real.
    Found by review of IMP-20260805-4ec901."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    rc, opened = _run_json(
        ["open", "--intent", "add backend endpoint", "--slug", "inconc-refuse",
         "--state", state, "--json"])
    wt = opened["path"]
    src = Path(wt) / "backend" / "src" / "kg" / "app.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x = 1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "backend src"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK and gate["verdict"] == "warn"

    # poison exactly one row the way a real refs-changed run would, then re-fold
    rec_path = MODULE._gate_record_path(state, wt)
    rec = json.loads(rec_path.read_text())
    poisoned = rec["gates"][0]["name"]
    rec["gates"][0].update({"status": "inconclusive", "rc": 1, "refs_changed": True})
    rec["verdict"] = MODULE.aggregate_verdict(rec["gates"])
    # if this were "block" the test would prove nothing — the existing block refusal
    # would catch it and the new one would never be exercised
    assert rec["verdict"] == "warn"
    rec_path.write_text(json.dumps(rec))

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert "inconclusive" in cut["error"]
    assert poisoned in cut["error"], "the refusal must name which gate to re-run"
    assert "backend/src/kg/app.py" not in _local_main_files(repo)

@gitmark
def test_gate_refuses_to_judge_a_tree_that_is_behind_base(scratch):
    # The cheap half: refuse BEFORE spending a gate run on a tree that cannot land.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind2",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _advance_local_main(repo, "peer")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert gate["behind_commits"] == 1
    assert gate["base_changed_files"] == ["peer.txt"]
    # refused BEFORE running anything: no verdict cached for a later cutover to consume
    assert not MODULE._gate_record_path(state, wt).exists()

@gitmark
def test_gate_plan_only_still_previews_a_behind_tree(scratch):
    # --plan-only runs no gate and writes no verdict, so it must stay usable as the
    # preview the refusal message points at (a refusal whose own advice is blocked is
    # a lie).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind3",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _advance_local_main(repo, "peer")
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state,
                          "--plan-only", "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "planned"

@gitmark
def test_cutover_refused_when_the_base_moved_under_a_fresh_verdict(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK and gate["verdict"] == "warn"
    gated_head = gate["head_sha"]

    _advance_local_main(repo, "peer")
    # WHO PRODUCED THE REFUSAL: pin that the stale-HEAD guard CANNOT be what fires —
    # the worktree HEAD is byte-identical to the one the verdict recorded.
    assert _git(["rev-parse", "HEAD"], wt) == gated_head

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["behind_commits"] == 1
    assert cut["base_changed_files"] == ["peer.txt"]
    assert "peer.txt" in _local_main_files(repo)       # the peer's work is still there
    assert "notes.txt" not in _local_main_files(repo)  # ours did NOT land

@gitmark
def test_cutover_dry_run_also_refuses_when_the_base_moved(scratch):
    # A refusal that only exists under --commit teaches the dry-run to lie: the dry-run
    # is what an agent reads to decide whether cutover is ready.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind-dry",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _advance_local_main(repo, "peer")

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["behind_commits"] == 1

@gitmark
def test_cutover_refuses_when_the_rebase_moves_head_off_the_gated_sha(scratch,
                                                                      monkeypatch):
    # The window the pre-flight containment check cannot close: a peer cutover lands on
    # local main AFTER the check and BEFORE the rebase (the rebase is deliberately taken
    # inside the trunk lock, against the CURRENT trunk). Injected at the lock seam —
    # real git, real rebase, no fake for the thing under test. The terminal invariant:
    # the sha that lands must be the sha that was gated.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "raced",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    gated_head = gate["head_sha"]

    real_lock = MODULE._main_advance_lock

    @contextmanager
    def racing_lock(primary):
        with real_lock(primary):
            _advance_local_main(repo, "peer")   # a peer landed inside the window
            yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", racing_lock)
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["gated_sha"] == gated_head
    assert cut["rebased_sha"] != gated_head
    assert "notes.txt" not in _local_main_files(repo)  # main did NOT advance
    assert "peer.txt" in _local_main_files(repo)       # the peer's work is intact

@gitmark
def test_behind_base_refusal_renders_in_human_mode_too(scratch):
    # The refusal must be legible without --json: an operator reading the terminal is
    # the reader most likely to act on it, and a guard that only speaks JSON reads as
    # silence to them. Also pins that stdout carries the human line INSTEAD of JSON.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind-human",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _advance_local_main(repo, "peer")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["cutover", "--worktree", wt, "--state", state, "--commit"])
    out = buf.getvalue()
    assert rc == MODULE.EXIT_BLOCK
    assert out.startswith("✗ cutover refused:")
    assert "1 commit(s), 1 file(s) changed on main" in out
    # the remedy is spelled out verbatim — and it names `catchup`, not raw git.
    # (The original reason was that the rebase kept conflicting on a 280KB generated
    # file; that file left version control in IMP-20260807-b9526c. The routing still
    # holds for the reason that outlived it: an error message telling an agent to go
    # run `git rebase` hands off a step whose failure mode is unbounded, and neither
    # `land` nor the gate sees what happens next.)
    assert f"catchup --worktree {wt} --commit" in out
    with pytest.raises(json.JSONDecodeError):       # human mode, not a JSON dump
        json.loads(out)

@gitmark
def test_landed_sha_equals_gated_sha_when_base_is_contained(scratch):
    # The property the guard buys, stated positively: with the base already contained,
    # cutover's rebase is a no-op, so the sha that LANDS is the sha that was GATED.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "same",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["sha"] == gate["head_sha"]

@gitmark
def test_resolve_refused_when_branch_not_landed(scratch):
    # nit2: resolve is a force-discard (worktree remove --force + branch -D). Called
    # out of order (before cutover) it would vaporize unlanded work. It must REFUSE a
    # branch not contained in base (tree-diff), unless --force.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "add share sheet", "--slug", "share-sheet",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("unlanded work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "unlanded"], wt)

    # resolve WITHOUT a prior cutover -> branch not landed -> refused, NO teardown.
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert res.get("landed") is False
    assert Path(wt).exists()                                   # worktree preserved
    assert "feat/share-sheet" in _local_branches(repo)         # branch preserved

    # --force overrides the floor (an operator that accepts the loss).
    rc, res2 = _run_json(
        ["resolve", "--worktree", wt, "--state", state, "--commit", "--force", "--json"]
    )
    assert rc == MODULE.EXIT_OK
    assert not Path(wt).exists()
    assert "feat/share-sheet" not in _local_branches(repo)

@gitmark
def test_open_rejects_non_kebab_slug(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(
        ["open", "--intent", "x", "--slug", "Bad_Slug", "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_USAGE

@gitmark
def test_preflight_runs_sweep_and_reports(scratch):
    # preflight = fetch + registry sweep --exclude-current (dry-run default). With a
    # clean scratch repo it should simply report a clean sweep, rc 0.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, pre = _run_json(["preflight", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert pre["schema"] == "kg.worktree.orchestrate.v1"
    assert pre["step"] == "preflight"
    assert "sweep" in pre

@gitmark
def test_resolve_from_inside_the_target_worktree_completes(scratch):
    # Regression: resolve invoked with cwd INSIDE the target worktree used to derive
    # its teardown cwd from repo_root() — the worktree's own toplevel. Step 1
    # (worktree remove) then vaporized that cwd and every remaining step (branch -D,
    # gate-cache strike) crashed with an unhandled FileNotFoundError, leaving a
    # half-resolved state. Standing inside the worktree is the natural place for a
    # working agent, so the full teardown must complete from there.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "inside-resolve",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["landed"] is True
    gate_cache = MODULE._gate_record_path(state, wt)
    assert gate_cache.exists()

    os.chdir(wt)
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()
    assert "debug/inside-resolve" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs["debug/inside-resolve"]["status"] == "merged"

@gitmark
def test_resolve_after_a_partial_teardown_never_retargets_the_base_branch(scratch):
    # IMP-20260806-1359bd, the whole incident in one test.
    #
    # Root cause: resolve derived the branch with `git rev-parse --abbrev-ref HEAD`
    # run with cwd=<worktree>. With the worktree's `.git` gone, git's repository
    # DISCOVERY WALKS UP the directory tree, finds the primary repo (worktrees live
    # at <repo>/.claude/worktrees/<slug>), and answers with the PRIMARY's branch —
    # `main`. resolve then planned `branch -D main` and `push origin --delete main`.
    # Only git's own refusals (main was checked out; main is the remote's default
    # branch) stopped it. Neither refusal belongs to this tool.
    #
    # The authoritative answer was available the whole time: `git worktree list
    # --porcelain` still reports `branch refs/heads/<the real branch>` for a
    # prunable entry. Note the landed-floor cannot help here — it is asked about
    # `main`, and `main` is trivially landed in `main`.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "partial-teardown")

    _cripple_worktree(wt)
    # git itself really does misreport here — asserted against git directly rather
    # than through MODULE._current_branch, so that hardening that helper later as
    # defence-in-depth improves the tool instead of breaking this test.
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], wt) == "main"
    # ...while git's worktree list still knows the truth
    assert any(w.get("branch") == branch and MODULE._norm(w["path"]) == MODULE._norm(wt)
               for w in MODULE.wr._worktrees())

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--json"])
    assert _targets_a_protected_branch(res) == [], (
        f"dry-run planned a base-branch deletion: {res}")
    assert res.get("branch") != "main"

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert _targets_a_protected_branch(res) == [], (
        f"resolve EXECUTED a base-branch deletion: {res}")
    assert res.get("branch") != "main"
    # the repository survived — these are the two things git refused for us before
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)

@gitmark
def test_resolve_refuses_when_asked_to_delete_the_base_branch_outright(scratch):
    # Guard (b), independent of path resolution: `branch -D main` is never a
    # legitimate resolve outcome, so an explicit --branch main must be refused
    # rather than merely refused downstream by git. The registry already owns this
    # invariant for sweep (worktree_registry.sweep_guards / _step_touches_protected);
    # resolve simply did not consult it.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, _branch = _landed_worktree(tmp_path, repo, state, "explicit-base")

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", "main",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    # assert the decision, not a prose substring, and not the mere ABSENCE of a plan
    # key — on a refusal payload neither `plan` nor `executed` exists, so
    # _targets_a_protected_branch() would be vacuously satisfied here.
    assert res.get("reason_code") == "branch-contradicts-git", res
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)
    # refused BEFORE mutating: the worktree is untouched
    assert Path(wt).is_dir()

@gitmark
def test_resolve_stops_when_no_authority_vouches_for_the_named_branch(scratch):
    # Guard (c). The tool ALREADY printed "no active registry record for branch=main"
    # during the incident — it had detected that its target was wrong and walked into
    # the destructive steps anyway. A detected anomaly must halt before mutation.
    #
    # Asserted on an UNPROTECTED branch on purpose, so neither guard (a) nor (b) can
    # be what stops it: --branch names a real branch that git does not associate with
    # this path and that the ledger holds no active record for. The old code took the
    # explicit --branch at face value, and the landed-floor waves a landed branch
    # through, so this deleted a bystander branch outright.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, _branch = _landed_worktree(tmp_path, repo, state, "wrong-branch")
    _git(["branch", "feat/someone-elses-work"], repo)   # landed (it IS main), unprotected

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", "feat/someone-elses-work",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert "feat/someone-elses-work" in _local_branches(repo)
    assert Path(wt).is_dir()

@gitmark
def test_resolve_proceeds_when_only_the_ledger_vouches(scratch):
    # The other side of the corroboration rule, so it cannot degenerate into "any
    # explicit --branch is refused": when the ledger DOES hold an active record for
    # the named branch, that is a sufficient authority on its own.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "ledger-vouches")

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", branch,
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert branch not in _local_branches(repo)

@gitmark
def test_resolve_of_a_live_worktree_survives_an_already_closed_ledger(scratch):
    # Regression guard for the rule's SHAPE. Requiring an active ledger record
    # unconditionally would look like a tighter safety net and would in fact strand
    # every interrupted teardown: resolve strikes the ledger BEFORE the git steps, so
    # by the time a run is interrupted the record is already closed. Finishing that
    # run is precisely what IMP-20260806-1359bd asks for, so git's worktree list must
    # be sufficient on its own.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "closed-ledger")
    ledger = json.loads(Path(state).read_text())
    for r in ledger["records"]:
        r["status"] = "merged"
    Path(state).write_text(json.dumps(ledger))

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch
    assert branch not in _local_branches(repo)
    assert not Path(wt).exists()

@gitmark
def test_resolve_finishes_an_interrupted_teardown_instead_of_stranding_it(scratch):
    # The flip side of guard (a): re-running resolve after a partial teardown is a
    # LEGITIMATE intent — the operator wants the teardown finished. Refusing to
    # misfire is necessary but not sufficient; the tool must still converge on zero
    # residue, targeting the branch git's worktree list names.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "finish-teardown")
    _cripple_worktree(wt)

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch
    assert branch not in _local_branches(repo)
    assert not Path(wt).exists()
    # git no longer carries a stale entry for it
    assert all(MODULE._norm(w["path"]) != MODULE._norm(wt)
               for w in MODULE.wr._worktrees())
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs[branch]["status"] == "merged"

@gitmark
def test_resolve_protects_the_trunk_even_under_a_different_base(scratch):
    # The protected set used to be derived SOLELY from --base (plus the primary's
    # current checkout), so it was a floor the caller could lower. Executed during
    # review: with the primary checked out off main and `--base origin/prod` — a real
    # ref in this repo's release plane, so a plausible copy-paste — `main` was absent
    # from the protected set and `git branch -D main` SUCCEEDED. Only the bare repo's
    # HEAD protection stopped the remote half, which is exactly the external net this
    # entry exists to stop relying on.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["update-ref", "refs/heads/prod", "refs/heads/main"], remote)
    # a primary parked elsewhere (repo surgery / hotfix / bisect), and a worktree that
    # has the trunk itself checked out. Order matters: main must be free first.
    _git(["checkout", "-q", "-b", "staging"], repo)
    mainwt = tmp_path / "mainwt"
    _git(["worktree", "add", "-q", str(mainwt), "main"], repo)

    rc, res = _run_json(["resolve", "--worktree", str(mainwt), "--base", "origin/prod",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert res.get("reason_code") == "protected-branch", res
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)

@gitmark
def test_resolve_refuses_when_git_contradicts_the_named_branch(scratch):
    # Executed during review: with two live worktrees, targeting alpha's PATH while
    # naming bravo's BRANCH tore down alpha and deleted origin/<bravo>. The ledger
    # vouched — because the record that matched belonged to a different path — and
    # `branch -D` was refused only by git's "used by worktree at ...".
    #
    # The structural error was collapsing "git has no information" and "git actively
    # contradicts you" into one condition. The second is strictly worse.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    alpha, _ = _landed_worktree(tmp_path, repo, state, "alpha")
    rc, bravo_opened = _run_json(["open", "--intent", "second stream", "--slug", "bravo",
                                  "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    bravo_branch = bravo_opened["branch"]
    _git(["push", "-q", "origin", bravo_branch], repo)
    assert bravo_branch in _local_branches(remote)

    rc, res = _run_json(["resolve", "--worktree", alpha, "--branch", bravo_branch,
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert res.get("reason_code") == "branch-contradicts-git", res
    # neither worktree touched, and bravo's remote branch survives
    assert Path(alpha).is_dir()
    assert Path(bravo_opened["path"]).is_dir()
    assert bravo_branch in _local_branches(repo)
    assert bravo_branch in _local_branches(remote)

@gitmark
def test_resolve_reclaims_the_directory_when_git_has_lost_the_entry(scratch):
    # Silent false success, found in review: with the admin entry already gone (an
    # errored `worktree remove` drops it, and so does any prune elsewhere in the repo)
    # no directory-removal step was planned at all, yet resolve reported failures: 0
    # and exited 0 — while the whole tree, 19 GB of it in the incident's shape, stayed
    # on disk. The ledger still records the path, so the branch is derivable and the
    # directory is reclaimable.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "lost-entry")
    _cripple_worktree(wt)
    _git(["worktree", "prune"], repo)                 # admin entry gone, tree remains
    assert Path(wt).is_dir()
    assert all(MODULE._norm(w["path"]) != MODULE._norm(wt)
               for w in MODULE.wr._worktrees())

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch                    # derived from the ledger, not HEAD
    assert not Path(wt).exists(), "reported success while leaving the tree behind"
    assert branch not in _local_branches(repo)

@gitmark
def test_resolve_aborts_the_remaining_steps_when_a_critical_one_fails(scratch):
    # The other half of the incident's trace: `worktree remove --force` returned 128
    # and the loop ran `branch -D` and `push origin --delete` anyway. Correct targeting
    # makes those harmless; it does not make "carry on after a destructive step failed"
    # correct. Here the directory removal is made to fail (its parent is read-only), so
    # the admin strike and the branch deletions must not proceed.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "critical-abort")
    _cripple_worktree(wt)
    parent = Path(wt).parent
    parent.chmod(0o500)                               # rm cannot unlink inside it
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    finally:
        parent.chmod(0o700)

    assert rc == MODULE.EXIT_BLOCK, res
    assert res["aborted_after"] == "remove leftover worktree directory", res
    ran = [r["cmd"] for r in res["executed"]]
    assert not any("branch -D" in c for c in ran), ran
    assert not any("--delete" in c for c in ran), ran
    assert branch in _local_branches(repo)

@gitmark
def test_resolve_refuses_a_path_that_is_not_a_registered_worktree(scratch):
    # The general form of the walk-up bug: ANY directory inside the repo answers
    # `rev-parse --abbrev-ref HEAD` with the enclosing checkout's branch. Only paths
    # git actually lists as worktrees may be resolved.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    stray = repo / "not-a-worktree"
    stray.mkdir()

    rc, res = _run_json(["resolve", "--worktree", str(stray), "--state", state,
                         "--commit", "--json"])
    # EXIT_USAGE, not EXIT_BLOCK: this is "you pointed me at the wrong thing", the
    # same class as cutover's own not-a-worktree and detached-HEAD refusals. The
    # safety refusals (protected branch, primary worktree, contradiction) are the
    # ones that carry EXIT_BLOCK.
    assert rc == MODULE.EXIT_USAGE, res
    assert res.get("reason_code") == "not-a-worktree", res
    assert "main" in _local_branches(repo)

@gitmark
def test_open_from_inside_another_worktree_anchors_at_primary_root(scratch):
    # Regression: open used repo_root() (cwd's toplevel), so opening from inside a
    # linked worktree would NEST the new worktree under it instead of anchoring at
    # the primary root's .claude/worktrees/ like every other flow expects.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, first = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "first",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    os.chdir(first["path"])
    try:
        rc, second = _run_json(
            ["open", "--intent", "fix the reader crash", "--slug", "second",
             "--state", state, "--json"]
        )
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    expected = (repo / ".claude" / "worktrees" / "second").resolve()
    assert Path(second["path"]).resolve() == expected

@gitmark
def test_resolve_from_inside_without_state_flag_completes(scratch):
    # The production invocation form (worktree-flow SKILL.md) passes NO --state. That
    # branch of _gate_record_path derives the ledger anchor lazily via the registry's
    # common_anchor() — a cwd-dependent git call. Computed AFTER the teardown loop it
    # runs from a vanished cwd (empty git output → Path("").resolve() → getcwd() →
    # FileNotFoundError), so it must be resolved BEFORE the worktree is removed.
    tmp_path, repo, remote = scratch
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "inside-default-state",
         "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["landed"] is True
    gate_cache = MODULE._gate_record_path(None, wt)
    assert gate_cache.exists()

    os.chdir(wt)
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--commit", "--json"])
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()
    assert "debug/inside-default-state" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()

@gitmark
def test_adopt_registers_an_out_of_band_worktree(scratch):
    # bare `git worktree add` needs no repo tooling; adopt backfills the ledger so the
    # rest of the flow (gate/cutover/resolve/sweep) sees a born-registered peer.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    rc, res = _run_json(["adopt", "--worktree", str(wt), "--intent", "hand-made worktree",
                         "--codex-thread-id", "thread-adopt", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["step"] == "adopt"
    assert res["branch"] == "feat/oob"
    recs = json.loads(Path(state).read_text())["records"]
    mine = [r for r in recs if r["branch"] == "feat/oob"]
    assert len(mine) == 1
    assert mine[0]["status"] == "active"
    assert mine[0]["codex_thread_id"] == "thread-adopt"
    assert Path(mine[0]["path"]).resolve() == wt.resolve()

@gitmark
def test_adopt_refuses_direct_scope_with_explicit_empty_backlog(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({
        "files": [{"path": "ops/direct.py", "operation": "modify"}],
    }), encoding="utf-8")
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)

    rc, _res = _run_json([
        "adopt", "--worktree", str(wt), "--intent", "direct scope",
        "--scope-file", str(scope), "--backlog", "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_USAGE
    assert not Path(state).exists()

@gitmark
def test_adopt_is_idempotent(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    for _ in range(2):
        rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "twice",
                              "--state", state, "--json"])
        assert rc == MODULE.EXIT_OK
    recs = json.loads(Path(state).read_text())["records"]
    assert len([r for r in recs if r["branch"] == "feat/oob"]) == 1

@gitmark
def test_adopt_defaults_to_cwd(scratch):
    # the bootstrap flow is `cd <fresh worktree> && orchestrate adopt --intent ...`
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    os.chdir(wt)
    try:
        rc, res = _run_json(["adopt", "--intent", "from inside", "--state", state, "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    assert res["branch"] == "feat/oob"

@gitmark
def test_adopt_refuses_primary_root(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["adopt", "--worktree", str(repo), "--intent", "nope",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE
    assert not (tmp_path / "reg.json").exists() or not json.loads(
        (tmp_path / "reg.json").read_text())["records"]

@gitmark
def test_adopt_refuses_detached_worktree(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "det"
    _git(["worktree", "add", "--detach", str(wt), "main"], repo)
    rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "nope",
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE

@gitmark
def test_freeze_status_and_reason_roundtrip(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert st["frozen"] is False

    rc, on = _run_json(["freeze", "on", "--reason", "history rewrite in progress",
                        "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert st["frozen"] is True
    assert st["reason"] == "history rewrite in progress"

    rc, _off = _run_json(["freeze", "off", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert st["frozen"] is False

@gitmark
def test_freeze_blocks_open_adopt_cutover_until_off(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # a live worktree from BEFORE the freeze, for the cutover/adopt probes
    rc, opened = _run_json(["open", "--intent", "fix the reader crash",
                            "--slug", "pre-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]

    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    rc, res = _run_json(["open", "--intent", "fix the reader crash",
                         "--slug", "during-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "surgery" in json.dumps(res)
    rc, _res = _run_json(["adopt", "--worktree", wt, "--intent", "nope",
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    rc, _res = _run_json(["cutover", "--worktree", wt, "--state", state,
                          "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK

    # resolve stays ALLOWED while frozen — surgery prep is about draining, not
    # trapping. The pre-freeze worktree is landed (freshly forked from main, zero
    # unique commits) so the landed-floor passes and the teardown must complete.
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()

    rc, _res = _run_json(["freeze", "off", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, _res = _run_json(["open", "--intent", "fix the reader crash",
                          "--slug", "post-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

@gitmark
def test_freeze_on_twice_requires_force(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(["freeze", "on", "--reason", "first", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, res = _run_json(["freeze", "on", "--reason", "second", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "first" in json.dumps(res)  # existing reason surfaced, not clobbered
    rc, _ = _run_json(["freeze", "on", "--reason", "second", "--force",
                       "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert st["reason"] == "second"

@gitmark
def test_sync_main_noop_when_up_to_date(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["sync-main", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"

@gitmark
def test_sync_main_ff_when_strictly_behind(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "one")
    (repo / "stray-untracked.txt").write_text("untracked must not block\n")
    before = _git(["rev-parse", "main"], repo)

    # dry-run: reports the plan, moves nothing
    rc, dry = _run_json(["sync-main", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert _git(["rev-parse", "main"], repo) == before

    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "ff"
    assert _git(["rev-parse", "main"], repo) == _git(["rev-parse", "origin/main"], repo)
    assert (repo / "one.txt").exists()  # working tree really moved
    assert (repo / "stray-untracked.txt").exists()  # untouched

@gitmark
def test_sync_main_commit_serializes_primary_advance(scratch, monkeypatch):
    """origin->local ff must share the primary-advance lock with cutover."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "locked")
    events = []
    real_lock = MODULE._main_advance_lock

    @contextmanager
    def observed_lock(primary):
        events.append(("enter", Path(primary).resolve()))
        with real_lock(primary):
            yield
        events.append(("exit", Path(primary).resolve()))

    monkeypatch.setattr(MODULE, "_main_advance_lock", observed_lock)
    rc, result = _run_json(["sync-main", "--state", state, "--commit", "--json"])

    assert rc == MODULE.EXIT_OK
    assert result["verdict"] == "ff"
    assert events == [("enter", repo.resolve()), ("exit", repo.resolve())]

@gitmark
def test_sync_main_refuses_dirty_primary(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "two")
    (repo / "f").write_text("tracked modification\n")
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "dirty" in json.dumps(res)
    _git(["checkout", "--", "f"], repo)
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and res["verdict"] == "ff"

@gitmark
def test_sync_main_refuses_diverged_main(scratch):
    # local main holds a commit origin lacks — NEVER auto-merged/rebased away
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "local-only.txt").write_text("unique local work\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "local unique"], repo)
    # fork the advance from origin/main (NOT local main) so the histories truly split
    _git(["fetch", "-q", "origin"], repo)
    _advance_origin_main(tmp_path, repo, "three", base="origin/main")
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "cutover" in json.dumps(res)  # points at the right recovery
    # untouched: the unique commit is still local main's tip
    assert (repo / "local-only.txt").exists()

@gitmark
def test_sync_main_refuses_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "four")
    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, _res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK

@gitmark
def test_sync_main_refuses_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "five")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)

@gitmark
def test_adopt_from_subdirectory_registers_the_worktree_root(scratch):
    # review B1: cd <wt>/sub && adopt must register the worktree ROOT, not the subdir
    # (a subdir path breaks all later path-addressed operations: resolve, sweep).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    (wt / "sub").mkdir()
    os.chdir(wt / "sub")
    try:
        rc, res = _run_json(["adopt", "--intent", "from a subdir", "--state", state,
                             "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    recs = json.loads(Path(state).read_text())["records"]
    assert Path(recs[0]["path"]).resolve() == wt.resolve()

@gitmark
def test_adopt_anchors_default_ledger_at_target_not_process_cwd(scratch):
    # review B2: invoked from OUTSIDE any repo with an explicit --worktree and no
    # --state, the ledger must be derived from the TARGET's git-common-dir — not the
    # process cwd (which would silently write a stray ledger the flow never reads).
    tmp_path, repo, remote = scratch
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    os.chdir(outside)
    try:
        rc, res = _run_json(["adopt", "--worktree", str(wt), "--intent", "from afar",
                             "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    ledger = repo / ".cache" / "worktree_registry.json"
    assert ledger.exists()
    recs = json.loads(ledger.read_text())["records"]
    assert [r for r in recs if r["branch"] == "feat/oob"]
    assert not (outside / ".cache").exists()
    assert not (tmp_path / ".cache").exists()

@gitmark
def test_adopt_refuses_unresolvable_base(scratch):
    # review N2: open gets ref validation for free from `git worktree add`; adopt
    # must check --base itself instead of recording garbage in the ledger.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "bad base",
                          "--base", "no/such-ref", "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE

@gitmark
def test_sync_main_refuses_merge_in_progress_even_with_clean_porcelain(scratch):
    # review: MERGE_HEAD is the ONLY load-bearing guard for `merge --no-commit -s
    # ours` (the ours strategy leaves porcelain clean, so the dirty check alone
    # would wave it through).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "side"], repo)
    (repo / "side.txt").write_text("side\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "side work"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--no-commit", "--no-ff", "-s", "ours", "side"], repo)
    assert not _git(["status", "--porcelain", "--untracked-files=no"], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "merge is in progress" in json.dumps(res)
    finally:
        _git(["merge", "--abort"], repo)
        _git(["branch", "-D", "side"], repo)

@gitmark
def test_sync_main_refuses_when_fetch_fails(scratch):
    # review: a dead origin must refuse, not report a stale-snapshot "noop"
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["remote", "set-url", "origin", str(tmp_path / "gone.git")], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "fetch failed" in json.dumps(res)
    finally:
        _git(["remote", "set-url", "origin", str(remote)], repo)

@gitmark
def test_deploy_noop_when_origin_already_current(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["deploy", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"

@gitmark
def test_deploy_dry_run_reports_range_and_backend_rollout(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # local main gets ahead with a backend change (origin is not pushed)
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, dry = _run_json(["deploy", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert dry["would_roll_out"] is True
    assert "backend/src/kg/app.py" in dry["backend_files"]
    # dry-run pushed nothing — origin/prod (deploy's target) untouched
    assert "backend/src/kg/app.py" not in _origin_prod_files(remote)

@gitmark
def test_deploy_commit_pushes_and_advances_origin(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "docs.md").write_text("note\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "a docs-only change"], repo)

    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "pushed"
    assert res["rolled_out"] is False           # no backend in range
    assert "docs.md" in _origin_prod_files(remote)     # origin/prod advanced (release plane)
    assert "docs.md" not in _origin_main_files(remote)  # origin/main untouched — deploy != sync

@gitmark
def test_deploy_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)

@gitmark
def test_deploy_refused_when_origin_diverged(scratch):
    # origin/prod holds a commit local main lacks -> deploy must refuse (never force-push)
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # advance origin/prod behind our back via a second clone (checkout prod there)
    other = tmp_path / "other"
    _git(["clone", "-q", "-b", "prod", str(remote), str(other)], tmp_path)
    _git(["config", "user.email", "o@o"], other); _git(["config", "user.name", "o"], other)
    (other / "remote-only.txt").write_text("from elsewhere\n")
    _git(["add", "-A"], other); _git(["commit", "-qm", "remote-only"], other)
    remote_only = _git(["rev-parse", "HEAD"], other)
    _git(["push", "-q", "origin", "HEAD:refs/heads/fixture-remote-only"], other)
    _git(["update-ref", "refs/heads/prod", remote_only], remote)
    # our local main also advances (diverging from origin/prod)
    (repo / "local-only.txt").write_text("mine\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "local-only"], repo)

    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "reconcile" in json.dumps(res)

@gitmark
def test_deploy_refused_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "x.txt").write_text("y\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "x"], repo)
    _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK

@gitmark
def test_sync_noop_when_origin_already_current(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["sync", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"

@gitmark
def test_sync_dry_run_has_no_rollout_fields(scratch):
    # backup plane never speaks of rollout — even a backend change carries no
    # would_roll_out/backend_files (that is the deploy plane's concern).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, dry = _run_json(["sync", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert "would_roll_out" not in dry
    assert "backend_files" not in dry

@gitmark
def test_sync_commit_mirrors_to_origin_main_not_prod(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "pushed"
    assert "rolled_out" not in res                       # backup carries no rollout verdict
    assert "backend/src/kg/app.py" in _origin_main_files(remote)     # origin/main advanced
    assert "backend/src/kg/app.py" not in _origin_prod_files(remote)  # prod untouched — no deploy

@gitmark
def test_sync_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)

@gitmark
def test_sync_refused_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "x.txt").write_text("y\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "x"], repo)
    _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK

@gitmark
def test_post_landing_repair_commits_only_reanchored_doc_paths(scratch):
    """Docs rewritten by reanchor share the repair commit's path contract."""
    _tmp, repo, _remote = scratch
    marker = repo / "invocations.txt"
    _install_ledger_stub(repo, marker, doc_reanchor=True)

    repair = MODULE._post_landing_repair(repo)

    assert repair["ok"] is True
    assert repair["committed"] is True
    assert "docs/reference/E.md" in repair["repair_paths"]
    changed = _git(["show", "--format=", "--name-only", "HEAD"], repo)
    assert "docs/runbook/backlog/E1.json" in changed
    assert "docs/reference/E.md" in changed
    assert (repo / "docs/reference/E.md").read_text() == "verified_against: new\n"

@gitmark
def test_cutover_repairs_the_ledger_it_just_rewrote(scratch, tmp_path):
    """cutover's rebase mutates the tree AFTER the gate last looked at it.

    Measured in a clone of the real repo: a `fixed_by` sha recorded on a branch
    becomes `fixed-by-orphaned` once main has moved under it — `validate` went
    0 problems -> 1 problems. The correct sha does not exist until the landing has
    happened, so the landing step owns the repair.

    Every flag here is load-bearing and every one of them was, at some point, not
    asserted: dropping `--commit` from both invocations left 294 tests green while
    the repair silently did nothing but dry-runs.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, probe_lock=True)
    state = str(tmp_path / "reg.json")

    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True

    calls = [ln.split("\t") for ln in
             marker.read_text(encoding="utf-8").splitlines()]
    argvs = [c[1] for c in calls]
    # the flags, not just the subcommand names
    assert "reanchor --docs --commit --json" in argvs, argvs
    assert "validate --baseline-check" in argvs, argvs
    # `render` is NOT here any more: the generated view left version control
    # (IMP-20260807-b9526c), so there is no tracked derived file for the trunk to
    # keep in step. `reanchor` stays — orphaned `fixed_by` shas are a fact about the
    # STORE, which the rebase really does invalidate.
    assert not any(a.startswith("render") for a in argvs), argvs
    # the ORDER: validating before the write would grade the old data
    assert argvs.index("reanchor --docs --commit --json") < argvs.index(
        "validate --baseline-check"
    ), argvs
    # the DIRECTORY: the repair is about the trunk, which lives in the primary
    assert {c[0] for c in calls} == {str(repo.resolve())}, calls
    # and the LOCK: the repair rewrites the same trunk files the ff just moved, so
    # it belongs to the same critical section. Run outside it, two concurrent
    # repairs raced in the atomic-write helper and one died, leaving the primary
    # dirty — which blocks every later cutover.
    assert all("trunk-lock=HELD" in ln
               for ln in marker.read_text(encoding="utf-8").splitlines()), \
        marker.read_text(encoding="utf-8")

    # and what the repair produced is COMMITTED — a repair left uncommitted just
    # moves the failure to the next cutover, which refuses on a dirty primary.
    # tracked-clean specifically: untracked residue does not block the next cutover,
    # a tracked leftover does.
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text() == "anchor=new\n"
    assert cut["repair"]["committed"] is True
    assert cut["trunk_tip"] == _git(["rev-parse", "HEAD"], repo).strip()
    assert cut["trunk_tip"] != cut["sha"]

@gitmark
def test_a_failed_repair_puts_the_primary_back_rather_than_blocking_every_later_cutover(
        scratch, tmp_path):
    """A repair step that exits non-zero must not leave its edits in the primary.

    Measured before this was handled: the first repair step wrote its edit, the
    second refused, the repair returned early, and the edit stayed in the primary's
    working tree. The next cutover then refused with "primary working tree is dirty …
    likely another session is working in the primary" — pointing the next agent at a
    co-tenant who does not exist, for residue this code left. In a round of ten
    branches that is nine of them dead on the first landing.

    The refusing step used to be `render` (its entry-loss guard exits 2 by design).
    That step is gone with the view, so the failure is injected into `reanchor`,
    which is the step that remains — the invariant under test is "a failed repair
    restores", not "render is the one that fails".
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, fail="reanchor")
    state = str(tmp_path / "reg.json")
    before = (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text()

    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])

    # the landing itself still succeeded — a completed ff is not rolled back
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["repair"]["ok"] is False and cut["repair"]["committed"] is False
    assert "exited 2" in cut["repair"]["error"]
    assert cut["repair"]["restored"] is True
    # the whole point: the next cutover is not blocked by this one's debris
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text() == before

@gitmark
def test_a_failed_reanchor_reports_and_restores_an_arbitrary_document_path(
        scratch, tmp_path):
    """A failed child command must still identify every document it touched.

    The real reanchor transaction rolls its own writes back.  This companion
    fixture covers the orchestrator boundary: even when the child exits before
    a success payload, its failure JSON carries the document path so the
    primary restore is not narrowed to the ledger directory.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, fail="reanchor", fail_with_doc_plan=True)
    before = (repo / "docs" / "reference" / "E.md").read_text(encoding="utf-8")

    repair = MODULE._post_landing_repair(repo)

    assert repair["ok"] is False
    assert repair["restored"] is True
    assert "docs/reference/E.md" in repair["repair_paths"]
    assert (repo / "docs" / "reference" / "E.md").read_text(encoding="utf-8") == before
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""

@gitmark
def test_catchup_leaves_a_conflict_in_an_ungenerated_file_for_a_human(scratch, tmp_path):
    """The narrowness is the safety. A conflict in any file the repo has not declared
    generated is a decision, and a tool that resolves decisions by regenerating one
    side of them is worse than one that stops."""
    _tmp, repo, _remote = scratch
    _install_ledger_stub(repo, tmp_path / "invocations.txt")
    _seed_neighbouring_rows(repo)
    _stub_repo_commit(repo, "seed view")
    state = str(tmp_path / "reg.json")

    rc, opened = _run_json(["open", "--intent", "file entries", "--slug", "entries",
                            "--state", state, "--json"])
    wt = Path(opened["path"])
    _diverge_on_the_generated_view(repo, wt, also="f")

    rc, out = _run_json(["catchup", "--worktree", str(wt), "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, out
    assert out["error"] == "rebase failed (aborted)", out
    assert out["rebased"] is False
    # aborted cleanly: no half-rebase left for the next command to trip over
    rc_state, _ = MODULE._git(["rev-parse", "--verify", "--quiet", "REBASE_HEAD"],
                              cwd=str(wt))
    assert rc_state != 0, "a rebase was left in progress"
    assert _git(["status", "--porcelain"], wt).strip() == ""

@gitmark
def test_catchup_on_an_up_to_date_worktree_changes_nothing(scratch, tmp_path):
    """A no-op has to be a cheap no-op, not a rewrite: `catchup` is the command the
    refusals name, so agents will run it speculatively."""
    _tmp, repo, _remote = scratch
    _install_ledger_stub(repo, tmp_path / "invocations.txt")
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "nothing", "--slug", "nothing",
                            "--state", state, "--json"])
    wt = Path(opened["path"])
    before = _git(["rev-parse", "HEAD"], wt).strip()
    rc, out = _run_json(["catchup", "--worktree", str(wt), "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and out["behind"] is False and out["rebased"] is False
    assert _git(["rev-parse", "HEAD"], wt).strip() == before

def test_the_behind_base_refusal_names_a_command_that_exists():
    """The refusal used to say `git -C <path> rebase main`. A refusal is a routing
    decision, and pointing it at raw git routes the agent out of the flow at exactly
    the moment the step can fail. (It was originally argued from a generated file
    that no longer exists — IMP-20260807-b9526c — but the routing argument does not
    depend on it.)"""
    msg = MODULE._behind_base_refusal("/w", "main",
                                      {"behind_commits": 2, "base_changed_files": ["a"]})
    assert "catchup" in msg and "git -C" not in msg, msg
    names = {a.dest for a in MODULE.build_parser()._subparsers._group_actions}
    assert MODULE.build_parser().parse_args(
        ["catchup", "--worktree", "/w"]).func is MODULE.cmd_catchup

@gitmark
def test_the_repair_never_commits_or_destroys_a_co_tenants_untracked_entry(
        scratch, tmp_path):
    """An untracked entry JSON sitting in the primary is a LEGAL, common state — an
    agent filed one and has not committed it — and `_primary_ff_ready` deliberately
    ignores it (`--untracked-files=no`), so it does not block anyone's cutover.

    Measured before this was fixed, both directions from that one state:
      * the repair's `git add -- docs/runbook/backlog` staged it, and the resulting
        commit — the one whose message says everything in it was re-derived by a
        tool — CONTAINED someone else's unfinished work;
      * on the failing path, `git checkout HEAD -- <dir>` is a silent no-op for a
        staged-new path absent from HEAD, so the restore reported success over a
        primary that was still dirty. Which blocks every later cutover.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker)
    state = str(tmp_path / "reg.json")
    cotenant = repo / "docs" / "runbook" / "backlog" / "COTENANT.json"
    cotenant.write_text("someone else is mid-thought\n", encoding="utf-8")

    rc, opened = _run_json(["open", "--intent", "x", "--slug", "co", "--state", state,
                            "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["repair"]["committed"] is True, cut

    landed = _git(["show", "--pretty=", "--name-only", "HEAD"], repo).split()
    assert "docs/runbook/backlog/COTENANT.json" not in landed, landed
    assert cotenant.exists(), "the repair deleted a co-tenant's file"
    assert cotenant.read_text() == "someone else is mid-thought\n"
    # untracked residue is fine; tracked residue is what blocks the next cutover
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""

@gitmark
def test_a_failed_repair_restores_even_when_a_co_tenants_file_is_present(
        scratch, tmp_path):
    """The failing half of the same state. `restored` must come from re-reading
    git's status, not from the restore command's exit code — the command can succeed
    while the tree is still dirty."""
    _tmp, repo, _remote = scratch
    # `reanchor` rather than `render`: the render step left the repair with the view
    # (IMP-20260807-b9526c). What is under test is "a failed repair restores", not
    # which subcommand happened to be the failing one.
    _install_ledger_stub(repo, tmp_path / "inv.txt", fail="reanchor")
    state = str(tmp_path / "reg.json")
    cotenant = repo / "docs" / "runbook" / "backlog" / "COTENANT.json"
    cotenant.write_text("mid-thought\n", encoding="utf-8")

    rc, opened = _run_json(["open", "--intent", "x", "--slug", "co2", "--state", state,
                            "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])

    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["repair"]["ok"] is False and cut["repair"]["restored"] is True
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert cotenant.exists() and cotenant.read_text() == "mid-thought\n"

def test_a_hostile_git_editor_cannot_freeze_a_git_mutation(tmp_path):
    """`git -c core.editor=true` does NOT prevent this: git reads `GIT_EDITOR` FIRST.

    Measured with `GIT_EDITOR` pointing at a 25-second sleep: the editor really ran
    (`elapsed=25.6s`). These runs carry no timeout and `cutover` holds the trunk lock
    while it works, so one operator's editor preference freezes every cutover in the
    repo. This machine's own `GIT_EDITOR=true` is exactly why the hole was invisible
    here, so the test sets a hostile one rather than trusting the environment.

    Driven through a `git commit --amend` with no `-m` — a command that opens the
    editor unconditionally — rather than through a conflicted rebase. The old version
    rode on `catchup`'s generated-view conflict RESOLVER, which called
    `rebase --continue`; that resolver is gone with the view (IMP-20260807-b9526c),
    and a guarantee must not disappear because the scenario that happened to exercise
    it did. `_noninteractive_env` is the site; this asserts at the site.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=repo, check=True)

    trap = tmp_path / "editor_trap.sh"
    trap.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    trap.chmod(0o755)
    prev = os.environ.get("GIT_EDITOR")
    os.environ["GIT_EDITOR"] = str(trap)
    try:
        # positive control: the trap is real and git does honour GIT_EDITOR, so a
        # green result below is the hardening and not a broken trap
        bare = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                               "commit", "--amend"], cwd=repo,
                              capture_output=True, text=True)
        assert bare.returncode != 0, "the editor trap did not fire — this test proves nothing"

        rc, out = MODULE._git_mutation(
            ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--amend"],
            cwd=repo, label="editor-probe")
    finally:
        if prev is None:
            os.environ.pop("GIT_EDITOR", None)
        else:
            os.environ["GIT_EDITOR"] = prev

    assert rc == 0, f"a hostile GIT_EDITOR reached a tool-run git command: {out}"
    assert MODULE._noninteractive_env()["GIT_EDITOR"] == "true"
    assert MODULE._noninteractive_env()["GIT_SEQUENCE_EDITOR"] == "true"

@gitmark
def test_catchup_is_blocked_by_freeze(scratch, tmp_path):
    """`freeze` is the stop-the-world lock for repo surgery. `catchup` rewrites
    history — that is what a rebase is — so it belongs on the blocked side. It was
    missed only because it is the newest verb, and a lock a new verb can walk past
    is not a lock."""
    _tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "frozen", "--state",
                            state, "--json"])
    wt = opened["path"]
    rc, _ = _run_json(["freeze", "on", "--reason", "history rewrite", "--state", state,
                       "--json"])
    assert rc == MODULE.EXIT_OK
    rc, out = _run_json(["catchup", "--worktree", wt, "--state", state, "--commit",
                         "--json"])
    assert rc == MODULE.EXIT_BLOCK, out
    assert "history rewrite" in json.dumps(out, ensure_ascii=False), out

@gitmark
def test_a_restore_that_did_not_work_is_reported_as_a_failure(tmp_path, monkeypatch):
    """`restored` must describe the TREE, not the exit code of the command that tried.

    Measured on the shape that motivated this: `git checkout HEAD -- <dir>` returns 0
    for a path that is staged-new and absent from HEAD, having changed nothing. A
    version that trusted that rc reported a clean primary over a dirty one — and a
    dirty primary is what blocks every later cutover. Here the restore is stubbed out
    entirely, so the only thing that can produce the right answer is re-reading git.
    """
    repo = tmp_path / "repo"; repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "docs" / "runbook" / "backlog").mkdir(parents=True)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text("committed\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "base"], repo)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text("half-written\n")

    real_git = MODULE._git

    def _git_without_restore(args, **kwargs):
        if args and args[0] in ("checkout", "reset"):
            return 0, ""          # succeeds loudly, does nothing
        return real_git(args, **kwargs)

    monkeypatch.setattr(MODULE, "_git", _git_without_restore)
    out: dict = {"error": "the repair failed"}
    MODULE._repair_restore(repo, out)

    assert out["restored"] is False, out
    assert "could not be restored" in out["error"], out
    assert "E1.json" in out["error"], out

"""Behavior-group collector for worktree_orchestrate (delivery)."""

from worktree_orchestrate_support import *  # noqa: F401,F403


def test_gate_tiering_and_deferral_flags_are_preserved_by_each_delivery_entrypoint():
    parser = MODULE.build_parser()
    gate = parser.parse_args([
        "gate", "--worktree", "/w", "--gate-tier", "S1",
        "--defer-gate", "ops-pytest=IMP-20260817-abcdef",
    ])
    assert gate.gate_tier == "S1"
    assert gate.defer_gate == ["ops-pytest=IMP-20260817-abcdef"]

    integrate = parser.parse_args([
        "integrate", "--slug", "wave", "--branches", "feat/source",
        "--gate-tier", "S3", "--defer-gate", "ops-pytest=IMP-20260817-fedcba",
    ])
    assert integrate.gate_tier == "S3"
    assert integrate.defer_gate == ["ops-pytest=IMP-20260817-fedcba"]

    close_wave = parser.parse_args([
        "close-wave", "--slug", "wave", "--branches", "feat/source",
        "--gate-tier", "S4",
    ])
    assert close_wave.gate_tier == "S4"
    assert close_wave.defer_gate == []

    land = parser.parse_args([
        "land", "--worktree", "/w", "--gate-tier", "S1",
        "--defer-gate", "ops-pytest=IMP-20260817-123456",
    ])
    assert land.gate_tier == "S1"
    assert land.defer_gate == ["ops-pytest=IMP-20260817-123456"]


def test_operator_contract_is_explicit_on_delivery_commands():
    parser = MODULE.build_parser()
    integrate = parser.parse_args([
        "integrate", "--slug", "wave", "--branches", "feat/source",
        "--operator", "integrator", "--commit", "--no-gate",
    ])
    assert integrate.operator == "integrator"
    assert integrate.no_gate is True

    for command, argv in {
        "close-wave": ["close-wave", "--slug", "wave", "--operator", "manager"],
        "cutover": ["cutover", "--worktree", "/w", "--operator", "manager"],
        "land": ["land", "--worktree", "/w", "--operator", "manager"],
        "sync": ["sync", "--operator", "manager"],
        "deploy": ["deploy", "--operator", "manager"],
    }.items():
        parsed = parser.parse_args(argv)
        assert parsed.operator == "manager", command


def test_manager_only_authority_refuses_integrator_mutations():
    assert MODULE.operator_refusal(
        command="cutover", operator="integrator", commit=True, manager_only=True,
    )["refusal"] == "manager-only"
    assert MODULE.operator_refusal(
        command="close-wave", operator="integrator", commit=True, manager_only=True,
    )["required_operator"] == "manager"
    assert MODULE.operator_refusal(
        command="integrate", operator="integrator", commit=True,
        integrator_staging=True,
    ) is None

@gitmark
def test_cutover_stamps_the_landed_sha_onto_this_branchs_staged_closures(scratch):
    """The sha only becomes knowable at the moment of landing.

    A hunter stages a closure before its branch has been rebased, so it cannot know
    which commit will carry the fix — and recording the pre-rebase sha is exactly
    the orphaned `fixed_by` the reanchor repair exists to clean up after. Stamping
    here means the closure names the commit that actually reached the trunk.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "stamped",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)

    _stage_row(repo, "debug/stamped", "IMP-0001")
    _stage_row(repo, "debug/other-branch", "IMP-0002")   # someone else's, untouched

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK

    rows = {r["id"]: r for r in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == payload["sha"]
    assert rows["IMP-0002"]["landed_sha"] is None, "stamped a row belonging to another branch"
    assert payload["staged_closures"] == ["IMP-0001"]

@gitmark
def test_a_cutover_refused_before_it_starts_stamps_nothing(scratch):
    """The easy half: a refusal so early the trunk is never touched.

    Kept, but named for what it actually exercises. It used to be the ONLY guard on
    the stamp's position and it cannot do that job: with no gate verdict recorded,
    `cmd_cutover` returns before it resolves the primary and before it takes the
    advance lock, so it never reaches the ff at all — every possible stamp position
    passes it. Moving the stamp to just after the rebase, which is exactly the
    dangerous placement, left this test green (mutant survived, measured). The
    post-ff half is the test below.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "refused",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/refused", "IMP-0001")

    # no gate verdict recorded -> cutover refuses before it does anything
    rc, _ = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert _queue_rows(repo)[0]["landed_sha"] is None

@gitmark
def test_a_cutover_that_gets_past_the_gate_and_then_fails_the_ff_stamps_nothing(scratch):
    """The half that actually pins the stamp's position.

    This drives the branch all the way through `gate` and the rebase, and then makes
    the fast-forward itself fail — an untracked file in the primary that the branch
    also adds, which `git merge --ff-only` refuses to overwrite and which the
    tracked-clean readiness check deliberately allows through. So the run reaches
    the inside of the advance lock, rebases, and returns EXIT_BLOCK with local main
    unmoved.

    That is the window the stamp must stay out of. `make_commit_state` accepts a sha
    reachable from HEAD *or* main, so a sha written here would still validate when
    `anchor` runs from a worktree that has not been torn down — and the entry would
    close against a commit sitting on no trunk, with nothing downstream to complain.

    Mutation-checked: moving `_stamp_anchor_queue` to just after the rebase makes
    this red and every other test in the suite stay green.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "ffblocked",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "collide.txt").write_text("from the branch\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: collide"], wt)
    _stage_row(repo, "debug/ffblocked", "IMP-0001")

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK

    # untracked in the primary: passes the tracked-clean check, blocks the ff.
    (Path(repo) / "collide.txt").write_text("already here, untracked\n")
    before_main = _git(["rev-parse", "main"], repo)

    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, f"expected the ff to be refused, got {payload}"
    assert _git(["rev-parse", "main"], repo) == before_main, \
        "local main moved; this test no longer exercises a refused landing"
    assert _queue_rows(repo)[0]["landed_sha"] is None, (
        "a cutover that did not land stamped a sha onto the queue — `anchor` would "
        "close the entry against a commit on no trunk")

@gitmark
def test_a_concurrent_stage_cannot_wipe_the_sha_cutover_just_stamped(scratch):
    """The stamp is a read-modify-write of the same file `stage` appends to.

    Both sides now take the same lock, and this is the side where losing matters
    more. `_stamp_anchor_queue` runs exactly once, during its branch's cutover; by
    the time anyone notices, the branch is in the trunk and `resolve` has torn the
    worktree down, so the sha is never re-derivable. `anchor` would then file the
    row under "its branch has not landed", which is false, and the only other copy
    of the answer was in a payload nobody kept.

    The window is widened on purpose — the same method this repo's `_view_lock`
    docstring uses — because the real stamp is shorter than one process start, so
    "it did not happen at N=4" is not "it cannot happen".
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "stampsafe",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/stampsafe", "IMP-0001")
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK

    queue = Path(repo) / ".cache" / "backlog_anchor_queue.jsonl"
    import threading

    def slow_appender():
        """A peer hunter staging its own row, holding the lock across the window."""
        with MODULE.wr._ledger_lock(queue):
            rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
            # Wide enough that cutover certainly reaches the stamp inside it. Erring
            # long is the safe direction: too short and an unlocked stamp simply
            # finishes first, the windows never overlap, and the mutant survives for
            # a timing reason rather than a correctness one.
            time.sleep(6.0)
            rows.append({"id": "IMP-0002", "verdict": "CONFIRMED-FIXED", "by": "peer",
                         "evidence": "ran it", "status": "fixed", "at": "2026-08-08",
                         "branch": "debug/peer", "landed_sha": None})
            queue.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                encoding="utf-8")

    thread = threading.Thread(target=slow_appender)
    thread.start()
    time.sleep(0.3)                              # let it read and settle into the gap
    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    thread.join(timeout=60)
    assert rc == MODULE.EXIT_OK, payload

    rows = {r["id"]: r for r in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == payload["sha"], (
        "the peer's unlocked-era write would have restored landed_sha to null while "
        "cutover still reported the stamp as done")
    assert "IMP-0002" in rows, "the peer's own row was lost instead"

@gitmark
def test_resolve_names_the_landed_closures_still_waiting_on_the_wave_anchor(scratch):
    """Said out loud, and NOT blocking — a handoff note, not a warning.

    The queue is gitignored and lives on this machine only, so nothing downstream
    of `resolve` can notice a row nobody anchored: not the gate, not the docs lint,
    and not any reader of the ledger — `list`, `show` and the generated view all
    read the store, where the entry just looks open. (Not "the board": the planned
    bounty board does not exist yet, and the only board this repo ever had,
    `converge_board.py`, is retired. The earlier docstring's "(measured)" had
    nothing behind it.)

    Blocking would be wrong: the closure HAS landed, the entry is merely not closed
    yet, and a teardown that refuses strands the worktree instead of fixing it. So
    would `⚠ never anchored`, which is what the first draft printed — stamped-but-
    unanchored is the documented normal state at this point, and a gate that reds on
    the normal path is one that gets switched off. What earns the line is that this
    is the last moment the worktree exists to say it.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "unanchored",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/unanchored", "IMP-0001")
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, "an unanchored closure must not block teardown"
    assert payload["pending_anchor"] == ["IMP-0001"]

@gitmark
def test_gate_refuses_a_worktree_with_an_operation_in_flight(scratch, tmp_path):
    """A conflicted tree must not be able to record a green verdict.

    Measured, and it is how this guard was found: a `git rebase` stopped on a
    delete-vs-modify conflict, and `gate` run over that tree reported
    `verdict: pass` with `changed_files: []` and two gates run. `git diff` against
    the trunk on a half-applied rebase describes the PARTIAL state, so `plan_gates`
    routed nothing and `aggregate_verdict([])` is "pass". That verdict is bound to
    the current HEAD and is exactly what `cutover` demands as proof.

    The signal is the OPERATION, not the empty diff: a branch already contained in
    the trunk legitimately has nothing to gate, and refusing on empty-diff alone
    would break that case.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "midflight",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = Path(opened["path"])

    # branch and trunk both touch the same line, so the rebase is guaranteed to stop
    (wt / "clash.txt").write_text("branch side\n", encoding="utf-8")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "branch: clash"], wt)
    (repo / "clash.txt").write_text("trunk side\n", encoding="utf-8")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "trunk: clash"], repo)

    rebase = subprocess.run(["git", "rebase", "main"], cwd=str(wt),
                            capture_output=True, text=True,
                            env={**os.environ, "GIT_EDITOR": "true"})
    assert rebase.returncode != 0, "the fixture failed to produce a stopped rebase"
    assert MODULE._interrupted_operation(wt) == "rebase"

    rc, payload = _run_json(["gate", "--worktree", str(wt), "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, f"gate did not refuse a mid-rebase tree: {payload}"
    assert payload.get("interrupted") == "rebase", payload
    assert "verdict" not in payload, "a refused gate must not record a verdict"

    # and the refusal lifts once the tree is coherent again
    subprocess.run(["git", "rebase", "--abort"], cwd=str(wt), check=True,
                   capture_output=True)
    assert MODULE._interrupted_operation(wt) is None

def test_a_doc_deleted_in_the_diff_does_not_block_the_docs_gate():
    """Removing a doc must not be un-gateable.

    All three docs gates READ the file, and a deleted path is still a changed path.
    `docs_lint --files <gone>` exits 2 with "--files 路徑不存在" — so before this,
    **every commit that removed a doc was blocked**, by an error phrased as if the
    caller had mistyped. Measured on the commit that removed the generated ledger
    view (IMP-20260807-b9526c): that was the second gate defect this repo's own
    dogfooding turned up in one session.

    The removal is NAMED rather than silently dropped, matching `ops-shell-untested`
    and `data-plane-unowned`: a gate list that quietly shrinks reads as "everything
    was checked".
    """
    gone, live = "docs/sop/removed.md", "docs/sop/kept.md"
    gates = _by_name(plan_gates([gone, live], ops_test_exists=lambda rel: rel != gone))

    assert "docs-lint" in gates
    assert gone not in gates["docs-lint"]["cmd"], "the deleted doc was handed to docs_lint"
    assert live in gates["docs-lint"]["cmd"]
    for name in ("docs-conflict-markers", "docs-verified-against"):
        assert gates[name]["files"] == [live], f"{name} still points at a deleted file"

    assert gates["docs-removed"]["files"] == [gone]
    assert gates["docs-removed"]["level"] == "warn", "a deletion is not a failure"

    # and with nothing left to lint, the reading gates do not appear at all rather
    # than running over an empty list
    only_gone = _by_name(plan_gates([gone], ops_test_exists=lambda rel: False))
    assert "docs-lint" not in only_gone
    assert only_gone["docs-removed"]["files"] == [gone]

@gitmark
def test_resolve_names_claimed_tickets_that_were_never_staged(scratch, tmp_path):
    """The failure this tool had on its own flagship task.

    `open --backlog X` claimed it, the work landed, `resolve` printed
    `pending_anchor: []`, the worktree vanished, and X was still `open`. Five other
    tickets in the same session closed correctly — every one of them FILED mid-work.
    The claim is taken at the start and the closure happens at the end, and nothing
    carried the obligation across; teardown is the last moment anyone knows the claim
    existed.

    `pending_anchor` cannot cover this: it asks "did someone who remembered to close
    it finish the job". Both report `[]` on the happy path, which is exactly why the
    second question needs its own answer — an unclosed claim and a clean teardown
    were byte-identical in the output.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "unclosed",
                            "--backlog", "IMP-0001", "IMP-0002",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, opened
    wt, wt_branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)

    # one of the two gets a closure; the other is the one that would vanish.
    # Branch name from the payload, never guessed: `open` derives the prefix from
    # the intent text, so a hardcoded "debug/…" stages a row nothing will match and
    # the test passes for the wrong reason.
    _stage_row(repo, wt_branch, "IMP-0001")

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, "an unclosed claim must not block teardown"
    assert payload["claimed_without_closure"] == ["IMP-0002"], payload
    assert payload["pending_anchor"] == ["IMP-0001"], (
        "the two questions must not collapse into one another")

def test_the_claim_is_read_before_the_ledger_record_is_struck(scratch, tmp_path):
    """Order is the whole trick.

    `resolve` closes the ledger record ahead of the git steps, and every reader of
    that ledger filters on `status == active`. Reading the claim afterwards would
    always answer "nothing was claimed" — a check that can only ever pass, which is
    worse than no check because it looks like one.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "ordering",
                            "--backlog", "IMP-0007", "--state", state, "--json"])
    wt, wt_branch = opened["path"], opened["branch"]
    assert MODULE._claimed_tickets(state, wt_branch) == ["IMP-0007"]

    _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--force",
               "--json"])
    assert MODULE._claimed_tickets(state, wt_branch) == [], (
        "a struck record still reported its claim — then the guard would fire after "
        "teardown instead of before it")

@gitmark
def test_a_claim_already_closed_in_the_store_is_not_reported(scratch, tmp_path):
    """The guard false-positived on its own first real teardown.

    `anchor --commit` DRAINS the queue. The documented order leaves the row in place
    when `resolve` looks (stage → cutover → resolve → wave-end anchor), but
    anchoring first is equally legitimate — and then the row that proved the closure
    is gone, so a queue-only predicate reports a correctly-closed ticket as
    abandoned. Measured: the teardown that landed this guard named its own ticket.

    A warning that fires on a normal path gets switched off, and takes the real
    signal with it. So the predicate is "claimed, AND not staged, AND not already
    resolved in the store".
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "drained",
                            "--backlog", "IMP-0100", "IMP-0101",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, opened
    wt, wt_branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    # IMP-0100 was closed and its queue row consumed; IMP-0101 was simply forgotten.
    store = Path(repo) / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True, exist_ok=True)
    (store / "IMP-0100.json").write_text(json.dumps({"id": "IMP-0100", "status": "fixed"}),
                                         encoding="utf-8")
    (store / "IMP-0101.json").write_text(json.dumps({"id": "IMP-0101", "status": "open"}),
                                         encoding="utf-8")

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert payload["claimed_without_closure"] == ["IMP-0101"], (
        f"a ticket already resolved in the store was reported as abandoned: {payload}")

def test_an_unreadable_entry_keeps_the_guard_talking(tmp_path):
    """Fail-OPEN, and the direction is the point.

    `_entry_is_closed` answering False for a file it could not read means the guard
    still speaks up. The opposite default would let a missing or corrupt entry
    silence a real abandoned claim — silence being the failure this guard exists to
    end.
    """
    root = tmp_path / "repo"
    (root / "docs" / "runbook" / "backlog").mkdir(parents=True)
    assert MODULE._entry_is_closed(root, "IMP-9999") is False          # absent
    (root / "docs" / "runbook" / "backlog" / "IMP-8888.json").write_text(
        "{not json", encoding="utf-8")
    assert MODULE._entry_is_closed(root, "IMP-8888") is False          # corrupt
    (root / "docs" / "runbook" / "backlog" / "IMP-7777.json").write_text(
        json.dumps({"id": "IMP-7777", "status": "wont-fix"}), encoding="utf-8")
    assert MODULE._entry_is_closed(root, "IMP-7777") is True           # closed counts

def test_the_landing_queue_hands_out_turns_in_arrival_order(tmp_path):
    primary = tmp_path
    a, fa = MODULE._land_enqueue(primary, "/wt/a")
    b, fb = MODULE._land_enqueue(primary, "/wt/b")
    c, fc = MODULE._land_enqueue(primary, "/wt/c")
    assert a < b < c
    assert MODULE._land_position(primary, a)[0] == 0
    assert MODULE._land_position(primary, b)[0] == 1
    assert MODULE._land_position(primary, c)[0] == 2
    MODULE._land_release(primary, a, fa)
    assert MODULE._land_position(primary, b)[0] == 0
    assert MODULE._land_position(primary, c)[0] == 1
    MODULE._land_release(primary, b, fb)
    MODULE._land_release(primary, c, fc)

def test_a_ticket_whose_owner_actually_died_stops_holding_the_queue(tmp_path):
    """An owner really dies here.

    The previous version of this test hand-wrote {"pid": 0} and called that a
    dead owner. It was not: it was a CORRUPT ticket, and it left the liveness
    probe itself untested — the whole `os.kill` body could be deleted and this
    test still passed. Liveness is now the kernel's answer to "is the flock
    free", so the honest way to ask is to have a real process take the lock and
    then kill it.
    """
    primary = tmp_path
    qdir = MODULE._land_queue_dir(primary)
    qdir.mkdir(parents=True, exist_ok=True)
    ticket = qdir / f"{1:012d}.json"
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,os,sys\n"
         "fd=os.open(sys.argv[1], os.O_CREAT|os.O_RDWR, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "os.write(fd, b'{\"pid\": 1, \"worktree\": \"/wt/dead\"}')\n"
         "sys.stdout.write('held'); sys.stdout.flush()\n"
         "import time; time.sleep(120)\n",
         str(ticket)],
        stdout=subprocess.PIPE)
    try:
        assert child.stdout.read(4) == b"held"
        mine, fd = MODULE._land_enqueue(primary, "/wt/mine")
        assert mine > 1, "the dead lane's ticket must sort ahead of ours"
        # ALIVE: the holder is in front of us and stays there.
        assert MODULE._land_position(primary, mine)[0] == 1
        assert ticket.exists()
    finally:
        child.kill()
        child.wait()
    # DEAD: the kernel dropped the flock with the process, so the turn moves.
    assert MODULE._land_position(primary, mine)[0] == 0
    assert not ticket.exists(), "a dead owner's ticket must be evicted, not skipped"
    MODULE._land_release(primary, mine, fd)

def test_a_corrupt_ticket_ahead_of_us_is_evicted_not_stepped_over(tmp_path):
    """Planted AHEAD of ours on purpose: a bad ticket behind us cannot change our
    position, so asserting position 0 with it behind would assert nothing at all.
    """
    primary = tmp_path
    mine, fd = MODULE._land_enqueue(primary, "/wt/mine")
    # planted AFTER we queue, at a LOWER sequence, so it really is in front of us
    # (planting it first is no good: enqueue sweeps it before picking our number,
    # and then the test proves only that enqueue ran).
    bad = MODULE._land_queue_dir(primary) / f"{mine - 1:012d}.json"
    bad.write_text("{not json")
    with MODULE._land_lock(primary):
        seqs_before = sorted(p.stem for p in
                             MODULE._land_queue_dir(primary).glob("*.json"))
    assert len(seqs_before) == 2, "the bad ticket should be sitting ahead of ours"
    assert MODULE._land_position(primary, mine)[0] == 0
    assert not bad.exists()
    MODULE._land_release(primary, mine, fd)

def test_land_refuses_a_blocking_gate_and_never_reaches_cutover(tmp_path, monkeypatch,
                                                                capsys):
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_land_stub("gate", MODULE.EXIT_BLOCK, {"verdict": "block"}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    assert "cutover" not in _land_stub.calls, \
        "a block verdict must not reach cutover"
    assert json.loads(capsys.readouterr().out)["landed"] is False
    assert _queued(primary) == [], "the turn must be released on refusal"

def test_land_refuses_when_catchup_fails_and_never_reaches_the_gate(tmp_path,
                                                                    monkeypatch,
                                                                    capsys):
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        catchup=_land_stub("catchup", MODULE.EXIT_BLOCK, {"error": "conflict"}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    assert _land_stub.calls == ["catchup"], \
        f"nothing may run after a failed catchup, ran: {_land_stub.calls}"
    assert json.loads(capsys.readouterr().out)["landed"] is False
    assert _queued(primary) == []

def test_land_releases_its_turn_even_when_a_step_raises(tmp_path, monkeypatch):
    """The failure that wedges every other lane. Without the `finally`, one
    exception parks the queue head until the process exits."""
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_land_stub("gate", boom=RuntimeError("gate exploded")))
    with pytest.raises(RuntimeError):
        MODULE.cmd_land(args)
    assert _queued(primary) == [], "an exception must not leave the turn held"

def test_land_shouts_when_cutovers_exit_code_and_payload_disagree(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """Reachable when a payload fails to parse: `landed` reads False while the
    trunk has already moved. Reporting a plain refusal there would be a lie."""
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        cutover=_land_stub("cutover", 0, {"no_landed_key": True}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert payload["landed"] is None
    assert "disagree" in payload["error"]
    assert _queued(primary) == []

def test_land_dry_run_takes_no_turn_and_runs_nothing(tmp_path, monkeypatch, capsys):
    """A dry run that enqueued would make `land --json` — the natural way to ask
    'how deep is the queue' — lengthen the queue it is reporting on."""
    primary, args = _land_harness(monkeypatch, tmp_path)
    args.commit = False
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_OK
    assert _land_stub.calls == [], "a dry run must not execute any step"
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run" and payload["landed"] is False
    assert _queued(primary) == []

@gitmark
def test_land_does_not_guess_the_branch_from_a_path_that_is_not_a_worktree(
        tmp_path, monkeypatch, capsys):
    """`cmd_land` only checks that `--worktree` is a directory. `_current_branch` answers
    by asking git from inside that path, and git discovery walks UP — so a directory that
    is merely INSIDE the repo (or a worktree that lost its `.git`) answers with the
    ENCLOSING checkout's branch, i.e. `main`. Feeding that to the coordination notice
    posts "blocked branch: `main`", which is worse than posting nothing: it names an
    innocent branch. `_worktree_entry` reads `git worktree list --porcelain`, which
    cannot invent a membership. Found by review of 233c78039, where the fix shipped with
    nothing able to observe a revert."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for a in (["init", "-q", "-b", "main"], ["-c", "user.email=t@t", "-c", "user.name=t",
                                             "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    inside = repo / "not-a-worktree"
    inside.mkdir()
    # the trap, demonstrated rather than asserted from memory
    assert MODULE._current_branch(str(inside)) == "main"

    primary, args = _land_harness(monkeypatch, tmp_path)
    args.worktree = str(inside)
    assert MODULE.cmd_land(args) == MODULE.EXIT_OK
    capsys.readouterr()

    assert _land_harness.ff_ready_calls, "the pre-gate primary check must have been asked"
    passed = _land_harness.ff_ready_calls[0]["branch"]
    assert passed != "main", (
        "cmd_land handed the ENCLOSING checkout's branch to the coordination notice")
    assert passed is None

def test_land_refuses_primary_dirty_before_gate_leaving_no_gate_record(
        tmp_path, monkeypatch, capsys):
    """The refusal has to arrive before anything expensive has been spent.

    Two independent witnesses, because each alone is weak: `_land_stub.calls`
    proves the step functions were never entered, and the absent gate record proves
    no verdict was produced. rc alone would prove neither — `land` already exits
    EXIT_BLOCK for a red gate, i.e. the number this refusal shares with the very
    outcome it is supposed to be distinguishable from.
    """
    state, wt = str(tmp_path / "registry.json"), str(tmp_path / "wt")
    rec = MODULE._gate_record_path(state, wt)
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_recording_gate_stub(state, wt),
        ff_ready=_dirty_primary())

    rc = MODULE.cmd_land(args)

    assert rc == MODULE.EXIT_BLOCK
    assert not rec.exists(), \
        "a gate verdict on disk means a gate ran — the whole cost this check avoids"
    assert _land_stub.calls == [], \
        f"nothing may run once the primary is known dirty, ran: {_land_stub.calls}"
    payload = json.loads(capsys.readouterr().out)
    assert payload["landed"] is False
    assert "dirty" in payload["error"]
    # The refusal must name WHICH files, or the operator is back to guessing which
    # of their own writes is in the way.
    assert payload["dirty_files"] == ["docs/runbook/backlog/IMP-0023.json"]
    assert _queued(primary) == [], "the turn must be released on refusal"

def test_land_precheck_lets_a_clean_primary_through_to_the_gate(
        tmp_path, monkeypatch, capsys):
    """The positive control for the test above.

    Without it, "no gate record was written" is satisfied by a stub that cannot
    write one at all, and by a `cmd_land` that refuses every lane for any reason.
    Same harness, same stub, one field flipped.
    """
    state, wt = str(tmp_path / "registry.json"), str(tmp_path / "wt")
    rec = MODULE._gate_record_path(state, wt)
    primary, args = _land_harness(
        monkeypatch, tmp_path, gate=_recording_gate_stub(state, wt))

    rc = MODULE.cmd_land(args)

    assert rc == MODULE.EXIT_OK
    assert _land_stub.calls == ["catchup", "gate", "cutover"]
    assert rec.exists(), "the stub must be able to write the record it is judged by"
    assert json.loads(capsys.readouterr().out)["landed"] is True
    assert _queued(primary) == []

def test_land_asks_the_primary_dirty_before_gate_question_exactly_once(
        tmp_path, monkeypatch, capsys):
    """`land` owns the CHEAP check; `cutover` owns the load-bearing one.

    The pre-check is not a replacement for cutover's pre-ff check and must not grow
    into one: the primary can be dirtied WHILE the gate runs — 2026-08-08 is exactly
    that story — so the answer this call gets expires. Anyone tempted to treat one of
    the two as redundant should read this test and
    `test_cutover_refused_when_primary_is_dirty`, which pins the other one.
    """
    asked = []

    def ff_ready(primary, local, branch=None, worktree=None):
        asked.append(local)
        return None
    primary, args = _land_harness(monkeypatch, tmp_path, ff_ready=ff_ready)

    assert MODULE.cmd_land(args) == MODULE.EXIT_OK
    capsys.readouterr()
    assert asked == ["main"], (
        "exactly one pre-check, against the LOCAL trunk `land` is heading for; "
        f"got {asked}")

def test_close_wave_does_not_block_on_foreign_active_worktrees(
        tmp_path, monkeypatch, capsys):
    """A Delivery Team may finish while another team still owns worktrees.

    The resolver still receives only this wave's explicit branches; unrelated
    active records are not a reason to make every team communicate manually.
    """
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE,
        "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [
            {"status": "active", "branch": "feat/source", "path": "/wt/source"},
            {"status": "active", "branch": "feat/catalog-agent-tool",
             "path": "/wt/catalog", "intent": "Catalog cutover"},
        ]),
    )
    args = argparse.Namespace(
        state=None,
        json=True,
        base="main",
        slug="delivery-wave",
        branches=["feat/source"],
        commit=False,
        sync=False,
    )

    rc = MODULE.cmd_close_wave(args)

    assert rc == MODULE.EXIT_OK
    output = capsys.readouterr().out
    assert "feat/catalog-agent-tool" not in output
    assert "foreign active" not in output

def test_close_wave_expected_ticket_set_is_derived_only_from_named_sources():
    records = [
        {"status": "active", "branch": "feat/source-a",
         "backlog": ["IMP-0002", "IMP-0001"]},
        {"status": "active", "branch": "feat/source-b",
         "backlog": ["IMP-0003"]},
        {"status": "active", "branch": "feat/foreign",
         "backlog": ["IMP-9999"]},
        {"status": "merged", "branch": "feat/source-a",
         "backlog": ["IMP-8888"]},
    ]

    assert MODULE._delivery_expected_ticket_ids(
        records, ["feat/source-b", "feat/source-a"]
    ) == ["IMP-0001", "IMP-0002", "IMP-0003"]
    records.append({
        "status": "active", "branch": "feat/source-c", "backlog": "IMP-0004",
    })
    assert MODULE._delivery_expected_ticket_reservation_errors(
        records, ["feat/source-c"]
    ) == [{
        "branch": "feat/source-c",
        "reason": "backlog must be a list of non-empty ticket ids",
    }]

def test_close_wave_expected_ticket_closure_requires_fixed_by_and_confirmed_verdict(
        tmp_path):
    store = tmp_path / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    (store / "IMP-0001.json").write_text(json.dumps({
        "id": "IMP-0001", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": ["abc123"],
    }), encoding="utf-8")
    (store / "IMP-0002.json").write_text(json.dumps({
        "id": "IMP-0002", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [],
    }), encoding="utf-8")
    (store / "IMP-0003.json").write_text(json.dumps({
        "id": "IMP-0003", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [""],
    }), encoding="utf-8")

    result = MODULE._delivery_expected_ticket_closure(
        tmp_path, ["IMP-0001", "IMP-0002", "IMP-0003", "IMP-0004"]
    )

    assert result["ok"] is False
    assert result["expected_ticket_ids"] == [
        "IMP-0001", "IMP-0002", "IMP-0003", "IMP-0004"
    ]
    assert result["failures"] == [
        {"id": "IMP-0002", "reason": "fixed_by is empty"},
        {"id": "IMP-0003", "reason": "fixed_by contains an empty sha"},
        {"id": "IMP-0004", "reason": "entry is missing or unreadable"},
    ]

def test_independent_no_ticket_default_closure_still_refuses_empty_set(tmp_path):
    """No-ticket closure is opt-in; the ordinary closure predicate stays fail-closed."""
    result = MODULE._delivery_expected_ticket_closure(tmp_path, [])

    assert result == {
        "ok": False,
        "expected_ticket_ids": [],
        "failures": [{"reason": "expected ticket set is empty"}],
    }

def test_independent_no_ticket_parser_and_provenance_are_explicit():
    parser = MODULE.build_parser()
    args = parser.parse_args([
        "close-wave", "--slug", "wave", "--branches", "feat/source",
        "--independent",
    ])
    assert args.independent is True

    provenance = MODULE._delivery_independent_no_ticket_provenance(
        state={
            "independent": True,
            "branch": "feat/integration",
            "gate": {"head_sha": "abc123", "verdict": "warn"},
        },
        manifest={
            "independent": True,
            "branch": "feat/integration",
            "head_sha": "abc123",
        },
        integration_record={
            "branch": "feat/integration",
            "independent": True,
            "intent": "independent-no-ticket: explicit fixture",
        },
        current_head="abc123",
        primary_dirty=[],
        queue=[],
    )
    assert provenance["ok"] is True, provenance
    assert provenance["mode"] == "independent-no-ticket"

@gitmark
def test_independent_no_ticket_integrate_resume_opt_in_is_consistent(scratch, monkeypatch):
    """Every append/continuation hint must preserve the wave's explicit opt-in."""
    tmp_path, repo, _remote = scratch

    ordinary_state = str(tmp_path / "ordinary.json")
    ordinary_sha = _make_branch(repo, "feat/src-ordinary", {"ordinary.txt": "x\n"},
                                "work: ordinary")
    rc, ordinary = _run_integrate_json([
        "integrate", "--slug", "ordinary", "--branches", "feat/src-ordinary",
        "--state", ordinary_state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, ordinary
    assert "--independent" not in ordinary["next_step"], ordinary

    late_ordinary = _make_branch(repo, "feat/late-ordinary", {"late.txt": "x\n"},
                                 "work: late ordinary")
    rc, refused = _run_integrate_json([
        "integrate", "--slug", "ordinary", "--append", "--branches",
        "feat/late-ordinary", "--state", ordinary_state, "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, refused
    assert refused["persisted_independent"] is False, refused
    assert refused["requested_independent"] is True, refused
    assert ordinary_sha and late_ordinary

    independent_state = str(tmp_path / "independent.json")
    independent_sha = _make_branch(repo, "feat/src-independent", {"independent.txt": "x\n"},
                                    "work: independent")
    rc, independent = _run_integrate_json([
        "integrate", "--slug", "independent", "--branches", "feat/src-independent",
        "--state", independent_state, "--commit", "--no-gate", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_OK, independent
    assert independent["independent"] is True, independent
    assert independent["next_step"].endswith("--continue --commit --independent"), independent

    rc, existing = _run_integrate_json([
        "integrate", "--slug", "independent", "--branches", "feat/src-independent",
        "--state", independent_state, "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, existing
    assert "--continue --commit --independent" in existing["error"], existing

    conflict_independent = _make_branch(
        repo, "feat/conflict-independent", {"conflict.txt": "x\n"},
        "work: conflict independent",
    )
    monkeypatch.setattr(MODULE, "_unmerged_paths", lambda _wt: ["conflict.txt"])
    monkeypatch.setattr(MODULE, "_interrupted_operation", lambda _wt: None)
    rc, conflict = _run_integrate_json([
        "integrate", "--slug", "independent", "--append", "--branches",
        "feat/conflict-independent", "--state", independent_state,
        "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, conflict
    assert conflict["next_step"].endswith("integrate --continue --independent"), conflict
    assert conflict_independent

    drive_independent = _make_branch(
        repo, "feat/drive-independent", {"drive.txt": "x\n"},
        "work: drive independent",
    )
    monkeypatch.setattr(MODULE, "_unmerged_paths", lambda _wt: [])
    state_path = MODULE._integrate_state_path(independent_state, "independent")
    saved = json.loads(state_path.read_text())
    saved["queue"] = [{
        "branch": "feat/drive-independent", "sha": drive_independent,
        "subject": "work: drive independent",
    }]
    saved["planned_total"] = int(saved.get("planned_total") or 0) + 1
    state_path.write_text(json.dumps(saved), encoding="utf-8")
    real_mutation = MODULE._git_mutation

    def fail_pick(argv, *, cwd, label):
        if label.startswith("integrate-cherry-pick:"):
            return 1, "empty-pick fixture"
        return real_mutation(argv, cwd=cwd, label=label)

    monkeypatch.setattr(MODULE, "_git_mutation", fail_pick)
    rc, drive = _run_integrate_json([
        "integrate", "--slug", "independent", "--state", independent_state,
        "--continue", "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, drive
    assert "--continue --commit --independent" in drive["error"], drive
    assert drive_independent
    monkeypatch.setattr(MODULE, "_git_mutation", real_mutation)

    late_independent = _make_branch(repo, "feat/late-independent", {"late-independent.txt": "x\n"},
                                     "work: late independent")
    rc, refused = _run_integrate_json([
        "integrate", "--slug", "independent", "--append", "--branches",
        "feat/late-independent", "--state", independent_state, "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, refused
    assert refused["persisted_independent"] is True, refused
    assert refused["requested_independent"] is False, refused
    assert independent_sha and late_independent

    (Path(repo) / "ops").mkdir()
    bad_sha = _make_branch(repo, "feat/src-independent-bad", {"ops/bad-round.sh": "if then\n"},
                           "work: independent bad")
    blocked_state = str(tmp_path / "blocked-independent.json")
    rc, blocked = _run_integrate_json([
        "integrate", "--slug", "blocked-independent", "--branches",
        "feat/src-independent-bad", "--state", blocked_state, "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, blocked
    assert "--continue --commit --independent" in blocked["next_step"], blocked
    assert bad_sha

@pytest.mark.parametrize("independent, expected_rc", [(False, MODULE.EXIT_BLOCK),
                                                       (True, MODULE.EXIT_OK)])
def test_independent_no_ticket_close_wave_completed_manifest_route(
        tmp_path, monkeypatch, capsys, independent, expected_rc):
    """A resumed completed manifest keeps the ordinary refusal and explicit route."""
    primary = tmp_path / "primary"
    primary.mkdir()
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "removed-integration"),
        "branch": "feat/integration",
        "status": "gated",
        "integration_revision": MODULE.sha256_file(Path(MODULE.__file__).resolve()),
        "independent": independent,
        "close_wave": {
            "status": "completed",
            "expected_ticket_ids": [],
            "independent_provenance": (
                {"ok": True, "mode": "independent-no-ticket"}
                if independent else None
            ),
        },
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE, "_delivery_state_paths", lambda _args: (state, [manifest])
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [{
            "status": "merged", "branch": "feat/source", "backlog": [],
        }]),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_sync_close_wave",
        lambda *_args, **_kwargs: (MODULE.EXIT_OK, None),
    )
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=False,
        independent=independent,
    )

    rc = MODULE.cmd_close_wave(args)
    payload = json.loads(capsys.readouterr().out)
    assert rc == expected_rc, payload
    if independent:
        assert payload["mode"] == "already-closed"
        assert payload["steps"][0]["ok"] is True
    else:
        assert payload["steps"][0]["ok"] is False
        assert payload["steps"][0]["failures"] == [
            {"reason": "expected ticket set is empty"}
        ]

@pytest.mark.parametrize("marker_status", ["completed", "validated"])
def test_close_wave_recovery_guard_refuses_open_expected_ticket(
        tmp_path, monkeypatch, capsys, marker_status):
    primary = tmp_path / "primary"
    store = primary / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_id = "IMP-0001"
    (store / f"{ticket_id}.json").write_text(json.dumps({
        "id": ticket_id, "status": "triaged", "verdict": "CONFIRMED-OPEN",
        "fixed_by": [],
    }), encoding="utf-8")
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "already-removed"),
        "branch": "feat/integration",
        "status": "gated",
        "integration_revision": MODULE.sha256_file(Path(MODULE.__file__).resolve()),
        "close_wave": {
            "status": marker_status,
            "expected_ticket_ids": [ticket_id],
        },
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE, "_delivery_state_paths", lambda _args: (state, [manifest])
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [{
            "status": "merged", "branch": "feat/source", "backlog": [ticket_id],
        }]),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_sync_close_wave",
        lambda *_args, **_kwargs: pytest.fail("recovery must stop before sync"),
    )
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=True,
    )

    rc = MODULE._cmd_close_wave_impl(args)

    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert "not fixed" in payload["error"]
    assert payload["steps"][0]["name"] == "expected-ticket-closure"

def test_delivery_json_tool_rejects_invalid_success_receipt_and_relays_stderr(
        tmp_path, monkeypatch, capsys):
    def fake_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0, stdout="{}\n", stderr="child diagnostic\n"
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, payload = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="receipt-probe",
        expected_schema="expected.v1", required_keys=("records",),
    )

    assert rc == MODULE.EXIT_BLOCK
    assert "invalid success receipt" in payload["error"]
    assert "schema" in payload["contract_errors"][0]
    assert payload["receipt"] == {}
    assert "child diagnostic" in capsys.readouterr().err

def test_delivery_json_tool_rejects_semantically_invalid_success_receipt(
        tmp_path, monkeypatch):
    def fake_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0,
            stdout=json.dumps({"schema": "expected.v1", "mode": "dry-run",
                               "landed": False, "sha": "stale"}),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, payload = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="receipt-probe",
        expected_schema="expected.v1", required_keys=("landed",),
        receipt_validator=MODULE._delivery_require_cutover_landed,
    )

    assert rc == MODULE.EXIT_BLOCK
    assert "mode" in payload["contract_errors"][0]
    assert payload["receipt"]["landed"] is False

@pytest.mark.parametrize(
    "runner_revision,integration_revision,expected",
    [
        ("a" * 64, "a" * 64, None),
        (None, "a" * 64, "runner_revision is missing"),
        ("a" * 64, None, "integration_revision is missing"),
        ("a" * 64, "b" * 64, "runner_revision does not match integration_revision"),
    ],
)
def test_close_wave_runner_revision_guard_requires_matching_revisions(
        runner_revision, integration_revision, expected):
    error = MODULE._delivery_revision_guard(
        runner_revision, integration_revision,
    )
    if expected is None:
        assert error is None
    else:
        assert expected in error

def test_integrate_gated_receipt_requires_integration_revision():
    payload = {
        "mode": "committed",
        "landed": False,
        "verdict": "pass",
        "manifest": "/tmp/integration.json",
        "runner_revision": "a" * 64,
        "integration_revision": "a" * 64,
    }
    assert MODULE._delivery_require_integrate_gated(payload) is None

    del payload["integration_revision"]
    error = MODULE._delivery_require_integrate_gated(payload)
    assert error is not None
    assert "integration_revision" in error

def test_close_wave_stops_before_sync_on_mismatched_revision_manifest(
        tmp_path, monkeypatch, capsys):
    primary = tmp_path / "primary"
    primary.mkdir()
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "already-removed"),
        "branch": "feat/integration",
        "status": "gated",
        "integration_revision": "b" * 64,
        "close_wave": {"status": "completed", "expected_ticket_ids": []},
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE, "_delivery_state_paths", lambda _args: (state, [manifest])
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, []),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_sync_close_wave",
        lambda *_args, **_kwargs: pytest.fail("revision mismatch must stop before sync"),
    )
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=True,
    )

    rc = MODULE._cmd_close_wave_impl(args)

    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "runner_revision does not match integration_revision"
    assert payload["runner_revision"] == MODULE.sha256_file(Path(MODULE.__file__).resolve())
    assert payload["integration_revision"] == "b" * 64

def test_delivery_registry_records_rejects_malformed_record(
        tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_delivery_json_tool",
        lambda *_args, **_kwargs: (MODULE.EXIT_OK, {
            "schema": "kg.worktree.registry.v1",
            "records": [{"path": str(tmp_path), "status": "active"}],
        }),
    )

    rc, records = MODULE._delivery_registry_records(argparse.Namespace(state=None))

    assert rc == MODULE.EXIT_BLOCK
    assert records == []

def test_delivery_registry_records_uses_explicit_primary_after_coordinator_teardown(
        tmp_path, monkeypatch):
    """A close-wave may remove the caller's source worktree mid-command."""
    primary = tmp_path / "primary"
    (primary / "ops").mkdir(parents=True)
    deleted_coordinator = tmp_path / "deleted" / "ops" / "worktree_orchestrate.py"
    seen = {}

    def fake_tool(script, cwd, argv, **_kwargs):
        seen.update(script=Path(script), cwd=Path(cwd), argv=argv)
        return MODULE.EXIT_OK, {"schema": "kg.worktree.registry.v1", "records": []}

    monkeypatch.setattr(MODULE, "__file__", str(deleted_coordinator))
    monkeypatch.setattr(MODULE, "primary_root", lambda: pytest.fail(
        "explicit primary must avoid rediscovering a deleted coordinator cwd"
    ))
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_tool)

    rc, records = MODULE._delivery_registry_records(
        argparse.Namespace(state=None), primary=primary
    )

    assert rc == MODULE.EXIT_OK
    assert records == []
    assert seen["script"] == primary / "ops" / "worktree_registry.py"
    assert seen["cwd"] == primary
    assert "--json" in seen["argv"], (
        "registry-list must request the machine-readable receipt explicitly"
    )

def test_delivery_json_tool_large_ledger_is_not_truncated(tmp_path, monkeypatch):
    """A real registry ledger can exceed the old 256 KiB capture ceiling."""
    payload = {
        "schema": "kg.worktree.registry.v1",
        "records": [{"path": f"/tmp/worktree-{index}",
                     "branch": f"feat/source-{index}",
                     "base": "main", "status": "merged",
                     "intent": "x" * 1800} for index in range(150)],
    }
    raw = json.dumps(payload)
    assert len(raw) > 256 * 1024
    seen = {}

    def fake_runner(_command, **kwargs):
        seen.update(kwargs)
        limit = kwargs["capture_limit"]
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0,
            stdout=raw[:limit], stderr="",
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, decoded = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="large-ledger",
        expected_schema="kg.worktree.registry.v1", required_keys=("records",),
    )

    assert seen["capture_limit"] > len(raw)
    assert rc == MODULE.EXIT_OK
    assert decoded == payload

def test_delivery_operation_target_uses_local_main_for_manifest_identity(tmp_path):
    """Manifest SHA is provenance; operational children run against local main."""
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "base": "deadbeef" * 8,
        "close_wave": {"anchor_base_sha": "deadbeef" * 8},
    }), encoding="utf-8")

    assert MODULE._delivery_operation_base(
        "deadbeef" * 8, manifest=MODULE._delivery_load_json(manifest)
    ) == "main"
    state = {
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "removed-worktree"),
        "branch": "feat/integration",
        "status": "gated",
    }
    assert MODULE._delivery_integration_error(
        state,
        label="integration state",
        slug="delivery-wave",
        base=MODULE._delivery_operation_base("deadbeef" * 8,
                                             manifest=MODULE._delivery_load_json(manifest)),
        branches=["feat/source"],
        require_gated=True,
        require_live_worktree=False,
    ) is None

def test_close_wave_expected_ticket_set_includes_staged_queue(tmp_path):
    """Stacked source rows survive source teardown through the anchor queue."""
    queue = tmp_path / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text("\n".join(json.dumps(row) for row in [
        {"id": "IMP-20260811-5a3b26", "branch": "feat/team-a-de285f",
         "landed_sha": "abc123"},
        {"id": "IMP-20260811-de285f", "branch": "feat/team-a-de285f",
         "landed_sha": None},
        {"id": "IMP-foreign", "branch": "feat/other", "landed_sha": "def456"},
    ]) + "\n", encoding="utf-8")
    records = [{"status": "merged", "branch": "feat/team-a-de285f",
                "backlog": ["IMP-20260811-de285f"]}]

    staged = MODULE._delivery_staged_ticket_ids(tmp_path, ["feat/team-a-de285f"])
    assert staged == ["IMP-20260811-5a3b26", "IMP-20260811-de285f"]
    assert MODULE._delivery_expected_ticket_ids(
        records, ["feat/team-a-de285f"], staged_ids=staged
    ) == ["IMP-20260811-5a3b26", "IMP-20260811-de285f"]

def test_delivery_integration_rejects_foreign_git_checkout(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    foreign = tmp_path / "foreign"
    for repo in (primary, foreign):
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base", "--allow-empty"],
                       cwd=repo, check=True)
    subprocess.run(["git", "switch", "-q", "-c", "feat/integration"],
                   cwd=foreign, check=True)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    payload = {
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(foreign),
        "branch": "feat/integration",
        "status": "gated",
    }

    error = MODULE._delivery_integration_error(
        payload,
        label="integration manifest",
        slug="delivery-wave",
        base="main",
        branches=["feat/source"],
        require_gated=True,
        require_live_worktree=True,
    )

    assert error is not None
    assert "not a linked worktree of this repository" in error

def test_a_cherry_picked_branch_is_vouched_for_by_patch_id(scratch):
    """The strong match: same change, different sha."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane"], repo)
    sha = _commit(repo, "lane.txt", "lane work\n", "ops: lane work")
    _git(["checkout", "-q", "main"], repo)
    # main MUST have moved first. With main still at the branch point, git
    # fast-forwards the cherry-pick and the branch becomes a literal ancestor —
    # a state the landed-floor already accepts, so the audit would never be
    # reached. Every real integration has main ahead (other lanes landed first).
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", sha], repo)

    audit = MODULE._audit_integrated("feat/lane", "main")
    assert audit["ok"] is True, audit
    assert [c["match"] for c in audit["commits"]] == ["patch-id"], audit

def test_a_branch_whose_content_was_amended_during_integration_still_vouches(scratch):
    """The realistic case, and the one tree-diff cannot see.

    Integration resolves a conflict, so what landed is NOT byte-identical to what
    the branch held — patch-id differs. Subject plus the set of files touched is
    the next strongest thing that is still mechanical.
    """
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane2"], repo)
    _commit(repo, "shared.md", "| lane2 |\n", "ops: lane2 row")
    _git(["checkout", "-q", "main"], repo)
    # same subject, same file, DIFFERENT content (a merged version)
    _commit(repo, "shared.md", "| lane1 |\n| lane2 |\n", "ops: lane2 row")

    audit = MODULE._audit_integrated("feat/lane2", "main")
    assert audit["ok"] is True, audit
    assert [c["match"] for c in audit["commits"]] == ["subject+files"], audit

def test_a_commit_that_never_landed_is_named_and_refused(scratch):
    """The whole point of keeping the floor: this is the case the manual audit
    exists to catch, and it is the case an impatient `--force` walks straight past."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane3"], repo)
    kept = _commit(repo, "a.txt", "landed\n", "ops: landed part")
    lost = _commit(repo, "b.txt", "dropped\n", "ops: the part integration missed")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", kept], repo)

    audit = MODULE._audit_integrated("feat/lane3", "main")
    assert audit["ok"] is False, audit
    unmatched = [c for c in audit["commits"] if c["match"] is None]
    assert [c["subject"] for c in unmatched] == ["ops: the part integration missed"]
    assert lost[:9] in [c["sha"] for c in unmatched][0], audit

def test_a_same_subject_commit_touching_other_files_does_not_vouch(scratch):
    """Subject alone is not evidence. Two commits can share a message and change
    unrelated things — the file set is what makes the weaker match usable."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane4"], repo)
    _commit(repo, "wanted.txt", "x\n", "ops: same subject")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "unrelated.txt", "y\n", "ops: same subject")

    audit = MODULE._audit_integrated("feat/lane4", "main")
    assert audit["ok"] is False, audit
    assert audit["commits"][0]["match"] is None, audit

def test_the_audit_reports_what_each_commit_was_matched_on(scratch):
    """A verdict without its grounds is the 'reason field nobody reads'. The
    operator has to be able to see that a branch got through on the WEAK match."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane5"], repo)
    strong = _commit(repo, "s.txt", "strong\n", "ops: strong one")
    _commit(repo, "w.txt", "weak\n", "ops: weak one")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", strong], repo)
    _commit(repo, "w.txt", "weak, but merged differently\n", "ops: weak one")

    audit = MODULE._audit_integrated("feat/lane5", "main")
    assert audit["ok"] is True, audit
    assert sorted(c["match"] for c in audit["commits"]) == ["patch-id", "subject+files"]
    assert all(c["matched_sha"] for c in audit["commits"]), audit

def test_resolve_refuses_without_the_flag_and_accepts_with_it(scratch):
    """End to end through the CLI: the floor still stands, and the flag is the
    second door — not a rename of --force."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "lane", "--slug", "picked",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "picked.txt").write_text("work\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "ops: picked work"], wt)
    sha = _git(["rev-parse", "HEAD"], wt).strip()
    _stage_row(repo, opened["branch"], "IMP-0001")
    # Integrate by hand, exactly as a batch integrator would: trunk moves first,
    # then the pick, then the conflict resolution EDITS the content — merging this
    # lane's line with another lane's. That last step is the whole point: without
    # it main holds a byte-identical copy, the tree-diff floor says "landed", and
    # the audit is never reached. With it, main holds a NEWER version and the floor
    # cannot tell that from "never landed".
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", sha], repo)
    _commit(repo, "picked.txt", "work\nand another lane's line\n",
            "ops: picked work")

    rc, refused = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert "--via-integration" in refused["reason"], (
        "the refusal must name the evidence path, or the only way past it is --force")

    rc, ok = _run_json(["resolve", "--worktree", wt, "--state", state,
                        "--via-integration", "main", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, ok
    assert ok["audit"]["ok"] is True
    # Either rung is a pass here, and which one is not the CLI's contract: the
    # pick itself survives in main's history with its patch-id intact, so the
    # STRONGER rung vouches even though a later commit edited the same file. The
    # weaker rung is exercised where it actually applies — a conflict resolved
    # inside the pick, which produces one commit whose content differs. See
    # test_a_branch_whose_content_was_amended_during_integration_still_vouches.
    assert all(c["match"] for c in ok["audit"]["commits"]), ok["audit"]
    assert all(c["matched_sha"] for c in ok["audit"]["commits"]), ok["audit"]
    rows = {row["id"]: row for row in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == _git(["rev-parse", "main"], repo).strip(), (
        "a vouched-for batch branch was torn down without stamping its closure")
    assert ok["pending_anchor"] == ["IMP-0001"], ok
    assert not Path(wt).exists(), "worktree survived a vouched-for resolve"

def test_resolve_refuses_an_integration_ref_that_has_not_landed_in_the_base(scratch):
    """A branch may vouch for the patch without vouching that it reached main."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "lane", "--slug", "unlanded-source",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "source.txt").write_text("source work\n", encoding="utf-8")
    _git(["add", "source.txt"], wt)
    _git(["commit", "-qm", "ops: source work"], wt)
    source_sha = _git(["rev-parse", "HEAD"], wt).strip()

    # The integration branch contains the source patch, but main does not. Before
    # this guard, --via-integration accepted the patch-id and deleted the only source
    # worktree even though nothing had landed in the trunk.
    _git(["checkout", "-q", "-b", "feat/unlanded-integration", "main"], repo)
    _git(["cherry-pick", source_sha], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, refused = _run_json([
        "resolve", "--worktree", wt, "--state", state,
        "--via-integration", "feat/unlanded-integration", "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert refused["reason_code"] == "integration-ref-not-landed", refused
    assert Path(wt).is_dir(), "an unlanded integration ref was allowed to delete source work"

@gitmark
def test_resolve_source_stamps_integration_rows_and_anchor_consumes_resolved_rows(scratch):
    """A resolved source must preserve the integration branch's queue identity.

    In the batch path the hunter stages its closure while checked out on the
    integration branch.  Resolving the source after that branch is already an
    ancestor of ``main`` used to tear the source down without a tree-diff audit,
    so the resolver stamped the source branch (which had no queue row) and left
    the integration row's ``landed_sha`` null.  This is the real supported path:
    stage through ``backlog.py``, resolve through the CLI, then consume through
    ``backlog.py anchor``; the test never edits the queue or marker files.
    """
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json([
        "open", "--intent", "source lane", "--slug", "source-lane",
        "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_OK, opened
    source_wt = opened["path"]
    source_sha = _commit(source_wt, "source.txt", "source work\n", "ops: source work")

    integration_branch = "feat/integration-lane"
    _git(["checkout", "-q", "-b", integration_branch, "main"], repo)
    _git(["cherry-pick", source_sha], repo)
    integration_sha = _git(["rev-parse", "HEAD"], repo)

    store = repo / "docs" / "runbook" / "backlog"
    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    entry_path = store / "IMP-0001.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["resolution"] = "fixture closure"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")
    backlog_spec = importlib.util.spec_from_file_location(
        "backlog_resolve_stamp_fixture", ROOT / "ops" / "backlog.py"
    )
    assert backlog_spec and backlog_spec.loader
    backlog = importlib.util.module_from_spec(backlog_spec)
    backlog_spec.loader.exec_module(backlog)
    backlog.GIT_REPO = repo

    def run_backlog(argv):
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            rc = backlog.main(argv)
        payload = json.loads(output.getvalue()) if output.getvalue().strip() else {}
        return rc, payload, errors.getvalue()

    rc, stage, stage_err = run_backlog([
        "stage", "IMP-0001", "--store", str(store), "--queue", str(queue),
        "--verdict", "CONFIRMED-FIXED", "--by", "fixture",
        "--evidence", "pytest resolve-via-integration fixture", "--json",
    ])
    assert rc == 0, stage_err or stage
    staged = {row["id"]: row for row in _queue_rows(repo)}
    assert staged["IMP-0001"]["branch"] == integration_branch
    assert staged["IMP-0001"]["landed_sha"] is None

    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--ff-only", integration_branch], repo)
    rc, resolved = _run_json([
        "resolve", "--worktree", source_wt, "--state", state,
        "--base", "main", "--via-integration", integration_branch,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, resolved
    assert not Path(source_wt).exists()
    rows = {row["id"]: row for row in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == integration_sha, resolved

    rc, anchored, anchor_err = run_backlog([
        "anchor", "--store", str(store), "--queue", str(queue),
        "--branches", integration_branch, "--commit", "--json",
    ])
    assert rc == 0, anchor_err or anchored
    assert anchored["applied"] == ["IMP-0001"], anchored
    assert _queue_rows(repo) == [], "anchor left a null or duplicate row"
    entry = json.loads((store / "IMP-0001.json").read_text(encoding="utf-8"))
    assert entry["status"] == "fixed"
    assert entry["fixed_by"] == [integration_sha]

@gitmark
def test_integrate_dry_run_names_every_commit_and_creates_nothing(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["mode"] == "dry-run", pay
    picks = {p["branch"]: [c["sha"] for c in p["commits"]] for p in pay["plan"]}
    assert picks == {"feat/a": [a], "feat/b": [b]}, pay
    # dry-run means dry-run: no worktree, no branch, no resumable state on disk.
    assert not (Path(repo) / ".claude" / "worktrees" / "batch").exists()
    assert "feat/batch" not in _local_branches(repo)
    assert not MODULE._integrate_state_path(state, "batch").exists()

@gitmark
def test_integrate_stops_at_the_conflicting_branch_and_names_the_file(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    # NAMING the file is the whole point: "cherry-pick failed" leaves the reader
    # exactly where a bare non-zero exit would.
    assert pay["conflicts"] == ["shared.txt"], pay
    assert pay["stopped"]["branch"] == "feat/b", pay
    assert pay["stopped"]["sha"] == b1, pay
    # It stops, it does not roll back: the first branch is already applied, and the
    # commit it stopped on is still at the head of the queue with its successor.
    assert [p["branch"] for p in pay["picked"]] == ["feat/a"], pay
    assert [c["sha"] for c in pay["remaining"]] == [b1, b2], pay
    wt = pay["worktree"]
    assert MODULE._interrupted_operation(wt) == "cherry-pick"
    assert "<<<<<<<" in (Path(wt) / "shared.txt").read_text()
    assert MODULE._integrate_state_path(state, "batch").exists(), (
        "a stop with no resumable state on disk makes --continue impossible")

@gitmark
def test_integrate_continue_gates_the_integrated_head_not_a_source_branch(scratch):
    """The acceptance criterion of IMP-20260807-267d60, stated as an assertion.

    A verdict bound to any source branch's HEAD is precisely the verdict the batch
    already had before integrating, and the one that missed five defects.

    Which assertion carries which defect, measured rather than assumed (a reviewer
    caught me claiming the wrong one):
      * `head_sha == integrated` catches a payload that MISREPORTS the head, because
        `integrated` is read back off the worktree. It does NOT catch a gate that ran
        too early — the run stops early, so the HEAD read afterwards is the early one
        too and both sides move together. It is a tautology for exactly the defect
        this test is named after.
      * `changed_files` / `picked` / the commit COUNT are what catch that one: they
        are expectations written here from the fixture, not read back from the run.
    Keep all of them; just do not mistake the first for the proof."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]

    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, done = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                          "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert done["gate"]["verdict"] in ("pass", "warn"), done

    integrated = _git(["rev-parse", "HEAD"], wt)
    assert done["head_sha"] == integrated, done
    rec = json.loads(MODULE._gate_record_path(state, wt).read_text())
    assert rec["head_sha"] == integrated, rec["head_sha"]
    assert rec["head_sha"] not in (a, b1, b2), (
        "the verdict is bound to a SOURCE branch head — that is the pre-integration "
        "verdict wearing a new name")
    # Everything both branches contributed is inside the tree that was judged —
    # including feat/b's commit AFTER the conflicted one, which is what a gate fired
    # the moment the conflict settled would be missing.
    assert set(rec["changed_files"]) == {"shared.txt", "b.txt"}, rec["changed_files"]
    assert [c["sha"] for c in done["picked"]] == [a, b1, b2], done["picked"]
    assert len(_git(["rev-list", "main..HEAD"], wt).split()) == 3, (
        "the integrated tree does not hold one commit per authored commit — this "
        "expectation comes from the fixture, not from anything the run reported")
    assert (Path(wt) / "shared.txt").read_text() == "alpha\nbeta\n"

@gitmark
def test_integrate_continue_no_gate_stops_before_the_gate(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, picked = _run_integrate_json(["integrate", "--slug", "batch",
                            "--state", state, "--continue", "--commit",
                            "--no-gate", "--json"])
    assert rc == MODULE.EXIT_OK, picked
    assert picked["mode"] == "picked", picked
    assert picked["gated"] is False, picked
    assert picked["verdict"] is None, picked
    assert [c["sha"] for c in picked["picked"]] == [a, b1, b2], picked
    assert MODULE.gate_history_rows(state) == []
    assert not MODULE._gate_record_path(state, wt).exists()
    saved = json.loads(MODULE._integrate_state_path(state, "batch").read_text())
    assert saved["queue"] == []
    assert saved["gate_pending"] is True
    assert saved["phase"] == "staging"
    assert saved["next_action"] == "manager-gate"
    assert saved["authority"]["next_operator"] == "manager"
    assert picked["phase"] == "staging"
    assert picked["next_operator"] == "manager"


@gitmark
def test_non_manager_mutations_are_refused_before_primary_or_gate_work(scratch):
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "operator.json")
    rc, opened = _run_json([
        "open", "--intent", "operator guard", "--slug", "operator-guard",
        "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_OK, opened
    wt = opened["path"]
    for argv in (
        ["cutover", "--worktree", wt, "--state", state, "--operator", "integrator", "--commit", "--json"],
        ["land", "--worktree", wt, "--state", state, "--operator", "integrator", "--commit", "--json"],
        ["sync", "--state", state, "--operator", "integrator", "--commit", "--json"],
        ["deploy", "--state", state, "--operator", "integrator", "--commit", "--json"],
        ["close-wave", "--slug", "operator-guard-wave", "--state", state, "--operator", "integrator", "--commit", "--json"],
        ["resolve", "--worktree", wt, "--state", state, "--operator", "integrator",
         "--via-integration", "main", "--commit", "--json"],
    ):
        rc, payload = _run_json(argv)
        assert rc == MODULE.EXIT_BLOCK, (argv, payload)
        assert payload["refusal"] == "manager-only", (argv, payload)
    assert not MODULE._gate_record_path(state, wt).exists()
    MODULE.main([
        "resolve", "--worktree", wt, "--state", state,
        "--force", "--commit", "--json",
    ])

@gitmark
def test_integrate_continue_no_gate_then_gate_runs_alone_on_the_final_tree(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, picked = _run_integrate_json(["integrate", "--slug", "batch",
                            "--state", state, "--continue", "--commit",
                            "--no-gate", "--json"])
    assert rc == MODULE.EXIT_OK, picked
    assert picked["mode"] == "picked", picked

    rc, done = _run_integrate_json(["integrate", "--slug", "batch",
                          "--state", state, "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert done["gate"]["verdict"] in ("pass", "warn"), done
    integrated = _git(["rev-parse", "HEAD"], wt)
    rec = json.loads(MODULE._gate_record_path(state, wt).read_text())
    assert rec["head_sha"] == integrated, rec
    assert MODULE.gate_history_rows(state), "the delayed gate must write its journal"
    assert not MODULE._integrate_state_path(state, "batch").exists()

@gitmark
def test_integrate_append_fans_in_late_children_without_running_a_premature_gate(scratch):
    """A Delivery Team master may integrate children as they hand back.

    Append extends the same round state and worktree, preserves source ownership,
    and remains pick-only even when the caller forgets --no-gate. The master
    chooses when the expected child set is complete and then runs the one final
    Gate through --continue.
    """
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", a)

    rc, first = _run_json([
        "integrate", "--slug", "round", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, first
    assert first["mode"] == "picked", first
    wt = first["worktree"]
    assert MODULE.gate_history_rows(state) == []

    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")
    _seed_handoff(state, repo, "feat/b", b)
    rc, appended = _run_json([
        "integrate", "--slug", "round", "--append", "--branches", "feat/b",
        "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, appended
    assert appended["mode"] == "picked", appended
    assert appended["gated"] is False, appended
    assert appended["branches"] == ["feat/a", "feat/b"], appended
    assert [item["sha"] for item in appended["picked"]] == [a, b], appended
    assert (Path(wt) / "a.txt").read_text() == "a\n"
    assert (Path(wt) / "b.txt").read_text() == "b\n"
    saved = json.loads(MODULE._integrate_state_path(state, "round").read_text())
    assert saved["branches"] == ["feat/a", "feat/b"], saved
    assert saved["planned_total"] == 2, saved
    assert saved["queue"] == [], saved
    assert saved["gate_pending"] is True, saved
    assert MODULE.gate_history_rows(state) == []

@gitmark
def test_integrate_runs_the_gate_once_for_the_whole_batch(scratch):
    """Counted from the gate's OWN journal, not from a number integrate reports about
    itself. A per-branch implementation would report `gate_runs: 1` just as happily."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    rows = MODULE.gate_history_rows(state)
    assert [r["gate"] for r in rows] == ["coverage"], rows
    wt_key = MODULE.hashlib.sha256(
        MODULE._norm(pay["worktree"]).encode()).hexdigest()[:16]
    assert rows[0]["wt"] == wt_key, rows

@gitmark
def test_integrate_copies_commits_rather_than_merging_the_sources(scratch):
    """cherry-pick, not merge. A merge would make the source commits ancestors of the
    integrated head, which drags along whatever else those branches happened to be
    carrying — measured on the 2026-08-06 batch, two branches each carried another
    session's discarded commit.

    The trunk is advanced AFTER the branches are cut, deliberately. Without that, the
    first cherry-pick lands on the very parent the commit already had and git
    reproduces the identical sha, so `a not in shas` would be measuring the clock
    (committer dates have one-second granularity) rather than the operation. Moving
    the trunk makes a rewrite unavoidable — and it is also the real shape: branches
    are cut, then main moves under them."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")
    _advance_local_main(repo, "trunkmove")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    wt = pay["worktree"]
    shas = _git(["rev-list", "main..HEAD"], wt).split()
    assert len(shas) == 2, shas
    assert a not in shas and b not in shas, (
        "the source commits are ancestors of the integrated head — that is a merge")
    assert _git(["rev-list", "--merges", "main..HEAD"], wt).split() == []
    assert (Path(wt) / "a.txt").exists() and (Path(wt) / "b.txt").exists()
    # every commit that arrived is one the tool NAMED, source sha and new sha both
    assert {(c["sha"], c["new_sha"]) for c in pay["picked"]} == {
        (a, shas[1]), (b, shas[0])}, pay["picked"]
    # the source branches are untouched by the integration
    assert _git(["rev-parse", "feat/a"], repo) == a
    assert _git(["rev-parse", "feat/b"], repo) == b

@gitmark
def test_integrate_does_not_advance_the_trunk(scratch):
    """`integrate` gates; `cutover` lands. Keeping the two apart is what leaves the
    existing "no block verdict may land" contract as the ONE place that rule lives."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert "a.txt" not in _local_main_files(repo)
    assert "cutover" in pay["next_step"], pay

@gitmark
def test_integrate_refuses_a_second_start_while_one_is_in_flight(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, _stopped = _run_integrate_json(["integrate", "--slug", "batch",
                              "--branches", "feat/a", "feat/b",
                              "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, _stopped
    rc, again = _run_integrate_json(["integrate", "--slug", "batch",
                           "--branches", "feat/a", "feat/b",
                           "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, again
    assert "--continue" in again["error"] and "--abort" in again["error"], again
    # Not just "the message mentions its own flags" — it must be ABOUT the live
    # integration: name the worktree, and be reachable only while one is genuinely
    # in flight (see test_integrate_forgets_a_finished_integration).
    assert again["worktree"] == _stopped["worktree"], again
    assert Path(again["worktree"]).is_dir()

@gitmark
def test_integrate_continue_without_an_integration_says_which_one_is_missing(scratch):
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, pay = _run_integrate_json(["integrate", "--slug", "ghost", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert "ghost" in pay["error"], pay

@gitmark
def test_integrate_continue_refuses_while_paths_are_still_unmerged(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["conflicts"] == ["shared.txt"], pay
    # and nothing was gated over the conflicted tree
    assert not MODULE._gate_record_path(state, stopped["worktree"]).exists()

@gitmark
def test_integrate_abort_clears_the_in_flight_cherry_pick(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    rc, dry = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--abort", "--json"])
    assert rc == MODULE.EXIT_OK and dry["mode"] == "dry-run", dry
    assert MODULE._interrupted_operation(wt) == "cherry-pick", (
        "a dry-run abort aborted something")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--abort", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert MODULE._interrupted_operation(wt) is None
    assert not MODULE._integrate_state_path(state, "batch").exists()
    # The worktree itself survives: teardown is `resolve`'s job, and it is the only
    # step that consults the landed-floor.
    assert Path(wt).is_dir()
    assert "resolve" in pay["next_step"], pay

@gitmark
def test_integrate_names_a_branch_that_does_not_resolve(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/nope",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert any("feat/nope" in p for p in pay["problems"]), pay
    assert not any("feat/a" in p for p in pay["problems"]), pay

@gitmark
def test_integrate_refuses_a_branch_carrying_a_merge_commit(scratch):
    """A merge commit has no single parent to diff against, so `rev-list --no-merges`
    would drop it silently — and silently dropping a commit is the failure mode the
    whole verb exists to prevent."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/side", {"side.txt": "s\n"}, "work: side")
    _git(["checkout", "-q", "-b", "feat/m", "main"], repo)
    (Path(repo) / "m.txt").write_text("m\n")
    _git(["add", "m.txt"], repo)
    _git(["commit", "-qm", "work: m"], repo)
    _git(["merge", "--no-ff", "-q", "-m", "merge side", "feat/side"], repo)
    merge_sha = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/m",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert any(merge_sha[:8] in p for p in pay["problems"]), pay

@gitmark
def test_integrate_is_refused_while_the_flow_is_frozen(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state,
                       "--json"])
    assert rc == MODULE.EXIT_OK
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["error"] == "frozen", pay

def test_integrate_is_wired_into_the_parser():
    p = MODULE.build_parser()
    ns = p.parse_args(["integrate", "--slug", "b", "--branches", "x", "y"])
    assert ns.func is MODULE.cmd_integrate
    assert ns.branches == ["x", "y"] and ns.commit is False
    assert ns.allow_unhanded is False and ns.append is False
    cw = p.parse_args([
        "close-wave", "--slug", "wave", "--branches", "x", "--sync",
    ])
    assert cw.func is MODULE.cmd_close_wave
    assert cw.sync is True and cw.commit is False

@gitmark
def test_integrate_refuses_a_source_branch_without_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["error"] == "source branches were not handed back for integration"
    assert pay["handoff"]["problems"][0]["reason"] == "no active registry record"
    assert "hand-back" in pay["handoff"]["problems"][0]["remedy"]

@gitmark
def test_integrate_refuses_a_branch_that_advanced_after_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    current = _commit_on(repo, "feat/a", {"b.txt": "b\n"}, "work: a follow-up")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    problem = pay["handoff"]["problems"][0]
    assert problem["reason"] == "branch advanced after hand-back"
    assert problem["handed_back_sha"] == handed_back
    assert problem["current_tip_sha"] == current

    # The explicit legacy bypass only covers a missing stamp; it must not turn a
    # stale stamp into permission to integrate code that was not handed back.
    rc, allowed = _run_json(["integrate", "--slug", "batch-allowed",
                             "--branches", "feat/a", "--state", state,
                             "--allow-unhanded", "--json"])
    assert rc == MODULE.EXIT_BLOCK, allowed
    assert allowed["handoff"]["problems"][0]["reason"] == "branch advanced after hand-back"

@gitmark
def test_integrate_accepts_a_branch_whose_tip_matches_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["handoff"]["problems"] == []
    assert pay["handoff"]["warnings"] == []

@gitmark
def test_a_handed_back_branch_can_feed_only_one_live_integration(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, first = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, first
    assert first["mode"] == "picked", first

    rc, second = _run_json([
        "integrate", "--slug", "round-five", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, second
    assert second["error"] == "source branches already belong to another integration"
    conflict = second["source_claim"]["conflicts"][0]
    assert conflict["branch"] == "feat/a", conflict
    assert conflict["owner"]["branch"] == first["branch"], conflict
    assert not (Path(repo) / ".claude" / "worktrees" / "round-five").exists()

@gitmark
def test_integrate_continue_recovers_a_crash_between_state_and_source_claim(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)
    rc, picked = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, picked

    assert MODULE.wr.release_integration_sources(
        Path(state), integration_branch=picked["branch"]) == ["feat/a"]
    spath = MODULE._integrate_state_path(state, "round-four")
    saved = json.loads(spath.read_text())
    saved.pop("source_claim", None)
    spath.write_text(json.dumps(saved))

    rc, resumed = _run_json([
        "integrate", "--slug", "round-four", "--state", state,
        "--continue", "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, resumed
    records = json.loads(Path(state).read_text())["records"]
    source = next(r for r in records if r["branch"] == "feat/a")
    assert source["integration_owner"]["branch"] == picked["branch"], source

@gitmark
def test_an_integration_tree_survives_until_its_sources_are_resolved(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, integrated = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, integrated

    rc, refused = _run_json([
        "resolve", "--worktree", integrated["worktree"], "--state", state,
        "--force", "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert refused["reason_code"] == "integration-sources-active", refused
    assert refused["source_branches"] == ["feat/a"], refused
    assert Path(integrated["worktree"]).is_dir()

@gitmark
def test_two_round_integrations_converge_through_one_parent_gate_and_cutover(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    leaf_specs = {
        "feat/r4-a": {"r4-a.txt": "r4-a\n"},
        "feat/r4-b": {"r4-b.txt": "r4-b\n"},
        "feat/r5-a": {"r5-a.txt": "r5-a\n"},
        "feat/r5-b": {"r5-b.txt": "r5-b\n"},
    }
    for branch, files in leaf_specs.items():
        sha = _make_branch(repo, branch, files, f"work: {branch}")
        _seed_handoff(state, repo, branch, sha)

    rc, round4 = _run_json([
        "integrate", "--slug", "round-four", "--branches",
        "feat/r4-a", "feat/r4-b", "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, round4
    rc, round5 = _run_json([
        "integrate", "--slug", "round-five", "--branches",
        "feat/r5-a", "feat/r5-b", "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, round5

    for branch in (round4["branch"], round5["branch"]):
        rc, handoff = MODULE._registry([
            "hand-back", "--state", state, "--branch", branch, "--json",
        ])
        assert rc == MODULE.EXIT_OK, handoff

    rc, parent = _run_integrate_json([
        "integrate", "--slug", "rounds-four-five", "--branches",
        round4["branch"], round5["branch"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, parent
    assert parent["verdict"] in ("pass", "warn"), parent
    for rel, body in {k: v for files in leaf_specs.values()
                      for k, v in files.items()}.items():
        assert (Path(parent["worktree"]) / rel).read_text() == body

    rc, landed = _run_json([
        "cutover", "--worktree", parent["worktree"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK and landed["landed"] is True, landed
    assert _git(["rev-parse", "main"], repo) == parent["head_sha"]
    assert len(MODULE.gate_history_rows(state)) == 3, (
        "the two round gates and the one parent gate are the three intended "
        "integrated-tree judgements; leaf gates belong to their workers")

    # The synthetic leaves share the fixture's primary path, so close their ledger
    # records directly; real workers use orchestrator resolve and remove their own
    # distinct worktrees. Once those ownership edges are terminal, the two round
    # trees and finally the parent can be torn down in dependency order.
    for branch in leaf_specs:
        rc, closed = MODULE._registry([
            "resolve", "--state", state, "--branch", branch,
            "--status", "merged", "--json",
        ])
        assert rc == MODULE.EXIT_OK, closed
    for round_result in (round4, round5):
        rc, closed = _run_json([
            "resolve", "--worktree", round_result["worktree"], "--state", state,
            "--via-integration", "main", "--commit", "--json",
        ])
        assert rc == MODULE.EXIT_OK, closed
    rc, closed = _run_json([
        "resolve", "--worktree", parent["worktree"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, closed
    ledger = json.loads(Path(state).read_text())
    assert [r for r in ledger["records"] if r["status"] == "active"] == []

@gitmark
def test_integrate_allow_unhanded_is_explicit_and_names_the_warning(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--allow-unhanded", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["handoff"]["problems"] == []
    assert pay["handoff"]["warnings"] == [{
        "branch": "feat/a",
        "reason": "no active registry record",
        "remedy": "./ops/worktree_registry.py hand-back --branch feat/a --json",
    }]

@gitmark
def test_integrate_refuses_to_gate_a_batch_its_own_books_do_not_add_up(scratch):
    """The failure this guard exists for is invisible without it: a batch that lost
    a branch's work gates GREEN, and green is exactly what `cutover` is waiting for.

    It judges nothing about the code — every commit leaves the queue into exactly one
    of `picked`/`skipped`, so the sum is an invariant of this tool's own bookkeeping.
    Same family as cutover's `gated_sha == rebased_sha`."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    spath = MODULE._integrate_state_path(state, "batch")
    st = json.loads(spath.read_text())
    assert st["planned_total"] == 3, st
    st["queue"] = []                       # the queue empties without the work landing
    st.pop("stopped", None)
    spath.write_text(json.dumps(st))
    _git(["cherry-pick", "--abort"], wt)   # so nothing else refuses first

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["planned_total"] == 3 and pay["accounted"] == 1, pay
    assert not MODULE._gate_record_path(state, wt).exists(), (
        "a verdict was recorded for a short batch — cutover would land it on green")

@gitmark
def test_integrate_surfaces_the_gates_own_refusal_rather_than_a_null_verdict(scratch):
    """`gate` has exits that REFUSE instead of judging (mid-operation tree, wrong
    orchestrator, base moved); those payloads carry `error` and no `verdict` at all.
    Reporting that as "verdict: None — fix the blocking gate(s)" hands the reader
    advice for a different problem while the real cause sits unread in gate's own
    payload — and points at a verdict record that was never written.

    Driven through the REAL refusal rather than a stubbed gate, and through the one
    that actually happens: the trunk moving while a human resolves a conflict. That
    is not an edge case — it is why `land` exists — and `integrate` does not run
    `catchup`, so it is on the normal path for a batch."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    _advance_local_main(repo, "moved-while-you-resolved")
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc != MODULE.EXIT_OK, pay
    assert pay["mode"] == "refused", pay
    # The CAUSE has to reach the operator, and so does the remedy gate itself names.
    assert "behind" in pay["error"], pay["error"]
    assert "catchup" in pay["error"], pay["error"]
    # …and it must not claim a verdict record that was never written.
    assert "verdict" not in pay or pay.get("verdict") is None, pay
    assert not MODULE._gate_record_path(state, wt).exists()

@gitmark
def test_integrate_continue_refuses_when_the_worktree_is_on_another_branch(scratch):
    """Everything after this point — the picks, the verdict, the sha cutover lands —
    is about whatever branch is actually checked out, not the one the state file
    names."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]
    _git(["cherry-pick", "--abort"], wt)
    _git(["checkout", "-q", "-b", "sidetrack"], wt)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["actual_branch"] == "sidetrack", pay
    assert pay["expected_branch"] == stopped["branch"], pay
    assert not MODULE._gate_record_path(state, wt).exists()

@gitmark
def test_integrate_forgets_a_finished_integration(scratch):
    """A drained queue with a verdict on it is not something you can `--continue`.

    Keeping the state file made a FINISHED integration answer the next
    `integrate --slug <same>` with "already in flight … resume it with --continue
    after resolving" — false about the state, false about the remedy, and pointing
    at conflicts that do not exist. It was also residue `resolve` cannot strike,
    against a module docstring that promises none."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["state_cleared"] is True, pay
    assert not MODULE._integrate_state_path(state, "batch").exists()
    manifest = Path(pay["manifest"])
    assert manifest.is_file(), pay
    completed = json.loads(manifest.read_text())
    assert completed["status"] == "gated", completed
    assert completed["head_sha"] == pay["head_sha"], completed
    assert completed["branches"] == ["feat/a"], completed

    # …and the follow-on question the residue used to answer wrongly.
    rc, again = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                           "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, again
    # Asserted against the WRONG CLAIM, not against a phrase: the honest answer here
    # ("no integration named 'batch' is in flight") legitimately contains the words
    # "in flight", and a first draft of this test failed on exactly that. What must
    # not appear is the assertion that one is ALREADY in flight, and the instruction
    # to resume it after resolving conflicts that do not exist.
    assert "already in flight" not in again["error"], again["error"]
    assert "resolving" not in again["error"], again["error"]
    assert "start one with" in again["error"], again["error"]

@gitmark
def test_a_blocking_integrated_gate_keeps_state_for_retry_or_abort(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    (Path(repo) / "ops").mkdir()
    handed_back = _make_branch(
        repo, "feat/bad-shell", {"ops/bad-round.sh": "if then\n"},
        "ops: add invalid shell fixture",
    )
    _seed_handoff(state, repo, "feat/bad-shell", handed_back)

    rc, blocked = _run_json([
        "integrate", "--slug", "blocked-round", "--branches", "feat/bad-shell",
        "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, blocked
    assert blocked["verdict"] == "block", blocked
    assert blocked["state_cleared"] is False, blocked
    assert blocked["manifest"] is None, blocked
    saved = json.loads(
        MODULE._integrate_state_path(state, "blocked-round").read_text())
    assert saved["gate_pending"] is True, saved
    assert saved["source_claim"]["claimed"] == ["feat/bad-shell"], saved
    assert "--continue --commit" in blocked["next_step"], blocked

@gitmark
def test_integrate_refuses_stacked_branches_that_queue_a_commit_twice(scratch):
    """The mirror image of silently dropping a commit.

    `main..feat/b` contains feat/a's commits when b is stacked on a, so naming both
    queues the same commit twice; the second pick is an EMPTY cherry-pick, which
    stops the run with no unmerged paths and a message about conflict resolution —
    a diagnosis pointing away from the actual mistake."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _git(["checkout", "-q", "-b", "feat/b", "feat/a"], repo)
    (Path(repo) / "b.txt").write_text("b\n")
    _git(["add", "b.txt"], repo)
    _git(["commit", "-qm", "work: b"], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    dup = [p for p in pay["problems"] if a[:8] in p]
    assert dup, pay["problems"]
    assert "feat/a" in dup[0] and "feat/b" in dup[0], dup
    # naming only the tip is the documented way through, and it must still work
    rc, ok = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/b",
                        "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, ok
    assert [c["sha"] for c in ok["plan"][0]["commits"]][0] == a, ok

@gitmark
def test_integrate_names_a_commit_that_produced_nothing_instead_of_losing_it(scratch):
    """`skipped` is the ONLY channel through which "a commit you named is not in the
    integrated tree" reaches the operator, and it had no test at all.

    Reached the way it really happens: two branches carrying the same change, so the
    second pick is empty and `git cherry-pick --skip` is what git itself tells you to
    run (verified against git's own output, not assumed)."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"dup.txt": "same\n"}, "work: a")
    c = _make_branch(repo, "feat/c", {"dup.txt": "same\n"}, "work: c (same change)")

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/c",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    # An empty pick has NO unmerged paths — the refusal must not invent conflicts.
    assert stopped["conflicts"] == [], stopped
    assert stopped["stopped"]["sha"] == c, stopped
    assert "--skip" in stopped["error"], stopped["error"]

    wt = stopped["worktree"]
    _git(["cherry-pick", "--skip"], wt)
    rc, done = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                          "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert [x["sha"] for x in done["skipped"]] == [c], done
    assert [x["sha"] for x in done["picked"]] == [a], done
    # the books still balance, so the gate was allowed to run
    assert done["gate"]["verdict"] in ("pass", "warn"), done

"""Behavior-group collector for worktree_orchestrate (claims)."""

from worktree_orchestrate_support import *  # noqa: F401,F403

@gitmark
def test_open_refuses_a_ticket_another_worktree_already_holds(scratch):
    """And refuses with a non-zero code.

    `cmd_open` used to read the registry's return value only to pick which of two
    sentences to print, then `return EXIT_OK` unconditionally — so a caller that
    checked the exit code (which is the only thing a script or an agent's `&&`
    checks) was told the open had succeeded no matter what the ledger said.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    rc, first = _run_json(["open", "--intent", "fix it", "--slug", "first",
                           "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert first["backlog"] == ["IMP-0001"]

    rc, second = _run_json(["open", "--intent", "fix it too", "--slug", "second",
                            "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, "a losing claimant was told the open succeeded"
    assert second["step"] == "open"
    # actionable: the loser has to be able to say WHO has it without reading the ledger
    assert second["conflicts"][0]["branch"] == "debug/first"

@gitmark
def test_a_losing_claimant_is_left_with_no_worktree_and_no_branch(scratch):
    """The reason `open` had to be reordered rather than just fixed.

    With `git worktree add` running first, the loser ended up holding a real
    directory and a real branch that no ledger record pointed at — residue that
    only `sweep` would find, and only if it happened to look. Claiming first means
    the loser never reaches the part that creates anything.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _run_json(["open", "--intent", "x", "--slug", "winner",
               "--backlog", "IMP-0001", "--state", state, "--json"])

    rc, _ = _run_json(["open", "--intent", "x", "--slug", "loser",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK

    assert not (repo / ".claude" / "worktrees" / "loser").exists()
    branches = subprocess.run(["git", "branch", "--list", "feat/loser"],
                              cwd=repo, capture_output=True, text=True).stdout
    assert branches.strip() == "", f"the refused open left a branch behind: {branches!r}"
    records = json.loads(Path(state).read_text())["records"]
    assert [r["branch"] for r in records if r["status"] == "active"] == ["feat/winner"]

@gitmark
def test_open_gives_the_claim_back_when_the_worktree_cannot_be_created(scratch):
    """Claiming first buys atomicity at the cost of a new failure window.

    Between the claim and the `git worktree add` there is now a moment where the
    ledger says a ticket is held by a worktree that does not exist. If `add` fails
    the claim has to be handed back, or the ticket is stuck until a human notices
    a record whose path is not there.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # The branch already exists, so `worktree add -b` fails. Deliberately NOT
    # "occupy the path": `open` checks for an existing path before it claims, so
    # that route never reaches the window this test is about.
    _git(["branch", "feat/blocked"], repo)

    rc, payload = _run_json(["open", "--intent", "x", "--slug", "blocked",
                             "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert payload.get("claim_released") is True

    records = json.loads(Path(state).read_text())["records"]
    assert [r for r in records if r["status"] == "active"] == [], (
        "a failed open left an active record holding the ticket"
    )
    # and the ticket is immediately claimable again
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "retry",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

@gitmark
def test_open_without_a_ticket_still_works_and_claims_nothing(scratch):
    """Most opens are not backlog work; the flag is optional and stays that way."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, payload = _run_json(["open", "--intent", "poke at something", "--slug",
                             "explore", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert payload["backlog"] == []
    rec = json.loads(Path(state).read_text())["records"][0]
    assert rec["backlog"] == [] and rec["claimed_at"] is None

@gitmark
def test_open_next_backlog_claims_the_next_available_ticket_instead_of_racing_on_a_stale_list(
        scratch):
    """Two coordinators must not both read the same dispatch head and make one lose.

    The selection and the registry claim are one operation: after the first caller
    takes the worst-first head, the second caller moves to the next still-unclaimed
    entry without being handed the first id and refused.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    rc1, first = _run_json([
        "open", "--intent", "round four lane", "--slug", "round-four-01",
        "--next-backlog", "--state", state, "--json",
    ])
    rc2, second = _run_json([
        "open", "--intent", "round five lane", "--slug", "round-five-01",
        "--next-backlog", "--state", state, "--json",
    ])

    assert (rc1, rc2) == (MODULE.EXIT_OK, MODULE.EXIT_OK)
    assert first["backlog"] == ["IMP-0001"], first
    assert second["backlog"] == ["IMP-0002"], second
    assert first["selection"]["mode"] == "dispatch-head"
    assert second["selection"]["skipped_claimed"] == 1

    active = [r for r in json.loads(Path(state).read_text())["records"]
              if r["status"] == "active"]
    assert {r["backlog"][0] for r in active} == {"IMP-0001", "IMP-0002"}

def test_next_backlog_uses_its_owning_repo_for_contract_preflight(tmp_path):
    repo = tmp_path / "external-repo"
    store = repo / "docs" / "runbook" / "backlog"
    (repo / "ops").mkdir(parents=True)
    (repo / "ops" / "d4d05e_next_fix.py").write_text("# fix\n", encoding="utf-8")
    (repo / "ops" / "d4d05e_next_test.py").write_text("# test\n", encoding="utf-8")
    store.mkdir(parents=True)
    ticket = "IMP-20260810-abc123"
    (store / f"{ticket}.json").write_text(json.dumps({
        "schema": "kg.backlog.entry.v1", "id": ticket, "status": "triaged",
        "stream": "IMP", "severity": "med", "category": "tool",
        "date": "2026-08-10", "source": "test", "detail": "external next",
        "brief": "external dispatch contract", "scope": "small test-only guard",
        "plan": "run the guard", "acceptance": "red then green",
        "acceptance_cmd": "test -f ops/d4d05e_next_test.py",
        "acceptance_expect_rc": 0, "fix_site": "ops/d4d05e_next_fix.py:1",
        "groomed_at": "2026-08-10", "groomed_by": "test",
        "contract_status": "ready", "contract_baseline": "red",
        "contract_checked_at": "2026-08-10", "contract_checked_by": "test",
        "contract_evidence": "fix_site=pass; dependency=pass; baseline=RED",
    }), encoding="utf-8")
    state = str(tmp_path / "registry.json")
    worktree = repo / ".claude" / "worktrees" / "external-next"
    worktree.parent.mkdir(parents=True)

    rc, _claim, claimed, _selection = MODULE._claim_next_backlog(
        root=repo, state_arg=state, path=worktree,
        branch="feat/external-next", intent="external next", base="main",
    )

    assert rc == MODULE.EXIT_OK
    assert claimed == [ticket]

@gitmark
def test_parallel_next_backlog_claims_are_distinct_inside_the_ledger_critical_section(
        scratch):
    """Pin the lock boundary, not merely the happy sequential result."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    def take(lane):
        return MODULE._claim_next_backlog(
            root=repo, state_arg=state,
            path=repo / ".claude" / "worktrees" / lane,
            branch=f"feat/{lane}", intent=lane, base="main",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(take, ["r4-1", "r4-2", "r5-1", "r5-2"]))

    assert [r[0] for r in results] == [MODULE.EXIT_OK] * 4
    claimed = [r[2][0] for r in results]
    assert len(set(claimed)) == 4, claimed
    records = [r for r in json.loads(Path(state).read_text())["records"]
               if r["status"] == "active"]
    assert len(records) == 4
    assert len({ticket for r in records for ticket in r["backlog"]}) == 4

@gitmark
def test_adopting_a_live_worktree_does_not_quietly_release_its_ticket(scratch):
    """The invariant this whole change adds, broken by the change itself.

    `open`/`adopt` used to forward `--backlog` unconditionally. With no ids the argv
    is `["--backlog", "--json"]`, and argparse's nargs="*" resolves that to `[]` —
    not None — which is the "replace the claim" branch. So the registry's
    "omit = leave it alone" rule was unreachable through the only two callers that
    exist, and the registry test pinning it was pinning dead semantics.

    Measured end to end before the fix: a LIVE worktree holding IMP-0001, a plain
    `adopt` elsewhere, and the ledger came back `backlog: []`, `claimed_at: None` —
    with a second agent able to take the ticket while the first was still working.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, live = _run_json(["open", "--intent", "x", "--slug", "live",
                          "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    # Re-registering THIS worktree with no --backlog. `adopt` is the reachable way
    # to do that (`open` refuses an existing path), and re-adopting a live worktree
    # is ordinary: it is the bootstrap path and it is idempotent by design.
    #
    # It has to be the SAME record. An earlier version of this test adopted an
    # unrelated second worktree and passed against the bug, because the empty list
    # overwrites the claim of the record being registered — so wiping the unrelated
    # record's (already empty) claim changed nothing and proved nothing.
    rc, _ = _run_json(["adopt", "--worktree", live["path"], "--intent", "x",
                       "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    records = json.loads(Path(state).read_text())["records"]
    held = {r["branch"]: r.get("backlog") for r in records if r["status"] == "active"}
    assert held.get("feat/live") == ["IMP-0001"], (
        f"the live worktree's claim was released by an unrelated adopt: {held}"
    )
    # and the ticket is still not available to anyone else
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "thief",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK

@gitmark
def test_when_the_claim_cannot_be_handed_back_open_says_what_to_run(scratch):
    """The failure path of the failure path.

    `open` releases the claim when `git worktree add` fails. If THAT release also
    fails the ticket is stuck, and the only thing standing between the operator and
    a ledger read is this message — which had no test, so nothing checked that it
    named a command that exists.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["branch", "feat/stuck"], repo)   # makes `worktree add -b` fail

    real = MODULE._registry
    calls = []

    def only_the_release_fails(argv):
        calls.append(argv[0])
        if argv[0] == "resolve":
            return MODULE.EXIT_USAGE, None
        return real(argv)

    MODULE._registry = only_the_release_fails
    try:
        rc, payload = _run_json(["open", "--intent", "x", "--slug", "stuck",
                                 "--backlog", "IMP-0001", "--state", state, "--json"])
    finally:
        MODULE._registry = real

    assert rc == MODULE.EXIT_BLOCK
    assert calls == ["register", "resolve"]
    assert payload["claim_released"] is False
    # the ticket really is still held — the payload is not being optimistic
    records = json.loads(Path(state).read_text())["records"]
    assert [r["backlog"] for r in records if r["status"] == "active"] == [["IMP-0001"]]

@gitmark
def test_a_refused_adopt_tells_the_operator_who_holds_the_ticket(scratch):
    """The human channel, which is the one a person actually reads.

    `_registry` is called with --json, so the registry's own "already claimed by
    [...]" line goes out as JSON and never reaches the terminal. `open` rebuilds
    that sentence; `adopt` printed a bare "register failed", which tells a losing
    agent nothing it can act on.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "holder",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    other = Path(repo) / ".claude" / "worktrees" / "contender"
    _git(["worktree", "add", "-b", "feat/contender", str(other), "main"], repo)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["adopt", "--worktree", str(other), "--intent", "same work",
                          "--backlog", "IMP-0001", "--state", state])
    human = buf.getvalue()
    assert rc == MODULE.EXIT_BLOCK
    assert "IMP-0001" in human and "feat/holder" in human, (
        f"the refusal names neither the ticket nor its holder:\n{human}"
    )

def test_a_groomed_open_ticket_is_claimable(tmp_path):
    store = _ticket(tmp_path, "IMP-20260808-aaaaaa", **GROOMED)
    assert MODULE._unclaimable(store, ["IMP-20260808-aaaaaa"]) == []

def test_claim_preflight_registry_probe_failure_is_fail_closed(tmp_path, monkeypatch):
    store = _ticket(tmp_path, "IMP-20260811-probe-fail", **GROOMED)

    def unreadable(_repo, **_kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(MODULE, "_active_worktree_files", unreadable)
    problems = MODULE._unclaimable(store, ["IMP-20260811-probe-fail"])
    assert [problem["kind"] for problem in problems] == ["preflight-read-failed"]

def test_pre_dispatch_refuses_missing_contract_evidence(tmp_path):
    """The claim boundary and backlog dispatch use the same contract guard."""
    store = _ticket(tmp_path, "IMP-20260810-contract", **{
        **GROOMED,
        "groomed_at": "2026-08-10",
    })
    problems = MODULE._unclaimable(store, ["IMP-20260810-contract"])
    assert [p["kind"] for p in problems] == ["contract-blocked"], problems
    assert any(p["kind"] == "contract-evidence-missing"
               for p in problems[0]["contract_problems"])

def test_an_explicit_claim_cannot_walk_around_dispatch_blocking_edges(tmp_path):
    blocker = "IMP-20260808-aaaaaa"
    blocked = "IMP-20260808-bbbbbb"
    store = _ticket(tmp_path, blocker, **GROOMED)
    _ticket(tmp_path, blocked, blocked_by=[blocker], **GROOMED)

    problems = MODULE._unclaimable(store, [blocked])

    assert [p["kind"] for p in problems] == ["blocked-by-unresolved"], problems
    assert problems[0]["blockers"] == [blocker]

def test_claiming_a_ticket_that_is_not_in_the_store_is_refused(tmp_path):
    """A typo used to claim a ticket that does not exist, and the ledger then held
    an id nobody could ever close."""
    store = _ticket(tmp_path, "IMP-20260808-aaaaaa", **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-typo0"])
    assert [p["kind"] for p in problems] == ["not-in-store"], problems
    assert problems[0]["id"] == "IMP-20260808-typo0"

def test_claiming_an_ungroomed_ticket_is_refused_and_names_the_repair(tmp_path):
    store = _ticket(tmp_path, "IMP-20260808-bbbbbb")     # no groom fields at all
    problems = MODULE._unclaimable(store, ["IMP-20260808-bbbbbb"])
    assert [p["kind"] for p in problems] == ["ungroomed"], problems
    assert "backlog.py update" in problems[0]["repair"], problems[0]
    assert "--allow-ungroomed" in problems[0]["repair"], (
        "the refusal has to name its own escape hatch, or the only way past it is "
        "to stop using the flag")
    # The flag list is the whole value of this hint, and it is hand-copied from
    # what `validate` demands — so it drifts silently. It already did: `--brief`
    # and `--scope` joined the groom requirement and this string kept teaching the
    # old command, which is worse than no hint at all because the agent believes
    # it followed the tool. Asserted per flag rather than as one blob so the
    # failure names which one went missing.
    # Asserted over the BACKTICKED COMMAND, not the whole repair string, and with
    # a word boundary. Both narrowings are load-bearing, and both were found by
    # mutation rather than reasoning:
    #   * the string also carries prose explaining --brief/--scope, so `"--brief"
    #     in repair` stayed green with the flags deleted from the command — the
    #     hint then taught a command `update` refuses with exit 64, which is the
    #     precise failure this assertion exists to catch.
    #   * `--acceptance` is a PREFIX of `--acceptance-cmd`, so a plain substring
    #     test is satisfied by a different flag that happens to start the same way.
    backticked = re.search(r"`([^`]+)`", problems[0]["repair"])
    # Named, not an IndexError from `.split("`")[1]`: the guard held either way,
    # but a failure that says "list index out of range" makes the reader debug
    # the test instead of reading the finding.
    assert backticked, (
        f"the repair hint no longer contains a backticked command:\n"
        f"  {problems[0]['repair']}")
    command = backticked.group(1)
    for flag in ("--plan", "--acceptance", "--fix-site", "--acceptance-cmd",
                 "--brief", "--scope", "--groomed-at", "--groomed-by"):
        assert re.search(rf"{re.escape(flag)}(?=[\s=]|$)", command), (
            f"the repair hint's command stopped naming {flag}; following it now "
            f"produces a command `backlog.py update` will refuse:\n  {command}")
    assert "structured JSON file claim" in problems[0]["repair"]
    assert "files[]" in problems[0]["repair"]
    assert "add|modify" in problems[0]["repair"]

def test_the_ungroomed_refusal_also_offers_a_ticket_that_needs_no_grooming(tmp_path):
    """Two different needs, so two exits — and the second one used to be missing.

    Everything else in this refusal answers "I need THIS ticket" by handing back a
    grooming chore. But the usual way to arrive here is picking an id off a list that
    does not distinguish claimable from not, and that caller wanted A ticket, not
    this one. Until the second exit was named, the only way to find it was to already
    know the command exists — which is the definition of a hint that is not one."""
    store = _ticket(tmp_path, "IMP-20260808-999999")     # no groom fields at all
    repair = MODULE._unclaimable(store, ["IMP-20260808-999999"])[0]["repair"]
    # The COMMAND, not the bare word: "dispatch" appears in ordinary prose about
    # handing out work, so a substring test on the word alone would be satisfied by
    # a sentence that names no way to run anything.
    assert "backlog.py dispatch" in repair, repair
    # …and it has to say what that command is FOR, or it reads as a third grooming
    # step rather than the way out of grooming.
    assert re.search(r"unclaimed|claimable|take right now", repair), repair
    # It must not have DISPLACED the grooming route: that is still the right answer
    # for the caller who really did need this particular ticket.
    assert "backlog.py update" in repair and "--allow-ungroomed" in repair, repair

def test_the_claim_gate_only_names_backlog_py_and_never_runs_it():
    """`_unclaimable` runs on the claim path, BEFORE any worktree exists, and the
    bootstrap case requires the orchestrator to work when the rest of the toolchain
    does not (its own docstring says so, and that is why it parses the store's JSON
    by hand rather than shelling out to `backlog.py list --json`).

    The repair hints name `backlog.py` subcommands, which makes "just call it" a
    standing temptation — and a subcommand named in a hint may not even exist on the
    branch being run, so calling one would turn a refusal into a crash. Naming is
    free; invoking is a dependency."""
    import inspect
    src = inspect.getsource(MODULE._unclaimable)
    for forbidden in ("subprocess", "run_streamed_command", "_tool_mutation",
                      "_git_mutation", "import backlog"):
        assert forbidden not in src, (
            f"_unclaimable now reaches for {forbidden!r} — it must only READ the "
            f"store's JSON; the hints name other tools, they do not run them")

def test_claiming_an_already_resolved_ticket_is_refused(tmp_path):
    """Work that is already done is the other way to waste an agent, and it reads
    exactly like a fresh ticket from the id alone."""
    store = _ticket(tmp_path, "IMP-20260808-cccccc", status="fixed",
                    fixed_by=["abc1234"], **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-cccccc"])
    assert [p["kind"] for p in problems] == ["already-resolved"], problems

def test_every_unclaimable_ticket_is_named_not_just_the_first(tmp_path):
    """A batch claim that reports one problem sends the caller round the loop N
    times. Same reason `anchor` reports the whole wave."""
    store = _ticket(tmp_path, "IMP-20260808-dddddd")
    _ticket(tmp_path, "IMP-20260808-eeeeee", status="wont-fix",
            resolution="decided against", **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-dddddd", "IMP-20260808-eeeeee",
                                        "IMP-20260808-ffffff"])
    assert sorted(p["kind"] for p in problems) == [
        "already-resolved", "not-in-store", "ungroomed"], problems

def test_an_unreadable_store_does_not_silently_permit_the_claim(tmp_path):
    """`could not check` must not become `fine`. The store directory not existing
    is the shape a fresh clone or a wrong --state has."""
    problems = MODULE._unclaimable(tmp_path / "no-such-store", ["IMP-20260808-aaaaaa"])
    assert [p["kind"] for p in problems] == ["not-in-store"], problems

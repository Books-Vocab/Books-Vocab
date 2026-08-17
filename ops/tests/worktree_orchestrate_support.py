"""Tests for ops/worktree_orchestrate.py — the P3 worktree orchestrator primitive.

Two tiers, mirroring the rest of ops/tests:

  1. PURE layer (no git, no IO): intent→branch-type classification and the
     impact→gate mapping (`plan_gates`). The gate mapping is the one real piece of
     judgement the orchestrator owns; it is asserted here as a contract so the set
     of gates selected for a given changed-file list can never silently drift. It
     never actually runs an iOS build.
  2. INTEGRATION (git-backed scratch repo): the full birth→cutover→resolve loop —
     open (worktree add off LOCAL main + registry register) → a mock work commit →
     gate (verdict pass; no impact gates for a neutral file) → cutover (rebase onto
     local main + ff the primary's LOCAL main, offline) → resolve (worktree remove +
     branch -D + ledger closure). Asserts the worktree is gone, the branch is gone,
     LOCAL main advanced (origin untouched — that is the separate deploy), and the
     ledger record reads merged — i.e. NO residue.

git-backed tests opt-skip if git is absent.
"""

from __future__ import annotations

import importlib.util

import argparse

import ast

import errno

import io

import json

import os

import re

import shutil

import subprocess

import sys

import textwrap

import time

from concurrent.futures import ThreadPoolExecutor

from contextlib import contextmanager, redirect_stderr, redirect_stdout

from datetime import datetime, timezone

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SPEC = importlib.util.spec_from_file_location(
    "worktree_orchestrate", ROOT / "ops" / "worktree_orchestrate.py"
)

assert SPEC and SPEC.loader

MODULE = importlib.util.module_from_spec(SPEC)

sys.modules[SPEC.name] = MODULE

SPEC.loader.exec_module(MODULE)

classify_intent = MODULE.classify_intent

branch_for = MODULE.branch_for

plan_gates = MODULE.plan_gates

aggregate_verdict = MODULE.aggregate_verdict

DISPATCH_SPEC = importlib.util.spec_from_file_location(
    "dispatch_preflight", ROOT / "ops" / "lib" / "dispatch_preflight.py"
)

assert DISPATCH_SPEC and DISPATCH_SPEC.loader

DISPATCH = importlib.util.module_from_spec(DISPATCH_SPEC)

sys.modules[DISPATCH_SPEC.name] = DISPATCH

DISPATCH_SPEC.loader.exec_module(DISPATCH)

def _names(gates):
    return {g["name"] for g in gates}

def _by_name(gates):
    return {g["name"]: g for g in gates}

def _dispatch_payload(**overrides):
    payload = {
        "id": "IMP-20260811-fixture",
        "status": "triaged",
        "fix_site": "ops/backlog.py; ops/tests/test_backlog.py",
        "acceptance_cmd": "uv run --no-project --python 3.13 --with pytest pytest -q ops/tests/test_backlog.py",
        "blocked_by": [],
    }
    payload.update(overrides)
    return payload

gitmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

def _normalise_fixture_ref(token):
    """Return a comparable branch name for a push refspec destination."""
    token = token.strip().lstrip("+")
    if ":" in token:
        token = token.rsplit(":", 1)[1]
    while True:
        for prefix in ("refs/remotes/", "refs/heads/", "origin/"):
            if token.startswith(prefix):
                token = token[len(prefix):]
                break
        else:
            return token.rsplit("/", 1)[-1]

def _is_production_ref(token):
    return _normalise_fixture_ref(token) == "prod"

def _is_network_target(token):
    lowered = token.lower()
    return (
        lowered.startswith("//")
        or lowered.startswith("ext::")
        or bool(re.match(r"^[a-z][a-z0-9+.-]*://", lowered))
        or (":" in token and not token.startswith(("/", "./", "../"))
            and not re.match(r"^[A-Za-z]:[\\/].*$", token))
    )

def _fixture_remote_urls(cwd):
    """Read configured remote URLs without invoking a process or network."""
    root = Path(cwd)
    marker = root / ".git"
    candidates = [root / "config"]
    if marker.is_dir():
        candidates.append(marker / "config")
    elif marker.is_file():
        try:
            gitdir_line = next(
                line for line in marker.read_text(encoding="utf-8").splitlines()
                if line.startswith("gitdir:")
            )
            gitdir = Path(gitdir_line.partition(":")[2].strip()).expanduser()
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            candidates.extend((gitdir / "config", gitdir.parent.parent / "config"))
        except (OSError, StopIteration, UnicodeError):
            pass
    urls = []
    for config in candidates:
        try:
            lines = config.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            if line.lstrip().startswith("[include"):
                urls.append("unresolved-config-include://fixture")
                break
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"url", "pushurl"}:
                urls.append(value.strip())
    return urls

def _assert_fixture_git_safe(args, cwd):
    """Keep scratch fixtures off production refs and network-capable remotes."""
    command = args[:1]
    network_commands = {"clone", "fetch", "ls-remote", "pull", "push", "remote", "submodule"}
    if command and command[0] not in network_commands:
        network_tokens = []
    else:
        tokens = list(enumerate(args[1:], start=1))
        if command == ["push"]:
            repository = next((index for index, token in tokens if not token.startswith("-")), None)
            network_tokens = [
                token for index, token in tokens
                if not (repository is not None and index > repository and ":" in token)
            ]
        else:
            network_tokens = [token for _, token in tokens]
    if command and command[0] in network_commands and (
        any(_is_network_target(token) for token in network_tokens)
        or any(_is_network_target(url) for url in _fixture_remote_urls(cwd))
    ):
        raise AssertionError("fixture git helper refuses network-capable remote")
    if command == ["push"] and any(token in {"--all", "--mirror"} for token in args[1:]):
        raise AssertionError("fixture git helper refuses implicit production ref push")
    if command == ["push"] and any(_is_production_ref(token) for token in args[1:]):
        raise AssertionError("fixture git helper refuses production ref push")

def _git(args, cwd):
    _assert_fixture_git_safe(args, cwd)
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()

def _local_branches(repo):
    return set(_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo).split())

def _origin_main_files(remote):
    # list files in the tip tree of origin's main
    out = _git(["ls-tree", "-r", "--name-only", "main"], remote)
    return set(out.splitlines())

def _origin_prod_files(remote):
    # list files in the tip tree of origin's prod (the release-plane ref deploy advances)
    out = _git(["ls-tree", "-r", "--name-only", "prod"], remote)
    return set(out.splitlines())

def _local_main_files(repo):
    # local-centric: cutover advances the PRIMARY's local main (origin is untouched
    # until a separate deploy). Assert against the local trunk's tip tree.
    out = _git(["ls-tree", "-r", "--name-only", "main"], repo)
    return set(out.splitlines())

SHELL_SCAN = ROOT / "ops" / "shell_scan.sh"

def _scan_fixture(tmp_path, name, offending=None):
    """A tracked tree the scanner can be pointed at.

    Twelve filler scripts because the scanner refuses to trust a run that saw
    suspiciously few files — a floor that exists so a broken probe cannot report
    "clean". Satisfying it is right; switching it off for the test would delete the
    property from exactly the place that checks the scanner.
    """
    repo = tmp_path / name
    (repo / "ops").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    for i in range(12):
        (repo / "ops" / f"filler{i}.sh").write_text(
            f'var=x\necho "filler {i}"\necho "safe ${{var}}，braced"\n',
            encoding="utf-8")
    if offending is not None:
        (repo / "ops" / "offender.sh").write_text(offending, encoding="utf-8")
    _git(["add", "-A"], repo)
    return repo

@pytest.fixture
def scratch(tmp_path):
    """A repo with a bare origin, main pushed. Chdir into the repo (the orchestrator
    derives repo_root + registry state from cwd's git context)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    (repo / "f").write_text("base\n")
    # A real, groomed, open ticket for the claim tests to take. Before the claim
    # gate existed these tests claimed `IMP-0001` out of thin air, which is exactly
    # the hole the gate closes — a claim on an id that is in no store. Seeding it
    # makes the fixture agree with the world the tests describe ("another worktree
    # already holds this TICKET").
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    def _seed(entry_id, **over):
        payload = {
            "schema": "kg.backlog.entry.v1", "id": entry_id, "status": "open",
            "stream": "IMP", "severity": "med", "category": "tool",
            "date": "2026-08-08", "source": "fixture",
            "detail": f"a ticket the claim tests can take ({entry_id})",
            "plan": "do the thing", "acceptance": "red then green",
            "fix_site": "ops/x.py:1", "acceptance_cmd": "true",
            "acceptance_expect_rc": 0, "groomed_at": "2026-08-08",
            "groomed_by": "fixture"}
        payload.update(over)
        (store / f"{entry_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    # Every id the claim tests reach for. They are groomed and open because the
    # claim gate now requires both — which is the world those tests already
    # describe in prose ("another worktree already holds this TICKET").
    for _id in ("IMP-0002", "IMP-0007", "IMP-0100", "IMP-0101"):
        _seed(_id)
    (store / "IMP-0001.json").write_text(json.dumps({
        "schema": "kg.backlog.entry.v1", "id": "IMP-0001", "status": "open",
        "stream": "IMP", "severity": "med", "category": "tool", "date": "2026-08-08",
        "source": "fixture", "detail": "a ticket the claim tests can take",
        "plan": "do the thing", "acceptance": "red then green",
        "fix_site": "ops/x.py:1", "acceptance_cmd": "true", "acceptance_expect_rc": 0,
        "groomed_at": "2026-08-08", "groomed_by": "fixture",
    }), encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)

    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)
    # seed origin/prod = origin/main (the release-plane ref deploy advances); the
    # switchover seeds it once, then only `deploy` moves it. Without it, deploy's noop
    # baseline is absent.
    _git(["update-ref", "refs/heads/prod", "main"], remote)

    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield tmp_path, repo, remote
    finally:
        os.chdir(prev)

def _run_json(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(argv)
    text = buf.getvalue()
    payload = json.loads(text) if text.strip() else {}
    return rc, payload

def _advance_local_main(repo, name):
    """Add a commit to LOCAL main that origin does not have (origin is never pushed).

    Stages the one file BY NAME, not `add -A`: worktrees live under the primary's own
    `.claude/worktrees/`, and `add -A` in the primary commits each of them to main as a
    gitlink. That artifact is invisible to assertions about the trunk's own files, but
    it shows up verbatim in any measurement of what the base gained since a fork.
    """
    (repo / f"{name}.txt").write_text("local-only\n")
    _git(["add", f"{name}.txt"], repo)
    _git(["commit", "-qm", f"local: {name}"], repo)

def _cripple_worktree(wt):
    """Reproduce the observed partial teardown (IMP-20260806-1359bd step 1).

    `git worktree remove --force` unlinks the worktree's `.git` file EARLY, then
    spends however long it takes to rm the tree itself (19 GB of iOS DerivedData in
    the incident). Interrupted in that window — a caller timeout — the directory
    survives with no `.git`, and git marks the entry `prunable`."""
    (Path(wt) / ".git").unlink()

def _landed_worktree(tmp_path, repo, state, slug):
    """open -> work -> gate -> cutover: a worktree whose branch IS landed, i.e. one
    that resolve's landed-floor will happily wave through to teardown."""
    rc, opened = _run_json(["open", "--intent", f"fix {slug}", "--slug", slug,
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    return wt, opened["branch"]

def _targets_a_protected_branch(payload, base="main"):
    """Any planned OR executed git step in a resolve payload that would delete the
    base branch, locally or on the remote."""
    steps = list(payload.get("plan") or []) + list(payload.get("executed") or [])
    bad = {f"git branch -D {base}", f"git push origin --delete {base}"}
    return [s["cmd"] for s in steps if s.get("cmd") in bad]

def _advance_origin_main(tmp_path, repo, name, base="main"):
    """Move origin/main one commit ahead WITHOUT touching the primary's main."""
    wt = tmp_path / f"adv-{name}"
    _git(["worktree", "add", "-b", f"adv-{name}", str(wt), base], repo)
    (wt / f"{name}.txt").write_text("advance\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", f"advance: {name}"], wt)
    _git(["push", "-q", "origin", f"adv-{name}:main"], wt)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

def _run_text(argv):
    """Run the CLI in HUMAN mode and return (rc, stdout). The text report is a
    first-class surface: a field that exists only in --json is invisible to the agent
    reading the terminal."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(argv)
    return rc, buf.getvalue()

def _open_wt(state, slug="prov"):
    rc, opened = _run_json(["open", "--intent", "add a thing", "--slug", slug,
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    return wt

def _plant_orchestrator(wt, body: str | None = None):
    """Give the scratch worktree its own copy of the orchestrator. `body=None` plants a
    byte-identical copy (the common case: the branch did not touch the tool)."""
    dst = Path(wt) / "ops" / "worktree_orchestrate.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        shutil.copyfile(Path(MODULE.__file__).resolve(), dst)
    else:
        dst.write_text(body)
    return dst

def _seed_python_scan(repo):
    """Seed the scanner in a scratch base so a Python diff can exercise its gate."""
    src = Path(MODULE.__file__).resolve().with_name("python_scan.py")
    dst = Path(repo) / "ops" / "python_scan.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(dst.stat().st_mode | 0o111)
    for index in range(50):
        (dst.parent / f"scan_fixture_{index:02d}.py").write_text(
            f"value_{index} = {index}\n", encoding="utf-8"
        )
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "seed python scanner"], repo)
    _git(["push", "-q", "origin", "main"], repo)
    _git(["fetch", "-q", "origin", "main"], repo)

def _history_lines(state):
    p = MODULE._gate_history_path(state)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]

def _with_canonical_ticket_id(payload):
    ticket_id = MODULE.backlog_tool.make_entry_id(**{
        field: payload[field] for field in MODULE.backlog_tool.DIGEST_FIELDS
    })
    return ticket_id, {**payload, "id": ticket_id}

def _write_history(state, rows):
    p = MODULE._gate_history_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))

def _row(base_name, status, head8, level="block", wt="0" * 16, gate=None):
    return {"ts": "2026-08-03T00:00:00Z", "gate": gate or base_name,
            "base_name": base_name, "status": status, "rc": 1, "level": level,
            "head8": head8, "orch8": "abcdef01", "wt": wt}

def _diagnosis(summary: str) -> str:
    """The clause after the em dash — the ONLY part of a spawn-failure summary derived
    from the exception. Everything before it is echoed from the spec, so asserting
    `"<path>" in summary` proves nothing about what the OS actually reported: a mutant
    that reports the command where the missing directory belongs still contains the
    directory, in the `cwd=` segment."""
    head, sep, tail = summary.partition("—")
    assert sep, f"summary has no diagnosis clause: {summary}"
    return tail.strip()

def _gate_from_script(tmp_path, body, name="noisy-gate"):
    tool = tmp_path / "ops" / "noisy.sh"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    tool.chmod(0o755)
    return MODULE._shell(name, "ops", ["ops/noisy.sh"], "block")

def _log_pointer(summary):
    """The path the summary tells an operator to open, read back the way one would."""
    for line in summary.splitlines():
        if line.strip().startswith("full output:"):
            return Path(line.split("full output:", 1)[1].strip())
    raise AssertionError(f"summary names no output log:\n{summary}")

LEDGER_VIEW_REL = "docs/runbook/improvement_backlog.md"

def _install_ledger_stub(repo: Path, marker: Path, *, fail: str = "",
                         probe_lock: bool = False, render_noop: bool = False,
                         doc_reanchor: bool = False,
                         fail_with_doc_plan: bool = False) -> None:
    """A stand-in for ops/backlog.py that records HOW it was called and behaves like
    the real generator: `render` rebuilds the view from the entry files, `--check`
    compares, `reanchor` rewrites an anchor field.

    The ledger half (does `reanchor` actually re-point an orphaned sha) is already
    witnessed by ops/tests/test_backlog.py; what is unwitnessed here is the
    orchestrator's side of the contract — which subcommands, with which flags, in
    which order, from which directory, and under which lock.

    Each invocation appends `<cwd>\t<argv...>` to `marker`, so a test can assert all
    four. `fail` names a subcommand that should exit 2 (the real `render`'s
    entry-loss refusal is an exit 2, not a crash). `probe_lock` makes the stub try
    the trunk lock non-blockingly and record whether it was already held.
    """
    (repo / "ops").mkdir(exist_ok=True)
    (repo / "docs" / "runbook" / "backlog").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text(
        "anchor=old\n", encoding="utf-8")
    if doc_reanchor or fail_with_doc_plan:
        (repo / "docs" / "reference").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "reference" / "E.md").write_text(
            "verified_against: old\n", encoding="utf-8")
    (repo / LEDGER_VIEW_REL).write_text("stale\n", encoding="utf-8")
    stub = repo / "ops" / "backlog.py"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import sys, pathlib, importlib.util, json
        # Anchored on THIS FILE, exactly like the real tool's ROOT. Hard-coding the
        # primary's path here made the worktree's copy read and write the primary's
        # store, so the branch never diverged and the conflict fixture quietly
        # stopped reproducing the thing it was named after.
        repo = pathlib.Path(__file__).resolve().parents[1]
        store = repo / "docs" / "runbook" / "backlog"
        view = repo / {LEDGER_VIEW_REL!r}
        note = ""
        if {probe_lock!r}:
            # Ask the same two functions the orchestrator uses, rather than
            # re-deriving the lock path here. The hand-copied version of this probe
            # watched `.cache/kg-main-advance` while the code locks
            # `.cache/kg-main-advance.lock`, so it reported FREE unconditionally —
            # a green light wired to nothing.
            def _load(name, path):
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                return mod
            _wr = _load("wr_probe", {str(ROOT / "ops" / "worktree_registry.py")!r})
            free = _wr._try_acquire_ledger_lock_nb(repo / ".cache" / "kg-main-advance")
            note = "\\ttrunk-lock=" + ("FREE" if free else "HELD")
        m = pathlib.Path({str(marker)!r})
        line = str(pathlib.Path.cwd()) + "\\t" + " ".join(sys.argv[1:]) + note + "\\n"
        m.write_text((m.read_text() if m.exists() else "") + line)
        sub = sys.argv[1]
        if sub == {fail!r}:
            if {fail_with_doc_plan!r} and "--json" in sys.argv:
                doc = repo / "docs" / "reference" / "E.md"
                doc.write_text("verified_against: new\\n")
                print(json.dumps({{"ok": False, "doc_paths": [
                    "docs/reference/E.md"
                ]}}))
            print("REFUSED: stub was told to refuse", file=sys.stderr)
            sys.exit(2)
        expected = "".join(sorted(p.read_text() for p in store.glob("*.json")))
        if sub == "reanchor" and "--commit" in sys.argv:
            for p in sorted(store.glob("*.json")):
                p.write_text(p.read_text().replace("anchor=old", "anchor=new"))
            if {doc_reanchor!r}:
                doc = repo / "docs" / "reference" / "E.md"
                doc.write_text("verified_against: new\\n")
            if "--json" in sys.argv:
                print(json.dumps({{"doc_plan": ([{{"path": "docs/reference/E.md", "old": "old", "new": "new"}}] if {doc_reanchor!r} else []), "doc_unmatched": [], "doc_landed": (["docs/reference/E.md"] if {doc_reanchor!r} else [])}}))
        elif sub == "render" and "--check" in sys.argv:
            sys.exit(0 if view.read_text() == expected else 1)
        elif sub == "render" and "--commit" in sys.argv:
            if not {render_noop!r}:
                view.write_text(expected)
        """), encoding="utf-8")
    stub.chmod(0o755)
    # Touching docs/** routes the docs gates; this scratch repo has no real ones and
    # a `block` verdict would stop the cutover before the rebase this test is about.
    lint = repo / "ops" / "docs_lint.sh"
    lint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lint.chmod(0o755)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "install ledger stub"], repo)

def _stub_repo_commit(repo: Path, msg: str) -> None:
    subprocess.run([sys.executable, str(repo / "ops" / "backlog.py"), "render",
                    "--commit"], cwd=str(repo), check=True, capture_output=True)
    _git(["add", "--", "docs/runbook"], repo)
    _git(["commit", "-qm", msg], repo)

def _seed_neighbouring_rows(repo: Path) -> None:
    """Rows that sort either side of what the branch and the trunk are about to add.

    Without them both sides append at end-of-file and git merges the two appends
    without complaint — the fixture would silently stop testing anything. With them,
    both sides insert a line into the SAME gap, which is the collision the real
    ledger produces once its rows are content-hash-scattered.
    """
    (repo / "docs" / "runbook" / "backlog" / "A.json").write_text("aaa\n")
    (repo / "docs" / "runbook" / "backlog" / "Z.json").write_text("zzz\n")

def _diverge_on_the_generated_view(repo: Path, wt: Path, *, also: str = "") -> None:
    """Branch and trunk each file an entry, so both rewrite the generated view at the
    same place — the shape that conflicts. `also` additionally puts a real (ungenerated)
    conflict in `f`."""
    (wt / "docs" / "runbook" / "backlog" / "E2.json").write_text("e2\n")
    if also:
        (wt / "f").write_text("branch edit\n")
        _git(["add", "--", "f"], wt)
    _stub_repo_commit(wt, "branch files E2")
    (repo / "docs" / "runbook" / "backlog" / "E3.json").write_text("e3\n")
    if also:
        (repo / "f").write_text("trunk edit\n")
        _git(["add", "--", "f"], repo)
    _stub_repo_commit(repo, "trunk files E3")

def _queue_rows(primary) -> list[dict]:
    q = Path(primary) / ".cache" / "backlog_anchor_queue.jsonl"
    if not q.exists():
        return []
    return [json.loads(ln) for ln in q.read_text(encoding="utf-8").splitlines() if ln.strip()]

def _stage_row(primary, branch: str, entry_id: str) -> None:
    """What `backlog.py stage` leaves behind, written directly.

    Direct rather than by driving backlog.py: this test is about what CUTOVER does
    to a queue, and shelling out to the real stager would make it depend on a store
    fixture and on backlog.py's own validation staying green.
    """
    q = Path(primary) / ".cache" / "backlog_anchor_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    with q.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": entry_id, "verdict": "CONFIRMED-FIXED", "by": "t",
                             "evidence": "ran it", "status": "fixed", "at": "2026-08-07",
                             "branch": branch, "landed_sha": None}) + "\n")

def _land_stub(name, rc=0, payload=None, boom=None):
    """A stand-in for cmd_catchup / cmd_gate / cmd_cutover.

    It must print its JSON to stdout, because that is the contract `_land_step`
    reads it through; a stub that merely returns a dict would test a code path
    that does not exist.
    """
    def run(_args, _n=name):
        _land_stub.calls.append(_n)
        if boom is not None:
            raise boom
        print(json.dumps(payload if payload is not None else {}))
        return rc
    return run

def _land_harness(monkeypatch, tmp_path, catchup=None, gate=None, cutover=None,
                  ff_ready=None):
    primary = tmp_path / "primary"
    primary.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _land_stub.calls = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *a, **k: None)
    # The harness primary is a bare directory, not a checkout, so the REAL
    # `_primary_ff_ready` would refuse every lane here on "detached HEAD". Default
    # it to "ready" and let the tests that care inject a refusal; that injection is
    # also what proves `cmd_land` consults this helper rather than a private copy
    # of the same judgement (a duplicated check would ignore the patch).
    # Recording default, not `lambda *a, **k: None`: with a blind stub nothing in the
    # suite ever observes the ARGUMENTS cmd_land passes, so reverting the branch source
    # to `_current_branch` left 22 tests green (review of 233c78039). A stub that
    # swallows its inputs silently un-tests every one of them.
    _land_harness.ff_ready_calls = []

    def _recording_ff_ready(primary, local, branch=None, worktree=None):
        _land_harness.ff_ready_calls.append({"primary": str(primary), "local": local,
                                             "branch": branch, "worktree": worktree})
        return None
    monkeypatch.setattr(MODULE, "_primary_ff_ready",
                        ff_ready if ff_ready is not None else _recording_ff_ready)
    monkeypatch.setattr(MODULE, "cmd_catchup",
                        catchup or _land_stub("catchup", 0, {"ok": True}))
    monkeypatch.setattr(MODULE, "cmd_gate",
                        gate or _land_stub("gate", 0, {"verdict": "pass"}))
    monkeypatch.setattr(MODULE, "cmd_cutover",
                        cutover or _land_stub("cutover", 0,
                                              {"landed": True, "sha": "abc1234"}))
    args = argparse.Namespace(worktree=str(wt), commit=True, json=True,
                              state=str(tmp_path / "registry.json"),
                              base="main", queue_timeout=5.0)
    return primary, args

def _recording_gate_stub(state, worktree):
    """A gate stub that leaves the artefact a real gate run leaves behind.

    `_land_stub.calls` reports whether the FUNCTION was entered; the ticket's
    question is the operator's — did a gate actually run, i.e. is there a verdict on
    disk that cost wall-clock time to produce. Asserting on the record file answers
    it in the currency the real system uses. An absent file is evidence only when
    something was capable of writing it, which is what the clean-primary companion
    test below establishes with the very same stub.
    """
    rec = MODULE._gate_record_path(state, worktree)

    def run(_args):
        _land_stub.calls.append("gate")
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
        print(json.dumps({"verdict": "pass"}))
        return 0
    return run

def _queued(primary):
    with MODULE._land_lock(primary):
        return MODULE._land_tickets(MODULE._land_queue_dir(primary))

def _dirty_primary(reason="primary working tree is dirty (tracked changes)"):
    calls = []

    def ff_ready(primary, local, branch=None, worktree=None):
        calls.append((str(primary), local))
        return (reason, {"dirty_files": ["docs/runbook/backlog/IMP-0023.json"],
                         "broadcast": None})
    ff_ready.calls = calls
    return ff_ready

def _git_repo_with_anchor_ticket(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    ticket = repo / "docs" / "runbook" / "backlog" / "IMP-20260809-crash.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("open\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.strip()
    ticket.write_text("closed\n", encoding="utf-8")
    return repo, base_sha

def _ticket(tmp_path, entry_id, **fields):
    store = tmp_path / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "kg.backlog.entry.v1", "id": entry_id, "status": "open",
               "stream": "IMP", "severity": "med", "category": "tool",
               "date": "2026-08-08", "source": "probe", "detail": "something"}
    payload.update(fields)
    (store / f"{entry_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return store

GROOMED = {"plan": "do the thing", "acceptance": "red then green",
           "fix_site": "ops/x.py:1", "groomed_at": "2026-08-08",
           "groomed_by": "probe", "acceptance_cmd": "true",
           "acceptance_expect_rc": 0}

def _commit(repo, name, body, msg):
    (Path(repo) / name).write_text(body, encoding="utf-8")
    _git(["add", name], repo)
    _git(["commit", "-qm", msg], repo)
    return _git(["rev-parse", "HEAD"], repo).strip()

def _make_branch(repo, branch, files, msg, base="main"):
    """A branch carrying exactly one commit, with the primary left back on `base`."""
    _git(["checkout", "-q", "-b", branch, base], repo)
    for rel, body in files.items():
        (Path(repo) / rel).write_text(body)
        _git(["add", rel], repo)
    _git(["commit", "-qm", msg], repo)
    _git(["checkout", "-q", base], repo)
    return _git(["rev-parse", branch], repo)

def _commit_on(repo, branch, files, msg, back_to="main"):
    _git(["checkout", "-q", branch], repo)
    for rel, body in files.items():
        (Path(repo) / rel).write_text(body)
        _git(["add", rel], repo)
    _git(["commit", "-qm", msg], repo)
    sha = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", back_to], repo)
    return sha

def _run_integrate_json(argv):
    """Legacy synthetic integration fixtures opt into the explicit bypass.

    These tests construct source branches directly and intentionally do not model a
    worker worktree hand-back. Production callers must omit this flag and use the
    registry hand-back stamp; keeping the exception visible at every fixture call
    prevents the test suite from quietly becoming the production contract.
    """
    assert argv and argv[0] == "integrate"
    return _run_json(["integrate", "--allow-unhanded", *argv[1:]])

def _seed_handoff(state, repo, branch, sha):
    path = Path(state)
    ledger = (json.loads(path.read_text()) if path.exists() else {
        "schema": "kg.worktree.registry.v1", "records": [],
    })
    record = {
        "path": str(repo), "branch": branch, "intent": "fixture",
        "base": "main", "created_at": "2999-01-01T00:00:00Z", "status": "active",
        "resolved_at": None, "backlog": [], "claimed_at": None,
        "base_sha": _git(["rev-parse", "main"], repo),
        "handed_back_at": "2999-01-01T00:00:00Z", "handed_back_sha": sha,
    }
    record["handback_seal"] = MODULE.wr._seal_with_digest(
        MODULE.wr._seal_body(
            record, base_sha=record["base_sha"], tip_sha=sha, outcomes=[],
            handed_back_at=record["handed_back_at"],
        )
    )
    ledger["records"].append(record)
    path.write_text(json.dumps(ledger))

def _conflicting_pair(repo):
    """Two branches that both create `shared.txt` — an add/add conflict on the SECOND
    cherry-pick — and `feat/b` carries a FURTHER commit after the conflicting one.

    That trailing commit is load-bearing for the tests, not decoration. With the
    conflict on the last commit of the last branch there is nothing left to pick once
    it is resolved, so "gate the moment the conflict is settled" and "gate when the
    queue is empty" become the same program and no assertion can tell them apart —
    which is precisely the mistake (a verdict bound to a tree that is not the final
    one) the whole ticket is about."""
    a = _make_branch(repo, "feat/a", {"shared.txt": "alpha\n"}, "work: a")
    b1 = _make_branch(repo, "feat/b", {"shared.txt": "beta\n"}, "work: b1")
    b2 = _commit_on(repo, "feat/b", {"b.txt": "b\n"}, "work: b2")
    return a, b1, b2

# Imported by the split collectors; include private fixture helpers too.
__all__ = [name for name in globals() if not name.startswith('__')]

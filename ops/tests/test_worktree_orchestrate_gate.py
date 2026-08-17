"""Behavior-group collector for worktree_orchestrate (gate)."""

from worktree_orchestrate_support import *  # noqa: F401,F403

def test_streamed_gate_runner_heartbeats_to_stderr_and_keeps_stdout_pure(tmp_path):
    stdout = io.StringIO()
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import time; print('first', flush=True); time.sleep(.08); print('last')",
    ]

    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc, tail, dur_s = MODULE._run_streamed_command(
            command,
            cwd=tmp_path,
            gate_name="slow-gate",
            heartbeat_interval=0.02,
        )

    progress = stderr.getvalue()
    assert rc == 0
    assert stdout.getvalue() == ""
    assert "gate=slow-gate phase=start" in progress
    assert "phase=heartbeat" in progress
    assert "elapsed=" in progress
    assert "pid=" in progress
    assert "alive=true" in progress
    assert "phase=done" in progress
    assert "rc=0" in progress
    assert tail.splitlines()[-1] == "last"
    assert dur_s >= 0.06

def test_streamed_gate_runner_bounds_capture_and_preserves_nonzero_exit(tmp_path):
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 200000 + '\\nEND\\n'); sys.exit(7)",
    ]

    with redirect_stderr(stderr):
        rc, tail, dur_s = MODULE._run_streamed_command(
            command,
            cwd=tmp_path,
            gate_name="failing-gate",
            heartbeat_interval=0.01,
            capture_limit=4096,
        )

    assert rc == 7
    assert len(tail.encode()) <= 4096
    assert tail.endswith("END\n")
    assert "phase=done" in stderr.getvalue()
    assert "rc=7" in stderr.getvalue()
    assert dur_s >= 0

def test_shell_and_internal_gate_results_carry_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (0, "lockWaitMs=9000 deviceRunLockWaitMs=3000", 12.5),
    )

    shell = MODULE._run_gate(
        MODULE._shell("ios-test-unit", "ios", ["ops/ios_ops.sh", "test"], "block"),
        str(tmp_path),
    )
    internal = MODULE._run_gate(
        MODULE._internal(
            "coverage", "meta", "warn", covered=[], neutral=[], uncovered=[]
        ),
        str(tmp_path),
    )

    assert shell["dur_s"] == 12.5
    assert internal["dur_s"] >= 0
    assert internal["status"] == "pass"

def test_shell_gate_separates_known_ios_lock_wait_from_work_duration(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (0, "lockWaitMs=9000 deviceRunLockWaitMs=3000", 12.5),
    )

    shell = MODULE._run_gate(
        MODULE._shell("ios-test-unit", "ios", ["ops/ios_ops.sh", "test"], "block"),
        str(tmp_path),
    )

    assert shell["dur_s"] == 12.5
    assert shell["lock_wait_ms"] == 12000
    assert shell["work_dur_s"] == pytest.approx(0.5)

def test_ios_gate_marks_missing_lock_metric_unknown_in_bounded_output(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        # ios_test.sh prints lockWaitMs before its final device timing line.  A
        # bounded tail can therefore retain the latter while dropping the former.
        lambda *args, **kwargs: (0, "deviceRunLockWaitMs=3000", 12.5),
    )

    shell = MODULE._run_gate(
        MODULE._shell("ios-test-unit", "ios", ["ops/ios_ops.sh", "test"], "block"),
        str(tmp_path),
    )

    assert shell["status"] == "pass"
    assert shell["timing_status"] == "unknown"
    assert shell["lock_wait_ms"] is None
    assert shell["work_dur_s"] is None

def test_ios_prepare_cache_gate_requires_only_process_lock_metric(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        # --prepare-cache exits after build-for-testing and never enters the
        # device execution-lock phase that emits deviceRunLockWaitMs.
        lambda *args, **kwargs: (0, "lockWaitMs=9000", 12.5),
    )

    shell = MODULE._run_gate(
        MODULE._shell(
            "ios-live-demo-uitest-compile",
            "ios",
            [
                "ops/ios_ops.sh",
                "test",
                "--configuration",
                "Release",
                "--destination",
                "generic/platform=iOS",
                "--prepare-cache",
                "--json",
            ],
            "block",
        ),
        str(tmp_path),
    )

    assert shell["status"] == "pass"
    assert shell["timing_status"] == "known"
    assert shell["lock_wait_ms"] == 9000
    assert shell["work_dur_s"] == pytest.approx(3.5)

def test_duration_fields_use_latest_lock_metrics_without_changing_verdict():
    metrics = MODULE._duration_fields(
        12.5,
        "lockWaitMs=100\nlockWaitMs: 9000\ndeviceRunLockWaitMs: 3000",
    )

    assert metrics == {
        "dur_s": 12.5,
        "lock_wait_ms": 12000,
        "work_dur_s": pytest.approx(0.5),
        "timing_status": "known",
    }

def test_git_mutation_streams_semantic_progress_without_exposing_argv(
    tmp_path, monkeypatch,
):
    """Silent git mutations heartbeat without leaking credential-shaped argv."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(textwrap.dedent("""\
        #!/bin/sh
        sleep 0.06
        printf 'mutation-output\\n'
    """))
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    err = io.StringIO()
    with redirect_stderr(err):
        rc, output = MODULE._git_mutation(
            ["push", "origin", "token=super-secret"],
            cwd=tmp_path,
            label="sync-push",
            heartbeat_interval=0.01,
        )

    assert rc == 0
    assert output == "mutation-output"
    progress = err.getvalue()
    assert "mutation=sync-push phase=start" in progress
    assert "mutation=sync-push phase=spawned" in progress
    assert "mutation=sync-push phase=heartbeat" in progress
    assert "mutation=sync-push phase=done" in progress
    assert "pid=" in progress and "alive=" in progress
    assert "super-secret" not in progress

def test_registry_mutation_keeps_json_parseable_and_progress_off_stdout(
    tmp_path, monkeypatch,
):
    payload = {"schema": "kg.worktree.registry.v1", "clear": []}

    def fake_stream(command, **kwargs):
        assert kwargs["label"] == "preflight-sweep"
        assert kwargs["merge_stderr"] is False
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "diagnostic")

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_stream)
    rc, parsed = MODULE._registry_mutation(
        ["sweep", "--commit", "--json"],
        cwd=tmp_path,
        label="preflight-sweep",
    )

    assert rc == 0
    assert parsed == payload

def test_registry_mutation_preserves_failure_diagnostic_without_stdout_pollution(
    tmp_path, monkeypatch,
):
    def fake_stream(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "sweep failed safely")

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_stream)
    rc, parsed = MODULE._registry_mutation(
        ["sweep", "--commit", "--json"],
        cwd=tmp_path,
        label="preflight-sweep",
    )

    assert rc == 1
    assert parsed == {"error": "registry mutation failed", "detail": "sweep failed safely"}

def test_committed_preflight_routes_sweep_through_observed_registry_runner(
    tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(MODULE, "_fetch", lambda: (0, ""))
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_registry_mutation",
        lambda argv, **kwargs: (calls.append((argv, kwargs)) or (0, {"clear": []})),
    )
    monkeypatch.setattr(
        MODULE,
        "_registry",
        lambda argv: pytest.fail("committed sweep must not use silent in-process route"),
    )
    args = MODULE.argparse.Namespace(
        commit=True, state=None, json=True, allow_offline=False,
    )

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = MODULE.cmd_preflight(args)

    assert rc == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert "--commit" in argv and "--json" in argv
    assert kwargs == {"cwd": tmp_path, "label": "preflight-sweep"}
    assert json.loads(stdout.getvalue())["sweep_rc"] == 0

def test_remote_branch_probe_routes_ls_remote_through_observed_runner(
    tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_git_mutation",
        lambda argv, **kwargs: (calls.append((argv, kwargs)) or (0, "abc refs/heads/x")),
    )
    monkeypatch.setattr(
        MODULE, "_git", lambda *args, **kwargs: pytest.fail("ls-remote must be observed"),
    )

    assert MODULE._remote_branch_exists("x") is True
    assert calls == [
        (["ls-remote", "--heads", "origin", "x"],
         {"cwd": tmp_path, "label": "remote-branch-probe"}),
    ]

def test_committed_sync_routes_push_and_remote_verification_through_observed_runner(
    tmp_path, monkeypatch,
):
    local_sha = "a" * 40
    upstream_sha = "b" * 40
    observed = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "_current_branch", lambda path: "main")
    monkeypatch.setattr(MODULE, "_fetch", lambda: (0, ""))

    def fake_probe(argv, cwd=None):
        if argv == ["rev-parse", "refs/heads/main"]:
            return 0, local_sha
        if argv == ["rev-parse", "origin/main"]:
            return 0, upstream_sha
        if argv[:2] == ["merge-base", "--is-ancestor"]:
            return 0, ""
        if argv[:2] == ["rev-list", "--count"]:
            return 0, "1"
        pytest.fail(f"unexpected silent probe: {argv}")

    def fake_observed(argv, **kwargs):
        observed.append((argv, kwargs["label"]))
        if argv[0] == "push":
            return 0, ""
        if argv[0] == "ls-remote":
            return 0, f"{local_sha}\trefs/heads/main"
        pytest.fail(f"unexpected observed command: {argv}")

    monkeypatch.setattr(MODULE, "_git", fake_probe)
    monkeypatch.setattr(MODULE, "_git_mutation", fake_observed)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = MODULE._guarded_advance(
            src_branch="main", dest_branch="main", production=False, step="sync",
            commit=True, as_json=True, state=None,
        )

    assert rc == 0
    assert observed == [
        (["push", "origin", "refs/heads/main:main"], "sync-push"),
        (["ls-remote", "origin", "main"], "sync-verify-remote"),
    ]
    assert json.loads(stdout.getvalue())["verdict"] == "pushed"

def test_potentially_long_git_operations_never_use_silent_probe_runner():
    """Static tripwire for every reviewed mutation family in this orchestrator."""
    tree = ast.parse((ROOT / "ops" / "worktree_orchestrate.py").read_text())
    forbidden = {
        "fetch", "push", "rebase", "merge", "worktree", "branch", "ls-remote",
    }
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_git" and node.args):
            continue
        argv = node.args[0]
        if not (isinstance(argv, ast.List) and argv.elts
                and isinstance(argv.elts[0], ast.Constant)):
            continue
        verb = argv.elts[0].value
        if verb in forbidden:
            violations.append((verb, node.lineno))
    assert violations == []

def test_safety_fixture_no_production_push():
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for function in (
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "test_production_ref_push_denied"
    ):
        for call in ast.walk(function):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_git"
                and call.args
                and isinstance(call.args[0], ast.List)
                and call.args[0].elts
                and isinstance(call.args[0].elts[0], ast.Constant)
                and call.args[0].elts[0].value == "push"
            ):
                continue
            for argument in call.args[0].elts[1:]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    assert not _is_production_ref(argument.value)
                elif isinstance(argument, ast.JoinedStr):
                    literal = "".join(
                        part.value for part in argument.values if isinstance(part, ast.Constant)
                    )
                    assert not _is_production_ref(literal)

def test_production_ref_push_denied(monkeypatch, tmp_path):
    calls = []

    def unexpected_subprocess(*args, **kwargs):
        calls.append(args[0])
        raise AssertionError("production ref reached subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected_subprocess)
    for ref in (
        "main:prod", "prod", "origin/prod", "HEAD:refs/heads/prod",
        "refs/heads/prod", "refs/remotes/origin/prod",
        "refs/heads/main:refs/heads/prod",
    ):
        with pytest.raises(AssertionError, match="fixture git helper refuses production ref"):
            _git(["push", "-q", "origin", ref], tmp_path)
    for option in ("--all", "--mirror"):
        with pytest.raises(AssertionError, match="fixture git helper refuses implicit production ref push"):
            _git(["push", "-q", "origin", option], tmp_path)
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "https://example.invalid/repository.git", "HEAD:fixture"], tmp_path)
    for remote in (
        "github.com:/repo.git", "git@github.com:/repo.git", "192.168.1.5:repo.git",
        "build-server:repo.git", "git@[::1]:repo.git", "//host/repo.git",
    ):
        with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
            _git(["push", remote, "HEAD:fixture"], tmp_path)
    configured = tmp_path / "configured-network"
    (configured / ".git").mkdir(parents=True)
    (configured / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git+ssh://git@example.invalid/repository.git\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["fetch", "origin"], configured)
    included = tmp_path / "included-config"
    (included / ".git").mkdir(parents=True)
    (included / ".git" / "config").write_text(
        "[include]\n\tpath = ~/.gitconfig-network\n", encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "origin", "HEAD:fixture"], included)
    linked = tmp_path / "linked-worktree"
    common_git = linked / "common.git"
    (common_git / "worktrees" / "fixture").mkdir(parents=True)
    linked.mkdir(exist_ok=True)
    (linked / ".git").write_text(
        f"gitdir: {common_git / 'worktrees' / 'fixture'}\n", encoding="utf-8"
    )
    (common_git / "config").write_text(
        '[remote "origin"]\n\turl = ssh://git@example.invalid/repository.git\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "origin", "HEAD:fixture"], linked)
    assert calls == []

@gitmark
def test_verified_against_requires_head_reachability(tmp_path):
    repo = tmp_path / "verified-against"
    (repo / "docs").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "probe@example.test"], repo)
    _git(["config", "user.name", "probe"], repo)
    doc = repo / "docs" / "x.md"

    def anchor(sha):
        doc.write_text(
            "<!-- doc-meta\nverified_against: " + sha + "\n-->\n",
            encoding="utf-8",
        )

    anchor("0000000")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)
    base = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", "-b", "wt-fixture"], repo)
    (repo / "note.txt").write_text("worktree commit\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "branch"], repo)
    branch = _git(["rev-parse", "HEAD"], repo)
    orphan = _git(
        ["-c", "user.email=probe@example.test", "-c", "user.name=probe",
         "commit-tree", "HEAD^{tree}", "-m", "orphan"],
        repo,
    )

    reachability = subprocess.run(
        ["git", "merge-base", "--is-ancestor", orphan, "HEAD"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert reachability.returncode != 0

    anchor(base)
    assert MODULE._run_verified_against(str(repo), ["docs/x.md"])["status"] == "pass"
    anchor(branch)
    assert MODULE._run_verified_against(str(repo), ["docs/x.md"])["status"] == "pass"

    anchor("0" * 40)
    absent = MODULE._run_verified_against(str(repo), ["docs/x.md"])
    assert absent["status"] != "pass"
    assert "absent" in absent["summary"]

    anchor(orphan)
    orphan_result = MODULE._run_verified_against(str(repo), ["docs/x.md"])
    assert orphan_result["status"] != "pass"
    assert "orphan" in orphan_result["summary"]

@gitmark
def test_shell_scan_blocks_a_var_abutting_full_width_punctuation(tmp_path):
    """The 2026-08-08 line, verbatim in shape."""
    repo = _scan_fixture(tmp_path, "dirty",
                         offending='dest=/tmp\necho "目錄：$dest（已標記）"\n')
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    # naming the site is the whole value: a scanner that only says "found 1" leaves
    # the reader where the 94-character summary left them
    assert "ops/offender.sh:2" in out, out

@gitmark
def test_shell_scan_passes_a_clean_tree_including_the_braced_form(tmp_path):
    """The positive control for the test above, and for `${VAR}` being the FIX: the
    fillers all contain `${var}，`, so a pattern broad enough to flag the safe form
    turns this red."""
    repo = _scan_fixture(tmp_path, "clean")
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr

@gitmark
def test_shell_scan_respects_a_named_exemption(tmp_path):
    """`fw-allow` with a reason is the documented escape hatch; a scan that ignored
    it would make its own fixtures unrepresentable."""
    repo = _scan_fixture(
        tmp_path, "exempt",
        offending='dest=/tmp\necho "目錄：$dest（已標記）"  # fw-allow: fixture\n')
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr

def test_shell_scan_has_a_help_surface():
    proc = subprocess.run([str(SHELL_SCAN), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout

@gitmark
def test_gate_record_carries_orchestrator_identity(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    orch = gate["orchestrator"]
    assert orch["path"] == "ops/worktree_orchestrate.py"
    assert _HEX64.match(orch["sha256"])
    assert orch["resolved"] == str(Path(MODULE.__file__).resolve())

@pytest.mark.parametrize(
    ("preflight_status", "expected_rc"),
    [("block", MODULE.EXIT_BLOCK), ("inconclusive", MODULE.EXIT_OK),
     ("warn", MODULE.EXIT_OK)],
)
@gitmark
def test_gate_stops_after_nonpassing_preflight(
        scratch, monkeypatch, preflight_status, expected_rc):
    """A typed cheap preflight failure must not launch later expensive gates."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "preflight-reg.json")
    wt = _open_wt(state, slug="review-preflight")
    source = Path(wt) / "ops" / "tests" / "test_worktree_orchestrate.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# preflight fixture\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "change orchestrator"], wt)

    calls = []

    preflight = {
        "name": "cheap-preflight",
        "category": "meta",
        "level": "block",
        "preflight": True,
        "cmd": ["true"],
    }
    expensive = {
        "name": "expensive-follow-up",
        "category": "ops",
        "level": "block",
        "cmd": ["false"],
    }

    monkeypatch.setattr(MODULE, "plan_gates", lambda *args, **kwargs: [
        preflight, expensive,
    ])

    def fake_run_gate(spec, worktree, *, record_path=None, state=None):
        calls.append(spec["name"])
        return {
            "name": spec["name"], "category": spec["category"],
            "level": spec["level"],
            "status": preflight_status if spec["name"] == "cheap-preflight" else "pass",
            "rc": 2 if spec["name"] == "cheap-preflight" else 0,
            "summary": "stubbed preflight" if spec["name"] == "cheap-preflight"
                       else "should not run",
        }

    monkeypatch.setattr(MODULE, "_run_gate", fake_run_gate)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    assert rc == expected_rc
    assert calls == ["cheap-preflight"]
    assert gate["gates"][0]["name"] == "cheap-preflight"
    assert gate["gates"][0]["status"] == preflight_status
    assert len(gate["gates"]) == 1
    progress = json.loads(
        MODULE._gate_progress_path(state, wt).read_text(encoding="utf-8")
    )
    assert progress["done"] == 1
    assert progress["plan_total"] == len(gate["plan"])
    assert progress["current"] is None

    rc, receipt = _run_text(
        ["gate", "--worktree", wt, "--state", state, "--receipt-line"]
    )
    assert rc == expected_rc
    assert f"gates={len(gate['plan'])}" in receipt
    assert "executed=1" in receipt

    if preflight_status == "warn":
        rc, cut = _run_json(
            ["cutover", "--worktree", wt, "--state", state, "--commit", "--json"]
        )
        assert rc == MODULE.EXIT_BLOCK
        assert cut["landed"] is False
        assert "gate record is incomplete" in cut["error"]
        assert "notes.txt" not in _local_main_files(repo)

def test_executed_gate_count_excludes_reuse_and_spawn_failures():
    assert MODULE._executed_gate_count([
        {"name": "rerun", "status": "pass"},
        {"name": "reused", "status": "pass",
         "reuse": {"decision": "reused"}},
        {"name": "spawn-failed", "status": "block", "executed": False},
    ]) == 1

@gitmark
def test_cutover_refuses_a_malformed_gate_record(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "malformed-record.json")
    wt = _open_wt(state, slug="malformed-gate-record")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, gate
    record_path = MODULE._gate_record_path(state, wt)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("plan")
    record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rc, cut = _run_json(
        ["cutover", "--worktree", wt, "--state", state, "--commit", "--json"]
    )
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert "gate record is malformed" in cut["error"]
    assert "notes.txt" not in _local_main_files(repo)

@gitmark
def test_gate_names_the_empty_worktree(scratch):
    """An empty diff is a legal re-gate, but its record must say it verified nothing."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "check an empty tree", "--slug", "empty-gate",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    rc, gate = _run_json(["gate", "--worktree", opened["path"],
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["changed_files"] == []
    assert gate["no_changed_files"] is True
    assert gate["verdict"] == "pass"

    rc, text = _run_text(["gate", "--worktree", opened["path"],
                          "--state", state])
    assert rc == MODULE.EXIT_OK
    assert "no changes in this worktree" in text
    assert opened["path"] in text

    rc, receipt = _run_text(["gate", "--worktree", opened["path"],
                             "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert "no-changes" in receipt

@gitmark
def test_gate_plan_only_receipt_does_not_record_empty_signal(scratch):
    """Plan-only previews must not masquerade as a recorded empty verification."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "plan-reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "preview empty tree", "--slug", "plan-empty",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    rc, receipt = _run_text(
        ["gate", "--worktree", opened["path"], "--state", state,
         "--plan-only", "--receipt-line"]
    )
    assert rc == MODULE.EXIT_OK
    assert "gate=planned" in receipt
    assert "record=<not recorded>" in receipt
    assert "no-changes" not in receipt
    assert not MODULE._gate_record_path(state, opened["path"]).exists()

@gitmark
def test_gate_marks_a_changed_worktree_as_nonempty(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state, slug="nonempty-gate")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["changed_files"] == ["notes.txt"]
    assert gate["no_changed_files"] is False

    rc, receipt = _run_text(["gate", "--worktree", wt, "--state", state,
                             "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert "no-changes" not in receipt

@gitmark
def test_gate_publishes_independent_progress_without_polluting_json(
        scratch, monkeypatch, capsys):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "progress-reg.json")
    _seed_python_scan(repo)
    wt = _open_wt(state, slug="progress-gate")
    # Make the impact plan contain two gates while keeping this regression offline.
    source = Path(wt) / "ops" / "tests" / "test_worktree_orchestrate.py"
    source.parent.mkdir(parents=True)
    source.write_text("# changed test fixture\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "change orchestrator"], wt)

    def fake_run_gate(spec, worktree, *, record_path=None, state=None):
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "stubbed gate"}

    progress_path = MODULE._gate_progress_path(state, wt)
    atomic_writes = []
    write_atomic = MODULE._write_atomic

    def recording_write_atomic(path, body):
        atomic_writes.append((path, body))
        write_atomic(path, body)

    monkeypatch.setattr(MODULE, "_run_gate", fake_run_gate)
    monkeypatch.setattr(MODULE, "_write_atomic", recording_write_atomic)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    stdout = json.dumps(gate)
    assert json.loads(stdout)["verdict"] == "pass"

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert len(atomic_writes) == len(gate["gates"]) + 1
    assert [path for path, _ in atomic_writes] == [progress_path] * len(atomic_writes)
    assert all(json.loads(body)["schema"] == MODULE.GATE_PROGRESS_SCHEMA
               for _, body in atomic_writes)
    assert progress["run_id"]
    assert progress["generation"] >= 1
    assert progress["head_sha"] == gate["head_sha"]
    assert progress["plan_total"] == len(gate["plan"]) == 3
    assert progress["done"] == progress["plan_total"]
    assert progress["current"] is None
    assert progress["completed"] == [
        {"name": result["name"], "status": result["status"]}
        for result in gate["gates"]
    ]

    stderr = capsys.readouterr().err
    assert f"phase=plan gates={progress['plan_total']}" in stderr
    for result in gate["gates"]:
        assert f"phase=gate gate={result['name']}" in stderr
        assert f"status={result['status']}" in stderr
    assert str(progress_path) in stderr

@gitmark
def test_newer_gate_owns_progress_sidecar_against_stale_run(scratch, monkeypatch):
    """A slower older gate must not publish after a newer run takes ownership."""
    tmp_path, repo, _remote = scratch
    state_path = str(tmp_path / "concurrent-progress.json")
    wt = _open_wt(state_path, slug="concurrent-progress")
    source = Path(wt) / "ops" / "tests" / "test_worktree_orchestrate.py"
    source.parent.mkdir(parents=True)
    source.write_text("# changed test fixture\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "change orchestrator"], wt)

    nested = False
    runs = []
    newer_progress = []

    def fake_run_gate(spec, worktree, *, record_path=None, state=None):
        nonlocal nested
        if not nested:
            nested = True
            rc, newer = _run_json(["gate", "--worktree", wt, "--state", state_path,
                                   "--json"])
            assert rc == MODULE.EXIT_OK, newer
            runs.append(newer)
            newer_progress.append(json.loads(
                MODULE._gate_progress_path(state_path, wt).read_text()))
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "stubbed gate"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run_gate)
    rc, older = _run_json(["gate", "--worktree", wt, "--state", state_path, "--json"])
    assert rc == MODULE.EXIT_OK, older
    assert len(runs) == 1
    newer = runs[0]
    progress = json.loads(MODULE._gate_progress_path(state_path, wt).read_text())
    assert newer_progress[0]["run_id"] == progress["run_id"]
    assert newer["head_sha"] == older["head_sha"]
    assert progress["generation"] > 1
    assert progress["done"] == progress["plan_total"] == len(newer["gates"])

@gitmark
def test_gate_warns_when_the_primary_is_dirty(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-dirty.json")
    rc, opened = _run_json(
        ["open", "--intent", "observe primary drift", "--slug", "primary-dirty",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    (repo / "f").write_text("leaked edit\n")
    try:
        rc, gate = _run_json(["gate", "--worktree", opened["path"],
                              "--state", state, "--json"])
        assert rc == MODULE.EXIT_OK
        assert gate["primary_dirty"] == ["f"]
        assert gate["primary_dirty_error"] is None
        assert gate["verdict"] == "pass"

        rc, text = _run_text(["gate", "--worktree", opened["path"],
                              "--state", state])
        assert rc == MODULE.EXIT_OK
        assert "primary working tree has 1 uncommitted tracked file(s): f" in text
        assert "rather than this worktree" in text
    finally:
        (repo / "f").write_text("base\n")

@gitmark
def test_gate_reports_a_clean_primary(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-clean.json")
    wt = _open_wt(state, slug="primary-clean")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["primary_dirty"] == []
    assert gate["primary_dirty_error"] is None

@gitmark
def test_gate_reports_primary_status_failure(scratch, monkeypatch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-status-failure.json")
    wt = _open_wt(state, slug="primary-status-failure")
    original_git = MODULE._git

    def fail_primary_status(argv, cwd=None):
        if list(argv) == ["status", "--porcelain", "--untracked-files=no"] \
                and Path(cwd).resolve() == repo.resolve():
            return 7, ""
        return original_git(argv, cwd=cwd)

    monkeypatch.setattr(MODULE, "_git", fail_primary_status)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["primary_dirty"] == []
    assert "rc=7" in gate["primary_dirty_error"]

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    assert "primary working tree status unavailable" in text
    assert "rc=7" in text

@gitmark
def test_gate_plan_only_does_not_probe_primary(scratch, monkeypatch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-plan-only.json")
    rc, opened = _run_json(
        ["open", "--intent", "preview primary drift", "--slug", "primary-plan-only",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    def unexpected_primary_probe():
        raise AssertionError("plan-only must not probe primary")

    monkeypatch.setattr(MODULE, "primary_root", unexpected_primary_probe)
    rc, gate = _run_json(["gate", "--worktree", opened["path"], "--state", state,
                          "--plan-only", "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "planned"
    assert "primary_dirty" not in gate

@gitmark
def test_gate_orchestrator_identity_is_null_when_worktree_has_no_copy(scratch):
    """The synthetic fixture repo has no ops/ tree. Provenance must degrade to "cannot
    compare" rather than inventing a mismatch — otherwise every existing test, and every
    non-kg repo, would be refused."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    orch = gate["orchestrator"]
    assert orch["worktree_copy_sha256"] is None
    assert orch["matches_worktree_copy"] is None
    assert orch["source"] == "invoked"

@gitmark
def test_gate_provenance_is_pinned_to_the_same_computation_on_every_surface(scratch):
    """SOURCE PIN. A shared helper is not enough: someone can hand-write one output
    surface and the shared-source assertions all stay green (learned the hard way —
    reverting a call site while leaving a printer intact kept five assertions green).
    So assert the JSON block IS the helper's output, AND that the human report and the
    receipt line carry that same digest."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    expected = MODULE._orchestrator_identity(wt)
    assert gate["orchestrator"] == expected

    # The digest ALONE is not enough to pin: it reads the same whether the worktree
    # agreed, had nothing to compare, or could not be read. Pin the rendered token.
    token = f"{expected['sha256'][:8]} ({expected['source']})"
    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    assert f"orchestrator={token}" in text.splitlines()[0]

    rc, line = _run_text(["gate", "--worktree", wt, "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert f"orch={token}" in line

@gitmark
def test_gate_report_last_line_is_the_pasteable_receipt_line(scratch):
    """One gate run supplies both the full report and its pasteable receipt."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    last = text.strip().splitlines()[-1]
    assert last.startswith("gate="), last

    rc, only = _run_text(["gate", "--worktree", wt, "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert only.strip() == last
    assert len(only.strip().splitlines()) == 1

    rc, planned = _run_text(["gate", "--worktree", wt, "--state", state, "--plan-only"])
    assert rc == MODULE.EXIT_OK
    assert not planned.strip().splitlines()[-1].startswith("gate=")

@gitmark
def test_gate_refuses_when_the_worktree_carries_a_different_orchestrator(scratch):
    """The incident this exists for: `gate` run from the primary checkout against a
    branch that changed the routing planned the OLD rule set and reported a green that
    read exactly like the new one's."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt, "# a different orchestrator\n")

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_USAGE
    running = MODULE._orchestrator_identity(wt)
    # both digests named, so the reader can tell WHICH two things disagree
    assert running["sha256"][:8] in text
    assert running["worktree_copy_sha256"][:8] in text
    # and a remedy that can be pasted, not deduced
    assert f"{wt}/ops/worktree_orchestrate.py" in text
    # refusing must be free of side effects: no verdict may be recorded
    assert not MODULE._gate_record_path(state, wt).exists()

@gitmark
def test_gate_does_not_refuse_a_byte_identical_worktree_orchestrator(scratch):
    """The gate must be NARROW: it fires only when the branch actually modified the
    tool. Refusing on a byte-identical copy would be pure friction — the plan is the
    same plan — and friction is what teaches people to route around a gate."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["orchestrator"]["matches_worktree_copy"] is True
    assert gate["orchestrator"]["source"] == "worktree"

@gitmark
def test_gate_names_unavailable_ops_tests_in_a_synthetic_worktree(scratch, monkeypatch):
    """A scratch tree with only an orchestrator copy cannot run the ops suite.

    The gate still needs to see the untracked orchestrator for omission/provenance
    checks, but invoking ``pytest ops/tests`` there exits rc=4 because that tree has
    no test directory.  This is unavailable infrastructure, not a failed change.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    wt = _open_wt(state)
    _plant_orchestrator(wt)
    monkeypatch.setattr(
        MODULE, "_changed_vs_base",
        lambda _worktree, _base: ["ops/worktree_orchestrate.py"],
    )

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, gate
    assert gate["verdict"] == "warn"
    assert not any(row["name"] == "ops-pytest" for row in gate["gates"])
    unavailable = next(row for row in gate["gates"]
                       if row["name"] == "ops-pytest-unavailable")
    assert unavailable["status"] == "warn"
    assert "ops/tests" in unavailable["summary"]

@gitmark
def test_gate_keeps_ops_pytest_block_when_an_ops_test_path_changed(scratch, monkeypatch):
    """A missing test tree is not advisory when the diff itself names an ops test."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)
    monkeypatch.setattr(
        MODULE, "_changed_vs_base",
        lambda _worktree, _base: [
            "ops/worktree_orchestrate.py", "ops/tests/test_missing.py",
        ],
    )

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, gate
    assert gate["verdict"] == "block"
    ops_gate = next(row for row in gate["gates"] if row["name"] == "ops-pytest")
    assert ops_gate["status"] == "block"
    assert "ops/tests" in next(
        plan["cmd"] for plan in gate["plan"] if plan["name"] == "ops-pytest"
    )
    assert not any(row["name"] == "ops-pytest-unavailable" for row in gate["gates"])

@gitmark
def test_cutover_refuses_a_verdict_produced_by_a_different_orchestrator(scratch):
    """Defence in depth for a record that predates the gate-side refusal, or one that
    was edited. Same family as the stale-HEAD refusal: a verdict is only usable if it
    is bound BOTH to the code it judged and to the judge."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)

    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    rec_path = MODULE._gate_record_path(state, wt)
    rec = json.loads(rec_path.read_text())
    rec["orchestrator"]["sha256"] = "0" * 64
    rec_path.write_text(json.dumps(rec))

    rc, res = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert res["landed"] is False
    assert "orchestrator" in res["error"]
    assert "notes.txt" not in _local_main_files(repo)

@gitmark
def test_cutover_accepts_a_verdict_when_the_orchestrator_cannot_be_compared(scratch):
    """No ops/ tree in the target (synthetic fixtures, any non-kg checkout) means
    "cannot compare", which must not be reported as a mismatch — otherwise every such
    caller is refused for a question that was never asked."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["orchestrator"]["worktree_copy_sha256"] is None

    rc, res = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["landed"] is True

def test_gate_history_records_duration_and_stable_run_order(tmp_path, monkeypatch):
    moments = iter([
        datetime(2026, 8, 9, 1, 2, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 1, 2, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 1, 2, 3, 3, tzinfo=timezone.utc),
    ])

    class SequencedDatetime:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return next(moments)

    monkeypatch.setattr(MODULE, "datetime", SequencedDatetime)
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    results = [
        {"name": "first", "status": "pass", "rc": 0, "level": "block", "dur_s": 1.25},
        {"name": "second", "status": "warn", "rc": 0, "level": "warn", "dur_s": 2.5},
    ]

    assert MODULE._append_gate_history(state, str(tmp_path), "b" * 40, orch, results) is None
    assert MODULE._append_gate_history(state, str(tmp_path), "c" * 40, orch, results[:1]) is None
    rows = _history_lines(state)

    assert [row["dur_s"] for row in rows] == [1.25, 2.5, 1.25]
    assert [row["idx"] for row in rows] == [0, 1, 0]
    assert rows[0]["run_id"] == rows[1]["run_id"]
    assert rows[2]["run_id"] != rows[0]["run_id"]
    assert len({(row["run_id"], row["idx"]) for row in rows}) == len(rows)
    assert [row["ts"] for row in rows] == [
        "2026-08-09T01:02:03.000001Z",
        "2026-08-09T01:02:03.000002Z",
        "2026-08-09T01:02:03.000003Z",
    ]

def test_gate_history_records_lock_wait_separately_from_work_duration(tmp_path):
    state = str(tmp_path / "reg.json")
    results = [{
        "name": "ios-test-unit",
        "status": "pass",
        "rc": 0,
        "level": "block",
        "dur_s": 12.5,
        "lock_wait_ms": 12000,
        "work_dur_s": 0.5,
        "timing_status": "known",
    }]

    assert MODULE._append_gate_history(
        state, str(tmp_path), "b" * 40, {"sha256": "a" * 64}, results,
    ) is None

    row = _history_lines(state)[0]
    assert row["dur_s"] == 12.5
    assert row["lock_wait_ms"] == 12000
    assert row["work_dur_s"] == 0.5
    assert row["timing_status"] == "known"

@gitmark
def test_gate_appends_one_history_line_per_executed_gate(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rows = _history_lines(state)
    assert [r["gate"] for r in rows] == [g["name"] for g in gate["gates"]]
    assert [r["dur_s"] for r in rows] == [g["dur_s"] for g in gate["gates"]]
    assert all(isinstance(g["dur_s"], float) and g["dur_s"] >= 0 for g in gate["gates"])
    assert [r["idx"] for r in rows] == list(range(len(rows)))
    assert len({r["run_id"] for r in rows}) == 1
    row = rows[0]
    assert row["status"] == "warn" and row["level"] == "warn"
    assert row["head8"] == gate["head_sha"][:8]
    assert row["orch8"] == gate["orchestrator"]["sha256"][:8]
    assert row["ts"].endswith("Z")

@gitmark
def test_gate_history_accumulates_and_survives_resolve(scratch):
    """Teardown strikes the per-worktree verdict (that one describes a worktree that no
    longer exists). The behavioural history must NOT go with it — deleting it would
    erase exactly the evidence that proves a gate is capable of passing."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert len(_history_lines(state)) == 2

    _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["gate_cache_removed"] is True
    assert len(_history_lines(state)) == 2

@gitmark
def test_gate_survives_an_unwritable_history(scratch):
    """Bookkeeping must never fail the caller — a gate that refuses because its own
    logging broke would be a new way for a green change to read as red."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    # occupy the history path with a DIRECTORY: every append will raise
    hist = MODULE._gate_history_path(state)
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.mkdir()

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "warn"

def test_never_green_fires_only_when_a_gate_has_never_passed(tmp_path):
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build-catalyst", "block", h)
                           for h in ("aaaaaaaa", "bbbbbbbb", "cccccccc")])
    assert MODULE._never_green(state, "ios-build-catalyst") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

def test_never_green_is_silenced_by_a_single_historical_pass(tmp_path):
    """One green ever is enough: the gate is PROVEN capable, and later reds are the
    change's problem, not the gate's."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ios-build", "block", "aaaaaaaa"),
        _row("ios-build", "pass", "bbbbbbbb"),
        _row("ios-build", "block", "cccccccc"),
        _row("ios-build", "block", "dddddddd"),
    ])
    assert MODULE._never_green(state, "ios-build") is None

def test_never_green_ignores_a_single_head_streak(tmp_path):
    """Someone hammering one broken commit is not evidence about the GATE."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-test-unit", "block", "aaaaaaaa")] * 5)
    assert MODULE._never_green(state, "ios-test-unit") is None

def test_never_green_needs_enough_attempts(tmp_path):
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("docs-lint", "block", "aaaaaaaa"),
                           _row("docs-lint", "block", "bbbbbbbb")])
    assert MODULE._never_green(state, "docs-lint") is None

def test_never_green_on_absent_history_is_silent(tmp_path):
    """A fresh clone knows nothing; "no data" must never be reported as "never green"."""
    assert MODULE._never_green(str(tmp_path / "reg.json"), "ios-build") is None

@gitmark
def test_a_gate_that_has_never_passed_says_so_at_the_moment_it_blocks(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "add a thing", "--slug", "nevergreen",
                            "--state", state, "--json"])
    wt = opened["path"]
    # The fixture repo has no ops/ tree; docs-lint therefore routes to a tool that does
    # not exist. Before IMP-0047 that raised and killed the whole run, so this test had
    # to plant a stub to reach the never-green annotation at all. It now reports as a
    # block, which is what a synthetic repo should look like — no stub needed.
    docs = Path(wt) / "docs"
    # exist_ok: the scratch fixture now commits docs/runbook/backlog (the claim gate
    # needs a real store), so `docs/` is checked out into every worktree.
    docs.mkdir(exist_ok=True)
    (docs / "x.md").write_text("<!-- doc-meta -->\n<<<<<<< HEAD\nours\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "docs: conflicted"], wt)

    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    marker = _by_name(first["gates"])["docs-conflict-markers"]
    assert "never green" not in marker["summary"]  # one attempt proves nothing

    (docs / "y.md").write_text("<!-- doc-meta -->\n>>>>>>> theirs\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "docs: more conflict"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, third = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    assert rc == MODULE.EXIT_BLOCK
    marker = _by_name(third["gates"])["docs-conflict-markers"]
    assert marker["never_green"] == {"attempts": 3, "heads": 2, "worktrees": 1}
    assert "3 block attempt(s) across 2 HEAD(s) / 1 worktree(s)" in marker["summary"]
    # A hypothesis, never a verdict — the data cannot distinguish a structurally-red
    # gate from three honest reds while fixing a real bug.
    assert "worth checking whether it can pass at all" in marker["summary"]
    assert "suspect the gate" not in marker["summary"]

@gitmark
def test_an_unreadable_worktree_orchestrator_is_a_mismatch_not_an_absence(scratch):
    """"Present but unreadable" must never render identically to "no ops/ tree at all".
    If it did, the guard (`matches_worktree_copy is not False`) would wave it through —
    reinstating the exact silent bypass this whole change exists to close, with a
    different trigger."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    planted = _plant_orchestrator(wt)
    planted.chmod(0o000)
    try:
        orch = MODULE._orchestrator_identity(wt)
        assert orch["matches_worktree_copy"] is False        # fail CLOSED
        assert orch["worktree_copy_sha256"] is None
        assert orch["source"] == "unreadable"
        assert "PermissionError" in orch["worktree_copy_error"]

        rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
        assert rc == MODULE.EXIT_USAGE
        assert "could not be read" in text
    finally:
        planted.chmod(0o644)

@gitmark
def test_absent_and_unreadable_orchestrators_do_not_render_identically(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    absent = MODULE._orchestrator_identity(wt)

    planted = _plant_orchestrator(wt)
    planted.chmod(0o000)
    try:
        unreadable = MODULE._orchestrator_identity(wt)
    finally:
        planted.chmod(0o644)
    assert absent != unreadable
    assert absent["matches_worktree_copy"] is None
    assert unreadable["matches_worktree_copy"] is False

def test_never_green_survives_one_corrupt_journal_line(tmp_path):
    """The journal is append-only and never rotated, so a single truncated write (disk
    full, SIGKILL mid-flush) must not disable the detector FOREVER, silently. That
    failure shape is the one this whole mechanism exists to find."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build-catalyst", "block", h)
                           for h in ("aaaaaaaa", "bbbbbbbb", "cccccccc")])
    p = MODULE._gate_history_path(state)
    p.write_text('{"base_name": "ios-build-cat\n' + p.read_text() + '{"truncated')
    assert MODULE._never_green(state, "ios-build-catalyst") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

def test_never_green_counts_only_block_level_rows(tmp_path):
    """A gate promoted from advisory to block would otherwise inherit the entire streak
    it built up while nobody was obliged to act on it, and trip on its first real block."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ui-quality-fast", "warn", "aaaaaaaa", level="warn"),
        _row("ui-quality-fast", "warn", "bbbbbbbb", level="warn"),
        _row("ui-quality-fast", "block", "cccccccc"),
    ])
    assert MODULE._never_green(state, "ui-quality-fast") is None

def test_never_green_reports_how_many_worktrees_the_streak_spans(tmp_path):
    """The journal is repo-wide, so three reds can be three unrelated worktrees. Say so,
    rather than letting it read as one persistent failure."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build", "block", h, wt=w) for h, w in
                           (("aaaaaaaa", "w1"), ("bbbbbbbb", "w2"), ("cccccccc", "w3"))])
    assert MODULE._never_green(state, "ios-build") == {
        "attempts": 3, "heads": 3, "worktrees": 3}

def test_never_green_folds_colon_suffixed_instances_into_one_capability(tmp_path):
    """`ios-test-ui:<Class>` names are per-diff instances of ONE check. Without folding,
    attempts never reach the threshold and the whole iOS UI family silently opts out —
    and a green from any instance must silence the rest."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ios-test-ui", "block", "aaaaaaaa", gate="ios-test-ui:FooTests"),
        _row("ios-test-ui", "block", "bbbbbbbb", gate="ios-test-ui:BarTests"),
        _row("ios-test-ui", "block", "cccccccc", gate="ios-test-ui:BazTests"),
    ])
    assert MODULE._never_green(state, "ios-test-ui") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

    _write_history(state, [
        _row("ios-test-ui", "block", "aaaaaaaa", gate="ios-test-ui:FooTests"),
        _row("ios-test-ui", "pass", "bbbbbbbb", gate="ios-test-ui:BarTests"),
        _row("ios-test-ui", "block", "cccccccc", gate="ios-test-ui:FooTests"),
    ])
    assert MODULE._never_green(state, "ios-test-ui") is None

@gitmark
def test_history_rows_carry_the_folded_base_name(scratch):
    """Pins the fold at the WRITE site too: recording the full instance name would make
    every row its own capability and the threshold unreachable."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    MODULE._append_gate_history(state, wt, "f" * 40, {"sha256": "a" * 64}, [
        {"name": "ios-test-ui:FooTests", "status": "block", "rc": 1, "level": "block"}])
    row = _history_lines(state)[-1]
    assert row["gate"] == "ios-test-ui:FooTests"
    assert row["base_name"] == "ios-test-ui"

@gitmark
def test_a_broken_journal_is_reported_not_swallowed(scratch):
    """A permanently unwritable journal and a fresh clone both look like "no history".
    If they render identically, the detector can die with zero signal."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    hist = MODULE._gate_history_path(state)
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.mkdir()

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["history_error"] and "IsADirectory" in gate["history_error"]
    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert "gate history not written" in text

def test_a_failing_gate_names_its_failing_lines_and_keeps_the_whole_output(tmp_path):
    spec = _gate_from_script(tmp_path, """\
        echo "OPENING-LINE-UNIQUE"
        i=0; while [ $i -lt 60 ]; do echo "  ✓ passing check $i"; i=$((i+1)); done
        echo "  ✗ named assertion"
        echo "══════════════════════════════"
        echo "  passed: 60  failed: 1"
        echo "══════════════════════════════"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert result["status"] == "block" and result["rc"] == 1
    # (1) the failing assertion's NAME reaches the operator, which is the whole ticket
    assert "named assertion" in result["summary"], result["summary"]
    # (2) the framing tail is still there — the new lines are added, not swapped in
    assert "passed: 60  failed: 1" in result["summary"]

    # (3) the rest survives on disk. Proven with a line that is neither failure-marked
    # nor inside the tail, so only a real capture of the child's output can contain
    # it: a log built by echoing the summary back would not.
    log = _log_pointer(result["summary"])
    assert log.is_file(), f"{log} does not exist"
    body = log.read_text(encoding="utf-8")
    assert "OPENING-LINE-UNIQUE" in body
    assert body.count("passing check") == 60
    assert "OPENING-LINE-UNIQUE" not in result["summary"], \
        "the summary stays a summary — the log is what holds everything"

def test_a_failing_gate_with_no_failure_markers_says_so_rather_than_going_quiet(
        tmp_path):
    """The negative control, and the reason it is not optional.

    Without it, "summary contains the failing line" is also satisfied by an
    implementation that simply kept printing the tail — because for many gates the
    tail IS where the failure marker sits. This one has no marker anywhere, so the
    only way to be right about it is to have actually looked and found nothing.
    """
    spec = _gate_from_script(tmp_path, """\
        echo "nothing here resembles a failure"
        echo "the last line, which is the tail"
        exit 3
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert result["rc"] == 3
    assert "no failure-marked lines found" in result["summary"], result["summary"]
    assert "the last line, which is the tail" in result["summary"]
    assert _log_pointer(result["summary"]).is_file()

    # "the last lines of the log", not "the failure". Measured cost of conflating the
    # two (IMP-20260808-8b4690): a gate went red, matched zero markers, and
    # its tail was an apparently green status line — so a BLOCKED gate displayed
    # passing lines in the slot an operator reads as evidence, and the operator
    # (correctly reading a green-looking summary) concluded the red was spurious.
    assert "NOT failure lines" in result["summary"], \
        "a zero-match tail must be labelled as not-evidence: " + result["summary"]
    assert "\n  tail:\n" not in result["summary"], \
        "the zero-match tail must not reuse the plain heading a real extraction uses"

def test_a_matched_failure_still_labels_its_tail_plainly(tmp_path):
    """The other half of the pair, and the reason the label is conditional.

    If the warning heading were unconditional it would be noise on every ordinary
    red — and a warning that fires on the happy path is one people stop reading,
    which is the failure mode this whole ticket is about, one level up.
    """
    spec = _gate_from_script(tmp_path, """\
        echo "  ✗ a marker the scanner knows"
        echo "the last line, which is the tail"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert "failure-marked lines" in result["summary"]
    assert "\n  tail:\n" in result["summary"], result["summary"]
    assert "NOT failure lines" not in result["summary"]

@pytest.mark.parametrize("marker,line", [
    ("cross", "  ✗ shell scan found a violation"),
    # U+2718, NOT the U+2717 above. Swift Testing prints this one, so every iOS test
    # failure was invisible to the extractor while the list looked complete — measured
    # on `.cache/worktree_gates/*.ios-test-unit.log`: 4 lines carry U+2718, 1 carries
    # U+2717 (IMP-20260808-8b4690). Two codepoints that render nearly identically is
    # exactly the shape a by-eye review of the tuple cannot catch.
    ("heavy-cross", "  ✘ Test testGuestGate() recorded an issue"),
    ("FAIL", "FAIL tests/test_thing.py::test_case"),
    ("AssertionError", "E   AssertionError: expected 3, got 4"),
    ("not ok", "not ok 7 - the tap-style failure"),
    ("error:", "ops/x.sh:12: error: unbound variable"),
])
def test_every_declared_failure_marker_is_actually_extracted(tmp_path, marker, line):
    """One case per marker the docstring promises.

    A single-marker test would let all but one be dropped silently, and the ones
    most likely to rot are the ones this repo uses least often day to day.

    The marker is printed FAR above the tail, and the first draft of this test did
    not do that — it sat two lines from the end, so every case passed against the
    old tail-only summary. The assertion was reading a string the OLD code had put
    there. Twenty filler lines is what makes the extractor the only possible source.
    """
    spec = _gate_from_script(tmp_path, f"""\
        echo "filler line one"
        echo "{line}"
        i=0; while [ $i -lt 20 ]; do echo "  ✓ unrelated passing line $i"; i=$((i+1)); done
        echo "filler tail line"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")
    assert line.strip() in result["summary"], f"{marker!r} not extracted: {result['summary']}"
    assert "no failure-marked lines found" not in result["summary"]

def test_the_failure_line_list_is_capped_and_says_how_many_it_shows(tmp_path):
    """The cap is what keeps the summary a summary.

    It travels into the gate record JSON and into `land`'s stdout payload, so an
    uncapped list lets one chatty gate bloat both. Untested, the slice could be
    deleted or widened and nothing would notice — the log is where the rest belongs,
    and it is one line away in the pointer.
    """
    # The three closing lines carry NO marker on purpose: the tail is reproduced in
    # the summary too, so a marker-bearing tail would make the count 23 and the test
    # would be measuring the fixture instead of the cap. (Measured — the first draft
    # did exactly that.)
    spec = _gate_from_script(tmp_path, """\
        i=0; while [ $i -lt 30 ]; do echo "  ✗ failure number $i"; i=$((i+1)); done
        echo "──────────────"
        echo "  passed: 0  failed: 30"
        echo "──────────────"
        exit 1
    """)
    summary = MODULE._run_gate(spec, str(tmp_path),
                               record_path=tmp_path / "gates" / "deadbeef.json")["summary"]
    assert summary.count("✗ failure number") == MODULE.GATE_MAX_FAILURE_LINES == 20
    assert f"({MODULE.GATE_MAX_FAILURE_LINES} shown)" in summary
    # the ones it dropped are still in the log it points at
    assert _log_pointer(summary).read_text(encoding="utf-8").count(
        "✗ failure number") == 30

def test_a_gate_going_green_clears_the_log_its_last_red_left(tmp_path):
    """A stale log outlives the failure it describes and nothing marks it stale.

    The verdict cache is overwritten on every run; its log has to obey the same rule
    or an operator opens a file describing a failure that was fixed hours ago — a
    fresh way to lose the ten minutes this ticket is about.
    """
    rec = tmp_path / "gates" / "deadbeef.json"
    red = MODULE._run_gate(_gate_from_script(tmp_path, 'echo "  ✗ boom"\nexit 1\n'),
                           str(tmp_path), record_path=rec)
    log = _log_pointer(red["summary"])
    assert log.is_file()

    green = MODULE._run_gate(_gate_from_script(tmp_path, "echo fine\nexit 0\n"),
                             str(tmp_path), record_path=rec)
    assert green["status"] == "pass"
    assert "full output" not in green["summary"], "a green gate points at no log"
    assert not log.exists(), "a green run must not leave the previous red's log behind"

def test_a_gate_run_without_a_record_path_still_reports_normally(tmp_path):
    """`_run_gate` is called directly by tests and could be by future callers; the
    log is an enhancement, not a precondition. No path, no log, no crash."""
    result = MODULE._run_gate(
        _gate_from_script(tmp_path, """\
            echo "  ✗ named thing"
            i=0; while [ $i -lt 20 ]; do echo "  ✓ filler $i"; i=$((i+1)); done
            exit 1
        """),
        str(tmp_path))
    assert result["status"] == "block" and result["rc"] == 1
    # far above the tail, so this still testifies about the extractor
    assert "named thing" in result["summary"]
    assert "full output" not in result["summary"]

def test_a_missing_gate_tool_is_a_readable_block_not_a_traceback(tmp_path):
    """The router and the tools it routes to can be different generations (IMP-0045):
    a branch that deletes a script leaves a stale router still pointing at it. Letting
    FileNotFoundError escape costs more than readability — it aborts the whole run, so
    every OTHER gate's result is lost too, and the operator is told nothing about which
    gate died."""
    spec = MODULE._shell("ghost", "ops", ["ops/definitely_not_here.sh"], "block")
    result = MODULE._run_gate(spec, str(tmp_path))
    assert result["status"] == "block"
    assert result["rc"] == 127
    assert result["executed"] is False
    # startswith, not `in`: the exception's own repr already contains the path, so
    # `"ops/... " in summary` is satisfied with the entire message deleted. Verified
    # by mutation — that assertion passed the whole suite against a stripped summary.
    assert result["summary"].startswith(
        "gate tool not runnable: cmd=ops/definitely_not_here.sh"), result["summary"]
    assert _diagnosis(result["summary"]) == \
        "FileNotFoundError on ops/definitely_not_here.sh"

def test_a_missing_gate_CWD_is_not_reported_as_a_missing_tool(tmp_path):
    """With spec["cwd"] set, the OS names the missing DIRECTORY, not the command — so
    a message built from the exception alone accuses a tool that is perfectly fine."""
    tool = tmp_path / "ops" / "docs_lint.sh"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    spec = MODULE._shell("ghost", "ops", ["ops/docs_lint.sh"], "block", cwd="backend")
    summary = MODULE._run_gate(spec, str(tmp_path))["summary"]
    assert not (tmp_path / "backend").exists(), (
        "a missing gate cwd must not be created by task-registry bookkeeping"
    )
    assert summary.startswith("gate tool not runnable: cmd=ops/docs_lint.sh")
    # `"backend" in summary` would pass against a mutant that reports the COMMAND here,
    # because the code echoes `cwd=` from the spec and "backend" appears twice. Only the
    # diagnosis clause comes from the exception, so only it can testify.
    assert _diagnosis(summary) == f"FileNotFoundError on {tmp_path}/backend"
    assert "docs_lint" not in _diagnosis(summary)

def test_an_unexecutable_gate_tool_is_reported_the_same_way(tmp_path):
    """Pins the breadth downward: narrowing the handler to FileNotFoundError silently
    reopens the hole for a script whose permission bit was lost."""
    tool = tmp_path / "ops" / "noexec.sh"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o644)
    result = MODULE._run_gate(
        MODULE._shell("ghost", "ops", ["ops/noexec.sh"], "block"), str(tmp_path))
    assert result["status"] == "block" and result["executed"] is False
    assert result["summary"].startswith("gate tool not runnable: cmd=ops/noexec.sh")
    # the OS names the command as GIVEN (relative), where the cwd case names an absolute
    # directory — which is exactly the distinction the diagnosis clause has to carry
    assert _diagnosis(result["summary"]) == "PermissionError on ops/noexec.sh"

def test_a_machine_that_cannot_fork_is_not_blamed_on_the_tool(tmp_path, monkeypatch):
    """EMFILE/ENOMEM are OSErrors that say nothing about the tool. Asserting the strong
    cause on weak evidence sends the operator hunting a stale router while a sibling
    worktree leaks fds — this repo has already lived that failure once, as pty
    exhaustion presenting as "the simulator is broken"."""
    def boom(*a, **k):
        raise OSError(errno.EMFILE, "Too many open files")
    monkeypatch.setattr(MODULE, "_run_streamed_command", boom)
    summary = MODULE._run_gate(
        MODULE._shell("ghost", "ops", ["ops/ios_ops.sh"], "block"), str(tmp_path))["summary"]
    assert "not runnable" not in summary
    assert f"errno {errno.EMFILE}" in summary
    assert "ops/ios_ops.sh" in summary

def test_a_non_oserror_from_the_runner_still_propagates(tmp_path, monkeypatch):
    """Pins the breadth upward: widening to `except Exception` would turn a genuine bug
    in this module into a confident "gate tool not runnable" block."""
    def boom(*a, **k):
        raise ValueError("a bug in the runner, not a missing tool")
    monkeypatch.setattr(MODULE, "_run_streamed_command", boom)
    with pytest.raises(ValueError):
        MODULE._run_gate(MODULE._shell("ghost", "ops", ["x"], "block"), str(tmp_path))

@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_the_tag_probe_reads_real_tags_and_reports_unreadable_as_unmeasured(tmp_path):
    """The positive control the whole mechanism rests on. Every test below monkeypatches
    `_tag_snapshot`, so a probe that silently returned None on every real repo would
    leave all of them green while the feature never fired once in production — a
    detector that cannot be observed failing is the disease this repo keeps catching.

    The other half is just as load-bearing: a path that is not a repo must come back
    UNMEASURED, not as an empty tag set. Empty-vs-populated would read as "every tag was
    just deleted" and turn honest reds into inconclusives."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True,  # noqa: E731
                                    capture_output=True)
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
        "--allow-empty", "-m", "x")
    run("tag", "v1")
    before = MODULE._tag_snapshot(repo)
    assert before is not None and "refs/tags/v1" in before
    run("tag", "v2")
    one_added = MODULE._tag_snapshot(repo)
    assert MODULE._tag_delta(before, one_added) == 1
    assert MODULE._tag_delta(before, before) == 0

    # the count is a count, not the constant 1: two more tags must read as two
    run("tag", "v3")
    run("tag", "v4")
    assert MODULE._tag_delta(one_added, MODULE._tag_snapshot(repo)) == 2
    # and a MOVED tag is one removal plus one addition — the docstring's claim, pinned
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
        "--allow-empty", "-m", "y")
    four = MODULE._tag_snapshot(repo)
    run("tag", "-f", "v1")
    assert MODULE._tag_delta(four, MODULE._tag_snapshot(repo)) == 2

    # unmeasured never counts as a change — BOTH ways it can happen:
    # a path that does not exist at all, and a real directory that is not a repo.
    missing = MODULE._tag_snapshot(tmp_path / "does-not-exist")
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    outside = MODULE._tag_snapshot(not_a_repo)
    assert missing is None and outside is None
    assert MODULE._tag_delta(before, outside) == 0
    assert MODULE._tag_delta(outside, four) == 0

def test_a_failing_gate_during_a_tag_change_is_inconclusive_not_block(tmp_path, monkeypatch):
    """A linked worktree shares `refs/` with the primary, so `release.sh` creating a tag
    over there changes what a child gate reads over here. Measured 2026-08-05: a batch
    gate saw `ops/test_ios_ops.sh` report 371 passed / 1 failed, rc=1; the same input
    rerun alone was 371 green, exit 0. In the gate's eyes that red was indistinguishable
    from a real one — the colour was a function of machine state, not of the branch.

    So the orchestrator says which one it measured. `inconclusive` is neither pass nor
    block: block would kill work for someone else's tag surgery, pass would let a real
    red through."""
    snaps = iter(["a1 refs/tags/v1",
                  "a1 refs/tags/v1\nb2 refs/tags/v2\nc3 refs/tags/v3"])
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: next(snaps))
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  passed: 371  failed: 1", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    assert r["status"] == "inconclusive"
    assert r["rc"] == 1, "the real rc must survive — the point is attribution, not amnesia"
    assert r["refs_changed"] is True
    # the count comes from the two snapshots THIS test supplied, not from a constant:
    # two tags appear, so a hard-coded "1" in the summary fails here
    assert "2 tag(s)" in r["summary"]
    assert MODULE.aggregate_verdict([r]) == "warn"

def test_a_failing_gate_with_stable_tags_still_blocks(tmp_path, monkeypatch):
    """The reverse guard, and the reason the pair is the acceptance rather than the one
    above alone: `_run_gate` rewritten to return `inconclusive` unconditionally would
    satisfy the positive test and disarm every block gate in the repo."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "a1 refs/tags/v1")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ boom", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    assert r["status"] == "block"
    assert r.get("refs_changed") is not True
    assert MODULE.aggregate_verdict([r]) == "block"

def test_contention_machine_state_detects_ios_processes_and_active_worktrees(
        tmp_path, monkeypatch):
    """The machine snapshot must be executable evidence, not an agent guess.

    Keep the process probe synthetic: starting a process whose argv merely contains
    ``xcodebuild`` would make this test slow and would not prove the parser's shape.
    The registry count is read from the same state file the orchestrator receives, so
    the result is scoped to the machine/workflow that produced the verdict.
    """
    state = tmp_path / "registry.json"
    state.write_text(json.dumps({"records": [
        {"status": "active", "path": "/tmp/a"},
        {"status": "merged", "path": "/tmp/b"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(MODULE.os, "getloadavg", lambda: (3.0, 2.0, 1.0))

    def fake_run(argv, **kwargs):
        assert argv == ["ps", "-axo", "pid=,command="]
        return subprocess.CompletedProcess(
            argv, 0,
            stdout="123 xcodebuild -scheme BooksAndVocab\n"
                   "456 /bin/bash ops/ios_test.sh --unit\n"
                   "789 python unrelated.py\n",
            stderr="",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    snapshot = MODULE._machine_state(str(state))

    assert snapshot["load_average"] == [3.0, 2.0, 1.0]
    assert snapshot["active_worktrees"] == 1
    assert snapshot["active_ios_process_count"] == 2
    assert snapshot["active_ios_processes"] == [
        {"pid": 123, "kind": "xcodebuild"},
        {"pid": 456, "kind": "ios_test.sh"},
    ]
    assert snapshot["probe_errors"] == []

def test_contention_sensitive_red_names_machine_and_rerun_command(tmp_path, monkeypatch):
    """A red under iOS contention stays red but explains how to reproduce it quietly."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ concurrency assertion", 1.0))
    busy = {
        "load_average": [8.0, 7.0, 6.0],
        "active_worktrees": 3,
        "active_ios_process_count": 1,
        "active_ios_processes": [{"pid": 123, "kind": "xcodebuild"}],
        "probe_errors": [],
    }
    monkeypatch.setattr(MODULE, "_machine_state", lambda _state=None: busy)

    spec = MODULE._shell("ios-test-unit", "ios",
                         ["ops/ios_ops.sh", "test", "--unit", "--lease"], "block")
    result = MODULE._run_gate(spec, str(tmp_path))

    assert result["status"] == "block", "contention must not downgrade a real red"
    assert result["machine_state"]["contention"] is True
    assert result["machine_state"]["contention_processes"] == busy["active_ios_processes"]
    assert "machine contention detected" in result["summary"]
    assert "may be non-reproducible" in result["summary"]
    assert "xcodebuild" in result["summary"]
    assert "Re-run when quiet" in result["summary"]
    assert "ops/ios_ops.sh test --unit --lease" in result["summary"]
    assert result["contention_warning"] is True

    state = tmp_path / "history-state.json"
    assert MODULE._append_gate_history(
        str(state), str(tmp_path), "a" * 40, {"sha256": "b" * 64}, [result]
    ) is None
    row = MODULE.gate_history_rows(str(state))[-1]
    assert row["machine_state"]["contention"] is True

def test_contention_warning_is_absent_when_machine_is_quiet(tmp_path, monkeypatch):
    """The warning must not become boilerplate that operators learn to ignore."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ real assertion", 1.0))
    quiet = {
        "load_average": [0.1, 0.2, 0.3],
        "active_worktrees": 1,
        "active_ios_process_count": 0,
        "active_ios_processes": [],
        "probe_errors": [],
    }
    monkeypatch.setattr(MODULE, "_machine_state", lambda _state=None: quiet)

    result = MODULE._run_gate(
        MODULE._shell("ops-shell:test_ios_test_discovery.sh", "ops",
                      ["ops/test_ios_test_discovery.sh"], "block"),
        str(tmp_path),
    )

    assert result["status"] == "block"
    assert result["machine_state"]["contention"] is False
    assert "machine contention detected" not in result["summary"]
    assert result.get("contention_warning") is not True

def test_a_red_whose_refs_probe_failed_says_so_instead_of_going_quiet(tmp_path, monkeypatch):
    """Fail-safe is the right direction — an unreadable probe must not downgrade a red —
    but silent fail-safe is not what this module does anywhere else. `history_error`,
    `log_error` and `executed: False` all exist for one reason: "could not measure" must
    not look identical to "measured, nothing happened". Without this, the probe going
    permanently blind on some machine reinstates the whole bug with zero signal.
    Found by review of IMP-20260805-4ec901."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: None)
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ boom", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    # the red still counts — fail-safe direction is unchanged
    assert r["status"] == "block"
    assert r.get("refs_changed") is not True
    # but the inability to attribute it is on the record, not swallowed
    assert r["refs_probe"] == "unmeasured"
    assert "unmeasured" in r["summary"]

    # control: when the probe DOES work and sees nothing, there is no such noise
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "a1 refs/tags/v1")
    clean = MODULE._run_gate(spec, str(tmp_path))
    assert clean["status"] == "block"
    assert "refs_probe" not in clean
    assert "unmeasured" not in clean["summary"]

def test_an_inconclusive_gate_is_not_evidence_that_it_can_never_pass(tmp_path):
    """Same family as the spawn-failure exclusion below, and the same reasoning: a red
    that was contaminated by someone else's tag surgery is not a data point about
    whether this gate can pass. It is journalled at `level: block` and `executed: True`,
    so without an explicit exclusion it would count toward the never-green streak and
    the NEXT genuine red would arrive carrying "no green ever recorded" — steering the
    reader away from their own bug, which is the exact harm `executed: False` exists to
    prevent."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    poisoned = [{"name": "ops-shell:test_ios_ops.sh", "level": "block",
                 "status": "inconclusive", "rc": 1, "refs_changed": True}]
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        assert MODULE._append_gate_history(state, str(tmp_path), head, orch,
                                           poisoned) is None
    assert MODULE._never_green(state, "ops-shell") is None

    # positive control: three ordinary reds on the same gate DO make the streak
    real = [{"name": "ops-shell:test_ios_ops.sh", "level": "block", "status": "block",
             "rc": 1}]
    for head in ("dddddddd", "eeeeeeee", "ffffffff"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, real)
    assert MODULE._never_green(state, "ops-shell") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

def test_a_gate_that_never_started_is_not_evidence_about_whether_it_can_pass(tmp_path):
    """`_never_green` reads level and status, never rc — so spawn failures would count
    as block attempts and push a healthy gate over the 3-attempt threshold. The next
    genuine red would then arrive carrying "no green ever recorded", which is exactly
    the wrong hypothesis to hand someone."""
    state = str(tmp_path / "reg.json")
    unexecuted = [{"name": "docs-lint", "level": "block", "status": "block",
                   "rc": 127, "executed": False}]
    orch = {"sha256": "a" * 64}
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        assert MODULE._append_gate_history(state, str(tmp_path), head, orch,
                                           unexecuted) is None
    assert MODULE._never_green(state, "docs-lint") is None

    ran = [{"name": "docs-lint", "level": "block", "status": "block", "rc": 1}]
    for head in ("dddddddd", "eeeeeeee", "ffffffff"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, ran)
    assert MODULE._never_green(state, "docs-lint") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

def test_gate_history_ignores_unestablished_rows_for_attempts_and_greens(tmp_path):
    """A producer that checked nothing must not prove a gate or inflate its streak."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        MODULE._append_gate_history(
            state, str(tmp_path), head, orch,
            [{"name": "ops-shell-syntax", "level": "block",
              "status": "block", "rc": 1, "established": False}],
        )
    MODULE._append_gate_history(
        state, str(tmp_path), "dddddddd", orch,
        [{"name": "ops-shell-syntax", "level": "block",
          "status": "pass", "rc": 0, "established": False}],
    )
    assert MODULE.gate_history_verdicts(state, ["ops-shell-syntax"])["ops-shell-syntax"] == {
        "verdict": "unproven", "attempts": 0, "heads": 0,
        "worktrees": 0, "last_green": None,
    }

def test_both_journal_consumers_read_it_through_the_same_function(tmp_path):
    """`gate_history_verdicts` is THE reader. The shell side used to parse the journal
    itself, and the two copies disagreed the moment `executed` was added: identical rows
    read as "never green" in one and "no data" in the other."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    unexecuted = [{"name": "ios-build", "level": "block", "status": "block",
                   "rc": 127, "executed": False}]
    for head in ("11111111", "22222222", "33333333"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, unexecuted)
    v = MODULE.gate_history_verdicts(state, ["ios-build"])["ios-build"]
    assert v == {"verdict": "unproven", "attempts": 0, "heads": 0,
                 "worktrees": 0, "last_green": None}
    assert len(MODULE.gate_history_rows(state)) == 3   # the rows ARE there, just mute

    MODULE._append_gate_history(state, str(tmp_path), "44444444", orch,
                                [{"name": "ios-build", "level": "block",
                                  "status": "pass", "rc": 0}])
    v = MODULE.gate_history_verdicts(state, ["ios-build"])["ios-build"]
    assert v["verdict"] == "proven" and v["attempts"] == 1 and v["last_green"]

def test_gate_can_fail_does_not_keep_its_own_copy_of_the_journal_reader():
    """Pins the single-reader property itself. Without this, the duplicate simply comes
    back the next time someone needs one more field out of the journal — which is how it
    arrived the first time."""
    src = (ROOT / "ops" / "tests" / "test_gate_can_fail.sh").read_text()
    assert "gate_history_verdicts" in src, "the shell side must call the shared reader"
    assert "json.loads" not in src, "a second journal parser has reappeared"

def test_a_missing_warn_level_tool_stays_advisory(tmp_path):
    """Level is the disposition; a missing tool must not promote an advisory into a
    blocker (nor the reverse — see the rc!=0 branch it mirrors)."""
    spec = MODULE._shell("ghost", "ops", ["ops/definitely_not_here.sh"], "warn")
    assert MODULE._run_gate(spec, str(tmp_path))["status"] == "warn"

@gitmark
def test_gate_reuse_records_and_reuses_out_of_scope_inputs(scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    rc, opened = _run_json(["open", "--intent", "gate reuse", "--slug", "reuse",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    (Path(wt) / "ops" / "lib" / "foo.py").write_text("value = 1\n")
    (Path(wt) / "ops" / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add gate input fixture"], wt)

    calls = []

    def fake_run(spec, worktree, *, record_path=None, state=None):
        calls.append(spec["name"])
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "fixture gate ran"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    first_head = first["head_sha"]
    ops_first = next(g for g in first["gates"] if g["name"] == "ops-pytest")
    assert calls == ["ops-python-scan", "ops-pytest", "coverage"]
    assert {"ops/lib/foo.py", "ops/tests/test_foo.py"}.issubset(
        ops_first["input"]["files"]
    )
    assert "ops/python_scan.py" in ops_first["input"]["files"]
    assert ops_first["input"]["fingerprint"]
    assert ops_first["reuse"]["decision"] == "rerun"
    progress_path = MODULE._gate_progress_path(state, wt)
    first_progress = json.loads(progress_path.read_text(encoding="utf-8"))
    first_run_id = first_progress["run_id"]

    (Path(wt) / "notes.txt").write_text("unrelated backlog follow-up\n")
    _git(["add", "notes.txt"], wt)
    _git(["commit", "-qm", "docs: add unrelated follow-up note"], wt)
    calls.clear()
    rc, second = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_second = next(g for g in second["gates"] if g["name"] == "ops-pytest")
    assert calls == ["coverage"], "the expensive ops gate must be reused"
    assert second["head_sha"] != first_head
    assert ops_second["reused"] is True
    assert ops_second["reused_from_head"] == first_head
    assert ops_second["reuse"] == {"decision": "reused", "source_head": first_head,
                                    "reason": "input_unchanged"}
    assert second["gate_reuse"]["reused"] == [
        {"name": "ops-python-scan", "source_head": first_head, "reason": "input_unchanged"},
        {"name": "ops-pytest", "source_head": first_head, "reason": "input_unchanged"},
    ]

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["head_sha"] == second["head_sha"]
    assert progress["run_id"] != first_run_id
    assert progress["done"] == progress["plan_total"] == len(second["gates"])
    assert progress["completed"] == [
        {"name": result["name"], "status": result["status"]}
        for result in second["gates"]
    ]

    # The progress sidecar is deliberately not a cutover input. Invalidating it must
    # not affect the verdict record produced above.
    progress_path.write_text("not-json\n", encoding="utf-8")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, cut
    assert cut["gate_reuse"]["reused"][0]["source_head"] == first_head
    rc, resolved = _run_json(["resolve", "--worktree", wt, "--state", state,
                              "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, resolved
    assert resolved["gate_progress_removed"] is True
    assert not progress_path.exists(), "resolve must leave no progress sidecar residue"

def test_gate_reuse_separates_ios_build_and_test_tool_inputs(tmp_path, monkeypatch):
    """A test-runner repair must not invalidate already-green build gates.

    This is the concrete retry shape: the first run compiled successfully but an iOS
    test gate failed; the repair changes only ios_test.sh.  Build and test both consume
    ios_ops.sh, but only the test gate consumes ios_test.sh.
    """
    monkeypatch.setattr(MODULE, "_git", lambda *args, **kwargs: (0, ""))
    tracked = [
        "ios/App.swift",
        "ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift",
        "ops/ios_ops.sh",
        "ops/ios_build.sh",
        "ops/ios_test.sh",
        "ops/ios_diagnostics.py",
        "ops/ios_coverage.py",
        "ops/ui_world_manifest.py",
        "ops/uitest_review_page.py",
        "ops/fixtures/ui_worlds/marketing_demo.json",
        "ops/lib/ios_ops_core.sh",
        "ops/lib/ios_build_progress.sh",
        "ops/lib/ios_test_discovery.sh",
    ]
    for rel in tracked:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rel}\n")

    specs = _by_name(MODULE.plan_gates(
        ["ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift"],
        ops_test_exists=lambda rel: rel in tracked,
    ))
    build = specs["ios-build"]
    test = specs["ios-test-unit"]
    live_compile = specs["ios-live-demo-uitest-compile"]
    build_before = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_before = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)
    live_before = MODULE._gate_input_scope(
        live_compile, str(tmp_path), tracked[:1], tracked)

    assert "ops/ios_ops.sh" in build_before["files"]
    assert "ops/ios_ops.sh" in test_before["files"]
    assert "ops/ios_build.sh" in build_before["files"]
    assert "ops/ios_test.sh" not in build_before["files"]
    assert "ops/ios_test.sh" in test_before["files"]
    assert "ops/ios_build.sh" not in test_before["files"]
    assert "ops/ios_diagnostics.py" in build_before["files"]
    assert "ops/ios_coverage.py" in test_before["files"]
    assert "ops/uitest_review_page.py" in test_before["files"]
    assert "ops/fixtures/ui_worlds/marketing_demo.json" in test_before["files"]
    assert live_before["kind"] == "tracked-ios-test-surface"
    assert "ops/ios_test.sh" in live_before["files"]

    previous = {
        "schema": MODULE.GATE_SCHEMA,
        "base": "main",
        "head_sha": "a" * 40,
        "orchestrator": {"sha256": "same"},
        "gates": [
            {"name": "ios-build", "category": "ios", "level": "block",
             "status": "pass", "rc": 0, "summary": "green", "input": build_before},
            {"name": "ios-test-unit", "category": "ios", "level": "block",
             "status": "pass", "rc": 0, "summary": "green", "input": test_before},
        ],
    }
    (tmp_path / "ops/ios_test.sh").write_text("repaired test runner\n")
    build_after = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_after = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)

    reused, reason = MODULE._reuse_gate(
        build, build_after, previous, None, {"sha256": "same"})
    assert reused is not None and reason == "input_unchanged"
    rerun, reason = MODULE._reuse_gate(
        test, test_after, previous, None, {"sha256": "same"})
    assert rerun is None and reason == "input_content_changed"

    # A shared dispatcher edit still invalidates both commands; the optimization
    # may narrow proven dependencies, never wish them away.
    (tmp_path / "ops/ios_test.sh").write_text("ops/ios_test.sh\n")
    (tmp_path / "ops/ios_ops.sh").write_text("changed shared dispatcher\n")
    build_shared = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_shared = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)
    for spec, current in ((build, build_shared), (test, test_shared)):
        reused, reason = MODULE._reuse_gate(
            spec, current, previous, None, {"sha256": "same"})
        assert reused is None and reason == "input_content_changed"

    # Runtime helpers are verdict inputs too.  A diagnostics edit affects both
    # runners; UI-world data/validation affects test gates but not app builds.
    for rel in ("ops/ios_ops.sh", "ops/ios_test.sh"):
        (tmp_path / rel).write_text(f"{rel}\n")
    runtime_mutations = [
        ("ops/ios_diagnostics.py", True, True),
        ("ops/ui_world_manifest.py", False, True),
        ("ops/fixtures/ui_worlds/marketing_demo.json", False, True),
    ]
    for rel, invalidates_build, invalidates_test in runtime_mutations:
        path = tmp_path / rel
        original = path.read_text()
        path.write_text("mutated runtime input\n")
        for spec, before, should_invalidate in (
            (build, build_before, invalidates_build),
            (test, test_before, invalidates_test),
        ):
            current = MODULE._gate_input_scope(spec, str(tmp_path), tracked[:1], tracked)
            prior = {**previous, "gates": [
                {"name": spec["name"], "category": "ios", "level": "block",
                 "status": "pass", "rc": 0, "summary": "green", "input": before},
            ]}
            reused, reason = MODULE._reuse_gate(
                spec, current, prior, None, {"sha256": "same"})
            if should_invalidate:
                assert reused is None and reason == "input_content_changed", rel
            else:
                assert reused is not None and reason == "input_unchanged", rel
        path.write_text(original)

    unknown = MODULE._internal("future-ios-gate", "ios", "block")
    unknown_scope = MODULE._gate_input_scope(
        unknown, str(tmp_path), tracked[:1], tracked)
    assert unknown_scope["kind"] == "tracked-ios-surface"
    assert "ops/ios_build.sh" in unknown_scope["files"]
    assert "ops/ios_test.sh" in unknown_scope["files"]

def test_gate_progress_treats_invalid_utf8_as_unreadable(tmp_path):
    progress_path = tmp_path / "gate.progress.json"
    progress_path.write_bytes(b"\xff\xfe\n")

    assert MODULE._read_gate_progress(progress_path) is None

def test_ios_gate_input_map_covers_declared_shell_dependencies():
    """A new sourced helper must not silently sit outside the reuse fingerprint."""
    def declared_libs(rel):
        text = (ROOT / rel).read_text()
        return {f"ops/lib/{name}" for name in re.findall(
            r"(?:source|METRICS_LIB=)[^\n]*?/lib/([A-Za-z0-9_]+[.]sh)", text)}

    def declared_files(rel):
        text = (ROOT / rel).read_text()
        names = re.findall(
            r"[$](?:SCRIPT_DIR|PROJECT_ROOT)/(?:ops/)?([A-Za-z0-9_./-]+[.](?:py|sh))",
            text,
        )
        return {f"ops/{name}" for name in names}

    common = set(MODULE._IOS_OPS_COMMON_INPUTS)
    common.update(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "ops/lib").glob("ios_ops_*.sh")
    )
    assert declared_libs("ops/ios_ops.sh") <= common
    assert declared_libs("ops/lib/ios_ops_catalog.sh") <= common
    assert declared_files("ops/ios_build.sh") <= (
        common | set(MODULE._IOS_BUILD_INPUTS))
    test_inputs = common | set(MODULE._IOS_TEST_INPUTS)
    test_inputs.update(
        p.relative_to(ROOT).as_posix()
        for pattern in ("ops/uitest_review_*.py", "ops/catalog_*.py")
        for p in ROOT.glob(pattern)
    )
    assert "ops/lib/ios_xctestrun_cache.sh" in MODULE._IOS_TEST_INPUTS
    assert declared_files("ops/ios_test.sh") <= test_inputs

@gitmark
def test_gate_reuse_is_fail_safe_for_changed_unknown_legacy_and_bad_sources(
        scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "gate reuse", "--slug", "reuse-fail-safe",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    foo = Path(wt) / "ops" / "lib" / "foo.py"
    test = Path(wt) / "ops" / "tests" / "test_foo.py"
    foo.write_text("value = 1\n")
    test.write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add gate input fixture"], wt)

    def fake_run(spec, worktree, *, record_path=None, state=None):
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "fixture gate ran"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_spec = next(s for s in MODULE.plan_gates(
        first["changed_files"], ops_test_exists=lambda rel: (Path(wt) / rel).is_file(),
        base="main") if s["name"] == "ops-pytest")

    foo.write_text("value = 2\n")
    _git(["add", "ops/lib/foo.py"], wt)
    _git(["commit", "-qm", "ops: change gate input"], wt)
    rc, changed = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_changed = next(g for g in changed["gates"] if g["name"] == "ops-pytest")
    assert ops_changed["reused"] is False
    assert ops_changed["reuse"]["reason"] == "input_content_changed"

    tracked = MODULE._tracked_paths(wt)
    unknown_spec = MODULE._internal("future-gate", "meta", "block")
    unknown = MODULE._gate_input_scope(unknown_spec, wt, changed["changed_files"], tracked)
    assert unknown["reusable"] is False
    previous, error = MODULE._read_gate_record(MODULE._gate_record_path(state, wt))
    assert error is None
    orch = MODULE._orchestrator_identity(wt)
    current_input = next(g for g in changed["gates"] if g["name"] == "ops-pytest")["input"]
    reused, reason = MODULE._reuse_gate(unknown_spec, unknown, previous, error, orch)
    assert reused is None and reason == "input_scope_not_reusable"

    legacy = json.loads(json.dumps(previous))
    legacy_ops = next(g for g in legacy["gates"] if g["name"] == "ops-pytest")
    legacy_ops.pop("input")
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, legacy, None, orch)
    assert reused is None and reason == "source_record_has_no_input_fingerprint"

    blocked = json.loads(json.dumps(previous))
    next(g for g in blocked["gates"] if g["name"] == "ops-pytest")["status"] = "block"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, blocked, None, orch)
    assert reused is None and reason == "source_status_block"
    inconclusive = json.loads(json.dumps(previous))
    next(g for g in inconclusive["gates"] if g["name"] == "ops-pytest")["status"] = "inconclusive"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, inconclusive, None, orch)
    assert reused is None and reason == "source_status_inconclusive"

    wrong_current = json.loads(json.dumps(current_input))
    wrong_current["schema"] = "wrong.input.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, wrong_current, previous, None, orch)
    assert reused is None and reason == "current_input_schema_unknown"
    wrong_source = json.loads(json.dumps(previous))
    wrong_source["schema"] = "wrong.gate.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, wrong_source, None, orch)
    assert reused is None and reason == "source_record_schema_unknown"
    wrong_input = json.loads(json.dumps(previous))
    next(g for g in wrong_input["gates"] if g["name"] == "ops-pytest")["input"]["schema"] = "wrong.input.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, wrong_input, None, orch)
    assert reused is None and reason == "source_input_schema_unknown"

    malformed_null_gates = json.loads(json.dumps(previous))
    malformed_null_gates["gates"] = None
    reused, reason = MODULE._reuse_gate(
        ops_spec, current_input, malformed_null_gates, None, orch)
    assert reused is None and reason == "source_record_gates_invalid"

    malformed_gate_item = json.loads(json.dumps(previous))
    malformed_gate_item["gates"] = ["not-a-gate"]
    reused, reason = MODULE._reuse_gate(
        ops_spec, current_input, malformed_gate_item, None, orch)
    assert reused is None and reason == "source_record_gates_invalid"

@gitmark
def test_gate_reuse_refuses_head_move_during_input_snapshot(scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "gate race", "--slug", "reuse-race",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    (Path(wt) / "ops" / "lib" / "foo.py").write_text("value = 1\n")
    (Path(wt) / "ops" / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add race fixture"], wt)
    initial = _git(["rev-parse", "HEAD"], wt)
    moved = _git(["rev-parse", "main"], repo)
    calls = []

    def fake_head(path):
        calls.append(path)
        return initial if len(calls) == 1 else moved

    def fake_run(*args, **kwargs):
        raise AssertionError("a moving HEAD must refuse before running a gate")

    monkeypatch.setattr(MODULE, "_head_sha", fake_head)
    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "HEAD moved while preparing gate inputs" in gate["error"]
    assert not MODULE._gate_record_path(state, wt).exists()

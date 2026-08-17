"""Behavior-group collector for worktree_orchestrate (recovery)."""

from worktree_orchestrate_support import *  # noqa: F401,F403

def test_delivery_anchor_guard_checks_primary_branch_inside_advance_lock(
        tmp_path, monkeypatch):
    @contextmanager
    def fake_lock(_primary):
        yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(
        MODULE, "_primary_ff_ready",
        lambda *_args, **_kwargs: ("primary is on the wrong branch", {}),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_primary_dirty",
        lambda _primary: pytest.fail("dirty check must not run after branch refusal"),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: pytest.fail(
            "registry must not run after branch refusal"
        ),
    )

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main"), tmp_path, set(), "delivery-wave", None
    )

    assert rc == MODULE.EXIT_BLOCK
    assert steps[0]["name"] == "anchor-guard"
    assert "wrong branch" in steps[0]["error"]

def test_delivery_anchor_noop_marker_empty_queue_is_explicit_noop_and_replayable(
        tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo, check=True)
    backlog = repo / "docs" / "runbook" / "backlog"
    backlog.mkdir(parents=True)
    (backlog / "README").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {"expected_ticket_ids": []},
    }), encoding="utf-8")

    @contextmanager
    def fake_lock(_primary):
        yield

    calls = 0

    def fake_anchor(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1",
            "mode": "commit",
            "applied": [],
            "problems": [],
            "unstamped": [],
        }

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda *_a, **_k: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_anchor)
    args = argparse.Namespace(base="main", state=None)

    for _ in range(2):
        rc, steps = MODULE._delivery_anchor_and_commit(
            args, repo, set(), "delivery-wave", manifest
        )
        assert rc == MODULE.EXIT_OK
        anchor_commit = next(
            step["payload"] for step in steps if step.get("name") == "anchor-commit"
        )
        assert anchor_commit["committed"] is False
        assert anchor_commit["noop"] is True
        marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
        assert marker["anchor_noop"] is True
        assert marker["anchor_committed"] is False
        assert "anchor_commit_sha" not in marker
        assert marker["phases"]["anchor"]["status"] == "completed"
        assert marker["phases"]["anchor"]["queue_state"] == "consumed"

    assert calls == 2
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout

def test_anchor_noop_recovery_after_metadata_commit(tmp_path, monkeypatch):
    """A durable noop may resume after a legal backlog metadata-only advance."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo, check=True)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    ticket_id = "IMP-20260812-noop-recovery"
    ticket = repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text('{"status":"triaged"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    queue = repo / MODULE.ANCHOR_QUEUE
    queue.parent.mkdir(parents=True)
    queue.write_text("", encoding="utf-8")
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {
            "expected_ticket_ids": [ticket_id],
            "anchor_base_sha": base_sha,
            "anchor_ids": [],
            "anchor_committed": False,
            "anchor_noop": True,
            "phases": {"anchor": {
                "status": "completed",
                "operation_base": base_sha,
                "landed_sha": base_sha,
                "expected_ticket_ids": [ticket_id],
                "applied_ticket_ids": [],
                "acceptance_receipt": {
                    "schema": "kg.backlog.anchor.v1",
                    "mode": "commit",
                    "applied": [],
                    "problems": [],
                },
                "queue_state": "consumed",
            }},
            "last_successful_phase": "anchor",
        },
    }), encoding="utf-8"),

    # This is the legal primary-side verify/groom advance that happened after
    # the noop marker was persisted: only the expected backlog document moves.
    ticket.write_text('{"status":"fixed","fixed_by":"metadata"}\n', encoding="utf-8")
    subprocess.run(["git", "add", str(ticket)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: verify metadata"], cwd=repo,
                   check=True)
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    assert current_sha != base_sha
    assert subprocess.run(
        ["git", "diff", "--name-only", base_sha, current_sha], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines() == [f"docs/runbook/backlog/{ticket_id}.json"]

    @contextmanager
    def fake_lock(_primary):
        yield

    def fake_anchor(*_args, **_kwargs):
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1",
            "mode": "commit",
            "applied": [],
            "problems": [],
            "unstamped": [],
        }

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda *_a, **_k: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_anchor)

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )
    assert rc == MODULE.EXIT_OK
    anchor_commit = next(
        step["payload"] for step in steps if step.get("name") == "anchor-commit"
    )
    assert anchor_commit["committed"] is False
    assert anchor_commit["noop"] is True
    marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert marker["anchor_noop"] is True
    assert marker["anchor_committed"] is False
    assert "anchor_commit_sha" not in marker
    assert marker["anchor_base_sha"] == current_sha
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout

def test_anchor_noop_recovery_after_multiple_metadata_commits(
        tmp_path, monkeypatch):
    """A noop survives every canonical metadata commit in one recovery wave."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo, check=True)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    ticket_id = "IMP-20260813-noop-recovery"
    backlog = repo / "docs" / "runbook" / "backlog"
    backlog.mkdir(parents=True)
    ticket = backlog / f"{ticket_id}.json"
    sibling = backlog / "IMP-20260813-legitimate-metadata.json"
    baseline = repo / "ops" / "backlog_closed_unverified_baseline.txt"
    baseline.parent.mkdir(parents=True)
    ticket.write_text('{"status":"triaged"}\n', encoding="utf-8")
    sibling.write_text('{"status":"open"}\n', encoding="utf-8")
    baseline.write_text("baseline-v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    queue = repo / MODULE.ANCHOR_QUEUE
    queue.parent.mkdir(parents=True)
    queue.write_text("", encoding="utf-8")
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {
            "expected_ticket_ids": [ticket_id],
            "anchor_base_sha": base_sha,
            "anchor_ids": [],
            "anchor_committed": False,
            "anchor_noop": True,
            "phases": {"anchor": {
                "status": "completed",
                "operation_base": base_sha,
                "landed_sha": base_sha,
                "expected_ticket_ids": [ticket_id],
                "applied_ticket_ids": [],
                "acceptance_receipt": {
                    "schema": "kg.backlog.anchor.v1",
                    "mode": "commit",
                    "applied": [],
                    "problems": [],
                },
                "queue_state": "consumed",
            }},
            "last_successful_phase": "anchor",
        },
    }), encoding="utf-8")

    # Three independent, canonical metadata-only advances after the noop.
    ticket.write_text('{"status":"fixed","fixed_by":"metadata-1"}\n',
                       encoding="utf-8")
    subprocess.run(["git", "add", str(ticket)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: verify expected metadata"],
                   cwd=repo, check=True)
    sibling.write_text('{"status":"fixed","fixed_by":"metadata-2"}\n',
                       encoding="utf-8")
    subprocess.run(["git", "add", str(sibling)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: verify sibling metadata"],
                   cwd=repo, check=True)
    baseline.write_text("baseline-v2\n", encoding="utf-8")
    subprocess.run(["git", "add", str(baseline)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: refresh generated baseline"],
                   cwd=repo, check=True)
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    assert current_sha != base_sha
    changed = subprocess.run(
        ["git", "diff", "--name-only", base_sha, current_sha], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert changed == [
        "docs/runbook/backlog/IMP-20260813-legitimate-metadata.json",
        f"docs/runbook/backlog/{ticket_id}.json",
        "ops/backlog_closed_unverified_baseline.txt",
    ]

    @contextmanager
    def fake_lock(_primary):
        yield

    def fake_anchor(*_args, **_kwargs):
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1",
            "mode": "commit",
            "applied": [],
            "problems": [],
            "unstamped": [],
        }

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda *_a, **_k: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_anchor)

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )
    assert rc == MODULE.EXIT_OK
    anchor_commit = next(
        step["payload"] for step in steps if step.get("name") == "anchor-commit"
    )
    assert anchor_commit["committed"] is False
    assert anchor_commit["noop"] is True
    marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert marker["anchor_noop"] is True
    assert marker["anchor_committed"] is False
    assert "anchor_commit_sha" not in marker
    assert marker["anchor_base_sha"] == current_sha
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout

    # A similarly named nested path is not canonical backlog metadata.
    nested_base_sha = current_sha
    nested = backlog / "nested" / "rogue.json"
    nested.parent.mkdir(parents=True)
    nested.write_text('{"status":"foreign"}\n', encoding="utf-8")
    subprocess.run(["git", "add", str(nested)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: foreign nested metadata"],
                   cwd=repo, check=True)
    persisted = json.loads(manifest.read_text(encoding="utf-8"))
    persisted["close_wave"]["anchor_base_sha"] = nested_base_sha
    manifest.write_text(json.dumps(persisted), encoding="utf-8")
    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )
    assert rc == MODULE.EXIT_BLOCK
    assert any(
        step.get("name") == "anchor-guard"
        and "primary moved after the persisted anchor base" in step.get("error", "")
        for step in steps
    )

@pytest.mark.parametrize(
    "illegal_path",
    [
        "docs/runbook/backlog/nested/rogue.json",
        "retired/foreign.json",
    ],
)
def test_noop_recovery_rejects_nested_or_foreign_source_paths(
        tmp_path, illegal_path):
    """Noop provenance accepts only top-level backlog metadata and baseline."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    ticket_id = "IMP-20260813-noop-recovery"
    ticket = repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text('{"status":"triaged"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    illegal = repo / illegal_path
    illegal.parent.mkdir(parents=True, exist_ok=True)
    illegal.write_text("foreign\n", encoding="utf-8")
    subprocess.run(["git", "add", str(illegal)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "foreign path"], cwd=repo, check=True)
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    marker = {
        "anchor_noop": True,
        "anchor_committed": False,
        "expected_ticket_ids": [ticket_id],
        "phases": {"anchor": {
            "status": "completed",
            "applied_ticket_ids": [],
            "queue_state": "consumed",
            "acceptance_receipt": {
                "schema": "kg.backlog.anchor.v1",
                "applied": [],
                "problems": [],
            },
        }},
    }
    assert not MODULE._delivery_anchor_noop_recovery_is_safe(
        repo, marker, stored_base=base_sha, current_head=current_head,
    )

def test_noop_recovery_preserves_true_anchor_exact_identity_refusal(tmp_path):
    """A true anchor still requires its exact persisted commit identity."""
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    ticket_id = "IMP-20260809-crash"
    rc, committed = MODULE._delivery_anchor_commit(
        repo, applied_ids=[ticket_id], anchor_base_sha=base_sha,
    )
    assert rc == MODULE.EXIT_OK
    assert committed["committed"] is True
    rc, refused = MODULE._delivery_anchor_commit(
        repo,
        applied_ids=[ticket_id],
        already_committed=True,
        anchor_base_sha=base_sha,
        already_committed_sha="0" * 40,
    )
    assert rc == MODULE.EXIT_BLOCK
    assert "exact commit" in refused["error"]

def test_noop_recovery_rejects_foreign_source_renamed_into_backlog(tmp_path):
    """A foreign source path cannot enter the allowlist via a rename."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    ticket_id = "IMP-20260813-noop-recovery"
    foreign = repo / "frozen" / "foreign.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text('{"status":"foreign"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base foreign source"],
                   cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    target = repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
    target.parent.mkdir(parents=True)
    subprocess.run(["git", "mv", str(foreign), str(target)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "rename foreign source"],
                   cwd=repo, check=True)
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    marker = {
        "anchor_noop": True,
        "anchor_committed": False,
        "expected_ticket_ids": [ticket_id],
        "phases": {"anchor": {
            "status": "completed",
            "applied_ticket_ids": [],
            "queue_state": "consumed",
            "acceptance_receipt": {
                "schema": "kg.backlog.anchor.v1",
                "applied": [],
                "problems": [],
            },
        }},
    }
    assert not MODULE._delivery_anchor_noop_recovery_is_safe(
        repo, marker, stored_base=base_sha, current_head=current_head,
    )

def test_delivery_anchor_identity_accepts_subject_and_paths(tmp_path):
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    ticket_path = "docs/runbook/backlog/IMP-20260809-crash.json"
    subprocess.run(
        ["git", "add", "--", ticket_path], cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", MODULE._DELIVERY_ANCHOR_SUBJECT],
        cwd=repo, check=True,
    )

    assert MODULE._delivery_anchor_identity(
        repo, {ticket_path}, base_sha=base_sha,
    ) == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()

def test_delivery_anchor_recovers_commit_when_marker_write_crashes(tmp_path):
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    ticket_id = "IMP-20260809-crash"

    rc, first = MODULE._delivery_anchor_commit(
        repo, applied_ids=[ticket_id], anchor_base_sha=base_sha
    )
    assert rc == MODULE.EXIT_OK
    assert first["committed"] is True

    rc, recovered = MODULE._delivery_anchor_commit(
        repo, applied_ids=[ticket_id], anchor_base_sha=base_sha
    )

    assert rc == MODULE.EXIT_OK
    assert recovered["already_committed"] is True
    assert recovered["recovered"] is True
    assert recovered["sha"] == first["sha"]

def test_delivery_anchor_replays_manifest_after_post_commit_marker_failure(
        tmp_path, monkeypatch):
    repo, _base_sha = _git_repo_with_anchor_ticket(tmp_path)
    (repo / "docs" / "runbook" / "backlog" / "IMP-20260809-crash.json").write_text(
        "open\n", encoding="utf-8"
    )
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({"schema": MODULE.INTEGRATE_SCHEMA,
                                    "close_wave": {}}), encoding="utf-8")
    ticket_id = "IMP-20260809-crash"
    calls = 0
    child_calls = 0

    @contextmanager
    def fake_lock(_primary):
        yield

    def fake_child(*_args, **_kwargs):
        nonlocal child_calls
        child_calls += 1
        if child_calls == 1:
            (repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json").write_text(
                "closed-by-anchor\n", encoding="utf-8"
            )
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.anchor.v1", "mode": "commit",
                "applied": [ticket_id], "problems": [], "unstamped": [],
            }
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1", "mode": "commit",
            "applied": [], "problems": [], "unstamped": [],
        }

    real_save = MODULE._integrate_save

    def crash_after_commit(path, payload):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated crash after anchor commit")
        return real_save(path, payload)

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda _args, **_kwargs: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_child)
    monkeypatch.setattr(MODULE, "_integrate_save", crash_after_commit)
    args = argparse.Namespace(base="main")

    first_rc, first_steps = MODULE._delivery_anchor_and_commit(
        args, repo, set(), "delivery-wave", manifest
    )
    assert first_rc == MODULE.EXIT_BLOCK
    assert any(step.get("name") == "anchor-commit" and step.get("rc") == 0
               for step in first_steps)
    marker_after_crash = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert marker_after_crash["anchor_committed"] is False

    second_rc, second_steps = MODULE._delivery_anchor_and_commit(
        args, repo, set(), "delivery-wave", manifest
    )

    assert second_rc == MODULE.EXIT_OK
    assert any(step.get("payload", {}).get("recovered") is True
               for step in second_steps if step.get("name") == "anchor-commit")
    final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert final_marker["anchor_committed"] is True
    assert final_marker["anchor_commit_sha"]

def test_close_wave_recovery_phase_ledger_is_durable_and_monotonic(tmp_path):
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "close_wave": {"expected_ticket_ids": ["IMP-0001"]},
    }), encoding="utf-8")

    started = MODULE._delivery_record_phase(
        manifest, "anchor", status="started", operation_base="base-sha",
        landed_sha="landed-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=[], acceptance_receipt={"rc": None},
    )
    assert started["phases"]["anchor"]["status"] == "started"
    assert started["last_successful_phase"] is None

    completed = MODULE._delivery_record_phase(
        manifest, "anchor", status="completed", operation_base="base-sha",
        landed_sha="landed-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=["IMP-0001"], acceptance_receipt={"rc": 0},
        anchor_commit="anchor-sha",
    )
    replay = MODULE._delivery_record_phase(
        manifest, "anchor", status="started", operation_base="other-base",
        landed_sha="other-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=[], acceptance_receipt={"rc": None},
    )

    assert completed["phases"]["anchor"]["status"] == "completed"
    assert completed["phases"]["anchor"]["anchor_commit"] == "anchor-sha"
    assert replay == completed
    assert json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]["last_successful_phase"] == "anchor"

def test_close_wave_phase_completion_never_regresses_or_reorders(tmp_path):
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({"close_wave": {}}), encoding="utf-8")

    MODULE._delivery_record_phase(
        manifest, "cutover", status="completed", operation_base="base",
        landed_sha="cutover-sha",
    )
    completed = MODULE._delivery_record_phase(
        manifest, "anchor", status="completed", operation_base="base",
        landed_sha="anchor-sha",
    )
    replay = MODULE._delivery_record_phase(
        manifest, "cutover", status="started", operation_base="other",
        landed_sha="other",
    )

    assert replay["phases"]["cutover"]["status"] == "completed"
    assert replay["phases"]["cutover"]["operation_base"] == "base"
    assert replay["last_successful_phase"] == "anchor"
    assert completed["last_successful_phase"] == "anchor"

def test_close_wave_anchor_recovery_allows_primary_advance_only_with_pending_queue(
        tmp_path):
    queue = tmp_path / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({
        "id": "IMP-0001", "branch": "feat/source", "landed_sha": "landed",
    }) + "\n", encoding="utf-8")
    marker = {
        "expected_ticket_ids": ["IMP-0001"], "anchor_ids": [],
        "phases": {"anchor": {
            "status": "started", "expected_ticket_ids": ["IMP-0001"],
            "applied_ticket_ids": [],
        }},
    }
    assert MODULE._delivery_anchor_recovery_is_safe(tmp_path, marker)

    queue.write_text("", encoding="utf-8")
    assert not MODULE._delivery_anchor_recovery_is_safe(tmp_path, marker)

@pytest.mark.parametrize("malformed_field", ["expected", "phase"])
def test_close_wave_recovery_rejects_malformed_persisted_ticket_ids(
        tmp_path, monkeypatch, malformed_field):
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "primary advance"], cwd=repo,
                   check=True)
    ticket_id = "IMP-20260809-crash"
    expected_ids = [123] if malformed_field == "expected" else [ticket_id]
    phase_ids = [123] if malformed_field == "phase" else []
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {
            "anchor_base_sha": base_sha,
            "anchor_ids": [],
            "expected_ticket_ids": expected_ids,
            "phases": {"anchor": {
                "status": "started",
                "expected_ticket_ids": [ticket_id],
                "applied_ticket_ids": phase_ids,
            }},
        },
    }), encoding="utf-8")

    @contextmanager
    def fake_lock(_primary):
        yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda _args, **_kwargs: (0, [])
    )

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )

    assert rc == MODULE.EXIT_BLOCK
    assert any(
        step.get("name") == "anchor-guard"
        and "malformed recovery ticket ids" in step.get("error", "")
        for step in steps
    )

@pytest.mark.parametrize(
    "failure_phase",
    ["cutover", "resolve-source", "anchor", "validate",
     "resolve-integration", "sync"],
)
def test_close_wave_recovery_resumes_each_phase_and_is_idempotent(
        tmp_path, monkeypatch, capsys, failure_phase):
    """One injected boundary failure must be recoverable without duplicate work."""
    repo = tmp_path / "primary"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    ops = repo / "ops"
    ops.mkdir()
    (ops / "worktree_orchestrate.py").write_text("# fixture\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_id = "IMP-20260811-recovery"
    ticket_path = store / f"{ticket_id}.json"
    ticket_path.write_text(json.dumps({
        "id": ticket_id, "status": "staged", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [],
    }) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()
    subprocess.run(["git", "checkout", "-qb", "feat/integration"], cwd=repo, check=True)
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    subprocess.run(["git", "add", "integration.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "integration"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "feat/source", base_sha], cwd=repo, check=True)

    source_path = tmp_path / "source"
    source_path.mkdir()
    integration_path = tmp_path / "integration"
    integration_path.mkdir()
    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({
        "id": ticket_id, "branch": "feat/source", "landed_sha": base_sha,
        "status": "staged", "verdict": "CONFIRMED-FIXED", "by": "fixture",
        "evidence": "fixture", "kind": "closure",
    }) + "\n", encoding="utf-8")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    manifest = manifest_dir / "delivery-wave.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA, "slug": "delivery-wave",
        "base": "main", "branches": ["feat/source"],
        "worktree": str(integration_path), "branch": "feat/integration",
        "status": "gated", "gate": {"verdict": "pass"},
        "integration_revision": MODULE.sha256_file(Path(MODULE.__file__).resolve()),
        "close_wave": {"status": "gated", "expected_ticket_ids": [ticket_id]},
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    records = [
        {"status": "active", "branch": "feat/source", "path": str(source_path),
         "base": "main", "backlog": [ticket_id]},
        {"status": "active", "branch": "feat/integration", "path": str(integration_path),
         "base": "main", "backlog": []},
    ]
    calls = {phase: 0 for phase in (
        "cutover", "resolve-source", "anchor", "validate",
        "resolve-integration", "sync",
    )}

    monkeypatch.setattr(MODULE, "primary_root", lambda: repo)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *_args: None)
    monkeypatch.setattr(MODULE, "_delivery_state_paths", lambda _args: (state, [manifest]))
    monkeypatch.setattr(MODULE, "_delivery_integration_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, records),
    )

    def fake_tool(_script, _cwd, argv, *, label, **_kwargs):
        phase = next((name for name in calls if label.startswith(f"{name}:")), None)
        if phase is not None:
            calls[phase] += 1
            if phase == failure_phase and calls[phase] == 1:
                if phase == "anchor":
                    ticket_path.write_text(json.dumps({
                        "id": ticket_id, "status": "fixed",
                        "verdict": "CONFIRMED-FIXED",
                        "fixed_by": ["partial-anchor"],
                    }) + "\n", encoding="utf-8")
                    queue.write_text("", encoding="utf-8")
                return MODULE.EXIT_BLOCK, {"error": f"injected {phase} failure"}
        if phase == "cutover":
            subprocess.run(["git", "branch", "-f", "feat/integration", "HEAD"],
                           cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            ).strip()
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed", "landed": True,
                "sha": head,
            }
        if phase == "resolve-source":
            records[0]["status"] = "merged"
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed",
                "resolved": "merged", "failures": 0,
            }
        if phase == "anchor":
            ticket_path.write_text(json.dumps({
                "id": ticket_id, "status": "fixed", "verdict": "CONFIRMED-FIXED",
                "fixed_by": ["fixture-anchor"],
            }) + "\n", encoding="utf-8")
            queue.write_text("", encoding="utf-8")
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.anchor.v1", "mode": "commit",
                "applied": [ticket_id], "problems": [], "unstamped": [],
            }
        if phase == "validate":
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.validate.v1", "ok": True, "problems": [],
            }
        if phase == "resolve-integration":
            records[1]["status"] = "merged"
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed",
                "resolved": "merged", "failures": 0,
            }
        if phase == "sync":
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            ).strip()
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "step": "sync", "verdict": "noop",
                "to": head,
            }
        pytest.fail(f"unexpected tool label={label!r} argv={argv!r}")

    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_tool)
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=True,
    )

    first_rc = MODULE.cmd_close_wave(args)
    first_payload = json.loads(capsys.readouterr().out)
    assert first_rc == MODULE.EXIT_BLOCK
    assert first_payload.get("steps"), first_payload
    assert calls[failure_phase] == 1

    second_rc = MODULE.cmd_close_wave(args)
    second_payload = json.loads(capsys.readouterr().out)
    assert second_rc == MODULE.EXIT_OK, second_payload
    assert calls[failure_phase] == 2
    final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert final_marker["last_successful_phase"] == "sync"
    assert all(final_marker["phases"][phase]["status"] == "completed"
               for phase in calls)
    assert MODULE._read_anchor_queue(repo) == []
    assert records[1]["status"] == "merged"
    anchor_commits = subprocess.check_output(
        ["git", "log", "--format=%s", "--all"], cwd=repo, text=True,
    ).splitlines().count(MODULE._DELIVERY_ANCHOR_SUBJECT)
    assert anchor_commits == 1

    before_queue = queue.read_bytes() if queue.exists() else b""
    before_log = subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=repo, text=True,
    )
    third_rc = MODULE.cmd_close_wave(args)
    third_payload = json.loads(capsys.readouterr().out)
    assert third_rc == MODULE.EXIT_OK, third_payload
    assert calls[failure_phase] == 2
    assert (queue.read_bytes() if queue.exists() else b"") == before_queue
    assert subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=repo, text=True,
    ) == before_log

@pytest.mark.parametrize(
    "failure_phase",
    ["cutover", "resolve-source", "anchor", "validate",
     "resolve-integration", "sync"],
)
@gitmark
def test_close_wave_recovery_real_subprocess_wiring(
        tmp_path, monkeypatch, capsys, failure_phase):
    """Exercise close-wave against real git, registry, backlog and sync commands."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "fixture@example.test"], repo)
    _git(["config", "user.name", "recovery fixture"], repo)
    shutil.copytree(
        ROOT / "ops", repo / "ops",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repo / "ops" / "backlog_id_drift_baseline.txt").write_text(
        "", encoding="utf-8"
    )
    assert (repo / "ops" / "backlog_id_drift_baseline.txt").read_text(
        encoding="utf-8"
    ) == ""
    (repo / ".gitignore").write_text(".cache/\n__pycache__/\n", encoding="utf-8")
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_payload = {
        "schema": "kg.backlog.entry.v1", "status": "open",
        "stream": "IMP", "severity": "med", "category": "tool",
        "date": "2026-08-11", "source": "fixture",
        "detail": "real close-wave recovery fixture",
        "brief": "recover a close-wave without duplicate side effects",
        "scope": "ops orchestration only", "plan": "exercise every phase",
        "acceptance": "the real fixture command exits zero",
        "fix_site": "ops/worktree_orchestrate.py",
        "acceptance_cmd": "true", "acceptance_expect_rc": 0,
        "resolution": "", "fixed_by": [],
        "groomed_at": "2026-08-11", "groomed_by": "fixture",
    }
    ticket_id, ticket_payload = _with_canonical_ticket_id(ticket_payload)
    assert ticket_payload["id"] == ticket_id == MODULE.backlog_tool.make_entry_id(**{
        field: ticket_payload[field] for field in MODULE.backlog_tool.DIGEST_FIELDS
    })
    (store / f"{ticket_id}.json").write_text(
        json.dumps(ticket_payload, indent=2) + "\n", encoding="utf-8"
    )
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "fixture base"], repo)
    base_sha = _git(["rev-parse", "main"], repo)

    source = tmp_path / "source"
    _git(["worktree", "add", "-q", "-b", "feat/source", str(source), "main"], repo)
    (source / "source.txt").write_text("source\n", encoding="utf-8")
    _git(["add", "source.txt"], source)
    _git(["commit", "-qm", "fixture source"], source)
    source_tip = _git(["rev-parse", "HEAD"], source)
    integration = tmp_path / "integration"
    _git(["worktree", "add", "-q", "-b", "feat/integration", str(integration),
          "feat/source"], repo)
    (integration / "integration.txt").write_text("integration\n", encoding="utf-8")
    _git(["add", "integration.txt"], integration)
    _git(["commit", "-qm", "fixture integration"], integration)
    integration_tip = _git(["rev-parse", "HEAD"], integration)

    remote = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)

    state = repo / ".cache" / "worktree_registry.json"
    state.parent.mkdir(parents=True, exist_ok=True)

    def registry(*argv):
        proc = subprocess.run(
            [sys.executable, str(repo / "ops" / "worktree_registry.py"), *argv,
             "--state", str(state), "--json"],
            cwd=repo, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return json.loads(proc.stdout)

    registry("register", "--path", str(source), "--branch", "feat/source",
             "--intent", "real recovery source", "--base", "main",
             "--backlog", ticket_id)
    registry("register", "--path", str(integration), "--branch", "feat/integration",
             "--intent", "real recovery integration", "--base", "main")
    ledger = json.loads(state.read_text(encoding="utf-8"))
    for record in ledger["records"]:
        record["base_sha"] = base_sha
        record["handed_back_sha"] = (
            source_tip if record["branch"] == "feat/source" else integration_tip
        )
        record["handed_back_at"] = "2026-08-11T00:00:00Z"
    state.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    queue.write_text(json.dumps({
        "id": ticket_id, "branch": "feat/integration", "landed_sha": None,
        "status": "fixed", "verdict": "CONFIRMED-FIXED", "by": "fixture",
        "evidence": "real recovery fixture", "kind": "closure",
    }) + "\n", encoding="utf-8")

    slug = "real-recovery"
    manifest_dir = repo / ".cache" / "worktree_integrations" / "completed"
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / f"{slug}-{integration_tip}.json"
    integration_revision = MODULE.sha256_file(
        integration / "ops" / "worktree_orchestrate.py"
    )
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA, "slug": slug, "base": "main",
        "branches": ["feat/source"], "worktree": str(integration),
        "branch": "feat/integration", "status": "gated",
        "integration_revision": integration_revision,
        "gate": {"verdict": "pass", "head_sha": integration_tip},
        "close_wave": {"status": "gated", "expected_ticket_ids": [ticket_id]},
    }, indent=2) + "\n", encoding="utf-8")
    gate_path = MODULE._gate_record_path(str(state), str(integration))
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    changed_files = MODULE._changed_vs_base(str(integration), "main")
    full_plan = MODULE._current_full_gate_plan(
        str(integration), changed_files, "S2", "main"
    )
    selected_plan, deferred_plan = MODULE.select_gate_plan(full_plan, "S2")
    gate_path.write_text(json.dumps({
        "schema": MODULE.GATE_SCHEMA, "step": "gate", "worktree": str(integration),
        "base": "main", "head_sha": integration_tip, "verdict": "pass",
        "changed_files": changed_files, "no_changed_files": not changed_files,
        "gate_tier": "S2",
        "required_tier": MODULE.required_cutover_tier(changed_files, full_plan),
        "canonical_plan_digest": MODULE._gate_plan_digest(full_plan),
        "selected_plan_digest": MODULE._gate_plan_digest(selected_plan),
        "plan": MODULE._gate_plan_projection(selected_plan),
        "deferred_plan": MODULE._gate_plan_projection(deferred_plan),
        "deferral_requests": [], "deferred_failures": [],
        "gates": [{
            "name": spec["name"], "category": spec.get("category"),
            "level": spec.get("level", "block"), "status": "pass", "rc": 0,
            "tier": spec.get("tier", "S2"),
        } for spec in selected_plan],
        "orchestrator": MODULE._orchestrator_identity(str(integration)),
    }, indent=2) + "\n", encoding="utf-8")

    calls = {phase: 0 for phase in (
        "cutover", "resolve-source", "anchor", "validate",
        "resolve-integration", "sync",
    )}
    real_tool = MODULE._delivery_json_tool

    def injected_tool(script, cwd, argv, *, label, **kwargs):
        phase = next((name for name in calls if label.startswith(f"{name}:")), None)
        if phase is None:
            return real_tool(script, cwd, argv, label=label, **kwargs)
        calls[phase] += 1
        if phase == failure_phase and calls[phase] == 1 and phase != "anchor":
            return MODULE.EXIT_BLOCK, {"error": f"injected {phase} boundary failure"}
        rc, payload = real_tool(script, cwd, argv, label=label, **kwargs)
        if phase == failure_phase and calls[phase] == 1 and phase == "anchor":
            # The real anchor has already written every ticket and drained the queue;
            # returning BLOCK models a process death before the coordinator persisted
            # its receipt, which is the dangerous partial-anchor window.
            return MODULE.EXIT_BLOCK, {**payload, "error": "injected post-anchor crash"}
        return rc, payload

    monkeypatch.setattr(MODULE, "_delivery_json_tool", injected_tool)
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug=slug,
        branches=["feat/source"], commit=True, sync=True,
    )
    previous_cwd = Path.cwd()
    os.chdir(repo)
    try:
        first_rc = MODULE.cmd_close_wave(args)
        first_payload = json.loads(capsys.readouterr().out)
        assert first_rc == MODULE.EXIT_BLOCK, first_payload
        second_rc = MODULE.cmd_close_wave(args)
        second_payload = json.loads(capsys.readouterr().out)
        assert second_rc == MODULE.EXIT_OK, second_payload
        assert second_payload["runner_revision"] == MODULE.sha256_file(
            Path(MODULE.__file__).resolve()
        ), second_payload
        assert second_payload["integration_revision"] == integration_revision, second_payload
        assert calls[failure_phase] == 2
        final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
        assert final_marker["last_successful_phase"] == "sync"
        assert all(final_marker["phases"][phase]["status"] == "completed"
                   for phase in calls)
        assert MODULE._read_anchor_queue(repo) == []
        assert not source.exists() and not integration.exists()
        ledger_after = json.loads(state.read_text(encoding="utf-8"))
        assert all(r["status"] == "merged" for r in ledger_after["records"])
        anchor_commits = subprocess.check_output(
            ["git", "log", "--format=%s", "--all"], cwd=repo, text=True,
        ).splitlines().count(MODULE._DELIVERY_ANCHOR_SUBJECT)
        assert anchor_commits == 1
        before_refs = _git(["rev-list", "--all"], repo)
        before_queue = queue.read_bytes() if queue.exists() else b""
        third_rc = MODULE.cmd_close_wave(args)
        third_payload = json.loads(capsys.readouterr().out)
        assert third_rc == MODULE.EXIT_OK, third_payload
        assert calls[failure_phase] == 2
        assert _git(["rev-list", "--all"], repo) == before_refs
        assert (queue.read_bytes() if queue.exists() else b"") == before_queue
    finally:
        os.chdir(previous_cwd)

def test_delivery_anchor_commit_refuses_staged_or_unstaged_foreign_paths(
        tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo,
                   check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    backlog = repo / "docs" / "runbook" / "backlog"
    backlog.mkdir(parents=True)
    ticket = backlog / "IMP-20260809-anchor.json"
    ticket.write_text("closed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    ticket.write_text("closed-again\n", encoding="utf-8")
    (repo / "foreign.txt").write_text("must stay\n", encoding="utf-8")

    rc, payload = MODULE._delivery_anchor_commit(
        repo, applied_ids=["IMP-20260809-anchor"]
    )

    assert rc == MODULE.EXIT_BLOCK
    assert payload["outside_paths"] == ["foreign.txt"]
    assert payload["missing_paths"] == []
    assert subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo,
                          check=True, capture_output=True, text=True).stdout == ""

def test_close_wave_refuses_malformed_persisted_state_before_registry(
        tmp_path, monkeypatch, capsys):
    state = tmp_path / "registry.json"
    integration_state = state.parent / "worktree_integrations" / "delivery-wave.json"
    integration_state.parent.mkdir(parents=True, exist_ok=True)
    integration_state.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True,
    )

    rc = MODULE.cmd_close_wave(args)

    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert "unreadable or malformed" in payload["error"]

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "app_review_evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("app_review_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evidence = load_module()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_producer_runner_reports_progress_on_stderr_and_preserves_json_stdout(tmp_path: Path):
    stdout = io.StringIO()
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import json,time; time.sleep(.08); print(json.dumps({'status':'pass'}))",
    ]

    with redirect_stdout(stdout), redirect_stderr(stderr):
        completed = evidence._run_producer_command(
            command,
            cwd=tmp_path,
            producer_name="desired-test",
            heartbeat_interval=0.02,
        )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"status": "pass"}
    assert stdout.getvalue() == ""
    progress = stderr.getvalue()
    assert "producer=desired-test phase=start" in progress
    assert "phase=heartbeat" in progress
    assert "alive=true" in progress
    assert "phase=done" in progress


def test_journey_demo_and_gate_use_named_streaming_runner(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def fake_runner(command, *, cwd, producer_name, heartbeat_interval=20.0):
        calls.append(producer_name)
        payload = {"verdict": {}, "blocks": []} if producer_name == "gate-evaluation" else {"status": "pass"}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(evidence, "_run_producer_command", fake_runner)
    evidence.execute_journey_run(
        workspace_root=tmp_path,
        dataset_file=tmp_path / "world.json",
        fixed_clock="2026-07-13T08:00:00Z",
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
        appearance="light",
        tests=["testCore"],
    )
    evidence.execute_demo_run(
        workspace_root=tmp_path,
        destination="platform=iOS,id=device",
        account_identity_sha256="d" * 64,
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
    )
    evidence.evaluate_gate(tmp_path / "spec.json", tmp_path)

    assert calls == ["journey-run", "demo-run", "gate-evaluation"]


PROJECT_FILE_REL = "ios/BooksAndVocab.xcodeproj/project.pbxproj"


def checked_spec() -> dict:
    return json.loads((ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8"))


def blob_bytes(commit: str, rel_path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "blob", f"{commit}:{rel_path}"],
        capture_output=True,
        check=True,
    ).stdout


def stub_desired_pipeline(monkeypatch, *, dataset_bytes: bytes) -> tuple[list[str], dict]:
    """Fake every subprocess of the desired pipeline; git sourcing stays real."""
    import capture_profile

    profile = type("Profile", (), {"profile_id": "review"})()
    monkeypatch.setattr(capture_profile, "load_profile", lambda _path: profile)
    monkeypatch.setattr(capture_profile, "reviewer_render_spec", lambda _profile: {"shots": []})
    calls: list[str] = []
    captured: dict = {}

    def fake_runner(command, *, cwd, producer_name, heartbeat_interval=20.0):
        calls.append(producer_name)
        if producer_name == "desired-build":
            Path(command[command.index("--out") + 1]).write_bytes(dataset_bytes)
        if producer_name == "desired-bundle":
            project_file = Path(command[command.index("--project-file") + 1])
            captured["projectFile"] = project_file
            captured["projectBytes"] = project_file.read_bytes()
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr(evidence, "_run_producer_command", fake_runner)
    return calls, captured


def desired_kwargs(tmp_path: Path) -> dict:
    profile_file = tmp_path / "profile.yml"
    profile_file.write_text("profile", encoding="utf-8")
    return {
        "workspace_root": ROOT,
        "profile_file": profile_file,
        "render_output_dir": tmp_path / "renders",
        "bundle_dir": tmp_path / "bundle",
        "fixed_clock": "2026-07-13T08:00:00Z",
        "locale": "zh-Hant",
        "commit": False,
    }


def synthetic_spec(dataset_bytes: bytes, source_commit: str) -> dict:
    return {
        "target": {
            "datasetSHA256": sha(dataset_bytes),
            "sourceCommit": source_commit,
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
        }
    }


def test_desired_pipeline_streams_every_subprocess_phase(tmp_path: Path, monkeypatch):
    dataset_bytes = b'{"schema":"world"}\n'
    spec = synthetic_spec(dataset_bytes, checked_spec()["target"]["sourceCommit"])
    calls, _ = stub_desired_pipeline(monkeypatch, dataset_bytes=dataset_bytes)

    evidence.produce_desired_bundle(spec, **desired_kwargs(tmp_path))

    assert calls == ["desired-shape", "desired-build", "desired-bundle"]


def test_desired_bundle_reads_project_file_from_source_commit_not_worktree(
    tmp_path: Path, monkeypatch
):
    source_commit = checked_spec()["target"]["sourceCommit"]
    dataset_bytes = b'{"schema":"world"}\n'
    spec = synthetic_spec(dataset_bytes, source_commit)
    calls, captured = stub_desired_pipeline(monkeypatch, dataset_bytes=dataset_bytes)

    evidence.produce_desired_bundle(spec, **desired_kwargs(tmp_path))

    assert calls == ["desired-shape", "desired-build", "desired-bundle"]
    assert captured["projectBytes"] == blob_bytes(source_commit, PROJECT_FILE_REL)
    assert captured["projectFile"].resolve() != (ROOT / PROJECT_FILE_REL).resolve()


def commit_all(root: Path) -> str:
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "pin"],
        check=True, capture_output=True,
    )
    return subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


def scratch_repo(tmp_path: Path, *, content: bytes) -> tuple[Path, str]:
    """A throwaway git repo, so drift probes never touch the shared checkout."""
    root = tmp_path / "scratch-repo"
    (root / PROJECT_FILE_REL).parent.mkdir(parents=True)
    (root / PROJECT_FILE_REL).write_bytes(content)
    subprocess.run(
        ["git", "-C", str(root), "-c", "init.defaultBranch=main", "init", "-q"],
        check=True, capture_output=True,
    )
    return root, commit_all(root)


def test_desired_bundle_project_bytes_ignore_worktree_edits(tmp_path: Path, monkeypatch):
    """The property the git sourcing buys: unrelated pbxproj edits cannot move it."""
    pinned = b"// pinned\nMARKETING_VERSION = 2.0.0;\nCURRENT_PROJECT_VERSION = 6;\n"
    root, commit = scratch_repo(tmp_path, content=pinned)
    dataset_bytes = b'{"schema":"world"}\n'
    spec = synthetic_spec(dataset_bytes, commit)
    _, captured = stub_desired_pipeline(monkeypatch, dataset_bytes=dataset_bytes)
    kwargs = desired_kwargs(tmp_path) | {"workspace_root": root}
    edited = pinned + b"// unrelated working-tree edit\n"

    evidence.produce_desired_bundle(spec, **kwargs)
    before = captured["projectBytes"]
    (root / PROJECT_FILE_REL).write_bytes(edited)
    evidence.produce_desired_bundle(spec, **kwargs)
    after = captured["projectBytes"]

    # Positive control first: without a real edit, the silence below proves nothing.
    assert (root / PROJECT_FILE_REL).read_bytes() == edited
    assert before == pinned
    assert after == pinned


def test_desired_bundle_refuses_unreachable_source_commit(tmp_path: Path, monkeypatch):
    """Negative control: no silent fall back to the worktree file."""
    dataset_bytes = b'{"schema":"world"}\n'
    spec = synthetic_spec(dataset_bytes, "0" * 40)
    calls, captured = stub_desired_pipeline(monkeypatch, dataset_bytes=dataset_bytes)

    # match= pins the cause: a well-formed but absent SHA must fail on
    # reachability, not get absorbed by the format guard that also mentions it.
    with pytest.raises(evidence.EvidenceError, match=r"sourceCommit\.unreachable"):
        evidence.produce_desired_bundle(spec, **desired_kwargs(tmp_path))

    assert calls == []
    assert "projectBytes" not in captured


def test_desired_bundle_refuses_non_sha_source_commit(tmp_path: Path, monkeypatch):
    dataset_bytes = b'{"schema":"world"}\n'
    calls, captured = stub_desired_pipeline(monkeypatch, dataset_bytes=dataset_bytes)

    for bogus in ("", "HEAD", "main", "60b7030e"):
        with pytest.raises(evidence.EvidenceError, match=r"sourceCommit\.format"):
            evidence.produce_desired_bundle(
                synthetic_spec(dataset_bytes, bogus), **desired_kwargs(tmp_path)
            )

    assert calls == []
    assert "projectBytes" not in captured


def test_materialize_tracked_file_rejects_non_regular_tree_entry(tmp_path: Path):
    """`git cat-file blob` exits 0 on a symlink and returns the link target."""
    root, _ = scratch_repo(tmp_path, content=b"pinned\n")
    linked = root / PROJECT_FILE_REL
    linked.unlink()
    linked.symlink_to("../../../etc/hosts")
    commit = commit_all(root)
    destination = tmp_path / "materialized"

    with pytest.raises(evidence.EvidenceError, match=r"sourceCommit\.not-regular-file"):
        evidence._materialize_tracked_file(
            workspace_root=root, commit=commit,
            rel_path=PROJECT_FILE_REL, destination=destination,
        )

    assert not destination.exists()


def test_materialize_tracked_file_reports_absent_git_as_typed_error(tmp_path: Path, monkeypatch):
    def missing_git(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(evidence.subprocess, "run", missing_git)

    with pytest.raises(evidence.EvidenceError, match=r"git\.unavailable"):
        evidence._materialize_tracked_file(
            workspace_root=ROOT, commit="a" * 40,
            rel_path=PROJECT_FILE_REL, destination=tmp_path / "materialized",
        )


# ── anchor refresh: the only sanctioned way to move target.desiredManifestSHA256 ──


def test_rewrite_anchor_changes_exactly_one_field_and_one_line():
    text = (ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8")

    updated, old = evidence.rewrite_anchor(text, "b" * 64)

    assert old == json.loads(text)["target"]["desiredManifestSHA256"]
    assert json.loads(updated)["target"]["desiredManifestSHA256"] == "b" * 64
    restored = json.loads(updated)
    restored["target"]["desiredManifestSHA256"] = old
    assert restored == json.loads(text)
    differing = [
        pair for pair in zip(text.splitlines(), updated.splitlines(), strict=True)
        if pair[0] != pair[1]
    ]
    assert len(differing) == 1


def test_rewrite_anchor_rejects_a_value_that_is_not_a_sha256():
    text = (ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8")

    with pytest.raises(evidence.EvidenceError, match=r"anchor\.value"):
        evidence.rewrite_anchor(text, "not-a-digest")


def test_rewrite_anchor_requires_exactly_one_anchor_literal():
    with pytest.raises(evidence.EvidenceError, match=r"anchor\.occurrences"):
        evidence.rewrite_anchor('{"target": {}}\n', "b" * 64)


def test_rewrite_anchor_does_not_reformat_a_non_canonical_spec():
    """The reason this is textual: re-serializing would silently recanonicalize."""
    non_canonical = (
        '{\n'
        '    "target": {\n'
        '        "zzz": "trailing key out of sort order",\n'
        '        "desiredManifestSHA256": "' + "a" * 64 + '",\n'
        '        "appID": "6759816274"\n'
        '    },\n'
        '    "schema": "kg.app_review.gate.v1"\n'
        '}\n'
    )

    updated, old = evidence.rewrite_anchor(non_canonical, "b" * 64)

    assert old == "a" * 64
    # Byte-exact except the digest: key order, 4-space indent and layout survive.
    assert updated == non_canonical.replace("a" * 64, "b" * 64)


def stub_bundle(monkeypatch, manifest_bytes: bytes) -> list[bool]:
    """Stand in for the real rebuild; record whether it was asked to publish."""
    published: list[bool] = []

    def fake_bundle(spec, *, bundle_dir, commit, **_kwargs):
        published.append(commit)
        # The rebuild must stay inside a temp dir; without this the stub would
        # happily accept an implementation that published into the repo.
        assert tempfile.gettempdir() in str(bundle_dir.resolve())
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "manifest.json").write_bytes(manifest_bytes)
        return {"manifest": {}}

    monkeypatch.setattr(evidence, "produce_desired_bundle", fake_bundle)
    return published


def stub_gate(monkeypatch, status: str, codes: list[str]) -> list[str]:
    """Stand in for the real gate; record which spec it was asked to judge."""
    asked: list[str] = []

    def fake_gate(spec_path, workspace_root):
        asked.append(str(spec_path))
        return {
            "verdict": {"status": status, "blockCount": len(codes)},
            "blocks": [{"code": code} for code in codes],
        }

    monkeypatch.setattr(evidence, "evaluate_gate", fake_gate)
    return asked


def refresh_argv(spec_path: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "refresh-anchor",
        "--spec", str(spec_path),
        "--profile", str(ROOT / "ops/capture_profiles/marketing_account.json"),
        "--render-output-dir", str(tmp_path / "renders"),
        "--fixed-clock", "2026-07-09T09:00:00Z",
        "--locale", "zh-Hant",
        "--workspace-root", str(ROOT),
        *extra,
    ]


def anchor_kwargs(tmp_path: Path) -> dict:
    return {
        "workspace_root": ROOT,
        "profile_file": ROOT / "ops/capture_profiles/marketing_account.json",
        "render_output_dir": tmp_path / "renders",
        "fixed_clock": "2026-07-09T09:00:00Z",
        "locale": "zh-Hant",
    }


def stale_spec(tmp_path: Path) -> tuple[Path, str]:
    original = (ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8")
    stale = original.replace(json.loads(original)["target"]["desiredManifestSHA256"], "0" * 64)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(stale, encoding="utf-8")
    return spec_path, stale


def test_refresh_anchor_writes_nothing_without_commit(tmp_path: Path, monkeypatch):
    spec_path, stale = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    published = stub_bundle(monkeypatch, manifest_bytes)

    report = evidence.refresh_desired_anchor(spec_path, commit=False, **anchor_kwargs(tmp_path))

    assert report["old"] == "0" * 64
    assert report["new"] == sha(manifest_bytes)
    assert report["changed"] is True
    assert report["status"] == "dry-run"
    assert spec_path.read_text(encoding="utf-8") == stale
    assert published == [True]  # measured from a published bundle, not a re-serialization


def test_refresh_anchor_commit_moves_only_the_anchor(tmp_path: Path, monkeypatch):
    spec_path, stale = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    stub_bundle(monkeypatch, manifest_bytes)
    stub_gate(monkeypatch, "pass", [])

    report = evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    landed = spec_path.read_text(encoding="utf-8")
    assert report["status"] == "written"
    assert report["gateCheck"] == "pass"
    assert json.loads(landed)["target"]["desiredManifestSHA256"] == sha(manifest_bytes)
    reverted = json.loads(landed)
    reverted["target"]["desiredManifestSHA256"] = "0" * 64
    assert reverted == json.loads(stale)
    assert len(landed) == len(stale)


def test_refresh_anchor_reports_current_and_writes_nothing_when_already_correct(
    tmp_path: Path, monkeypatch
):
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    original = (ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8")
    current = original.replace(
        json.loads(original)["target"]["desiredManifestSHA256"], sha(manifest_bytes)
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(current, encoding="utf-8")
    stub_bundle(monkeypatch, manifest_bytes)
    stub_gate(monkeypatch, "pass", [])

    report = evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert report["changed"] is False
    assert report["status"] == "current"
    assert spec_path.read_text(encoding="utf-8") == current


def test_refresh_anchor_rejects_an_unrewritable_spec_before_rebuilding(
    tmp_path: Path, monkeypatch
):
    """A spec that can never be rewritten must not cost a full rebuild first."""
    original = (ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8")
    doubled = original.replace(
        '"schema": "kg.app_review.gate.v1"',
        '"decoy": {"desiredManifestSHA256": "' + "c" * 64 + '"},\n  "schema": "kg.app_review.gate.v1"',
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(doubled, encoding="utf-8")
    published = stub_bundle(monkeypatch, b'{"schema":"x"}\n')
    asked = stub_gate(monkeypatch, "pass", [])

    with pytest.raises(evidence.EvidenceError, match=r"anchor\.occurrences:2"):
        evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert published == []
    assert asked == []  # nor a gate evaluation: the text-only precondition still runs first
    assert spec_path.read_text(encoding="utf-8") == doubled


def test_refresh_anchor_refuses_to_revert_an_edit_made_during_the_rebuild(
    tmp_path: Path, monkeypatch
):
    spec_path, stale = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    concurrent = stale.replace('"appID": "6759816274"', '"appID": "9999999999"')

    def racing_bundle(spec, *, bundle_dir, commit, **_kwargs):
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "manifest.json").write_bytes(manifest_bytes)
        spec_path.write_text(concurrent, encoding="utf-8")  # another writer lands
        return {"manifest": {}}

    monkeypatch.setattr(evidence, "produce_desired_bundle", racing_bundle)
    stub_gate(monkeypatch, "pass", [])

    with pytest.raises(evidence.EvidenceError, match=r"anchor\.spec-changed-during-rebuild"):
        evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert spec_path.read_text(encoding="utf-8") == concurrent  # their edit survives


def test_refresh_anchor_commit_replaces_the_spec_by_rename(tmp_path: Path, monkeypatch):
    """Crash-safety is not unit-testable, so pin the mechanism that supplies it.

    This asserts *how* the write happens, not the property it buys. A no-staging-
    file assertion cannot tell an atomic rename from an in-place truncation —
    both leave a tidy directory — so without this, reverting to write_text()
    goes unnoticed.
    """
    spec_path, _ = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "pass", [])
    destinations: list[str] = []
    real_replace = evidence.os.replace

    def recording_replace(src, dst, **kwargs):
        destinations.append(str(dst))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(evidence.os, "replace", recording_replace)

    evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert destinations == [str(spec_path)]


def test_refresh_anchor_commit_leaves_no_staging_file_behind(tmp_path: Path, monkeypatch):
    spec_path, _ = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "pass", [])

    evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["spec.json"]


def test_refresh_anchor_cli_is_wired_and_dry_run_by_default(tmp_path: Path, monkeypatch, capsys):
    spec_path, stale = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    stub_bundle(monkeypatch, manifest_bytes)

    code = evidence.main(refresh_argv(spec_path, tmp_path))

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "kg.app_review.anchor_refresh.v1"
    assert document["field"] == "target.desiredManifestSHA256"
    assert document["old"] == "0" * 64
    assert document["new"] == sha(manifest_bytes)
    assert document["commit"] is False
    assert spec_path.read_text(encoding="utf-8") == stale


def test_refresh_anchor_dry_run_never_consults_the_gate(tmp_path: Path, monkeypatch):
    """The comparison stays free: only the write is worth a gate evaluation.

    Without this the guard could quietly turn every `old -> new` preview into a
    networked gate run, and the cheapest way to ask "has the anchor moved?"
    would stop being cheap.
    """
    spec_path, stale = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    asked = stub_gate(monkeypatch, "block", ["desired.manifest-sha256"])

    report = evidence.refresh_desired_anchor(spec_path, commit=False, **anchor_kwargs(tmp_path))

    assert asked == []
    assert report["gateCheck"] == "not-required"
    assert report["acknowledgedGateBlock"] is False
    assert spec_path.read_text(encoding="utf-8") == stale


def test_refresh_anchor_commit_refuses_while_gate_blocks(
    tmp_path: Path, monkeypatch, capsys
):
    """Moving the anchor must not be the one-liner that erases a red gate.

    The refusal names the gate's own block codes rather than a generic message:
    the operator is being told exactly which red light they were about to turn
    green, and that string can only come from the gate report.
    """
    spec_path, stale = stale_spec(tmp_path)
    published = stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    asked = stub_gate(monkeypatch, "block", ["desired.manifest-sha256", "attestation.human.expired"])

    code = evidence.main(refresh_argv(spec_path, tmp_path, "--commit"))

    document = json.loads(capsys.readouterr().out)
    assert code == 2
    assert document["status"] == "block"
    assert "desired.manifest-sha256" in document["error"]
    assert "attestation.human.expired" in document["error"]
    assert "--acknowledge-gate-block" in document["error"]
    assert spec_path.read_text(encoding="utf-8") == stale
    assert asked == [str(spec_path)]
    assert published == []  # refused before paying for a rebuild


def test_refresh_anchor_refusal_previews_blocks_and_reports_the_total(
    tmp_path: Path, monkeypatch, capsys
):
    """A refusal nobody reads teaches nothing.

    The real gate returns ~48 codes on a cold spec; splicing all of them into one
    line produces a wall the operator scrolls past on the way to the override.
    Preview a few, state the true total, and name where the rest live.
    """
    spec_path, stale = stale_spec(tmp_path)
    codes = [f"claim.metadata.surface-{index:02d}" for index in range(20)]
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "block", codes)

    code = evidence.main(refresh_argv(spec_path, tmp_path, "--commit"))

    error = json.loads(capsys.readouterr().out)["error"]
    assert code == 2
    assert codes[0] in error
    assert codes[-1] not in error  # truncated, not dumped
    assert "20 blocks" in error  # the count is the gate's, not the preview's length
    assert "status --spec" in error  # and the full list is one named command away
    assert spec_path.read_text(encoding="utf-8") == stale


def test_refresh_anchor_commit_with_acknowledgement_writes(
    tmp_path: Path, monkeypatch, capsys
):
    """The escape hatch exists, is explicit, and writes down what it silenced.

    The write destroys its own evidence: afterwards nothing on disk separates a
    override of one block from an override of forty-eight. So the gate is still
    consulted here — it just no longer decides — and its codes land in the
    report, which is the only place that record can still exist.
    """
    spec_path, _ = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    stub_bundle(monkeypatch, manifest_bytes)
    asked = stub_gate(monkeypatch, "block", ["desired.manifest-sha256", "urls.missing"])

    code = evidence.main(
        refresh_argv(spec_path, tmp_path, "--commit", "--acknowledge-gate-block")
    )

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["status"] == "written"
    assert document["acknowledgedGateBlock"] is True
    assert document["gateCheck"] == "acknowledged"
    assert document["gateBlocks"] == ["desired.manifest-sha256", "urls.missing"]
    assert json.loads(spec_path.read_text(encoding="utf-8"))["target"][
        "desiredManifestSHA256"
    ] == sha(manifest_bytes)
    assert asked == [str(spec_path)]  # observed, not obeyed


def test_refresh_anchor_acknowledgement_survives_an_unusable_gate(
    tmp_path: Path, monkeypatch, capsys
):
    """Observing the blocks must not quietly become a second gate.

    The override is for the case where the gate cannot be satisfied, and that
    includes the case where it cannot be run at all. A null record says "nobody
    looked" — which is worse than a list, and still better than a refusal that
    leaves the operator with no path at all.
    """
    spec_path, _ = stale_spec(tmp_path)
    manifest_bytes = b'{"schema":"kg.app_review.submission.v1"}\n'
    stub_bundle(monkeypatch, manifest_bytes)

    def unusable_gate(spec_path, workspace_root):
        raise evidence.EvidenceError("gate.report.invalid")

    monkeypatch.setattr(evidence, "evaluate_gate", unusable_gate)

    code = evidence.main(
        refresh_argv(spec_path, tmp_path, "--commit", "--acknowledge-gate-block")
    )

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["status"] == "written"
    assert document["gateCheck"] == "acknowledged"
    assert document["gateBlocks"] is None
    assert json.loads(spec_path.read_text(encoding="utf-8"))["target"][
        "desiredManifestSHA256"
    ] == sha(manifest_bytes)


def test_refresh_anchor_refuses_an_acknowledgement_that_writes_nothing(
    tmp_path: Path, monkeypatch, capsys
):
    """Without --commit there is no block being acknowledged, only a miscount.

    `acknowledgedGateBlock: true` on a dry-run would make any later tally of
    "how often did we override the gate" wrong in the direction that flatters us.
    """
    spec_path, stale = stale_spec(tmp_path)
    published = stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    asked = stub_gate(monkeypatch, "pass", [])

    code = evidence.main(refresh_argv(spec_path, tmp_path, "--acknowledge-gate-block"))

    document = json.loads(capsys.readouterr().out)
    assert code == 2
    assert "anchor.acknowledge-without-commit" in document["error"]
    assert spec_path.read_text(encoding="utf-8") == stale
    assert published == []
    assert asked == []


@pytest.mark.parametrize("status", ["block", "warn", "", "unknown-future-verdict"])
def test_refresh_anchor_commit_refuses_every_verdict_that_is_not_pass(
    tmp_path: Path, monkeypatch, status: str
):
    """Fail-closed on the verdict, not open on everything the gate hasn't said yet.

    An `!= "block"` test would pass today and open a write path the first time
    the gate learns a fourth verdict word.
    """
    spec_path, stale = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, status, [])

    with pytest.raises(evidence.EvidenceError, match=r"anchor\.gate-blocked"):
        evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert spec_path.read_text(encoding="utf-8") == stale


def test_refresh_anchor_commit_refuses_when_the_gate_cannot_be_evaluated(
    tmp_path: Path, monkeypatch
):
    """A gate that cannot answer is not a gate that said yes."""
    spec_path, stale = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')

    def unusable_gate(spec_path, workspace_root):
        raise evidence.EvidenceError("gate.execution:1")

    monkeypatch.setattr(evidence, "evaluate_gate", unusable_gate)

    with pytest.raises(evidence.EvidenceError, match=r"gate\.execution:1"):
        evidence.refresh_desired_anchor(spec_path, commit=True, **anchor_kwargs(tmp_path))

    assert spec_path.read_text(encoding="utf-8") == stale


def test_refresh_anchor_refusal_previews_the_block_the_write_would_erase(
    tmp_path: Path, monkeypatch, capsys
):
    """The anchor's own block leads the preview regardless of the gate's order.

    Today `desired.*` happens to be emitted first, so a naive head-of-list
    preview shows it by luck. Insert one new check ahead of it and the refusal
    would preview six codes that have nothing to do with what is being written.
    """
    spec_path, _ = stale_spec(tmp_path)
    late = [f"journey.surface-{index:02d}.missing" for index in range(8)]
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "block", [*late, "desired.manifest-sha256"])

    code = evidence.main(refresh_argv(spec_path, tmp_path, "--commit"))

    error = json.loads(capsys.readouterr().out)["error"]
    assert code == 2
    # Anchor block first, then the rest in the order the gate emitted them.
    assert error.startswith(f"anchor.gate-blocked:desired.manifest-sha256,{late[0]},{late[1]}")
    assert late[-1] not in error


def test_refresh_anchor_refusal_names_only_the_block_a_write_could_erase(
    tmp_path: Path, monkeypatch, capsys
):
    """Do not tell the operator that 48 blocks are about to vanish.

    Writing the spec can only clear `desired.manifest-sha256`
    (ops/app_review_gate.py:988); the rest are unaffected. A warning that
    overstates by 47 teaches the reader to discount the next one.
    """
    spec_path, _ = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "block", ["desired.manifest-sha256", "urls.missing"])

    evidence.main(refresh_argv(spec_path, tmp_path, "--commit"))

    error = json.loads(capsys.readouterr().out)["error"]
    assert "would erase the desired.manifest-sha256 block" in error
    assert "would erase them" not in error


def test_refresh_anchor_refusal_repeats_the_workspace_root_it_was_given(
    tmp_path: Path, monkeypatch, capsys
):
    """The suggested `status` command must evaluate the same workspace.

    `status --workspace-root` defaults to the cwd, so a refusal that omits the
    root hands the operator a command that inspects a different world than the
    one that just refused them.
    """
    spec_path, _ = stale_spec(tmp_path)
    stub_bundle(monkeypatch, b'{"schema":"kg.app_review.submission.v1"}\n')
    stub_gate(monkeypatch, "block", ["desired.manifest-sha256"])

    evidence.main(refresh_argv(spec_path, tmp_path, "--commit"))

    error = json.loads(capsys.readouterr().out)["error"]
    assert f"--workspace-root {ROOT}" in error


def test_materialize_tracked_file_refuses_path_absent_at_commit(tmp_path: Path):
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    destination = tmp_path / "materialized"

    with pytest.raises(evidence.EvidenceError) as raised:
        evidence._materialize_tracked_file(
            workspace_root=ROOT,
            commit=head,
            rel_path="ios/BooksAndVocab.xcodeproj/does-not-exist.pbxproj",
            destination=destination,
        )

    assert "does-not-exist.pbxproj" in str(raised.value)
    assert not destination.exists()


def test_materialize_tracked_file_writes_blob_bytes_verbatim(tmp_path: Path):
    source_commit = checked_spec()["target"]["sourceCommit"]
    destination = tmp_path / "nested" / "project.pbxproj"

    written = evidence._materialize_tracked_file(
        workspace_root=ROOT,
        commit=source_commit,
        rel_path=PROJECT_FILE_REL,
        destination=destination,
    )

    assert written == destination
    assert destination.read_bytes() == blob_bytes(source_commit, PROJECT_FILE_REL)


def test_checked_spec_desired_manifest_anchor_matches_reproducible_bundle_without_self_reference(
    tmp_path: Path,
):
    spec = json.loads((ROOT / "ops/app_review/2.0.0.json").read_text(encoding="utf-8"))
    kwargs = {
        "workspace_root": ROOT,
        "profile_file": ROOT / "ops/capture_profiles/marketing_account.json",
        "render_output_dir": ROOT / "promotion/screenshots/dist/app-store/iphone",
        "bundle_dir": tmp_path / "bundle",
        "fixed_clock": "2026-07-09T09:00:00Z",
        "locale": "zh-Hant",
    }

    result = evidence.produce_desired_bundle(spec, commit=True, **kwargs)
    manifest = result["manifest"]
    actual = sha((tmp_path / "bundle/manifest.json").read_bytes())
    changed_anchor = json.loads(json.dumps(spec))
    changed_anchor["target"]["desiredManifestSHA256"] = "0" * 64
    changed_result = evidence.produce_desired_bundle(changed_anchor, commit=False, **kwargs)

    assert changed_result["manifest"] == manifest
    assert spec["target"]["desiredManifestSHA256"] == actual


def base_spec(tmp_path: Path) -> dict:
    dataset = tmp_path / "world.json"
    dataset.write_text(json.dumps({"datasetID": "world-1"}), encoding="utf-8")
    return {
        "schema": "kg.app_review.gate.v1",
        "target": {
            "appID": "app-1",
            "versionID": "version-1",
            "bundleID": "com.example.app",
            "marketingVersion": "2.0.0",
            "buildNumber": "6",
            "sourceCommit": "a" * 40,
            "datasetID": "world-1",
            "datasetSHA256": sha(dataset.read_bytes()),
            "demoAccountIdentitySHA256": "d" * 64,
        },
        "artifacts": {
            "urlChecks": {"path": "url.json", "maxAgeHours": 12},
            "journeys": [{"id": "core", "path": "core.json", "maxAgeHours": 24}],
            "attestations": {"human": "human.json", "agent": "agent.json"},
        },
        "requiredLiveURLs": [
            {"id": "site", "url": "https://example.com/", "claimIDs": ["web"]}
        ],
        "claims": [{"id": "web", "journeyIDs": []}, {"id": "core-claim", "journeyIDs": ["core"]}],
        "producers": {
            "urlChecks": {"type": "url-checks", "authority": "live-https-get", "command": "url command"},
            "journey.core": {"type": "ios-ui-journey", "authority": "ios-release-test", "command": "journey command"},
            "attestation.human": {"type": "human-attestation", "authority": "release-owner", "command": "human command"},
            "attestation.agent": {"type": "agent-attestation", "authority": "gate-agent", "command": "agent command"},
        },
    }


def test_url_checks_get_hashes_exact_body_and_rejects_redirect_or_error(tmp_path: Path):
    spec = base_spec(tmp_path)

    passed = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda url: (200, url, b"body"),
    )
    redirected = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda _url: (302, "https://example.com/new", b"redirect"),
    )
    failed = evidence.produce_url_checks(
        spec,
        observed_at="2026-07-13T10:00:00Z",
        fetch=lambda _url: (_ for _ in ()).throw(OSError("offline")),
    )

    assert passed["schema"] == "kg.app_review.url_checks.v1"
    assert passed["results"][0] == {
        "id": "site",
        "url": "https://example.com/",
        "status": "pass",
        "httpStatus": 200,
        "finalUrl": "https://example.com/",
        "contentSHA256": sha(b"body"),
    }
    assert redirected["results"][0]["status"] == "error"
    assert failed["results"][0]["status"] == "error"


def valid_run(tmp_path: Path, spec: dict) -> dict:
    artifact = tmp_path / "journey.png"
    artifact.write_bytes(b"png")
    target = spec["target"]
    return {
        "schema": "kg.ios.run.v1",
        "status": "ok",
        "result": "ok",
        "executed": "2",
        "options": {
            "evidenceProducer": "ops/ios_test.sh",
            "configuration": "Release",
            "bundleID": target["bundleID"],
            "marketingVersion": target["marketingVersion"],
            "buildNumber": target["buildNumber"],
            "sourceCommit": target["sourceCommit"],
            "datasetID": target["datasetID"],
            "datasetSHA256": target["datasetSHA256"],
            "fixedClock": "2026-07-13T08:00:00Z",
            "startedAt": "2026-07-13T09:00:00Z",
            "finishedAt": "2026-07-13T09:05:00Z",
            "evidenceKind": "release-equivalent-simulator",
            "device": "iPhone 17 Pro Max",
            "os": "iOS 26.0",
            "locale": "zh-Hant",
            "timezone": "Asia/Taipei",
            "appearance": "light",
            "networkMode": "fixture",
            "fixtureDataUsed": True,
        },
        "artifacts": {"uiContactSheet": str(artifact)},
    }


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda run: run.update(executed="0"), "journey.tests"),
        (lambda run: run["options"].update(configuration="Debug"), "journey.configuration"),
        (lambda run: run["options"].update(sourceCommit="b" * 40), "journey.sourceCommit"),
        (lambda run: run["options"].update(datasetSHA256="b" * 64), "journey.datasetSHA256"),
        (lambda run: run["options"].update(buildNumber="7"), "journey.buildNumber"),
        (lambda run: run["options"].update(evidenceKind="live-demo"), "journey.evidenceKind"),
        (lambda run: run["options"].update(evidenceProducer="caller"), "journey.producer"),
    ],
)
def test_journey_consumer_blocks_false_green_debug_and_provenance_drift(tmp_path: Path, mutation, code: str):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    mutation(run)

    with pytest.raises(evidence.EvidenceError, match=code):
        evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)


def test_journey_producer_hashes_artifacts_and_emits_exact_contract(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)

    result = evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)

    assert result["schema"] == "kg.app_review.journey.v1"
    assert result["result"]["testsExecuted"] == 2
    assert result["execution"]["configuration"] == "Release"
    assert result["artifacts"][0]["path"] == "journey.png"
    assert result["artifacts"][0]["sha256"] == sha(b"png")


def test_demo_producer_rejects_fixture_masquerading_as_live_demo(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    release = run["options"]
    run["demoEvidence"] = {
        **release,
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "live-demo",
        "networkMode": "live",
        "fixtureDataUsed": True,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": "d" * 64,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.fixtureDataUsed"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_consumer_rejects_caller_magic_string_without_ios_owner(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["demoEvidence"] = {"evidenceProducer": "ops/app_review_evidence.py:live-demo"}

    with pytest.raises(evidence.EvidenceError, match="demo.producer"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_public_cli_does_not_accept_caller_supplied_demo_receipts():
    subparsers = next(
        action for action in evidence.parser()._actions
        if isinstance(action, evidence.argparse._SubParsersAction)
    )

    assert "demo" not in subparsers.choices


def test_demo_identity_resolver_hash_closes_live_mirror_and_rejects_wrong_fingerprint(tmp_path: Path):
    spec = base_spec(tmp_path)
    bundle = tmp_path / "live"
    bundle.mkdir()
    audit = {
        "schema": "kg.app_review.asc_audit.v1",
        "live": {"appID": spec["target"].get("appID"), "version": {"id": spec["target"].get("versionID")}, "reviewDetail": {"fields": {
            "demoAccountName": {"present": True, "identitySHA256": "d" * 64, "ref": "asc://review#name"}
        }}},
    }
    audit_bytes = json.dumps(audit, sort_keys=True).encode()
    (bundle / "audit.json").write_bytes(audit_bytes)
    (bundle / "manifest.json").write_text(json.dumps({
        "schema": "kg.app_review.asc_mirror_bundle.v1",
        "files": [{"path": "audit.json", "byteSize": len(audit_bytes), "sha256": sha(audit_bytes)}],
    }), encoding="utf-8")

    identity = evidence.resolve_demo_identity(spec, bundle)
    assert identity == {"accountRef": "asc://review#name", "identitySHA256": "d" * 64}
    spec["target"]["demoAccountIdentitySHA256"] = "e" * 64
    with pytest.raises(evidence.EvidenceError, match="demo.identity.spec-live"):
        evidence.resolve_demo_identity(spec, bundle)


@pytest.mark.parametrize("identity", [None, "not-a-sha", "A" * 64])
def test_demo_producer_rejects_missing_or_malformed_identity(tmp_path: Path, identity: str | None):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["options"]["liveDemoAccountIdentitySHA256"] = identity
    run["demoEvidence"] = {
        **run["options"],
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "exact-device",
        "networkMode": "live",
        "fixtureDataUsed": False,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": identity,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.account.identitySHA256"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_producer_rejects_spoofed_receipt_identity(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    run["options"]["liveDemoAccountIdentitySHA256"] = "e" * 64
    run["demoEvidence"] = {
        **run["options"],
        "evidenceProducer": "ops/ios_test.sh:live-demo",
        "evidenceKind": "exact-device",
        "networkMode": "live",
        "fixtureDataUsed": False,
        "account": {
            "provenance": "live-account",
            "accountRef": "asc://review#name",
            "accountIdentitySHA256": "d" * 64,
            "entitlementSource": "live-backend",
        },
        "observedAt": "2026-07-13T09:05:00Z",
        "login": "pass",
        "entitlements": ["pro"],
    }

    with pytest.raises(evidence.EvidenceError, match="demo.account.identity-receipt"):
        evidence.produce_demo_access(spec, run, workspace_root=tmp_path)


def test_demo_run_command_contains_only_fingerprint_not_raw_identity(tmp_path: Path):
    command = evidence.build_demo_run_command(
        workspace_root=tmp_path,
        destination="platform=iOS,id=device-1",
        account_identity_sha256="d" * 64,
        locale="zh-Hant",
        timezone_name="Asia/Taipei",
    )

    rendered = " ".join(command)
    assert "--live-demo-account-identity-sha256 " + "d" * 64 in rendered
    assert "demo@example.com" not in rendered


def test_journey_rejects_artifact_outside_workspace(tmp_path: Path):
    spec = base_spec(tmp_path)
    run = valid_run(tmp_path, spec)
    outside = tmp_path.parent / "outside-review-proof.png"
    outside.write_bytes(b"png")
    run["artifacts"]["uiContactSheet"] = str(outside)

    with pytest.raises(evidence.EvidenceError, match="journey.artifact.outside-workspace"):
        evidence.produce_journey(spec, "core", run, workspace_root=tmp_path)


def test_plan_hard_blocks_missing_producer_and_lists_authority(tmp_path: Path):
    spec = base_spec(tmp_path)
    spec["producers"].pop("journey.core")

    plan = evidence.build_plan(spec, tmp_path)

    missing = next(item for item in plan["evidence"] if item["id"] == "journey.core")
    human = next(item for item in plan["evidence"] if item["id"] == "attestation.human")
    assert missing["status"] == "block"
    assert missing["reason"] == "producer-missing"
    assert human["authority"] == "release-owner"
    assert human["command"] == "human command"


def test_status_does_not_mark_existing_but_invalid_artifact_ready(tmp_path: Path):
    spec = base_spec(tmp_path)
    (tmp_path / "url.json").write_text("{}", encoding="utf-8")
    plan = evidence.build_plan(spec, tmp_path)

    status = evidence.apply_gate_blocks(
        plan,
        {"verdict": {"status": "block"}, "blocks": [{"code": "urls.schema"}]},
    )

    url_item = next(item for item in status["evidence"] if item["id"] == "urlChecks")
    assert url_item["status"] == "block"
    assert url_item["reason"] == "gate:urls.schema"


def test_appearance_producer_requires_receipt_and_target_bindings(tmp_path: Path):
    spec = base_spec(tmp_path)
    spec["target"]["sourceCommit"] = "a" * 40
    root = tmp_path / "catalog"
    root.mkdir()
    shared = {
        "sourceCommit": "a" * 40,
        "datasetID": spec["target"]["datasetID"],
        "datasetSHA256": spec["target"]["datasetSHA256"],
        "fixedClock": "2026-07-13T08:00:00Z",
    }
    (root / "catalog_appearance.json").write_text(json.dumps({"schema": "kg.catalog.appearance.v1", **shared, "verdict": {"status": "pass"}}), encoding="utf-8")
    (root / "catalog_run_receipt.json").write_text(json.dumps({"schema": "kg.ios.catalog.run_receipt.v1", **shared, "status": "pass"}), encoding="utf-8")

    assert evidence.produce_appearance(spec, root)["verdict"]["status"] == "pass"
    drift = json.loads((root / "catalog_run_receipt.json").read_text(encoding="utf-8"))
    drift["sourceCommit"] = "b" * 40
    (root / "catalog_run_receipt.json").write_text(json.dumps(drift), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="appearance.receipt.sourceCommit"):
        evidence.produce_appearance(spec, root)


@pytest.mark.skipif(sys.platform != "darwin", reason="renameatx_np is the macOS atomic directory exchange")
def test_desired_publication_atomically_exchanges_complete_directories(tmp_path: Path):
    destination = tmp_path / "bundle"
    staged = tmp_path / "stage"
    destination.mkdir()
    staged.mkdir()
    (destination / "old").write_text("old", encoding="utf-8")
    (staged / "new").write_text("new", encoding="utf-8")

    evidence._publish_directory_atomically(staged, destination)

    assert (destination / "new").read_text(encoding="utf-8") == "new"
    assert not (destination / "old").exists()
    assert (staged / "old").read_text(encoding="utf-8") == "old"

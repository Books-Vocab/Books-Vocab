"""RED contract for the canonical Felix compute control-plane surfaces."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from felix_compute_worker import FelixComputeWorker, WorkerError
from lib.compute_admission import AdmissionError, admit
from lib.compute_capsule import CapsuleError, materialize_tracked_capsule
from lib.compute_job_lifecycle import JobLifecycle, LifecycleError
from lib.compute_receipt import (
    AckReplayError,
    OscarAckAuthority,
    ReceiptError,
    ReceiptSigner,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _committed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "backend").mkdir()
    (repo / "backend" / "test.py").write_text("print('ok')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_tracked_capsule_excludes_git_and_rejects_dirty_or_untracked(tmp_path: Path):
    repo, commit = _committed_repo(tmp_path)
    capsule = materialize_tracked_capsule(repo, commit, tmp_path / "capsule")
    assert capsule.commit == commit
    assert ".git" not in capsule.files
    assert capsule.tree_sha256
    (repo / "untracked.txt").write_text("nope\n", encoding="utf-8")
    with pytest.raises(CapsuleError, match="dirty|untracked"):
        materialize_tracked_capsule(repo, commit, tmp_path / "dirty-capsule")
    (repo / "untracked.txt").unlink()
    (repo / "backend" / "test.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(CapsuleError, match="dirty"):
        materialize_tracked_capsule(repo, commit, tmp_path / "modified-capsule")


def test_admission_requires_host_health_and_exact_sandbox():
    safe = {
        "host_role": "felix",
        "host_id": "felix-test",
        "health": {"healthy": True, "deploy_lock": False, "backup_active": False, "reconcile_active": False},
        "sandbox": {"network": "none", "read_only_rootfs": True, "non_root": True, "cap_drop": ["ALL"], "no_new_privileges": True},
    }
    assert admit(safe).host_id == "felix-test"
    with pytest.raises(AdmissionError, match="deploy-lock"):
        admit({**safe, "health": {**safe["health"], "deploy_lock": True}})
    with pytest.raises(AdmissionError, match="sandbox"):
        admit({**safe, "sandbox": {**safe["sandbox"], "network": "host"}})


def test_receipt_is_asymmetric_and_ack_is_controller_only(tmp_path: Path):
    signer = ReceiptSigner.generate()
    payload = {"job_id": "job-1", "request_digest": "a" * 64, "source_commit": "b" * 40, "profile": "fake.echo", "spec_digest": "c" * 64, "runner_image_digest": "sha256:" + "d" * 64, "host_id": "felix", "returncode": 0, "duration_ms": 1, "log_digest": "e" * 64, "artifact_digest": "f" * 64}
    receipt = signer.sign(payload)
    assert signer.verify(receipt)["job_id"] == "job-1"
    public_verifier = ReceiptSigner.from_public_bytes(signer.public_bytes())
    assert public_verifier.verify(receipt)["job_id"] == "job-1"
    with pytest.raises(ReceiptError, match="signature"):
        signer.verify({**receipt, "returncode": 1})
    authority = OscarAckAuthority(tmp_path / "ack-ledger.json", key=b"k" * 32)
    ack = authority.issue("job-1", receipt["receipt_digest"])
    assert authority.verify(ack) is True
    reloaded = OscarAckAuthority(tmp_path / "ack-ledger.json", key=b"k" * 32)
    with pytest.raises(AckReplayError, match="replay"):
        reloaded.verify(ack)
    wrong_digest = dict(ack, receipt_digest="0" * 64)
    with pytest.raises(AckReplayError, match="digest|replay|invalid"):
        authority.verify(wrong_digest)
    with pytest.raises(AckReplayError, match="replay"):
        authority.verify(ack)


def test_lifecycle_requires_order_and_reaps_only_terminal(tmp_path: Path):
    lifecycle = JobLifecycle(tmp_path / "jobs.json", ttl_seconds=1)
    lifecycle.stage("job-1")
    lifecycle.transition("job-1", "running")
    lifecycle.transition("job-1", "terminal")
    lifecycle.transition("job-1", "fetched")
    lifecycle.transition("job-1", "acked")
    assert lifecycle.reap(now=10_000) == ["job-1"]
    lifecycle.stage("job-active")
    lifecycle.transition("job-active", "running")
    lifecycle.stage("job-terminal")
    lifecycle.transition("job-terminal", "running")
    lifecycle.transition("job-terminal", "terminal")
    assert lifecycle.reap(now=10_000) == ["job-terminal"]
    assert lifecycle.get("job-active")["state"] == "running"
    with pytest.raises(LifecycleError, match="order"):
        lifecycle.transition("job-2", "acked")


def test_worker_refuses_caller_paths_and_admin_is_honest():
    worker = FelixComputeWorker(controller_root=Path("/host-owned/controller"))
    with pytest.raises(WorkerError, match="source-root|controller-owned"):
        worker.submit({"source_root": "/tmp/caller", "receipt_key_path": "/tmp/key"})
    # The repository-only selftest must never claim a live cross-host proof.
    from felix_compute_admin import selftest_payload

    report = selftest_payload()
    assert report["mode"] == "local-fixture"
    assert report["cross_host_verified"] is False

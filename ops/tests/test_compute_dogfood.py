from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.compute_dogfood import (
    AckReplayError,
    AdmissionError,
    CapsuleError,
    ComputeController,
    HostProof,
    ReceiptError,
)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix().encode()
            digest.update(len(rel).to_bytes(4, "big"))
            digest.update(rel)
            data = path.read_bytes()
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def _safe_request(root: Path) -> dict:
    return {
        "job_id": "job-001",
        "profile": "fake.echo",
        "source_root": str(root),
        "source_commit": "a" * 40,
        "tree_sha256": _tree_digest(root),
        "command": ["echo", "hello"],
        "sandbox": {
            "network": "none",
            "read_only_rootfs": True,
            "non_root": True,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
        },
    }


def test_fake_host_controller_runs_and_ack_is_one_time(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "hello.txt").write_text("hello\n", encoding="utf-8")
    controller = ComputeController(
        allowed_source_roots=(tmp_path,),
        host_key=b"host-proof-key",
        receipt_key=b"receipt-key",
        runner=lambda request: {"stdout": "hello\n", "returncode": 0},
    )
    request = _safe_request(tmp_path)
    request["host_proof"] = HostProof.sign(
        {"host_role": "felix", "host_id": "felix-test", "controller": "fake"},
        key=b"host-proof-key",
    )
    result = controller.run(request)
    assert result["receipt"]["source_commit"] == request["source_commit"]
    assert result["receipt"]["host_id"] == "felix-test"
    assert result["ack"]["verified"] is True
    with pytest.raises(AckReplayError):
        controller.verify_ack(result["ack"]["job_id"], result["ack"]["receipt_digest"], result["ack"]["mac"])


def test_capsule_rejects_symlink_and_protected_root(tmp_path: Path):
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "escape").symlink_to("/etc/passwd")
    controller = ComputeController(
        allowed_source_roots=(tmp_path,), host_key=b"k", receipt_key=b"r", runner=lambda _: {}
    )
    with pytest.raises(CapsuleError, match="symlink"):
        controller.run({
            **_safe_request(tmp_path),
            "host_proof": HostProof.sign(
                {"host_role": "felix", "host_id": "f", "controller": "fake"},
                key=b"k",
            ),
        })


def test_admission_rejects_missing_lock_and_unsafe_sandbox(tmp_path: Path):
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    controller = ComputeController(
        allowed_source_roots=(tmp_path,), host_key=b"k", receipt_key=b"r", runner=lambda _: {}
    )
    proof = HostProof.sign(
        {"host_role": "felix", "host_id": "f", "controller": "fake"}, key=b"k"
    )
    request = {**_safe_request(tmp_path), "host_proof": proof}
    request["sandbox"] = dict(request["sandbox"], cap_drop=["ALL", "SYS_ADMIN"])
    with pytest.raises(AdmissionError, match="cap-drop"):
        controller.run(request)
    request["sandbox"] = dict(_safe_request(tmp_path)["sandbox"], network="internet")
    with pytest.raises(AdmissionError, match="network"):
        controller.run(request)


def test_receipt_rejects_tampering_and_wrong_host(tmp_path: Path):
    (tmp_path / "safe.txt").write_text("ok", encoding="utf-8")
    controller = ComputeController(
        allowed_source_roots=(tmp_path,), host_key=b"k", receipt_key=b"r", runner=lambda _: {}
    )
    request = {**_safe_request(tmp_path), "host_proof": HostProof.sign(
        {"host_role": "oscar", "host_id": "oscar", "controller": "fake"}, key=b"k"
    )}
    with pytest.raises(AdmissionError, match="host-role"):
        controller.run(request)
    request["host_proof"] = HostProof.sign(
        {"host_role": "felix", "host_id": "felix", "controller": "fake"}, key=b"k"
    )
    result = controller.run(request)
    receipt = dict(result["receipt"], returncode=9)
    with pytest.raises(ReceiptError, match="signature"):
        controller.verify_receipt(receipt)

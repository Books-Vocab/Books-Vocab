"""Fail-closed fake-host compute controller for local dogfood only.

This module deliberately accepts an injected runner and fake HostProof so the
repository contract can be exercised without claiming that Felix has a
host-owned controller, pinned OCI image, or live cross-host attestation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ComputeDogfoodError(ValueError):
    """Base class for named, fail-closed fake-host refusals."""


class AdmissionError(ComputeDogfoodError):
    """Request or host admission failed."""


class CapsuleError(ComputeDogfoodError):
    """Source tree cannot become a clean capsule."""


class ReceiptError(ComputeDogfoodError):
    """Receipt is malformed or its signature does not verify."""


class AckReplayError(ComputeDogfoodError):
    """A one-time controller ACK was consumed or is unknown."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _mac(key: bytes, value: Any) -> str:
    return hmac.new(key, _canonical(value), hashlib.sha256).hexdigest()


def _tree_digest(root: Path) -> tuple[str, list[str]]:
    digest = hashlib.sha256()
    files: list[str] = []
    entries = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    for path in entries:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise CapsuleError(f"symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CapsuleError(f"special-file: {relative}")
        rel_bytes = relative.encode("utf-8")
        data = path.read_bytes()
        digest.update(len(rel_bytes).to_bytes(4, "big"))
        digest.update(rel_bytes)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        files.append(relative)
    return digest.hexdigest(), files


def _under(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


@dataclass(frozen=True)
class HostProof:
    payload: dict[str, Any]
    signature: str

    @classmethod
    def sign(cls, payload: dict[str, Any], *, key: bytes) -> HostProof:
        if not isinstance(payload, dict):
            raise AdmissionError("host-proof-schema")
        return cls(dict(payload), _mac(key, payload))

    def verify(self, *, key: bytes) -> dict[str, Any]:
        expected = _mac(key, self.payload)
        if not hmac.compare_digest(self.signature, expected):
            raise AdmissionError("host-proof-signature")
        if self.payload.get("host_role") != "felix":
            raise AdmissionError("host-role")
        if not isinstance(self.payload.get("host_id"), str) or not self.payload["host_id"]:
            raise AdmissionError("host-id")
        if self.payload.get("controller") != "fake":
            raise AdmissionError("controller-provenance")
        if self.payload.get("issuer") != "felix-controller-fake":
            raise AdmissionError("host-issuer")
        captured_at = self.payload.get("captured_at")
        if not isinstance(captured_at, (int, float)) or abs(time.time() - captured_at) > 300:
            raise AdmissionError("host-freshness")
        if not isinstance(self.payload.get("sequence"), int) or self.payload["sequence"] <= 0:
            raise AdmissionError("host-sequence")
        health = self.payload.get("health")
        if not isinstance(health, dict) or health != {
            "healthy": True,
            "deploy_lock": False,
            "backup_active": False,
            "reconcile_active": False,
        }:
            raise AdmissionError("host-health")
        return dict(self.payload)


class _AckAuthority:
    """Controller-only one-time MAC store; candidate receives only the MAC."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], bytearray] = {}

    def issue(self, job_id: str, receipt_digest: str) -> tuple[str, str]:
        key = secrets.token_bytes(32)
        self._pending[(job_id, receipt_digest)] = bytearray(key)
        mac = hmac.new(
            key, _canonical({"job_id": job_id, "receipt_digest": receipt_digest}), hashlib.sha256
        ).hexdigest()
        for index in range(len(key)):
            key = key[:index] + b"\x00" + key[index + 1 :]
        return mac, receipt_digest

    def verify(self, job_id: str, receipt_digest: str, mac: str) -> None:
        token = (job_id, receipt_digest)
        stored = self._pending.pop(token, None)
        if stored is None:
            raise AckReplayError("ack-replay")
        key = bytes(stored)
        expected = hmac.new(
            key, _canonical({"job_id": job_id, "receipt_digest": receipt_digest}), hashlib.sha256
        ).hexdigest()
        for index in range(len(stored)):
            stored[index] = 0
        if not hmac.compare_digest(mac, expected):
            raise AckReplayError("ack-invalid")


class ComputeController:
    """Local fake-host controller with no production/network side effects."""

    def __init__(
        self,
        *,
        allowed_source_roots: tuple[Path, ...],
        host_key: bytes,
        receipt_key: bytes,
        runner: Callable[[dict[str, Any]], dict[str, Any]],
        allow_fake_fixture: bool = False,
    ) -> None:
        if not allowed_source_roots or not callable(runner):
            raise AdmissionError("controller-config")
        self._roots = tuple(Path(root).resolve() for root in allowed_source_roots)
        self._host_key = bytes(host_key)
        self._receipt_key = bytes(receipt_key)
        self._runner = runner
        self._allow_fake_fixture = allow_fake_fixture
        self._acks = _AckAuthority()
        self._last_host_sequence = 0

    def _admit(self, request: dict[str, Any], proof: HostProof) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise AdmissionError("request-schema")
        proof_payload = proof.verify(key=self._host_key)
        sandbox = request.get("sandbox")
        if not isinstance(sandbox, dict):
            raise AdmissionError("sandbox-schema")
        expected = {
            "network": "none",
            "read_only_rootfs": True,
            "non_root": True,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
        }
        if sandbox != expected:
            for field, value in expected.items():
                if sandbox.get(field) != value:
                    code = "cap-drop" if field == "cap_drop" else field.replace("_", "-")
                    raise AdmissionError(code)
            raise AdmissionError("sandbox-policy")
        source_commit = request.get("source_commit")
        if not isinstance(source_commit, str) or len(source_commit) != 40 or any(
            character not in "0123456789abcdef" for character in source_commit
        ):
            raise AdmissionError("source-commit")
        if proof_payload.get("source_commit") != source_commit:
            raise AdmissionError("source-commit-attestation")
        profile = request.get("profile")
        if not isinstance(profile, str) or not profile or "/" in profile:
            raise AdmissionError("profile")
        command = request.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(token, str) and token for token in command
        ):
            raise AdmissionError("command-schema")
        shell_tokens = {Path(token).name for token in command if not token.startswith("-")}
        if shell_tokens & {
            "sh", "bash", "dash", "zsh", "ksh", "fish", "pwsh", "powershell", "cmd", "env"
        } or any(token in {"-c", "--command"} for token in command):
            raise AdmissionError("command")
        return proof_payload

    def _capsule(self, request: dict[str, Any]) -> dict[str, Any]:
        raw_root = request.get("source_root")
        if not isinstance(raw_root, str) or not raw_root:
            raise CapsuleError("source-root")
        root = Path(raw_root)
        if not root.is_absolute():
            raise CapsuleError("source-root-absolute")
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise CapsuleError(f"source-root: {exc}") from exc
        if not _under(resolved, self._roots):
            raise CapsuleError("source-root-allowlist")
        if resolved == Path("/") or resolved in {Path("/etc"), Path("/var"), Path("/private") }:
            raise CapsuleError("protected-root")
        source_kind = request.get("source_kind")
        if source_kind not in {"fake-fixture", "clean-committed-tree"}:
            raise CapsuleError("source-kind")
        if source_kind == "fake-fixture" and not self._allow_fake_fixture:
            raise CapsuleError("source-kind-fake-disabled")
        if source_kind == "clean-committed-tree":
            if not (resolved / ".git").exists():
                raise CapsuleError("source-git")
            status = subprocess.run(
                ["git", "-C", str(resolved), "status", "--porcelain", "--untracked-files=all"],
                capture_output=True,
                check=False,
                text=True,
            )
            if status.returncode != 0 or status.stdout:
                raise CapsuleError("source-git-dirty")
            head = subprocess.run(
                ["git", "-C", str(resolved), "rev-parse", "HEAD"],
                capture_output=True,
                check=False,
                text=True,
            )
            if head.returncode != 0 or head.stdout.strip() != request["source_commit"]:
                raise CapsuleError("source-commit")
        actual_digest, files = _tree_digest(resolved)
        if request.get("tree_sha256") != actual_digest:
            raise CapsuleError("tree-digest")
        return {
            "source_root": str(resolved),
            "source_commit": request["source_commit"],
            "tree_sha256": actual_digest,
            "files": files,
        }

    def _materialize(self, capsule: dict[str, Any], destination: Path) -> None:
        source = Path(capsule["source_root"])
        for relative in capsule["files"]:
            source_path = source / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target, follow_symlinks=False)
            os.chmod(target, 0o444)
        for directory in sorted(
            (path for path in destination.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            os.chmod(directory, 0o555)
        os.chmod(destination, 0o555)

    def _receipt(self, request: dict[str, Any], proof: dict[str, Any], capsule: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or not isinstance(result.get("stdout"), str):
            raise ReceiptError("runner-result")
        returncode = result.get("returncode")
        if not isinstance(returncode, int):
            raise ReceiptError("returncode")
        stdout_digest = hashlib.sha256(result["stdout"].encode()).hexdigest()
        payload = {
            "schema": "kg.compute_receipt.fake-host.v1",
            "job_id": request["job_id"],
            "profile": request["profile"],
            "source_commit": capsule["source_commit"],
            "tree_sha256": capsule["tree_sha256"],
            "host_id": proof["host_id"],
            "host_role": proof["host_role"],
            "returncode": returncode,
            "stdout_digest": stdout_digest,
            "log_digest": stdout_digest,
            "artifact_digest": capsule["tree_sha256"],
            "duration_ms": 0,
            "nonce": secrets.token_hex(16),
            "request_digest": hashlib.sha256(
                _canonical(
                    {
                        "job_id": request["job_id"],
                        "profile": request["profile"],
                        "source_root": capsule["source_root"],
                        "source_commit": capsule["source_commit"],
                        "tree_sha256": capsule["tree_sha256"],
                        "command": request["command"],
                        "sandbox": request["sandbox"],
                    }
                )
            ).hexdigest(),
            "spec_digest": hashlib.sha256(
                _canonical(
                    {
                        "profile": request["profile"],
                        "command": request["command"],
                        "sandbox": request["sandbox"],
                    }
                )
            ).hexdigest(),
            "runner_identity": "fake-runner",
            "runner_image_digest": "sha256:" + ("0" * 64),
            "ack_binding": {"job_id": request["job_id"]},
            "live_selftest": False,
            "host_provenance": "fake-host",
        }
        payload["signature"] = _mac(self._receipt_key, payload)
        return payload

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict) or not isinstance(request.get("job_id"), str):
            raise AdmissionError("request-schema")
        proof = request.get("host_proof")
        if not isinstance(proof, HostProof):
            raise AdmissionError("host-proof-schema")
        proof_payload = self._admit(request, proof)
        capsule = self._capsule(request)
        sequence = proof_payload["sequence"]
        if sequence <= self._last_host_sequence:
            raise AdmissionError("host-sequence")
        with tempfile.TemporaryDirectory(prefix="kg-compute-capsule-") as materialized:
            self._materialize(capsule, Path(materialized))
            capsule_for_runner = {**capsule, "materialized_root": materialized}
            result = self._runner(
                {
                    "job_id": request["job_id"],
                    "profile": request["profile"],
                    "command": list(request["command"]),
                    "sandbox": dict(request["sandbox"]),
                    "capsule": capsule_for_runner,
                }
            )
        receipt = self._receipt(request, proof_payload, capsule, result)
        self._last_host_sequence = sequence
        unsigned = dict(receipt)
        signature = unsigned.pop("signature")
        receipt_digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
        mac, _ = self._acks.issue(request["job_id"], receipt_digest)
        return {
            "receipt": receipt,
            "ack": {
                "job_id": request["job_id"],
                "receipt_digest": receipt_digest,
                "mac": mac,
                "verified": False,
                "signature": signature,
            },
        }

    def verify_ack(self, job_id: str, receipt_digest: str, mac: str) -> bool:
        self._acks.verify(job_id, receipt_digest, mac)
        return True

    def verify_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(receipt, dict):
            raise ReceiptError("receipt-schema")
        signature = receipt.get("signature")
        if not isinstance(signature, str):
            raise ReceiptError("signature")
        unsigned = dict(receipt)
        unsigned.pop("signature", None)
        required = {
            "schema", "job_id", "profile", "source_commit", "tree_sha256", "host_id",
            "host_role", "returncode", "stdout_digest", "live_selftest", "host_provenance",
            "log_digest", "artifact_digest", "duration_ms", "nonce", "request_digest",
            "spec_digest", "runner_identity", "runner_image_digest",
            "ack_binding",
        }
        if set(unsigned) != required:
            raise ReceiptError("receipt-fields")
        expected = _mac(self._receipt_key, unsigned)
        if not hmac.compare_digest(signature, expected):
            raise ReceiptError("signature")
        return unsigned

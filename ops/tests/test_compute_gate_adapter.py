from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib import compute_receipt
from lib.compute_receipt import (
    ReceiptSigner,
    RemoteGateAdapter,
    RemoteGateError,
    RemotePreStartError,
)

NOW = 1_700_000_000.0
SOURCE_COMMIT = "a" * 40
TREE_SHA = "b" * 64
SPEC_DIGEST = "c" * 64
RUNNER_IMAGE = "sha256:" + "d" * 64
LOG = b"remote child passed\n"
ARTIFACT = b"artifact-bytes"
ADMISSION = {"host": "felix", "source_kind": "clean-committed-tree"}


def _profile(*, remote_eligible: bool = True, **overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "command": {"argv": ["ignored", "{test_path}"], "shell": False},
        "remote_eligible": remote_eligible,
        "git_metadata_required": False,
        "source_kind": "clean-committed-tree",
        "side_effects": ["repo-read"],
        "network_policy": "none",
        "runner_image_digest": RUNNER_IMAGE,
        "timeout_seconds": 300,
    }
    profile.update(overrides)
    return profile


def _adapter(
    tmp_path: Path,
    signer: ReceiptSigner,
    *,
    profile: dict[str, Any] | None = None,
    clock: float = NOW,
) -> RemoteGateAdapter:
    return RemoteGateAdapter(
        {"profiles": {"remote.echo": profile or _profile()}},
        pinned_public_key=signer.public_bytes(),
        job_ledger=tmp_path / "remote-jobs",
        pinned_key_id="felix-test-key",
        clock=lambda: clock,
    )


def _prepare(adapter: RemoteGateAdapter) -> dict[str, Any]:
    return adapter.prepare(
        "remote.echo",
        source_commit=SOURCE_COMMIT,
        tree_sha256=TREE_SHA,
        spec_digest=SPEC_DIGEST,
        admission_snapshot=ADMISSION,
    )


def _receipt_payload(
    request: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": compute_receipt.REMOTE_RECEIPT_SCHEMA,
        "job_id": request["job_id"],
        "nonce": request["nonce"],
        "pinned_key_id": request["pinned_key_id"],
        "request_digest": request["request_digest"],
        "host": request["host"],
        "profile": request["profile"],
        "spec_digest": request["spec_digest"],
        "runner_image_digest": request["runner_image_digest"],
        "source_commit": request["source_commit"],
        "tree_sha256": request["tree_sha256"],
        "admission_snapshot": request["admission_snapshot"],
        "started_at": NOW + 0.1,
        "finished_at": NOW + 0.5,
        "duration_ms": 400,
        "returncode": 0,
        "status": "pass",
        "log_digest": hashlib.sha256(LOG).hexdigest(),
        "artifact_digest": hashlib.sha256(ARTIFACT).hexdigest(),
        "runner_identity": request["runner_identity"],
        "tool_identity": request["tool_identity"],
        "worker_state": "completed",
        "summary": "remote child passed",
    }
    payload.update(overrides)
    return payload


def _signed_receipt(
    signer: ReceiptSigner,
    request: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    return signer.sign(_receipt_payload(request, **overrides))


def test_prepare_binds_felix_and_never_forwards_profile_command(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    request = _prepare(_adapter(tmp_path, signer))

    assert request["schema"] == compute_receipt.REMOTE_REQUEST_SCHEMA
    assert request["host"] == "felix"
    assert len(request["nonce"]) == 64
    assert request["nonce"].islower()
    assert "command" not in request
    assert request["profile"] == "remote.echo"
    assert request["runner_image_digest"] == RUNNER_IMAGE


def test_valid_remote_receipt_is_trusted_once_and_preserves_child_summary(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)

    result = adapter.adapt(
        request,
        receipt,
        name="remote-child",
        level="block",
        cwd=".",
        log_bytes=LOG,
        artifact_bytes=ARTIFACT,
        current_head=SOURCE_COMMIT,
    )

    assert result["status"] == "pass"
    assert result["rc"] == 0
    assert result["executed"] is True
    assert result["output_tail"] == LOG.decode()
    assert result["remote_validation"]["status"] == "validated"
    assert result["remote_validation"]["host"] == "felix"
    assert result["summary"] == "remote child passed"

    with pytest.raises(RemoteGateError, match="replay"):
        adapter.validate(
            request,
            receipt,
            log_bytes=LOG,
            artifact_bytes=ARTIFACT,
            current_head=SOURCE_COMMIT,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pinned_key_id", "wrong-key"),
        ("nonce", "e" * 64),
        ("job_id", "job-other"),
        ("host", "oscar"),
        ("profile", "other.profile"),
        ("spec_digest", "e" * 64),
        ("runner_image_digest", "sha256:" + "e" * 64),
        ("source_commit", "f" * 40),
        ("tree_sha256", "f" * 64),
        ("runner_identity", "fake-runner"),
        ("tool_identity", "fake-tool"),
        ("admission_snapshot", {"host": "oscar"}),
        ("worker_state", "interrupted"),
        ("status", "block"),
        ("returncode", 1),
        ("started_at", NOW + 5),
    ],
)
def test_receipt_binding_matrix_rejects_signed_mismatch(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request, **{field: value})

    with pytest.raises(RemoteGateError):
        adapter.validate(
            request,
            receipt,
            log_bytes=LOG,
            artifact_bytes=ARTIFACT,
            current_head=SOURCE_COMMIT,
        )


def test_rejects_fake_signature_and_modified_log_without_local_fallback(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)
    forged = _signed_receipt(ReceiptSigner.generate(), request)

    with pytest.raises(RemoteGateError, match="signature"):
        adapter.validate(
            request,
            forged,
            log_bytes=LOG,
            artifact_bytes=ARTIFACT,
            current_head=SOURCE_COMMIT,
        )
    with pytest.raises(RemoteGateError, match="log-digest"):
        adapter.validate(
            request,
            receipt,
            log_bytes=b"modified",
            artifact_bytes=ARTIFACT,
            current_head=SOURCE_COMMIT,
        )


def test_nonce_is_csprng_bound_and_reuse_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    job_ids = iter(("1" * 32, "2" * 32))

    def fake_token_hex(length: int) -> str:
        return next(job_ids) if length == 16 else "a" * 64

    monkeypatch.setattr(compute_receipt.secrets, "token_hex", fake_token_hex)
    _prepare(adapter)
    with pytest.raises(RemoteGateError, match="nonce-replay"):
        _prepare(adapter)


def test_head_movement_rejects_remote_result_before_record_admission(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)

    with pytest.raises(RemoteGateError, match="head-moved"):
        adapter.validate(
            request,
            receipt,
            log_bytes=LOG,
            artifact_bytes=ARTIFACT,
            current_head="f" * 40,
        )


def test_only_named_pre_start_transport_failure_can_fallback_local(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    local_calls: list[str] = []

    def local_check() -> dict[str, Any]:
        local_calls.append("called")
        return {"status": "pass", "level": "block", "rc": 0}

    def transport(_request: dict[str, Any]) -> dict[str, Any]:
        raise RemotePreStartError("transport-unavailable")

    result = adapter.run(
        "remote.echo",
        source_commit=SOURCE_COMMIT,
        tree_sha256=TREE_SHA,
        spec_digest=SPEC_DIGEST,
        admission_snapshot=ADMISSION,
        local_check=local_check,
        transport=transport,
        current_head=SOURCE_COMMIT,
    )

    assert local_calls == ["called"]
    assert result["status"] == "pass"
    assert result["remote_validation"]["status"] == "fallback-local"
    assert result["remote_validation"]["reason"] == "transport-unavailable"


def test_post_start_bad_receipt_blocks_without_local_fallback(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    local_calls: list[str] = []

    def local_check() -> dict[str, Any]:
        local_calls.append("called")
        return {"status": "pass", "level": "block", "rc": 0}

    def transport(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "receipt": {"schema": "forged"},
            "log": LOG,
            "artifact": ARTIFACT,
            "request": request,
        }

    result = adapter.run(
        "remote.echo",
        source_commit=SOURCE_COMMIT,
        tree_sha256=TREE_SHA,
        spec_digest=SPEC_DIGEST,
        admission_snapshot=ADMISSION,
        local_check=local_check,
        transport=transport,
        current_head=SOURCE_COMMIT,
    )

    assert local_calls == []
    assert result["status"] == "block"
    assert result["executed"] is False
    assert result["remote_validation"]["status"] == "rejected"


def test_ineligible_profile_stays_on_local_route(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer, profile=_profile(remote_eligible=False))
    local_calls: list[str] = []

    result = adapter.run(
        "remote.echo",
        source_commit=SOURCE_COMMIT,
        tree_sha256=TREE_SHA,
        spec_digest=SPEC_DIGEST,
        admission_snapshot=ADMISSION,
        local_check=lambda: local_calls.append("called") or {"status": "pass"},
        transport=lambda _request: pytest.fail(
            "ineligible profile was routed remotely"
        ),
        current_head=SOURCE_COMMIT,
    )

    assert local_calls == ["called"]
    assert result["status"] == "pass"
    assert result["remote_validation"]["status"] == "local"

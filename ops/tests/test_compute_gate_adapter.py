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


def _validate(
    adapter: RemoteGateAdapter,
    request: dict[str, Any],
    receipt: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "log_bytes": LOG,
        "artifact_bytes": ARTIFACT,
        "current_head": SOURCE_COMMIT,
    }
    kwargs.update(overrides)
    return adapter.validate(request, receipt, **kwargs)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"started_at": NOW - 10, "finished_at": NOW - 9}, "timestamp-order"),
        ({"finished_at": NOW + 600}, "timestamp-future"),
        ({"duration_ms": 5_000}, "duration"),
        ({"duration_ms": 301_000}, "duration"),
        ({"log_digest": "0" * 64}, "log-digest"),
        ({"artifact_digest": "0" * 64}, "artifact-digest"),
        ({"status": "bogus"}, "status"),
        ({"returncode": 1, "status": "pass"}, "status-returncode"),
        ({"returncode": 0, "status": "block"}, "status-returncode"),
    ],
)
def test_signed_but_unattributable_receipts_are_rejected(
    tmp_path: Path, overrides: dict[str, Any], match: str
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request, **overrides)

    with pytest.raises(RemoteGateError, match=match):
        _validate(adapter, request, receipt)


def test_stale_receipt_is_rejected_by_freshness(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer, clock=NOW)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)
    later = _adapter(tmp_path, signer, clock=NOW + 10_000)

    with pytest.raises(RemoteGateError, match="stale"):
        _validate(later, request, receipt)


def test_post_signature_tamper_and_missing_fields_fail_closed(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)

    tampered = {**receipt, "status": "warn"}
    with pytest.raises(RemoteGateError, match="signature"):
        _validate(adapter, request, tampered)

    missing = dict(receipt)
    missing.pop("log_digest")
    with pytest.raises(RemoteGateError):
        _validate(adapter, request, missing)

    extra = signer.sign({**_receipt_payload(request), "injected": "field"})
    with pytest.raises(RemoteGateError, match="receipt-schema"):
        _validate(adapter, request, extra)

    for log, artifact in ((None, ARTIFACT), (LOG, None)):
        with pytest.raises(RemoteGateError, match="unattributable"):
            _validate(adapter, request, receipt, log_bytes=log, artifact_bytes=artifact)

    # None of the failures above consumed the job; the genuine receipt still works.
    assert _validate(adapter, request, receipt)["status"] == "pass"


def test_request_tamper_is_rejected(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)

    with pytest.raises(RemoteGateError, match="request-digest"):
        _validate(adapter, {**request, "tree_sha256": "9" * 64}, receipt)


def test_receipt_swapped_across_jobs_is_rejected_and_consumes_nothing(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request_a = _prepare(adapter)
    request_b = _prepare(adapter)
    receipt_a = _signed_receipt(signer, request_a)

    with pytest.raises(RemoteGateError, match="binding:"):
        _validate(adapter, request_b, receipt_a)
    # Job A is still consumable exactly once.
    assert _validate(adapter, request_a, receipt_a)["status"] == "pass"
    with pytest.raises(RemoteGateError, match="replay"):
        _validate(adapter, request_a, receipt_a)


def test_replay_across_adapter_instances_uses_persistent_ledger(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    first = _adapter(tmp_path, signer)
    request = _prepare(first)
    receipt = _signed_receipt(signer, request)
    _validate(first, request, receipt)

    second = _adapter(tmp_path, signer)
    with pytest.raises(RemoteGateError, match="replay"):
        _validate(second, request, receipt)


def test_unreserved_request_cannot_be_consumed(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)
    other_ledger = RemoteGateAdapter(
        {"profiles": {"remote.echo": _profile()}},
        pinned_public_key=signer.public_bytes(),
        job_ledger=tmp_path / "other-ledger",
        pinned_key_id="felix-test-key",
        clock=lambda: NOW,
    )

    with pytest.raises(RemoteGateError, match="job-unknown"):
        _validate(other_ledger, request, receipt)


def test_head_moving_during_validation_discards_result_without_consuming(
    tmp_path: Path,
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    receipt = _signed_receipt(signer, request)

    with pytest.raises(RemoteGateError, match="head-moved"):
        _validate(adapter, request, receipt, head_reader=lambda: "f" * 40)
    assert _validate(adapter, request, receipt, head_reader=lambda: SOURCE_COMMIT)


def test_wrong_pinned_key_cannot_validate_even_with_matching_key_id(
    tmp_path: Path,
) -> None:
    pinned = ReceiptSigner.generate()
    attacker = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, pinned)
    request = _prepare(adapter)

    with pytest.raises(RemoteGateError, match="signature"):
        _validate(adapter, request, _signed_receipt(attacker, request))


@pytest.mark.parametrize(
    "overrides",
    [
        {"remote_eligible": False},
        {"git_metadata_required": True},
        {"side_effects": ["repo-read", "production-write"]},
        {"network_policy": "egress"},
        {"requires_xcode": True},
        {"requires_simulator": True},
        {"required_capabilities": ["xcode"]},
        {"runner_image_digest": "latest"},
        {"bootstrap": ["install-something"]},
    ],
)
def test_ineligible_profiles_are_never_prepared_for_remote(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer, profile=_profile(**overrides))

    assert adapter.is_remote_eligible("remote.echo") is False
    with pytest.raises(RemoteGateError, match="profile-not-remote-eligible"):
        _prepare(adapter)


def test_unknown_profile_stays_local(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)

    assert adapter.profile_status("nope") == (False, "profile-missing")


def test_request_and_ledger_never_carry_plan_commands(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    adapter = _adapter(
        tmp_path,
        signer,
        profile=_profile(command={"argv": ["sentinel-binary"], "shell": False}),
    )
    request = _prepare(adapter)

    blob = repr(request) + "".join(
        path.read_text()
        for path in (tmp_path / "remote-jobs").rglob("*")
        if path.is_file()
    )
    assert "sentinel-binary" not in blob
    assert "argv" not in blob and "cmd" not in request and "command" not in request


def test_adapter_writes_only_inside_its_job_ledger(tmp_path: Path) -> None:
    signer = ReceiptSigner.generate()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    adapter = _adapter(sandbox, signer)
    request = _prepare(adapter)
    _validate(adapter, request, _signed_receipt(signer, request))

    written = {p.relative_to(sandbox).parts[0] for p in sandbox.rglob("*")}
    assert written == {"remote-jobs"}


def test_ledger_marks_job_consumed_with_receipt_digest(tmp_path: Path) -> None:
    import json

    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)
    request = _prepare(adapter)
    job_file = tmp_path / "remote-jobs" / "jobs" / f"{request['job_id']}.json"
    assert json.loads(job_file.read_text())["state"] == "pending"

    result = _validate(adapter, request, _signed_receipt(signer, request))
    record = json.loads(job_file.read_text())
    assert record["state"] == "consumed"
    assert record["receipt_digest"] == result["receipt_digest"]


def test_real_profile_registry_routes_only_eligible_profiles(
    tmp_path: Path,
) -> None:
    from lib import compute_contract

    registry = compute_contract.load_profile_registry()
    signer = ReceiptSigner.generate()
    adapter = RemoteGateAdapter(
        registry,
        pinned_public_key=signer.public_bytes(),
        job_ledger=tmp_path / "jobs",
        pinned_key_id="felix-test-key",
    )
    for name, profile in registry["profiles"].items():
        assert adapter.is_remote_eligible(name) is profile["remote_eligible"], name


def test_orchestrator_remote_check_end_to_end_valid_and_forged(
    tmp_path: Path,
) -> None:
    import worktree_orchestrate as coordinator

    signer = ReceiptSigner.generate()
    adapter = _adapter(tmp_path, signer)

    def check_for(receipt_signer: ReceiptSigner) -> dict[str, Any]:
        def transport(request: dict[str, Any]) -> dict[str, Any]:
            return {
                "receipt": _signed_receipt(receipt_signer, request),
                "log": LOG,
                "artifact": ARTIFACT,
            }

        return {
            "name": "remote.echo",
            "kind": "remote",
            "cwd": ".",
            "cmd": ["false"],
            "level": "block",
            "remote_adapter": adapter,
            "remote_profile": "remote.echo",
            "remote_source_commit": SOURCE_COMMIT,
            "remote_tree_sha256": TREE_SHA,
            "remote_spec_digest": SPEC_DIGEST,
            "remote_admission_snapshot": ADMISSION,
            "remote_local_check": lambda: pytest.fail("must not run locally"),
            "remote_transport": transport,
            "remote_current_head": SOURCE_COMMIT,
            "remote_head_reader": lambda: SOURCE_COMMIT,
        }

    good = coordinator._run_check(check_for(signer), tmp_path)
    assert (good["status"], good["executed"]) == ("pass", True)

    forged = coordinator._run_check(check_for(ReceiptSigner.generate()), tmp_path)
    assert (forged["status"], forged["executed"]) == ("block", False)
    assert forged["remote_validation"]["verdict"] == "not-executed"

    missing = coordinator._run_check(
        {"name": "x", "kind": "remote", "cwd": ".", "level": "block", "cmd": ["true"]},
        tmp_path,
    )
    assert missing["status"] == "block" and missing["executed"] is False

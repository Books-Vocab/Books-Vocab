"""Focused transport/provenance contract for the Felix dogfood child."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.xmachine_transport import (
    TransportError,
    build_xmachine_argv,
    sign_request,
    verify_remote_result,
)


def _request() -> dict[str, object]:
    return {
        "schema": "kg.compute.request.v1",
        "request_id": "req-0001",
        "nonce": "nonce-0001",
        "profile": "ops.compute-contract-tests",
        "argv": ["uv", "run", "--no-project", "--python", "3.13", "pytest", "-q"],
        "source_head": "a" * 40,
        "profile_digest": "b" * 64,
        "runner_image_digest": "sha256:" + "c" * 64,
        "sandbox_policy": "repo-readonly",
        "issued_at": 1_000,
        "expires_at": 1_060,
    }


def _result(
    request: dict[str, object], key: str = "transport-test-key"
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": "kg.compute.result.v1",
        "request_id": request["request_id"],
        "nonce": request["nonce"],
        "profile": request["profile"],
        "source_head": request["source_head"],
        "profile_digest": request["profile_digest"],
        "runner_image_digest": request["runner_image_digest"],
        "sandbox_policy": request["sandbox_policy"],
        "started_at": 1_010,
        "finished_at": 1_020,
        "artifact": {
            "path": ".cache/compute/req-0001.json",
            "sha256": "d" * 64,
            "bytes": 12,
        },
        "ack": {
            "request_id": request["request_id"],
            "nonce": request["nonce"],
            "status": "ok",
        },
    }
    result["signature"] = sign_request(result, key)
    return result


def test_fixed_launcher_is_literal_shell_false_and_has_no_transport_secret() -> None:
    argv = build_xmachine_argv(["uv", "run", "--no-project", "pytest", "-q"])

    assert argv == [
        "xmachine",
        "felix",
        "--",
        "uv",
        "run",
        "--no-project",
        "pytest",
        "-q",
    ]
    assert all(isinstance(token, str) for token in argv)
    assert "shell=false" not in argv
    assert "SSH_AUTH_SOCK" not in argv
    assert "--identity-file" not in argv


def test_oscar_verifies_request_identity_provenance_freshness_artifact_and_ack() -> (
    None
):
    request = _request()
    request["signature"] = sign_request(request, "transport-test-key")
    verified = verify_remote_result(
        request, _result(request), signing_key="transport-test-key", now=1_025
    )

    assert verified["verdict"] == "accepted"
    assert verified["reason_code"] == "remote-result-accepted"

    for field in ("source_head", "runner_image_digest", "nonce", "request_id"):
        tampered = _result(request)
        tampered[field] = "tampered"
        with pytest.raises(TransportError, match="verification"):
            verify_remote_result(
                request, tampered, signing_key="transport-test-key", now=1_025
            )

    stale = _result(request)
    stale["finished_at"] = 1_100
    with pytest.raises(TransportError, match="freshness"):
        verify_remote_result(
            request, stale, signing_key="transport-test-key", now=1_025
        )

    missing_artifact = copy.deepcopy(_result(request))
    del missing_artifact["artifact"]
    missing_artifact["signature"] = sign_request(missing_artifact, "transport-test-key")
    with pytest.raises(TransportError, match="artifact"):
        verify_remote_result(
            request, missing_artifact, signing_key="transport-test-key", now=1_025
        )

    bad_ack = copy.deepcopy(_result(request))
    bad_ack["ack"]["nonce"] = "wrong"
    bad_ack["signature"] = sign_request(bad_ack, "transport-test-key")
    with pytest.raises(TransportError, match="ack"):
        verify_remote_result(
            request, bad_ack, signing_key="transport-test-key", now=1_025
        )

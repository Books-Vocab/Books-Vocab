"""Bounded xmachine transport and Oscar-side Felix result verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Sequence

SCHEMA = "kg.compute.transport.v1"
REQUEST_SCHEMA = "kg.compute.request.v1"
RESULT_SCHEMA = "kg.compute.result.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_TRANSPORT_TOKENS = frozenset(
    {"--identity-file", "--private-key", "SSH_AUTH_SOCK", "Authorization"}
)


class TransportError(ValueError):
    """Named fail-closed transport or verification refusal."""


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        {key: value for key, value in payload.items() if key != "signature"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_request(payload: dict[str, Any], signing_key: str) -> str:
    if not isinstance(signing_key, str) or not signing_key:
        raise TransportError("verification: signing key is required")
    return hmac.new(signing_key.encode("utf-8"), _canonical(payload), hashlib.sha256).hexdigest()


def build_xmachine_argv(child_argv: Sequence[str]) -> list[str]:
    """Build the only permitted remote launcher argv; no shell or SSH secret."""

    if not child_argv or not all(isinstance(token, str) and token for token in child_argv):
        raise TransportError("launcher: child argv must be non-empty literal strings")
    if any(token in _FORBIDDEN_TRANSPORT_TOKENS for token in child_argv):
        raise TransportError("launcher: raw transport secret or credential flag")
    return ["xmachine", "felix", "--", *child_argv]


def make_request(
    *,
    request_id: str,
    nonce: str,
    profile: str,
    argv: Sequence[str],
    source_head: str,
    profile_digest: str,
    runner_image_digest: str,
    sandbox_policy: str,
    issued_at: int,
    expires_at: int,
    signing_key: str,
    source_root: str = "",
    source_clean: bool = True,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "nonce": nonce,
        "profile": profile,
        "argv": list(argv),
        "source_head": source_head,
        "profile_digest": profile_digest,
        "runner_image_digest": runner_image_digest,
        "sandbox_policy": sandbox_policy,
        "source_root": source_root,
        "source_clean": source_clean,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    request["signature"] = sign_request(request, signing_key)
    return request


def _fail(detail: str) -> None:
    raise TransportError(f"verification: {detail}")


def verify_remote_result(
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    signing_key: str,
    now: int,
) -> dict[str, Any]:
    """Verify every Oscar/Felix binding before accepting a remote artifact."""

    if request.get("schema") != REQUEST_SCHEMA or result.get("schema") != RESULT_SCHEMA:
        _fail("schema")
    if not isinstance(now, int) or not isinstance(request.get("issued_at"), int) or not isinstance(request.get("expires_at"), int):
        _fail("freshness")
    if not request["issued_at"] <= now <= request["expires_at"]:
        raise TransportError("freshness: request is outside its validity window")
    if not isinstance(result.get("finished_at"), int) or not request["issued_at"] <= result["finished_at"] <= request["expires_at"]:
        raise TransportError("freshness: result is outside request validity window")

    for field in ("request_id", "nonce", "profile", "source_head", "runner_image_digest", "sandbox_policy"):
        if result.get(field) != request.get(field):
            _fail(field)
    for field in ("profile_digest", "source_root", "source_clean"):
        if field in request and result.get(field) != request.get(field):
            _fail(field)
    if result.get("signature") != sign_request(result, signing_key):
        _fail("signature")

    if request.get("signature") != sign_request(request, signing_key):
        _fail("request signature")

    artifact = result.get("artifact")
    if not isinstance(artifact, dict):
        raise TransportError("artifact: missing artifact object")
    path = artifact.get("path")
    if not isinstance(path, str) or not path.startswith(".cache/compute/") or "/../" in f"/{path}":
        raise TransportError("artifact: path must remain in current worktree cache")
    if not isinstance(artifact.get("sha256"), str) or not _SHA256.fullmatch(artifact["sha256"]):
        raise TransportError("artifact: invalid sha256")
    if not isinstance(artifact.get("bytes"), int) or artifact["bytes"] < 0:
        raise TransportError("artifact: invalid byte count")

    ack = result.get("ack")
    if not isinstance(ack, dict) or ack.get("request_id") != request["request_id"] or ack.get("nonce") != request["nonce"] or ack.get("status") != "ok":
        raise TransportError("ack: request was not acknowledged")
    return {"schema": SCHEMA, "verdict": "accepted", "reason_code": "remote-result-accepted"}

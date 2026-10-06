"""Oscar-side adapter for the fixed Felix compute launcher.

Boundary rules (the agent never sees any of this):

* Exactly one launcher executable is ever invoked, as a literal ``list[str]``
  argv with ``shell=False``.  Verbs and option names are a closed set; every
  dynamic value (CSPRNG job id, hex digest, closed profile key, typed profile
  parameter) becomes its own argv element and is never interpolated, evaluated
  or echoed into heartbeats/logs.
* The launcher owns ssh/xmachine, source transfer, remote paths, PIDs and
  cleanup.  This module only builds argv, parses one JSON object from stdout,
  and verifies what comes back.
* A Felix result is trusted only after Oscar verifies the pinned-key
  signature, nonce, request digest, source/spec/runner identity, freshness,
  log digest and replay ledger, has persisted the result atomically, and has
  returned a one-time HMAC ACK.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lib.compute_receipt import (
    AckReplayError,
    OscarAckAuthority,
    ReceiptError,
    ReceiptSigner,
)

OPS_DIR = Path(__file__).resolve().parents[1]
LAUNCHER = OPS_DIR / "felix_compute_launcher.py"
RECEIPT_SCHEMA = "kg.compute.receipt.v1"
TRANSPORT_KIND = "xmachine-ssh"
VERBS = ("probe", "submit", "fetch", "ack")
RECEIPT_MAX_AGE_SECONDS = 600.0

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# option -> value validator; the only dynamic fields a launcher call may carry
_LOCAL_PATH = re.compile(r"^/[^\x00-\x1f]+$")
_FIELDS: dict[str, re.Pattern[str]] = {
    "nonce": _HEX32,
    "request-digest": _HEX64,
    "commit": _HEX40,
    "tree-digest": _HEX64,
    "spec-digest": _HEX64,
    "receipt-digest": _HEX64,
    "ack-token": _HEX32,
    "ack-mac": _HEX64,
    "profile": _PROFILE_KEY,
    "capsule": _LOCAL_PATH,  # Oscar-local capsule root; the launcher owns the remote side
}


class TransportError(ValueError):
    """Named transport/verification refusal; ``code`` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def new_job_id() -> str:
    return secrets.token_hex(16)


def new_nonce() -> str:
    return secrets.token_hex(16)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def request_digest(
    *,
    job_id: str,
    nonce: str,
    profile: str,
    spec_digest: str,
    commit: str,
    tree_digest: str,
) -> str:
    return hashlib.sha256(
        canonical(
            {
                "commit": commit,
                "job_id": job_id,
                "nonce": nonce,
                "profile": profile,
                "spec_digest": spec_digest,
                "tree_digest": tree_digest,
            }
        )
    ).hexdigest()


def build_argv(
    verb: str,
    *,
    job_id: str,
    fields: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    launcher: Path | str = LAUNCHER,
) -> list[str]:
    """Return the literal launcher argv; every dynamic value is its own element."""

    if verb not in VERBS:
        raise TransportError("verb", verb)
    if not isinstance(job_id, str) or not _HEX32.fullmatch(job_id):
        raise TransportError("job-id")
    argv: list[str] = [str(launcher), verb, "--job-id", job_id]
    for key in sorted(fields or {}):
        pattern = _FIELDS.get(key)
        value = (fields or {})[key]
        if pattern is None:
            raise TransportError("field", key)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise TransportError("field-value", key)
        argv.extend([f"--{key}", value])
    for name in sorted(params or {}):
        value = (params or {})[name]
        if not _PARAM_NAME.fullmatch(name) or not isinstance(value, str) or not value:
            raise TransportError("param", name)
        if "\x00" in value:
            raise TransportError("param", name)
        argv.extend(["--param", name, value])
    return argv


def streamed_runner(job_id: str, cwd: Path) -> Runner:
    """Default runner: secret-safe heartbeat on stderr, stdout kept for JSON."""

    from lib.streaming_command import run_streamed_command

    def run(argv: list[str]) -> "subprocess.CompletedProcess[str]":
        return run_streamed_command(
            argv,
            cwd=cwd,
            label_key="job",
            label=job_id,
            progress_prefix="[compute][felix]",
            timeout_seconds=900.0,
        )

    return run


class XmachineTransport:
    def __init__(self, *, runner: Runner, launcher: Path | str = LAUNCHER) -> None:
        self._runner = runner
        self._launcher = Path(launcher)

    def _call(self, verb: str, job_id: str, **kwargs: Any) -> dict[str, Any]:
        if not self._launcher.is_file():
            raise TransportError("launcher-missing")
        argv = build_argv(verb, job_id=job_id, launcher=self._launcher, **kwargs)
        assert all(isinstance(item, str) for item in argv)
        try:
            completed = self._runner(argv)
        except OSError as error:
            raise TransportError("launcher-exec", type(error).__name__) from error
        if completed.returncode != 0:
            raise TransportError("launcher-exit", str(completed.returncode))
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise TransportError("launcher-output") from error
        if not isinstance(payload, dict):
            raise TransportError("launcher-output")
        return payload

    def probe(
        self, job_id: str, *, fields: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return self._call("probe", job_id, fields=fields)

    def submit(
        self, job_id: str, *, fields: dict[str, str], params: dict[str, str]
    ) -> dict[str, Any]:
        return self._call("submit", job_id, fields=fields, params=params)

    def fetch(self, job_id: str) -> dict[str, Any]:
        return self._call("fetch", job_id)

    def ack(self, job_id: str, *, fields: dict[str, str]) -> dict[str, Any]:
        return self._call("ack", job_id, fields=fields)


def verify_receipt(
    receipt: Any,
    log: Any,
    *,
    signer: ReceiptSigner,
    expected: dict[str, Any],
    caller_host_id: str,
    now: float,
    max_age: float = RECEIPT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Verify a Felix receipt against what Oscar requested; raise on any doubt."""

    try:
        body = signer.verify(receipt)
    except ReceiptError as error:
        raise TransportError("receipt-signature") from error
    if body.get("schema") != RECEIPT_SCHEMA:
        raise TransportError("receipt-schema")
    for key, code in (
        ("job_id", "receipt-job"),
        ("nonce", "receipt-nonce"),
        ("request_digest", "receipt-request-digest"),
        ("profile", "receipt-profile"),
        ("spec_digest", "receipt-spec"),
        ("runner_image_digest", "receipt-runner"),
    ):
        if body.get(key) != expected.get(key):
            raise TransportError(code)
    source = body.get("source")
    if not isinstance(source, dict) or source != {
        "commit_sha": expected["commit_sha"],
        "tree_sha256": expected["tree_sha256"],
    }:
        raise TransportError("receipt-source")
    host = body.get("host")
    if (
        not isinstance(host, dict)
        or host.get("host_role") != "felix"
        or not isinstance(host.get("host_id"), str)
        or host["host_id"] == caller_host_id
    ):
        raise TransportError("receipt-host")
    issued = body.get("issued_at")
    if (
        not isinstance(issued, (int, float))
        or isinstance(issued, bool)
        or now - issued > max_age
        or issued > now + 5
    ):
        raise TransportError("receipt-stale")
    if (
        not isinstance(log, str)
        or body.get("log_digest") != hashlib.sha256(log.encode()).hexdigest()
    ):
        raise TransportError("receipt-log-digest")
    if not isinstance(body.get("returncode"), int) or isinstance(
        body.get("returncode"), bool
    ):
        raise TransportError("receipt-schema")
    if not isinstance(body.get("artifact_digests"), dict):
        raise TransportError("receipt-schema")
    return body


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f".{path.name}.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _replay_key(body: dict[str, Any]) -> str:
    return f"{body['job_id']}:{body['nonce']}"


def _ledger_read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TransportError("replay-ledger") from error
    if not isinstance(value, dict):
        raise TransportError("replay-ledger")
    return value


def accept_receipt(
    receipt: Any,
    log: Any,
    *,
    transport: XmachineTransport,
    signer: ReceiptSigner,
    authority: OscarAckAuthority,
    expected: dict[str, Any],
    caller_host_id: str,
    cache_root: Path,
    now: float,
) -> dict[str, Any]:
    """verify -> replay check -> atomic persist -> record -> one-time ACK.

    Nothing trusted is produced unless every step succeeds in that order, and a
    result is never written for a receipt that failed verification.
    """

    body = verify_receipt(
        receipt,
        log,
        signer=signer,
        expected=expected,
        caller_host_id=caller_host_id,
        now=now,
    )
    job_id = body["job_id"]
    ledger_path = cache_root / "replay-ledger.json"
    result_path = cache_root / job_id / "result.json"
    with _locked(ledger_path):
        ledger = _ledger_read(ledger_path)
        if _replay_key(body) in ledger:
            raise TransportError("receipt-replay")
        result = {
            "schema": RECEIPT_SCHEMA,
            "job_id": job_id,
            "receipt": body,
            "receipt_digest": body["receipt_digest"],
            "signature_verified": True,
            "nonce_verified": True,
            "replay_checked": True,
            "log": log,
        }
        atomic_write_json(result_path, result)
        ledger[_replay_key(body)] = {
            "receipt_digest": body["receipt_digest"],
            "at": now,
        }
        atomic_write_json(ledger_path, ledger)
    ack = authority.issue(job_id, body["receipt_digest"])
    try:
        outcome = transport.ack(
            job_id,
            fields={
                "ack-token": ack["token"],
                "ack-mac": ack["mac"],
                "receipt-digest": ack["receipt_digest"],
            },
        )
    except TransportError as error:
        raise TransportError("ack-failed", error.code) from error
    if outcome.get("cleanup") != "acked":
        raise TransportError("ack-failed", "cleanup")
    echoed = outcome.get("ack")
    try:
        if not isinstance(echoed, dict) or not authority.verify(echoed):
            raise TransportError("ack-failed", "mac")
    except AckReplayError as error:
        raise TransportError("ack-failed", "mac") from error
    result.update(
        {
            "ack_verified": True,
            "cleanup": {"state": "acked"},
            "result_path": str(result_path),
        }
    )
    atomic_write_json(result_path, result)
    return result


__all__ = [
    "AckReplayError",
    "LAUNCHER",
    "RECEIPT_SCHEMA",
    "TRANSPORT_KIND",
    "TransportError",
    "XmachineTransport",
    "accept_receipt",
    "atomic_write_json",
    "build_argv",
    "new_job_id",
    "new_nonce",
    "request_digest",
    "streamed_runner",
    "verify_receipt",
]

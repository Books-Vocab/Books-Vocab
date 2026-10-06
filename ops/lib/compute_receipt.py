"""Ed25519 receipts and persistent, one-time Oscar ACK authority."""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import math
import os
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except (
    ModuleNotFoundError
):  # local dogfood can use the host's OpenSSL 3 Ed25519 implementation
    Ed25519PrivateKey = Any  # type: ignore[assignment,misc]
    Ed25519PublicKey = Any  # type: ignore[assignment,misc]


class ReceiptError(ValueError):
    """Receipt schema or signature is invalid."""


class AckReplayError(ValueError):
    """ACK was unknown, consumed, or malformed."""


class RemoteGateError(ReceiptError):
    """A remote gate request or receipt failed closed validation."""


class RemotePreStartError(RemoteGateError):
    """The remote route failed before a worker started; local fallback is allowed."""


REMOTE_REQUEST_SCHEMA = "kg.compute.request.v1"
REMOTE_RECEIPT_SCHEMA = "kg.compute.receipt.v1"
REMOTE_GATE_RESULT_SCHEMA = "kg.compute.gate-result.v1"
REMOTE_VALIDATION_SCHEMA = "kg.compute.remote-validation.v1"
REMOTE_HOST = "felix"
REMOTE_STATUSES = frozenset({"pass", "warn", "block", "inconclusive"})
_REMOTE_SAFE_SIDE_EFFECTS = frozenset({"repo-read", "artifact-write"})
_REMOTE_FORBIDDEN_MARKERS = (
    "xcode",
    "simulator",
    "git-metadata",
    "git_metadata",
    "production",
)
_REMOTE_REQUEST_FIELDS = frozenset(
    {
        "schema",
        "job_id",
        "nonce",
        "pinned_key_id",
        "host",
        "profile",
        "spec_digest",
        "runner_image_digest",
        "source_commit",
        "tree_sha256",
        "admission_snapshot",
        "requested_at",
        "runner_identity",
        "tool_identity",
        "request_digest",
    }
)
_REMOTE_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "job_id",
        "nonce",
        "pinned_key_id",
        "request_digest",
        "host",
        "profile",
        "spec_digest",
        "runner_image_digest",
        "source_commit",
        "tree_sha256",
        "admission_snapshot",
        "started_at",
        "finished_at",
        "duration_ms",
        "returncode",
        "status",
        "log_digest",
        "artifact_digest",
        "runner_identity",
        "tool_identity",
        "worker_state",
        "summary",
    }
)


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class ReceiptSigner:
    def __init__(self, private: Any, public: Any):
        self._private = private
        self._public = public

    @classmethod
    def generate(cls) -> ReceiptSigner:
        if hasattr(Ed25519PrivateKey, "generate"):
            private = Ed25519PrivateKey.generate()
            return cls(private, private.public_key())
        with tempfile.TemporaryDirectory(prefix="kg-ed25519-") as directory:
            key = Path(directory) / "private.pem"
            public = Path(directory) / "public.der"
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-in",
                    str(key),
                    "-pubout",
                    "-outform",
                    "DER",
                    "-out",
                    str(public),
                ],
                check=True,
                capture_output=True,
            )
            return cls(key.read_bytes(), public.read_bytes())

    @classmethod
    def from_public_bytes(cls, raw: bytes) -> ReceiptSigner:
        if hasattr(Ed25519PublicKey, "from_public_bytes"):
            return cls(None, Ed25519PublicKey.from_public_bytes(raw))
        return cls(None, bytes(raw))

    def public_bytes(self) -> bytes:
        if hasattr(self._public, "public_bytes"):
            from cryptography.hazmat.primitives import serialization

            return self._public.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        return self._public

    def sign(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._private is None:
            raise ReceiptError("private-key-required")
        unsigned = dict(payload)
        unsigned["receipt_digest"] = hashlib.sha256(_canonical(payload)).hexdigest()
        data = _canonical(unsigned)
        if hasattr(self._private, "sign"):
            signature = self._private.sign(data)
        else:
            with tempfile.TemporaryDirectory(prefix="kg-ed25519-") as directory:
                key = Path(directory) / "private.pem"
                source = Path(directory) / "payload"
                signed = Path(directory) / "signature"
                key.write_bytes(self._private)
                os.chmod(key, 0o600)
                source.write_bytes(data)
                subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-sign",
                        "-inkey",
                        str(key),
                        "-rawin",
                        "-in",
                        str(source),
                        "-out",
                        str(signed),
                    ],
                    check=True,
                    capture_output=True,
                )
                signature = signed.read_bytes()
        unsigned["signature"] = base64.b64encode(signature).decode("ascii")
        return unsigned

    def verify(self, receipt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(receipt, dict) or not isinstance(
            receipt.get("signature"), str
        ):
            raise ReceiptError("signature")
        signature = receipt["signature"]
        unsigned = dict(receipt)
        unsigned.pop("signature")
        digest = unsigned.pop("receipt_digest", None)
        if (
            not isinstance(digest, str)
            or digest != hashlib.sha256(_canonical(unsigned)).hexdigest()
        ):
            raise ReceiptError("receipt-digest")
        data = _canonical({**unsigned, "receipt_digest": digest})
        try:
            raw_signature = base64.b64decode(signature, validate=True)
            if hasattr(self._public, "verify"):
                self._public.verify(raw_signature, data)
            else:
                with tempfile.TemporaryDirectory(prefix="kg-ed25519-") as directory:
                    public = Path(directory) / "public.der"
                    source = Path(directory) / "payload"
                    signed = Path(directory) / "signature"
                    public.write_bytes(self._public)
                    source.write_bytes(data)
                    signed.write_bytes(raw_signature)
                    subprocess.run(
                        [
                            "openssl",
                            "pkeyutl",
                            "-verify",
                            "-pubin",
                            "-inkey",
                            str(public),
                            "-keyform",
                            "DER",
                            "-rawin",
                            "-in",
                            str(source),
                            "-sigfile",
                            str(signed),
                        ],
                        check=True,
                        capture_output=True,
                    )
        except Exception as exc:
            raise ReceiptError("signature") from exc
        return {**unsigned, "receipt_digest": digest}


class OscarAckAuthority:
    def __init__(self, ledger: Path | str, *, key: bytes):
        self._ledger = Path(ledger)
        self._key = bytes(key)
        if len(self._key) != 32:
            raise AckReplayError("ack-key")

    @contextlib.contextmanager
    def _locked(self):
        self._ledger.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._ledger.with_name(f".{self._ledger.name}.lock")
        with lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, str]:
        if not self._ledger.exists():
            return {}
        try:
            value = json.loads(self._ledger.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AckReplayError("ledger") from exc
        if not isinstance(value, dict):
            raise AckReplayError("ledger")
        return {str(k): str(v) for k, v in value.items()}

    def _write(self, value: dict[str, str]) -> None:
        self._ledger.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self._ledger.name}.", dir=self._ledger.parent
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._ledger)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def issue(self, job_id: str, receipt_digest: str) -> dict[str, str]:
        with self._locked():
            ledger = self._read()
            token = secrets.token_hex(16)
            message = _canonical({"job_id": job_id, "receipt_digest": receipt_digest})
            mac = hmac.new(
                self._key, message + token.encode(), hashlib.sha256
            ).hexdigest()
            ledger[token] = f"{job_id}:{receipt_digest}:{mac}"
            self._write(ledger)
            return {
                "token": token,
                "job_id": job_id,
                "receipt_digest": receipt_digest,
                "mac": mac,
            }

    def verify(self, ack: dict[str, str]) -> bool:
        with self._locked():
            ledger = self._read()
            token = ack.get("token")
            expected = ledger.get(token) if isinstance(token, str) else None
            if expected is None:
                raise AckReplayError("replay")
            job_id, digest, mac = expected.split(":", 2)
            if ack.get("job_id") != job_id or ack.get("receipt_digest") != digest:
                raise AckReplayError("digest")
            submitted_mac = ack.get("mac")
            if not isinstance(submitted_mac, str) or not hmac.compare_digest(
                submitted_mac, mac
            ):
                raise AckReplayError("invalid")
            ledger.pop(token, None)
            self._write(ledger)
            return True


def _remote_is_hex(value: Any, lengths: tuple[int, ...]) -> bool:
    return (
        isinstance(value, str)
        and len(value) in lengths
        and all(character in "0123456789abcdef" for character in value)
    )


def _remote_is_runner_image(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and _remote_is_hex(value.removeprefix("sha256:"), (64,))
    )


def _remote_is_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _remote_number(value: Any, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RemoteGateError(code)
    number = float(value)
    if not math.isfinite(number):
        raise RemoteGateError(code)
    return number


def _remote_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RemoteGateError("admission-snapshot")
    try:
        snapshot = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RemoteGateError("admission-snapshot") from exc
    if not isinstance(snapshot, dict):
        raise RemoteGateError("admission-snapshot")
    return snapshot


class RemoteJobLedger:
    """Atomic one-time admission ledger for remote compute jobs."""

    def __init__(self, root: Path | str):
        self._root = Path(root).expanduser().resolve()

    @contextlib.contextmanager
    def _locked(self):
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self._root / ".ledger.lock"
        with lock_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _new_file(path: Path, value: dict[str, Any]) -> None:
        fd = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _replace(path: Path, value: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteGateError("job-ledger") from exc
        if not isinstance(value, dict):
            raise RemoteGateError("job-ledger")
        return value

    def reserve(self, request: dict[str, Any]) -> None:
        job_id = request.get("job_id")
        nonce = request.get("nonce")
        if not _remote_is_component(job_id) or not _remote_is_hex(nonce, (64,)):
            raise RemoteGateError("job-admission")
        jobs = self._root / "jobs"
        nonces = self._root / "nonces"
        jobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        nonces.mkdir(parents=True, exist_ok=True, mode=0o700)
        job_path = jobs / f"{job_id}.json"
        nonce_path = nonces / str(nonce)
        with self._locked():
            try:
                self._new_file(
                    nonce_path,
                    {
                        "job_id": job_id,
                        "request_digest": request["request_digest"],
                    },
                )
            except FileExistsError as exc:
                raise RemoteGateError("nonce-replay") from exc
            try:
                self._new_file(
                    job_path,
                    {
                        "state": "pending",
                        "job_id": job_id,
                        "nonce": nonce,
                        "request_digest": request["request_digest"],
                    },
                )
            except FileExistsError as exc:
                try:
                    nonce_path.unlink()
                except FileNotFoundError:
                    pass
                raise RemoteGateError("job-replay") from exc
            except OSError as exc:
                try:
                    nonce_path.unlink()
                except FileNotFoundError:
                    pass
                raise RemoteGateError("job-ledger") from exc

    def consume(
        self,
        request: dict[str, Any],
        receipt_digest: str,
        consumed_at: float,
    ) -> None:
        job_id = request.get("job_id")
        if not _remote_is_component(job_id) or not _remote_is_hex(
            receipt_digest, (64,)
        ):
            raise RemoteGateError("job-consume")
        job_path = self._root / "jobs" / f"{job_id}.json"
        with self._locked():
            if not job_path.is_file():
                raise RemoteGateError("job-unknown")
            record = self._read(job_path)
            if record.get("state") != "pending":
                raise RemoteGateError("replay")
            if record.get("nonce") != request.get("nonce") or record.get(
                "request_digest"
            ) != request.get("request_digest"):
                raise RemoteGateError("job-binding")
            try:
                self._replace(
                    job_path,
                    {
                        **record,
                        "state": "consumed",
                        "receipt_digest": receipt_digest,
                        "consumed_at": consumed_at,
                    },
                )
            except OSError as exc:
                raise RemoteGateError("job-ledger") from exc


class RemoteGateAdapter:
    """Validate a Felix child result and adapt it to the existing gate result shape."""

    def __init__(
        self,
        profile_registry: dict[str, Any],
        *,
        pinned_public_key: bytes,
        job_ledger: Path | str,
        pinned_key_id: str,
        clock: Callable[[], float] = time.time,
        freshness_seconds: float = 300.0,
        future_skew_seconds: float = 5.0,
        runner_identity: str = "felix-compute-runner",
        tool_identity: str = "felix-compute-worker",
    ):
        if not isinstance(profile_registry, dict):
            raise RemoteGateError("profile-registry")
        if not isinstance(pinned_public_key, (bytes, bytearray)):
            raise RemoteGateError("pinned-key")
        if not _remote_is_component(pinned_key_id):
            raise RemoteGateError("pinned-key-id")
        if not _remote_is_component(runner_identity) or not _remote_is_component(
            tool_identity
        ):
            raise RemoteGateError("worker-identity")
        if (
            isinstance(freshness_seconds, bool)
            or not isinstance(freshness_seconds, (int, float))
            or not math.isfinite(float(freshness_seconds))
            or freshness_seconds <= 0
        ):
            raise RemoteGateError("freshness")
        if (
            isinstance(future_skew_seconds, bool)
            or not isinstance(future_skew_seconds, (int, float))
            or not math.isfinite(float(future_skew_seconds))
            or future_skew_seconds < 0
        ):
            raise RemoteGateError("clock-skew")
        try:
            verifier = ReceiptSigner.from_public_bytes(bytes(pinned_public_key))
        except (TypeError, ValueError) as exc:
            raise RemoteGateError("pinned-key") from exc
        self._profile_registry = profile_registry
        self._verifier = verifier
        self._ledger = RemoteJobLedger(job_ledger)
        self._pinned_key_id = pinned_key_id
        self._clock = clock
        self._freshness_seconds = float(freshness_seconds)
        self._future_skew_seconds = float(future_skew_seconds)
        self._runner_identity = runner_identity
        self._tool_identity = tool_identity

    def _now(self) -> float:
        try:
            return _remote_number(self._clock(), "clock")
        except RemoteGateError:
            raise
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            raise RemoteGateError("clock") from exc

    def _profile(self, profile_name: str) -> dict[str, Any] | None:
        if not isinstance(profile_name, str):
            return None
        profiles = self._profile_registry.get("profiles")
        if not isinstance(profiles, dict):
            return None
        profile = profiles.get(profile_name)
        return profile if isinstance(profile, dict) else None

    def profile_status(self, profile_name: str) -> tuple[bool, str]:
        profile = self._profile(profile_name)
        if profile is None:
            return False, "profile-missing"
        if profile.get("remote_eligible") is not True:
            return False, "remote-ineligible"
        if profile.get("git_metadata_required") is not False:
            return False, "git-metadata-required"
        if profile.get("source_kind") not in (None, "clean-committed-tree"):
            return False, "source-kind"
        for field in (
            "requires_xcode",
            "xcode_required",
            "requires_simulator",
            "simulator_required",
            "requires_git_metadata",
            "requires_production_state",
            "production_state_required",
        ):
            if profile.get(field):
                return False, field
        for field in ("required_capabilities", "runner_capabilities"):
            capabilities = profile.get(field)
            if capabilities is None:
                continue
            if not isinstance(capabilities, list) or not all(
                isinstance(item, str) and item for item in capabilities
            ):
                return False, "capability-contract"
            lowered = [item.lower() for item in capabilities]
            if any(
                marker in capability
                for capability in lowered
                for marker in _REMOTE_FORBIDDEN_MARKERS
            ):
                return False, "capability-forbidden"
        effects = profile.get("side_effects")
        if (
            not isinstance(effects, list)
            or not effects
            or not all(isinstance(item, str) for item in effects)
        ):
            return False, "side-effects"
        if not set(effects) <= _REMOTE_SAFE_SIDE_EFFECTS:
            return False, "side-effects-forbidden"
        if profile.get("network_policy") != "none":
            return False, "network-policy"
        if profile.get("bootstrap") not in (None, []):
            return False, "bootstrap"
        runner_image_digest = profile.get("runner_image_digest")
        if not _remote_is_runner_image(runner_image_digest):
            return False, "runner-image-digest"
        timeout_seconds = profile.get("timeout_seconds")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
        ):
            return False, "timeout"
        return True, "eligible"

    def is_remote_eligible(self, profile_name: str) -> bool:
        return self.profile_status(profile_name)[0]

    def prepare(
        self,
        profile_name: str,
        *,
        source_commit: str,
        tree_sha256: str,
        spec_digest: str,
        admission_snapshot: dict[str, Any],
        runner_image_digest: str | None = None,
    ) -> dict[str, Any]:
        eligible, reason = self.profile_status(profile_name)
        if not eligible:
            raise RemoteGateError(f"profile-not-remote-eligible:{reason}")
        if not _remote_is_hex(source_commit, (40, 64)):
            raise RemoteGateError("source-commit")
        if not _remote_is_hex(tree_sha256, (64,)):
            raise RemoteGateError("tree-digest")
        if not _remote_is_hex(spec_digest, (64,)):
            raise RemoteGateError("spec-digest")
        profile = self._profile(profile_name)
        assert profile is not None
        expected_runner_image = profile["runner_image_digest"]
        if (
            runner_image_digest is not None
            and runner_image_digest != expected_runner_image
        ):
            raise RemoteGateError("runner-image-binding")
        snapshot = _remote_snapshot(admission_snapshot)
        requested_at = self._now()
        body: dict[str, Any] = {
            "schema": REMOTE_REQUEST_SCHEMA,
            "job_id": f"job-{secrets.token_hex(16)}",
            "nonce": secrets.token_hex(32),
            "pinned_key_id": self._pinned_key_id,
            "host": REMOTE_HOST,
            "profile": profile_name,
            "spec_digest": spec_digest,
            "runner_image_digest": expected_runner_image,
            "source_commit": source_commit,
            "tree_sha256": tree_sha256,
            "admission_snapshot": snapshot,
            "requested_at": requested_at,
            "runner_identity": self._runner_identity,
            "tool_identity": self._tool_identity,
        }
        request = {
            **body,
            "request_digest": hashlib.sha256(_canonical(body)).hexdigest(),
        }
        self._ledger.reserve(request)
        return request

    def _validate_request(self, request: dict[str, Any]) -> None:
        if not isinstance(request, dict) or set(request) != _REMOTE_REQUEST_FIELDS:
            raise RemoteGateError("request-schema")
        if request.get("schema") != REMOTE_REQUEST_SCHEMA:
            raise RemoteGateError("request-schema")
        if not _remote_is_component(request.get("job_id")):
            raise RemoteGateError("job-id")
        if not _remote_is_hex(request.get("nonce"), (64,)):
            raise RemoteGateError("nonce")
        if request.get("pinned_key_id") != self._pinned_key_id:
            raise RemoteGateError("key-id")
        if request.get("host") != REMOTE_HOST:
            raise RemoteGateError("host")
        eligible, reason = self.profile_status(request.get("profile"))
        if not eligible:
            raise RemoteGateError(f"profile-not-remote-eligible:{reason}")
        if not _remote_is_hex(request.get("source_commit"), (40, 64)):
            raise RemoteGateError("source-commit")
        if not _remote_is_hex(request.get("tree_sha256"), (64,)):
            raise RemoteGateError("tree-digest")
        if not _remote_is_hex(request.get("spec_digest"), (64,)):
            raise RemoteGateError("spec-digest")
        if not _remote_is_runner_image(request.get("runner_image_digest")):
            raise RemoteGateError("runner-image-digest")
        if request.get("runner_identity") != self._runner_identity:
            raise RemoteGateError("runner-identity")
        if request.get("tool_identity") != self._tool_identity:
            raise RemoteGateError("tool-identity")
        _remote_snapshot(request.get("admission_snapshot"))
        _remote_number(request.get("requested_at"), "requested-at")
        body = {
            key: request[key]
            for key in _REMOTE_REQUEST_FIELDS
            if key != "request_digest"
        }
        expected_digest = hashlib.sha256(_canonical(body)).hexdigest()
        if request.get("request_digest") != expected_digest:
            raise RemoteGateError("request-digest")
        profile = self._profile(request["profile"])
        assert profile is not None
        if request["runner_image_digest"] != profile["runner_image_digest"]:
            raise RemoteGateError("runner-image-binding")

    def _verified_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        try:
            verified = self._verifier.verify(receipt)
        except ReceiptError as exc:
            raise RemoteGateError("signature") from exc
        if set(verified) != _REMOTE_RECEIPT_FIELDS | {"receipt_digest"}:
            raise RemoteGateError("receipt-schema")
        if verified.get("schema") != REMOTE_RECEIPT_SCHEMA:
            raise RemoteGateError("receipt-schema")
        return verified

    def validate(
        self,
        request: dict[str, Any],
        receipt: dict[str, Any],
        *,
        log_bytes: bytes | bytearray | None,
        artifact_bytes: bytes | bytearray | None,
        current_head: str,
        head_reader: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        self._validate_request(request)
        if current_head != request["source_commit"]:
            raise RemoteGateError("head-moved-before-record")
        verified = self._verified_receipt(receipt)
        for field in (
            "job_id",
            "nonce",
            "pinned_key_id",
            "host",
            "profile",
            "spec_digest",
            "runner_image_digest",
            "source_commit",
            "tree_sha256",
            "admission_snapshot",
            "runner_identity",
            "tool_identity",
            "request_digest",
        ):
            if verified.get(field) != request.get(field):
                raise RemoteGateError(f"binding:{field}")
        if verified.get("pinned_key_id") != self._pinned_key_id:
            raise RemoteGateError("key-id")
        if verified.get("host") != REMOTE_HOST:
            raise RemoteGateError("host")
        if verified.get("worker_state") != "completed":
            raise RemoteGateError("worker-state")
        status = verified.get("status")
        if status not in REMOTE_STATUSES:
            raise RemoteGateError("status")
        returncode = verified.get("returncode")
        if (
            isinstance(returncode, bool)
            or not isinstance(returncode, int)
            or not -255 <= returncode <= 255
        ):
            raise RemoteGateError("returncode")
        if (returncode == 0 and status == "block") or (
            returncode != 0 and status == "pass"
        ):
            raise RemoteGateError("status-returncode")
        summary = verified.get("summary")
        if not isinstance(summary, str) or len(summary) > 4096:
            raise RemoteGateError("summary")
        started_at = _remote_number(verified.get("started_at"), "started-at")
        finished_at = _remote_number(verified.get("finished_at"), "finished-at")
        requested_at = float(request["requested_at"])
        if started_at < requested_at or finished_at < started_at:
            raise RemoteGateError("timestamp-order")
        now = self._now()
        if finished_at > now + self._future_skew_seconds:
            raise RemoteGateError("timestamp-future")
        if now - finished_at > self._freshness_seconds:
            raise RemoteGateError("stale")
        duration_ms = _remote_number(verified.get("duration_ms"), "duration")
        if duration_ms < 0:
            raise RemoteGateError("duration")
        profile = self._profile(request["profile"])
        assert profile is not None
        timeout_seconds = profile.get("timeout_seconds")
        if timeout_seconds is not None and duration_ms > timeout_seconds * 1000:
            raise RemoteGateError("duration")
        if abs(duration_ms - (finished_at - started_at) * 1000) > 1000:
            raise RemoteGateError("duration")
        if not isinstance(log_bytes, (bytes, bytearray)):
            raise RemoteGateError("log-unattributable")
        if not isinstance(artifact_bytes, (bytes, bytearray)):
            raise RemoteGateError("artifact-unattributable")
        if verified.get("log_digest") != hashlib.sha256(bytes(log_bytes)).hexdigest():
            raise RemoteGateError("log-digest")
        if (
            verified.get("artifact_digest")
            != hashlib.sha256(bytes(artifact_bytes)).hexdigest()
        ):
            raise RemoteGateError("artifact-digest")
        if head_reader is not None:
            if not callable(head_reader):
                raise RemoteGateError("head-reader")
            try:
                latest_head = head_reader()
            except Exception as exc:
                raise RemoteGateError("head-read") from exc
            if latest_head != request["source_commit"]:
                raise RemoteGateError("head-moved-before-record")
        self._ledger.consume(request, verified["receipt_digest"], now)
        return {
            "status": status,
            "rc": returncode,
            "duration_ms": duration_ms,
            "summary": summary,
            "output_tail": bytes(log_bytes).decode("utf-8", errors="replace")[-12000:],
            "receipt_digest": verified["receipt_digest"],
        }

    @staticmethod
    def _rejected_result(
        *,
        name: str,
        level: str,
        cwd: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "schema": REMOTE_GATE_RESULT_SCHEMA,
            "name": name,
            "kind": "remote",
            "cwd": cwd,
            "level": "block",
            "status": "block",
            "rc": 125,
            "duration_s": 0.0,
            "output_tail": f"remote gate rejected: {reason}",
            "executed": False,
            "remote_validation": {
                "schema": REMOTE_VALIDATION_SCHEMA,
                "status": "rejected",
                "verdict": "not-executed",
                "reason": reason,
            },
        }

    def adapt(
        self,
        request: dict[str, Any],
        receipt: dict[str, Any],
        *,
        name: str,
        level: str,
        cwd: str,
        log_bytes: bytes | bytearray | None,
        artifact_bytes: bytes | bytearray | None,
        current_head: str,
        head_reader: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        try:
            validated = self.validate(
                request,
                receipt,
                log_bytes=log_bytes,
                artifact_bytes=artifact_bytes,
                current_head=current_head,
                head_reader=head_reader,
            )
        except RemoteGateError as exc:
            return self._rejected_result(
                name=name,
                level=level,
                cwd=cwd,
                reason=str(exc),
            )
        return {
            "schema": REMOTE_GATE_RESULT_SCHEMA,
            "name": name,
            "kind": "remote",
            "cwd": cwd,
            "level": "block" if validated["status"] == "block" else level,
            "status": validated["status"],
            "rc": validated["rc"],
            "duration_s": round(validated["duration_ms"] / 1000, 3),
            "output_tail": validated["output_tail"],
            "summary": validated["summary"],
            "executed": True,
            "remote_validation": {
                "schema": REMOTE_VALIDATION_SCHEMA,
                "status": "validated",
                "host": REMOTE_HOST,
                "request_digest": request["request_digest"],
                "receipt_digest": validated["receipt_digest"],
            },
        }

    @staticmethod
    def _local_route(
        local_check: Callable[[], dict[str, Any]],
        *,
        profile_name: str,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        try:
            result = local_check()
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            return RemoteGateAdapter._rejected_result(
                name=profile_name,
                level="block",
                cwd=".",
                reason=f"local-fallback-failed:{type(exc).__name__}",
            )
        if not isinstance(result, dict):
            return RemoteGateAdapter._rejected_result(
                name=profile_name,
                level="block",
                cwd=".",
                reason="local-result-schema",
            )
        routed = dict(result)
        routed["remote_validation"] = {
            "schema": REMOTE_VALIDATION_SCHEMA,
            "status": status,
            "profile": profile_name,
            "reason": reason,
        }
        return routed

    def run(
        self,
        profile_name: str,
        *,
        source_commit: str,
        tree_sha256: str,
        spec_digest: str,
        admission_snapshot: dict[str, Any],
        local_check: Callable[[], dict[str, Any]],
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None,
        current_head: str,
        head_reader: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        eligible, reason = self.profile_status(profile_name)
        if not eligible:
            return self._local_route(
                local_check,
                profile_name=profile_name,
                status="local",
                reason=reason,
            )
        try:
            request = self.prepare(
                profile_name,
                source_commit=source_commit,
                tree_sha256=tree_sha256,
                spec_digest=spec_digest,
                admission_snapshot=admission_snapshot,
            )
        except RemoteGateError as exc:
            return self._rejected_result(
                name=profile_name,
                level="block",
                cwd=".",
                reason=f"admission:{exc}",
            )
        if not callable(transport):
            return self._local_route(
                local_check,
                profile_name=profile_name,
                status="fallback-local",
                reason="transport-unavailable",
            )
        try:
            envelope = transport(_remote_snapshot(request))
        except RemotePreStartError as exc:
            return self._local_route(
                local_check,
                profile_name=profile_name,
                status="fallback-local",
                reason=str(exc),
            )
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            subprocess.SubprocessError,
        ) as exc:
            return self._rejected_result(
                name=profile_name,
                level="block",
                cwd=".",
                reason=f"remote-transport-failed:{type(exc).__name__}",
            )
        if not isinstance(envelope, dict) or set(envelope) != {
            "receipt",
            "log",
            "artifact",
        }:
            return self._rejected_result(
                name=profile_name,
                level="block",
                cwd=".",
                reason="remote-envelope",
            )
        return self.adapt(
            request,
            envelope["receipt"],
            name=profile_name,
            level="block",
            cwd=".",
            log_bytes=envelope["log"],
            artifact_bytes=envelope["artifact"],
            current_head=current_head,
            head_reader=head_reader,
        )

    def route(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Compatibility spelling for callers describing this operation as routing."""
        return self.run(*args, **kwargs)

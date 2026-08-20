"""Ed25519 receipts and persistent, one-time Oscar ACK authority."""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ModuleNotFoundError:  # local dogfood can use the host's OpenSSL 3 Ed25519 implementation
    Ed25519PrivateKey = Any  # type: ignore[assignment,misc]
    Ed25519PublicKey = Any  # type: ignore[assignment,misc]


class ReceiptError(ValueError):
    """Receipt schema or signature is invalid."""


class AckReplayError(ValueError):
    """ACK was unknown, consumed, or malformed."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
            subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)], check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER", "-out", str(public)], check=True, capture_output=True)
            return cls(key.read_bytes(), public.read_bytes())

    @classmethod
    def from_public_bytes(cls, raw: bytes) -> ReceiptSigner:
        if hasattr(Ed25519PublicKey, "from_public_bytes"):
            return cls(None, Ed25519PublicKey.from_public_bytes(raw))
        return cls(None, bytes(raw))

    def public_bytes(self) -> bytes:
        if hasattr(self._public, "public_bytes"):
            from cryptography.hazmat.primitives import serialization

            return self._public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
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
                subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(source), "-out", str(signed)], check=True, capture_output=True)
                signature = signed.read_bytes()
        unsigned["signature"] = base64.b64encode(signature).decode("ascii")
        return unsigned

    def verify(self, receipt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("signature"), str):
            raise ReceiptError("signature")
        signature = receipt["signature"]
        unsigned = dict(receipt)
        unsigned.pop("signature")
        digest = unsigned.pop("receipt_digest", None)
        if not isinstance(digest, str) or digest != hashlib.sha256(_canonical(unsigned)).hexdigest():
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
                    subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public), "-keyform", "DER", "-rawin", "-in", str(source), "-sigfile", str(signed)], check=True, capture_output=True)
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
        fd, temporary = tempfile.mkstemp(prefix=f".{self._ledger.name}.", dir=self._ledger.parent)
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
            mac = hmac.new(self._key, message + token.encode(), hashlib.sha256).hexdigest()
            ledger[token] = f"{job_id}:{receipt_digest}:{mac}"
            self._write(ledger)
            return {"token": token, "job_id": job_id, "receipt_digest": receipt_digest, "mac": mac}

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
            if not isinstance(submitted_mac, str) or not hmac.compare_digest(submitted_mac, mac):
                raise AckReplayError("invalid")
            ledger.pop(token, None)
            self._write(ledger)
            return True

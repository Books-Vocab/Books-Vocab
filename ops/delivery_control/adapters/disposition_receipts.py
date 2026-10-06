"""Locked append-only NDJSON journal for explicit disposition receipts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from ..domain.errors import DeliverySourceError


def _canonical(body: Mapping[str, object]) -> str:
    return json.dumps(
        body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
    )


class DispositionReceiptNdjsonAdapter:
    """Each row carries a SHA-256 over its own body; rows are never rewritten."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    @staticmethod
    def _assert_wellformed(lines: list[str]) -> None:
        for number, raw in enumerate(lines, start=1):
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as error:
                raise DeliverySourceError(
                    f"disposition journal malformed at line {number}"
                ) from error
            if not isinstance(row, dict) or type(row.get("digest")) is not str:
                raise DeliverySourceError(
                    f"disposition journal malformed at line {number}"
                )
            body = {key: value for key, value in row.items() if key != "digest"}
            digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
            if digest != row["digest"]:
                raise DeliverySourceError(
                    f"disposition journal malformed at line {number}: digest mismatch"
                )

    def append(self, receipt: Mapping[str, object]) -> None:
        if "digest" in receipt:
            raise DeliverySourceError("disposition receipt must not carry a digest")
        body = dict(receipt)
        row = {
            **body,
            "digest": hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.seek(0)
                self._assert_wellformed(stream.read().splitlines())
                stream.seek(0, os.SEEK_END)
                stream.write(_canonical(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

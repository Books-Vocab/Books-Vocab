"""Atomic persistence for one external runtime liveness receipt."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, PolicyViolation
from ..domain.runtime_models import RuntimeReceipt

_UNSET = object()


class RuntimeReceiptFile:
    """Persist a single receipt without becoming a delivery-state database.

    The file is deliberately one receipt per runtime.  Atomic replacement and
    monotonic timestamps make an interrupted tick observable without allowing
    an older process to overwrite newer liveness evidence.
    """

    def __init__(self, path: Path) -> None:
        if path == Path("-"):
            raise PolicyViolation("runtime receipt path must be a real file")
        self.path = path.expanduser().resolve()

    def read(self) -> RuntimeReceipt | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return RuntimeReceipt.from_payload(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise PolicyViolation(
                f"runtime receipt is unreadable: {self.path}"
            ) from error

    def write(
        self,
        receipt: RuntimeReceipt,
        *,
        expected_cycle_id: str | None = None,
        expected_last_action_id: str | None | object = _UNSET,
    ) -> RuntimeReceipt:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                current = self.read()
                if current is not None and current.thread_id != receipt.thread_id:
                    raise CompareAndSwapConflict(
                        "runtime receipt thread changed before write"
                    )
                if expected_cycle_id is not None:
                    actual = current.cycle_id if current is not None else None
                    if actual != expected_cycle_id:
                        raise CompareAndSwapConflict(
                            "runtime receipt cycle changed before write"
                        )
                if expected_last_action_id is not _UNSET:
                    actual = current.last_action_id if current is not None else None
                    if actual != expected_last_action_id:
                        raise CompareAndSwapConflict(
                            "runtime receipt wake action changed before write"
                        )
                if current is not None:
                    if receipt.observed_at < current.observed_at:
                        raise CompareAndSwapConflict(
                            "runtime receipt observed_at moved backwards"
                        )
                    if receipt.last_progress_at < current.last_progress_at:
                        raise CompareAndSwapConflict(
                            "runtime receipt last_progress_at moved backwards"
                        )

                encoded = (
                    json.dumps(receipt.to_payload(), ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
                temporary: str | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=self.path.parent,
                        prefix=f".{self.path.name}.",
                        delete=False,
                    ) as handle:
                        temporary = handle.name
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.path)
                    temporary = None
                    try:
                        directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    except OSError:
                        directory_fd = None
                    if directory_fd is not None:
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                finally:
                    if temporary is not None:
                        try:
                            os.unlink(temporary)
                        except FileNotFoundError:
                            pass
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return receipt


__all__ = ["RuntimeReceiptFile"]

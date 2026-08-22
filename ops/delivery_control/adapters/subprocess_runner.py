from __future__ import annotations

import math
import subprocess
from pathlib import Path

from ..ports.process import CommandResult


class SubprocessCommandRunner:
    """Run one argv-only command with a bounded, structured failure.

    Delivery observations and mutations must never wait forever on a broken
    GitHub CLI, Git transport, or registry child process.  A timeout is
    returned as a non-zero result so existing adapters fail closed, while the
    explicit ``timed_out`` bit lets callers distinguish infrastructure timeout
    from an ordinary command failure.
    """

    DEFAULT_TIMEOUT_SECONDS = 120.0

    def __init__(self, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("command timeout must be finite and positive")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            stderr = self._text(error.stderr)
            detail = f"command timed out after {self.timeout_seconds:g}s"
            if stderr:
                stderr = f"{stderr.rstrip()}\n{detail}"
            else:
                stderr = detail
            return CommandResult(
                argv=argv,
                exit_code=124,
                stdout=self._text(error.stdout),
                stderr=stderr,
                timed_out=True,
            )
        return CommandResult(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

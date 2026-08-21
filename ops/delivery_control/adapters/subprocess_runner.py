from __future__ import annotations

import subprocess
from pathlib import Path

from delivery_control.ports.process import CommandResult


class SubprocessCommandRunner:
    """Small argv-only process adapter; shell interpolation is intentionally absent."""

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

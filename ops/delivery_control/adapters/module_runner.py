"""Synchronous adapter for a co-versioned Python command module."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from ..ports.process import CommandResult


class ModuleCommandRunner:
    """Run a loaded command module after its source checkout is released."""

    def __init__(
        self,
        *,
        executable: Path,
        main: Callable[[list[str] | None], int],
    ) -> None:
        self.executable = executable.resolve()
        self.main = main
        self._lock = Lock()

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> CommandResult:
        del cwd
        if not argv or Path(argv[0]).resolve() != self.executable:
            return CommandResult(argv, 64, "", "module executable does not match")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            self._lock,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                exit_code = int(self.main(list(argv[1:])))
            except SystemExit as error:
                exit_code = int(error.code or 0)
            except Exception as error:  # noqa: BLE001 - command process boundary
                exit_code = 1
                print(f"{type(error).__name__}: {error}", file=stderr)
        return CommandResult(argv, exit_code, stdout.getvalue(), stderr.getvalue())

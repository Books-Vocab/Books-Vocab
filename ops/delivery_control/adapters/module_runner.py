"""Synchronous adapter for a co-versioned Python command module."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from ..ports.process import CommandResult
from .source_provenance import inspect_checkout, source_compatibility_problem

PROVENANCE_EXIT_CODE = 78


class ModuleCommandRunner:
    """Run a loaded command module after optional source/target validation."""

    def __init__(
        self,
        *,
        executable: Path,
        main: Callable[[list[str] | None], int],
        source_root: Path | None = None,
        target_repo: Path | None = None,
    ) -> None:
        self.executable = executable.resolve()
        self.main = main
        if (source_root is None) != (target_repo is None):
            raise ValueError("source_root and target_repo must be provided together")
        self.source_root = source_root.resolve() if source_root is not None else None
        self.target_repo = target_repo.resolve() if target_repo is not None else None
        self._validated_source_fingerprint: str | None = None
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
        if self.source_root is not None and self.target_repo is not None:
            problem = source_compatibility_problem(
                source_root=self.source_root,
                target_repo=self.target_repo,
                expected_source_fingerprint=self._validated_source_fingerprint,
            )
            if problem is not None:
                return CommandResult(argv, PROVENANCE_EXIT_CODE, "", problem)
            if self.source_root.exists():
                self._validated_source_fingerprint = inspect_checkout(
                    self.source_root
                ).control_plane_fingerprint
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


__all__ = ["ModuleCommandRunner", "PROVENANCE_EXIT_CODE"]

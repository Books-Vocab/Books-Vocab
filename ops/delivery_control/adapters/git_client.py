"""Low-level argv-only Git execution shared by adapter components."""

from __future__ import annotations

from pathlib import Path

from ..ports.process import CommandResult, CommandRunnerPort
from .errors import AdapterCommandError


class GitCliClient:
    def __init__(self, *, repo: Path, runner: CommandRunnerPort) -> None:
        self.repo = repo
        self.runner = runner

    def execute(self, *args: str, cwd: Path | None = None) -> CommandResult:
        target = (cwd or self.repo).resolve()
        argv = ("git", "-C", str(target), *args)
        return self.runner.run(argv)

    def execute_with_timeout(
        self,
        *args: str,
        timeout_seconds: float,
        cwd: Path | None = None,
    ) -> CommandResult:
        target = (cwd or self.repo).resolve()
        argv = ("git", "-C", str(target), *args)
        bounded_runner = getattr(self.runner, "run_with_timeout", None)
        if callable(bounded_runner):
            return bounded_runner(
                argv,
                cwd=target,
                timeout_seconds=timeout_seconds,
            )
        return self.runner.run(argv, cwd=target)

    def run(self, *args: str, cwd: Path | None = None) -> str:
        result = self.execute(*args, cwd=cwd)
        if result.exit_code != 0:
            raise AdapterCommandError(result)
        return result.stdout.strip()

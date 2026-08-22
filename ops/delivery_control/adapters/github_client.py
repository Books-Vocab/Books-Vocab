"""Low-level argv-only GitHub CLI execution shared by adapter components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError


class GitHubCliClient:
    def __init__(self, *, repo: Path, runner: CommandRunnerPort) -> None:
        self.repo = repo
        self.runner = runner

    def run(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> str:
        result = self.runner.run(argv, cwd=self.repo)
        if result.exit_code != 0 and (not allow_nonzero or not result.stdout.strip()):
            raise AdapterCommandError(result)
        return result.stdout.strip()

    def load_json(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> Any:
        output = self.run(argv, allow_nonzero=allow_nonzero)
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError(f"invalid JSON from {' '.join(argv)}") from error

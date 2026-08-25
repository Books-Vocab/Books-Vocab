"""Low-level argv-only GitHub CLI execution shared by adapter components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..ports.process import CommandResult, CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError

_READ_ONLY_JSON_COMMANDS = frozenset(
    {
        ("repo", "view"),
        ("issue", "list"),
        ("pr", "list"),
        ("pr", "view"),
        ("label", "list"),
    }
)
_TRANSIENT_ERROR_MARKERS = (
    "tls handshake timeout",
    "connection reset",
    "connection refused",
    "temporary network failure",
    "temporary failure in name resolution",
    "network is unreachable",
)


def _option_value(argv: tuple[str, ...], *options: str) -> str | None:
    for index, value in enumerate(argv[:-1]):
        if value in options:
            return argv[index + 1]
    return None


def _is_read_only_json_query(argv: tuple[str, ...]) -> bool:
    if (
        len(argv) >= 3
        and argv[0] == "gh"
        and (argv[1], argv[2]) in _READ_ONLY_JSON_COMMANDS
    ):
        return True
    if len(argv) < 2 or argv[0] != "gh" or argv[1] != "api":
        return False
    method = _option_value(argv, "--method", "-X")
    if len(argv) >= 3 and argv[2] == "graphql":
        query = next(
            (value.partition("=")[2] for value in argv if value.startswith("query=")),
            None,
        )
        if query is None:
            return False
        operation = query.lstrip()
        return operation.startswith(("query ", "query{", "{"))
    return method is None or method.upper() == "GET"


def _is_transient_failure(result: CommandResult) -> bool:
    if result.timed_out:
        return True
    detail = f"{result.stdout}\n{result.stderr}".casefold()
    return any(marker in detail for marker in _TRANSIENT_ERROR_MARKERS)


class GitHubCliClient:
    def __init__(self, *, repo: Path, runner: CommandRunnerPort) -> None:
        self.repo = repo
        self.runner = runner

    def _run_result(
        self,
        argv: tuple[str, ...],
        *,
        allow_nonzero: bool = False,
        retry_read_only: bool = False,
    ) -> CommandResult:
        result = self.runner.run(argv, cwd=self.repo)
        if (
            retry_read_only
            and _is_read_only_json_query(argv)
            and _is_transient_failure(result)
        ):
            result = self.runner.run(argv, cwd=self.repo)
        if result.exit_code != 0 and (not allow_nonzero or not result.stdout.strip()):
            raise AdapterCommandError(result)
        return result

    def run(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> str:
        return self._run_result(argv, allow_nonzero=allow_nonzero).stdout.strip()

    def load_json(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> Any:
        output = self._run_result(
            argv,
            allow_nonzero=allow_nonzero,
            retry_read_only=True,
        ).stdout.strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError(f"invalid JSON from {' '.join(argv)}") from error

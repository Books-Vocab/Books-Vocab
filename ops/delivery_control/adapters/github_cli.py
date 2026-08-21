from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from delivery_control.domain.models import PullRequestSnapshot
from delivery_control.domain.states import CheckStatus
from delivery_control.ports.process import CommandRunnerPort

from .errors import AdapterCommandError, AdapterPayloadError
from .subprocess_runner import SubprocessCommandRunner

_PR_FIELDS = "number,url,headRefName,baseRefOid,headRefOid,state,isDraft,mergeable"


class GitHubCliAdapter:
    def __init__(self, *, runner: CommandRunnerPort | None = None) -> None:
        self.runner = runner or SubprocessCommandRunner()

    def _json(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> Any:
        result = self.runner.run(argv)
        if result.exit_code != 0 and not (allow_nonzero and result.stdout.strip()):
            raise AdapterCommandError(result)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError(f"invalid JSON from {' '.join(argv)}") from error

    @staticmethod
    def _pull_request(payload: Mapping[str, Any]) -> PullRequestSnapshot:
        try:
            return PullRequestSnapshot(
                number=int(payload["number"]),
                url=str(payload["url"]),
                branch=str(payload["headRefName"]),
                base_sha=str(payload["baseRefOid"]),
                head_sha=str(payload["headRefOid"]),
                state=str(payload["state"]),
                draft=bool(payload["isDraft"]),
                mergeable=str(payload["mergeable"]).upper() == "MERGEABLE",
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AdapterPayloadError("GitHub PR payload is malformed") from error

    def list_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        payload = self._json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                _PR_FIELDS,
            )
        )
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub PR list must be a JSON list")
        return tuple(
            self._pull_request(item) for item in payload if isinstance(item, Mapping)
        )

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        matches = [
            item for item in self.list_open_pull_requests() if item.branch == branch
        ]
        if len(matches) > 1:
            raise AdapterPayloadError(f"multiple open PRs found for {branch}")
        return matches[0] if matches else None

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        payload = self._json(("gh", "pr", "view", str(number), "--json", _PR_FIELDS))
        if not isinstance(payload, Mapping):
            raise AdapterPayloadError("GitHub PR view must be a JSON object")
        return self._pull_request(payload)

    def required_check_status(self, number: int) -> CheckStatus:
        payload = self._json(
            (
                "gh",
                "pr",
                "checks",
                str(number),
                "--required",
                "--json",
                "name,state",
            ),
            allow_nonzero=True,
        )
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub required checks must be a JSON list")
        states = {
            str(item.get("state", "")).upper()
            for item in payload
            if isinstance(item, Mapping)
        }
        if not states:
            return CheckStatus.ABSENT
        if states & {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
            return CheckStatus.FAILURE
        if states <= {"SUCCESS", "SKIPPED", "NEUTRAL"}:
            return CheckStatus.SUCCESS
        return CheckStatus.PENDING

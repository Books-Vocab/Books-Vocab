from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..domain.errors import CompareAndSwapConflict
from ..domain.models import CheckStatus
from ..domain.observations import (
    CheckSnapshot,
    InventoryProblem,
    PullRequestInventory,
    PullRequestSnapshot,
)
from ..ports.process import CommandRunnerPort
from .errors import AdapterCommandError, AdapterPayloadError
from .github_queue import GitHubQueueGraphQLAdapter
from .subprocess_runner import SubprocessCommandRunner

_PR_FIELDS = (
    "id,number,url,headRefName,baseRefName,baseRefOid,headRefOid,state,isDraft,mergeable,title,body,"
    "autoMergeRequest"
)


class GitHubCliAdapter:
    def __init__(
        self,
        *,
        repo: Path | None = None,
        runner: CommandRunnerPort | None = None,
    ) -> None:
        self.repo = (repo or Path.cwd()).resolve()
        self.runner = runner or SubprocessCommandRunner()
        self.queue = GitHubQueueGraphQLAdapter(repo=self.repo, runner=self.runner)

    def _run(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> str:
        result = self.runner.run(argv, cwd=self.repo)
        if result.exit_code != 0 and (not allow_nonzero or not result.stdout.strip()):
            raise AdapterCommandError(result)
        return result.stdout.strip()

    def _json(self, argv: tuple[str, ...], *, allow_nonzero: bool = False) -> Any:
        output = self._run(argv, allow_nonzero=allow_nonzero)
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise AdapterPayloadError(f"invalid JSON from {' '.join(argv)}") from error

    @staticmethod
    def _pull_request(payload: Mapping[str, Any]) -> PullRequestSnapshot:
        required = {
            "id": str,
            "number": int,
            "url": str,
            "headRefName": str,
            "baseRefName": str,
            "baseRefOid": str,
            "headRefOid": str,
            "state": str,
            "isDraft": bool,
            "mergeable": str,
            "title": str,
            "body": str,
        }
        if any(
            type(payload.get(key)) is not expected for key, expected in required.items()
        ):
            raise AdapterPayloadError("GitHub PR payload is malformed")
        auto_merge_request = payload.get("autoMergeRequest")
        if auto_merge_request is not None and not isinstance(
            auto_merge_request, Mapping
        ):
            raise AdapterPayloadError("GitHub auto-merge payload is malformed")
        return PullRequestSnapshot(
            number=payload["number"],
            url=payload["url"],
            branch=payload["headRefName"],
            base_branch=payload["baseRefName"],
            base_sha=payload["baseRefOid"],
            head_sha=payload["headRefOid"],
            state=payload["state"],
            draft=payload["isDraft"],
            mergeable=payload["mergeable"].upper() == "MERGEABLE",
            title=payload["title"],
            body=payload["body"],
            auto_merge_enabled=auto_merge_request is not None,
            node_id=payload["id"],
        )

    @classmethod
    def _pull_request_inventory(cls, payload: object) -> PullRequestInventory:
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub PR list must be a JSON list")
        records: list[PullRequestSnapshot] = []
        problems: list[InventoryProblem] = []
        for index, item in enumerate(payload):
            identity = f"entry[{index}]"
            if isinstance(item, Mapping):
                identity = f"PR#{item.get('number', index)}"
                try:
                    records.append(cls._pull_request(item))
                    continue
                except AdapterPayloadError as error:
                    reason = str(error)
            else:
                reason = "PR entry is not an object"
            problems.append(InventoryProblem("github", identity, reason))
        return PullRequestInventory(records=tuple(records), problems=tuple(problems))

    def list_open_pull_requests(self) -> PullRequestInventory:
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
        return self._pull_request_inventory(payload)

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        payload = self._json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--head",
                branch,
                "--limit",
                "100",
                "--json",
                _PR_FIELDS,
            )
        )
        return self._pull_request_inventory(payload)

    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("merge history limit must be between 1 and 100")
        payload = self._json(
            (
                "gh",
                "pr",
                "list",
                "--state",
                "merged",
                "--limit",
                str(limit),
                "--json",
                "mergedAt",
            )
        )
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub merge history must be a JSON list")
        observed: list[datetime] = []
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping) or type(item.get("mergedAt")) is not str:
                raise AdapterPayloadError(f"GitHub merge history[{index}] is malformed")
            try:
                timestamp = datetime.fromisoformat(
                    item["mergedAt"].replace("Z", "+00:00")
                )
            except ValueError as error:
                raise AdapterPayloadError(
                    f"GitHub merge history[{index}] has an invalid timestamp"
                ) from error
            if timestamp.utcoffset() is None:
                raise AdapterPayloadError(
                    f"GitHub merge history[{index}] timestamp is not aware"
                )
            observed.append(timestamp)
        return tuple(sorted(observed))

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        inventory = self.list_open_pull_requests()
        if inventory.problems:
            raise AdapterPayloadError("GitHub PR inventory contains malformed entries")
        matches = [item for item in inventory.records if item.branch == branch]
        if len(matches) > 1:
            raise AdapterPayloadError(f"multiple open PRs found for {branch}")
        return matches[0] if matches else None

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        payload = self._json(("gh", "pr", "view", str(number), "--json", _PR_FIELDS))
        if not isinstance(payload, Mapping):
            raise AdapterPayloadError("GitHub PR view must be a JSON object")
        return self._pull_request(payload)

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        before = self.get_pull_request(number)
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
        names: list[str] = []
        states: set[str] = set()
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise AdapterPayloadError(f"required check[{index}] is not an object")
            name = item.get("name")
            state = item.get("state")
            if type(name) is not str or type(state) is not str:
                raise AdapterPayloadError(f"required check[{index}] is malformed")
            names.append(name)
            states.add(state.upper())
        after = self.get_pull_request(number)
        if before.head_sha != after.head_sha:
            raise CompareAndSwapConflict(
                "PR HEAD changed while reading required checks"
            )
        if not states:
            status = CheckStatus.ABSENT
        elif states & {
            "FAILURE",
            "ERROR",
            "CANCELLED",
            "TIMED_OUT",
            "ACTION_REQUIRED",
        }:
            status = CheckStatus.FAILURE
        elif states <= {"SUCCESS", "SKIPPED", "NEUTRAL"}:
            status = CheckStatus.SUCCESS
        else:
            status = CheckStatus.PENDING
        return CheckSnapshot(
            status=status,
            head_sha=after.head_sha,
            observed_at=datetime.now(tz=UTC),
            names=tuple(sorted(names)),
        )

    def changed_paths(self, number: int) -> tuple[str, ...]:
        payload = self._json(("gh", "pr", "view", str(number), "--json", "files"))
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("files"), list
        ):
            raise AdapterPayloadError("GitHub PR files payload is malformed")
        paths: list[str] = []
        for index, item in enumerate(payload["files"]):
            if not isinstance(item, Mapping) or type(item.get("path")) is not str:
                raise AdapterPayloadError(f"GitHub PR file[{index}] is malformed")
            paths.append(item["path"])
        return tuple(sorted(paths))

    def _repo_name(self) -> str:
        payload = self._json(("gh", "repo", "view", "--json", "nameWithOwner"))
        if (
            not isinstance(payload, Mapping)
            or type(payload.get("nameWithOwner")) is not str
        ):
            raise AdapterPayloadError("GitHub repository payload is malformed")
        return payload["nameWithOwner"]

    def branch_is_protected(self, branch: str) -> bool:
        output = self._run(
            (
                "gh",
                "api",
                f"repos/{self._repo_name()}/branches/{quote(branch, safe='')}",
                "--jq",
                ".protected",
            )
        )
        if output not in {"true", "false"}:
            raise AdapterPayloadError("GitHub branch protection payload is malformed")
        return output == "true"

    def merge_queue_enabled(self, branch: str) -> bool:
        payload = self._json(
            (
                "gh",
                "api",
                f"repos/{self._repo_name()}/rules/branches/{quote(branch, safe='')}",
            )
        )
        if not isinstance(payload, list):
            raise AdapterPayloadError("GitHub branch rules payload is malformed")
        for index, rule in enumerate(payload):
            if not isinstance(rule, Mapping) or type(rule.get("type")) is not str:
                raise AdapterPayloadError(f"GitHub branch rule[{index}] is malformed")
            if rule["type"] == "merge_queue":
                return True
        return False

    def merge_queue_entry_id(self, pull_request_id: str) -> str | None:
        return self.queue.snapshot(pull_request_id).entry_id

    def create_pull_request(
        self, *, branch: str, title: str, body: str
    ) -> PullRequestSnapshot:
        self._run(
            (
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            )
        )
        created = self.find_open_pull_request(branch)
        if created is None:
            raise CompareAndSwapConflict("created PR did not read back by branch")
        return created

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        before = self.get_pull_request(number)
        if before.head_sha != expected_head_sha:
            raise CompareAndSwapConflict("PR HEAD changed before metadata update")
        self._run(("gh", "pr", "edit", str(number), "--title", title, "--body", body))
        after = self.get_pull_request(number)
        if after.head_sha != expected_head_sha:
            raise CompareAndSwapConflict("PR HEAD changed during metadata update")
        return after

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        before = self.get_pull_request(number)
        self._run(("gh", "pr", "ready", str(number)))
        after = self.get_pull_request(number)
        if after.head_sha != before.head_sha:
            raise CompareAndSwapConflict("PR HEAD changed while marking ready")
        return after

    def enqueue(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> None:
        before = self.get_pull_request(number)
        if (
            before.base_branch != "main"
            or before.base_sha != expected_base_sha
            or before.head_sha != expected_head_sha
            or before.body != expected_body
        ):
            raise CompareAndSwapConflict("PR tuple changed before enqueue")
        if not self.merge_queue_enabled("main"):
            raise CompareAndSwapConflict("main has no native merge queue rule")
        self.queue.enqueue(
            pull_request_id=before.node_id,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_body=expected_body,
        )

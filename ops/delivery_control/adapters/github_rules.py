"""GitHub repository identity, branch protection, and merge-queue rules."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import quote

from .errors import AdapterPayloadError
from .github_client import GitHubCliClient


def read_repository_name(client: GitHubCliClient) -> str:
    payload = client.load_json(("gh", "repo", "view", "--json", "nameWithOwner"))
    if not isinstance(payload, Mapping) or type(payload.get("nameWithOwner")) is not str:
        raise AdapterPayloadError("GitHub repository payload is malformed")
    return payload["nameWithOwner"]


class GitHubRules:
    def __init__(
        self,
        *,
        client: GitHubCliClient,
        repository_name: Callable[[], str],
    ) -> None:
        self.client = client
        self.repository_name = repository_name

    def branch_is_protected(self, branch: str) -> bool:
        output = self.client.run(
            (
                "gh",
                "api",
                f"repos/{self.repository_name()}/branches/{quote(branch, safe='')}",
                "--jq",
                ".protected",
            )
        )
        if output not in {"true", "false"}:
            raise AdapterPayloadError("GitHub branch protection payload is malformed")
        return output == "true"

    def required_status_contexts(self, branch: str) -> tuple[str, ...]:
        payload = self.client.load_json(
            (
                "gh",
                "api",
                f"repos/{self.repository_name()}/branches/{quote(branch, safe='')}/protection",
            )
        )
        if not isinstance(payload, Mapping):
            raise AdapterPayloadError("GitHub branch protection payload is malformed")
        required = payload.get("required_status_checks")
        if required is None:
            return ()
        if not isinstance(required, Mapping):
            raise AdapterPayloadError("GitHub required status checks payload is malformed")
        contexts = required.get("contexts", [])
        checks = required.get("checks", [])
        if not isinstance(contexts, list) or any(type(item) is not str for item in contexts):
            raise AdapterPayloadError("GitHub required contexts payload is malformed")
        if not isinstance(checks, list) or any(
            not isinstance(item, Mapping) or type(item.get("context")) is not str for item in checks
        ):
            raise AdapterPayloadError("GitHub required checks payload is malformed")
        return tuple(sorted({*contexts, *(item["context"] for item in checks)}))

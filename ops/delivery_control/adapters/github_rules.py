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
        repository_name = self.repository_name()
        protection_payload = self.client.load_json(
            (
                "gh",
                "api",
                f"repos/{repository_name}/branches/{quote(branch, safe='')}/protection",
            )
        )
        if not isinstance(protection_payload, Mapping):
            raise AdapterPayloadError("GitHub branch protection payload is malformed")
        protection_contexts: set[str] = set()
        required = protection_payload.get("required_status_checks")
        if required is not None and not isinstance(required, Mapping):
            raise AdapterPayloadError("GitHub required status checks payload is malformed")
        if isinstance(required, Mapping):
            contexts = required.get("contexts", [])
            checks = required.get("checks", [])
            if not isinstance(contexts, list) or any(
                type(item) is not str for item in contexts
            ):
                raise AdapterPayloadError("GitHub required contexts payload is malformed")
            if not isinstance(checks, list) or any(
                not isinstance(item, Mapping)
                or type(item.get("context")) is not str
                for item in checks
            ):
                raise AdapterPayloadError("GitHub required checks payload is malformed")
            protection_contexts.update(contexts)
            protection_contexts.update(item["context"] for item in checks)

        # Rulesets are the effective source when branch protection reports null.
        # Keep the legacy endpoint above because repositories can have both.
        rules_payload = self.client.load_json(
            (
                "gh",
                "api",
                f"repos/{repository_name}/rules/branches/{quote(branch, safe='')}",
            )
        )
        if not isinstance(rules_payload, list):
            raise AdapterPayloadError("GitHub branch rules payload is malformed")
        ruleset_contexts: set[str] = set()
        for index, rule in enumerate(rules_payload):
            if not isinstance(rule, Mapping) or type(rule.get("type")) is not str:
                raise AdapterPayloadError(f"GitHub branch rule[{index}] is malformed")
            if rule["type"] != "required_status_checks":
                continue
            parameters = rule.get("parameters")
            if not isinstance(parameters, Mapping):
                raise AdapterPayloadError(
                    f"GitHub branch rule[{index}] required parameters are malformed"
                )
            checks = parameters.get("required_status_checks", [])
            if not isinstance(checks, list) or any(
                not isinstance(item, Mapping)
                or type(item.get("context")) is not str
                for item in checks
            ):
                raise AdapterPayloadError(
                    f"GitHub branch rule[{index}] required contexts are malformed"
                )
            ruleset_contexts.update(item["context"] for item in checks)
        return tuple(sorted(protection_contexts | ruleset_contexts))

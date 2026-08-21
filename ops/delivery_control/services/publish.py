"""Idempotent Git/GitHub publication transaction for typed handbacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.errors import InvalidReceipt, PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot
from ..ports.git import GitCommandPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from .publish_preflight import PublicationContext

_RECEIPT_BEGIN = "<!-- kg.delivery.receipt.v1\n"
_RECEIPT_END = "\n-->"


class PublicationOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ALREADY_PUBLISHED = "already_published"


@dataclass(frozen=True)
class PublicationResult:
    outcome: PublicationOutcome
    pull_request: PullRequestSnapshot


class PublishPreflightPort(Protocol):
    def check(self, receipt: HandbackReceipt) -> PublicationContext: ...


def render_pull_request_body(receipt: HandbackReceipt) -> str:
    scope_lines = "\n".join(
        f"- `{item.operation.value}` `{item.path}`" for item in receipt.scope.files
    )
    if receipt.validation:
        validation_lines = "\n".join(
            f"- exit `{item.exit_code}`: `{json.dumps(list(item.command), ensure_ascii=False)}`"
            for item in receipt.validation
        )
    else:
        validation_lines = (
            "- Local quality gates are not required before publication; "
            "GitHub required checks are authoritative."
        )
    machine_receipt = json.dumps(
        receipt.to_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "## Scope\n"
        f"{scope_lines}\n\n"
        "## Handback\n"
        "- Registry handback schema: `kg.worktree.handback.v1`\n"
        f"- Normalized schema: `{receipt.schema}`\n"
        f"- Lane: `{receipt.lane_id}`\n"
        f"- Owner: `{receipt.owner_thread_id}`\n"
        f"- Claim generation: `{receipt.claim_generation}`\n"
        f"- Base SHA: `{receipt.base_sha}`\n"
        f"- Parent SHA: `{receipt.parent_sha}`\n"
        f"- Head SHA: `{receipt.head_sha}`\n"
        f"- Origin main observed by owner: `{receipt.origin_main_sha}`\n"
        f"- Scope fingerprint: `{receipt.scope.digest}`\n"
        f"- Digest: `{receipt.content_digest}`\n\n"
        "## Validation\n"
        f"{validation_lines}\n\n"
        f"{_RECEIPT_BEGIN}{machine_receipt}{_RECEIPT_END}\n"
    )


def parse_pull_request_body(body: str) -> HandbackReceipt:
    if body.count(_RECEIPT_BEGIN) != 1:
        raise PolicyViolation("PR body must contain one typed delivery receipt")
    start = body.index(_RECEIPT_BEGIN) + len(_RECEIPT_BEGIN)
    end = body.find(_RECEIPT_END, start)
    if end < 0 or _RECEIPT_BEGIN in body[end:]:
        raise PolicyViolation("PR body typed delivery receipt is malformed")
    try:
        payload = json.loads(body[start:end])
    except json.JSONDecodeError as error:
        raise PolicyViolation("PR body typed delivery receipt is invalid JSON") from error
    if not isinstance(payload, dict):
        raise PolicyViolation("PR body typed delivery receipt must be an object")
    try:
        return HandbackReceipt.from_payload(payload)
    except InvalidReceipt as error:
        raise PolicyViolation("PR body typed delivery receipt is invalid") from error


class PublishService:
    def __init__(
        self,
        *,
        preflight: PublishPreflightPort,
        git: GitCommandPort,
        github_query: GitHubQueryPort,
        github_command: GitHubCommandPort,
    ) -> None:
        self.preflight = preflight
        self.git = git
        self.github_query = github_query
        self.github_command = github_command

    def publish(self, *, receipt: HandbackReceipt, title: str) -> PublicationResult:
        if (
            not title
            or title != title.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in title)
        ):
            raise PolicyViolation("PR title must be canonical text")
        context = self.preflight.check(receipt)
        pull_request = context.pull_request
        remote_sha = context.remote_sha
        pushed = False
        if remote_sha != receipt.head_sha:
            if remote_sha is None and pull_request is not None:
                raise PolicyViolation("existing PR branch is missing from remote")
            if remote_sha is not None:
                if pull_request is None or pull_request.head_sha != remote_sha:
                    raise PolicyViolation(
                        "remote mismatch is not owned by the unique existing PR"
                    )
                if self.github_query.branch_is_protected(receipt.branch):
                    raise PolicyViolation("refusing to rewrite a protected branch")
            self.git.push_branch(
                worktree=context.worktree.path,
                branch=receipt.branch,
                expected_local_sha=receipt.head_sha,
                expected_remote_sha=remote_sha,
            )
            pushed = True

        body = render_pull_request_body(receipt)
        if pull_request is None:
            pull_request = self.github_command.create_pull_request(
                branch=receipt.branch,
                title=title,
                body=body,
            )
            outcome = PublicationOutcome.CREATED
        elif pull_request.title != title or pull_request.body != body:
            pull_request = self.github_command.update_pull_request(
                number=pull_request.number,
                title=title,
                body=body,
                expected_head_sha=receipt.head_sha,
            )
            outcome = PublicationOutcome.UPDATED
        else:
            outcome = (
                PublicationOutcome.UPDATED
                if pushed
                else PublicationOutcome.ALREADY_PUBLISHED
            )

        readback = self.github_query.get_pull_request(pull_request.number)
        if (
            readback.state != "OPEN"
            or readback.draft
            or readback.branch != receipt.branch
            or readback.head_sha != receipt.head_sha
            or readback.title != title
            or readback.body != body
        ):
            raise PolicyViolation("published PR readback differs from exact handback")
        return PublicationResult(outcome=outcome, pull_request=readback)

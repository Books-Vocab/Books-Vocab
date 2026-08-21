"""Idempotent Git/GitHub publication transaction for typed handbacks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.errors import PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import (
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..ports.git import GitCommandPort
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from .correlation import scope_matches_snapshot
from .pr_contract import (
    pull_request_holds,
    render_pull_request_body,
)
from .publish_preflight import PublicationContext


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


def receipt_from_active_claim(
    record: RegistrySnapshot, snapshot: WorktreeSnapshot
) -> HandbackReceipt:
    """Normalize the legacy registry seal into the durable PR receipt."""

    if record.status != "active":
        raise PolicyViolation("receipt normalization requires one active claim")
    if (
        record.owner_thread_id is None
        or record.handed_back_sha is None
        or record.handback_claim_generation != record.claim_generation
        or not record.handback_valid
        or record.handback_digest is None
        or record.handback_origin_main_sha is None
    ):
        raise PolicyViolation("active claim lacks an exact registry-backed handback")
    if (
        not snapshot.clean
        or snapshot.path.resolve() != record.path.resolve()
        or snapshot.branch != record.branch
        or snapshot.base_sha != record.base_sha
        or snapshot.head_sha != record.handed_back_sha
        or not scope_matches_snapshot(record, snapshot)
    ):
        raise PolicyViolation("physical worktree differs from the sealed active claim")
    return HandbackReceipt(
        lane_id=record.lane_id,
        owner_thread_id=record.owner_thread_id,
        claim_generation=record.claim_generation,
        branch=record.branch,
        worktree_path=str(record.path.resolve()),
        base_sha=record.base_sha,
        parent_sha=snapshot.parent_sha,
        head_sha=snapshot.head_sha,
        origin_main_sha=record.handback_origin_main_sha,
        content_digest=record.handback_digest,
        scope=record.scope,
    )


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

        body = render_pull_request_body(
            receipt,
            holds=pull_request_holds(pull_request),
        )
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

        if pull_request.draft:
            pull_request = self.github_command.mark_ready(pull_request.number)
            outcome = PublicationOutcome.UPDATED

        readback = self.github_query.get_pull_request(pull_request.number)
        if (
            readback.state != "OPEN"
            or readback.draft
            or readback.base_branch != "main"
            or readback.branch != receipt.branch
            or readback.head_sha != receipt.head_sha
            or readback.title != title
            or readback.body != body
        ):
            raise PolicyViolation("published PR readback differs from exact handback")
        return PublicationResult(outcome=outcome, pull_request=readback)

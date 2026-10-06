"""Exact PR-body hold reconciliation after an explicit clearance decision."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import PolicyViolation
from ..domain.observations import PullRequestSnapshot
from ..domain.states import HoldKind
from ..ports.github import GitHubCommandPort, GitHubQueryPort
from .pr_contract import (
    parse_pull_request_body,
    pull_request_holds,
    pull_request_label_holds,
    render_pull_request_body,
)


@dataclass(frozen=True)
class HoldReconciliation:
    pull_request: PullRequestSnapshot
    holds: frozenset[HoldKind]


class HoldService:
    def __init__(
        self,
        *,
        query: GitHubQueryPort,
        command: GitHubCommandPort,
    ) -> None:
        self.query = query
        self.command = command

    def reconcile(
        self,
        *,
        number: int,
        holds: frozenset[HoldKind],
        clear_all: bool,
    ) -> HoldReconciliation:
        if clear_all == bool(holds):
            raise PolicyViolation(
                "choose explicit holds or --clear-all, not both/neither"
            )
        pull_request = self.query.get_pull_request(number)
        receipt = parse_pull_request_body(pull_request.body)
        label_holds = pull_request_label_holds(pull_request)
        if clear_all and label_holds:
            raise PolicyViolation(
                "delivery hold labels remain; authorized clearance must remove them first"
            )
        requested = frozenset() if clear_all else holds
        if not label_holds.issubset(requested):
            raise PolicyViolation("requested body holds omit a durable delivery label")
        body = render_pull_request_body(receipt, holds=requested)
        self.command.update_pull_request(
            number=number,
            title=pull_request.title,
            body=body,
            expected_head_sha=pull_request.head_sha,
        )
        readback = self.query.get_pull_request(number)
        if (
            readback.head_sha != pull_request.head_sha
            or readback.body != body
            or pull_request_holds(readback) != requested
        ):
            raise PolicyViolation("PR hold reconciliation readback is not exact")
        return HoldReconciliation(pull_request=readback, holds=requested)

"""One-Issue candidate admission with read-before/write/readback safeguards."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..domain.candidate_issues import CANDIDATE_ISSUE_LABEL, CandidateSpec
from ..domain.demand_issues import DemandIssue, issue_body_sha256
from ..domain.errors import (
    CompareAndSwapConflict,
    DeliverySourceError,
    PolicyViolation,
)
from ..ports.process import CommandRunnerPort
from ..services.candidate_contract import render_candidate_body
from .github_client import GitHubCliClient
from .github_issue_queries import GitHubIssueQueries


class GitHubIssueCommands:
    """Mutate one explicitly admitted Issue; never bulk-migrates the backlog."""

    def __init__(
        self,
        *,
        repo: Path,
        runner: CommandRunnerPort,
        client: GitHubCliClient,
        query: GitHubIssueQueries,
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.client = client
        self.query = query

    def _issue(self, number: int) -> DemandIssue:
        inventory = self.query.list_open_issues()
        if not inventory.complete:
            raise DeliverySourceError(
                "cannot admit an Issue from an incomplete raw inventory"
            )
        matches = [item for item in inventory.records if item.number == number]
        if len(matches) != 1:
            raise PolicyViolation(f"open Issue #{number} is not uniquely readable")
        target_identity = f"Issue#{number}"
        if any(
            problem.identity == target_identity
            or problem.identity.startswith(f"{target_identity}@")
            for problem in inventory.problems
        ) or any(
            entry.issue_number == number for entry in inventory.source_entries
        ):
            raise DeliverySourceError(
                f"cannot admit Issue #{number} while its raw source entry is malformed"
            )
        return matches[0]

    @staticmethod
    def _validate_operator_text(value: str, name: str) -> None:
        if type(value) is not str or not value.strip() or any(
            character in "\r\n" or ord(character) < 32 or ord(character) == 127
            for character in value
        ):
            raise PolicyViolation(f"Issue admission {name} must be one safe line")

    def _add_label(self, number: int) -> None:
        self.client.run(
            (
                "gh",
                "issue",
                "edit",
                str(number),
                "--add-label",
                CANDIDATE_ISSUE_LABEL,
            )
        )

    def _candidate_label_exists(self) -> bool:
        payload = self.client.load_json(
            (
                "gh",
                "label",
                "list",
                "--search",
                CANDIDATE_ISSUE_LABEL,
                "--limit",
                "100",
                "--json",
                "name",
            )
        )
        if not isinstance(payload, list):
            raise PolicyViolation("GitHub label inventory is malformed")
        return any(
            isinstance(item, dict) and item.get("name") == CANDIDATE_ISSUE_LABEL
            for item in payload
        )

    def admit_candidate(
        self,
        *,
        issue_number: int,
        expected_updated_at: datetime,
        expected_body_sha256: str,
        spec: CandidateSpec,
        triage_reason: str,
        operator: str,
    ) -> DemandIssue:
        self._validate_operator_text(triage_reason, "triage_reason")
        self._validate_operator_text(operator, "operator")
        current = self._issue(issue_number)
        if current.candidate_spec is not None:
            if current.candidate_spec != spec:
                raise CompareAndSwapConflict(
                    f"Issue #{issue_number} already contains a different candidate contract"
                )
            if CANDIDATE_ISSUE_LABEL not in current.labels:
                self._add_label(issue_number)
                final = self._issue(issue_number)
                if CANDIDATE_ISSUE_LABEL not in final.labels:
                    raise CompareAndSwapConflict(
                        f"Issue #{issue_number} label readback did not converge"
                    )
                return final
            return current
        if (
            current.updated_at != expected_updated_at
            or current.body_sha256 != expected_body_sha256
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} changed after triage fingerprint"
            )
        if CANDIDATE_ISSUE_LABEL in current.labels:
            raise PolicyViolation(
                f"Issue #{issue_number} has candidate label without a valid contract"
            )
        if spec.initial_holds:
            raise PolicyViolation(
                "security/P0/P1 candidates cannot enter the dispatchable reservoir"
            )
        if not self._candidate_label_exists():
            raise PolicyViolation(
                f"GitHub label {CANDIDATE_ISSUE_LABEL!r} is not configured"
            )
        body = render_candidate_body(
            spec,
            original_body=current.body,
            triage_reason=triage_reason,
            operator=operator,
        )
        self.client.run(
            (
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--body",
                body,
            )
        )
        after_body = self._issue(issue_number)
        if (
            after_body.body != body
            or issue_body_sha256(after_body.body) != issue_body_sha256(body)
            or after_body.candidate_spec != spec
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} body admission did not read back exactly"
            )
        self._add_label(issue_number)
        final = self._issue(issue_number)
        if (
            CANDIDATE_ISSUE_LABEL not in final.labels
            or final.candidate_spec != spec
            or final.body != body
        ):
            raise CompareAndSwapConflict(
                f"Issue #{issue_number} candidate admission did not converge"
            )
        return final

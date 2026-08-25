"""Fail-closed synchronization of canonical local main."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.errors import CompareAndSwapConflict, PolicyViolation
from ..domain.observations import RegistrySnapshot
from ..ports.git import GitCommandPort, GitQueryPort
from ..ports.registry import RegistryQueryPort
from .correlation import scope_matches_snapshot

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAIN_PRESERVATION_RECEIPT_SCHEMA = "kg.delivery.main-preservation.v1"
MAIN_PRESERVATION_RESULT_SCHEMA = "kg.delivery.main-preservation-result.v1"


@dataclass(frozen=True)
class MainSyncResult:
    before_sha: str
    origin_sha: str
    after_sha: str
    changed: bool


@dataclass(frozen=True)
class MainPreservationReceipt:
    """Receipt for preserving one owner-bound local main divergence."""

    owner_thread_id: str
    external_id: str
    operator: str
    reason: str
    preservation_branch: str
    preservation_path: str
    preserved_head_sha: str
    expected_local_head: str
    expected_origin_head: str
    before_local_head: str
    after_local_head: str
    claim_generation: int
    schema: str = field(
        default=MAIN_PRESERVATION_RECEIPT_SCHEMA,
        init=False,
    )


@dataclass(frozen=True)
class MainPreservationResult:
    """Machine-readable result for the separate main-preservation command."""

    receipt: MainPreservationReceipt
    changed: bool
    idempotent: bool
    schema: str = field(
        default=MAIN_PRESERVATION_RESULT_SCHEMA,
        init=False,
    )


class MainSyncService:
    def __init__(
        self,
        *,
        canonical_path: Path,
        query: GitQueryPort,
        command: GitCommandPort,
    ) -> None:
        self.canonical_path = canonical_path.resolve()
        self.query = query
        self.command = command

    def _validate_checkout(self, *, expected_head_sha: str) -> None:
        snapshot = self.query.inspect_worktree(self.canonical_path, expected_head_sha)
        if (
            snapshot.path.resolve() != self.canonical_path
            or snapshot.branch != "main"
            or not snapshot.clean
            or snapshot.head_sha != expected_head_sha
        ):
            raise PolicyViolation(
                "canonical checkout must be clean, on main, and match local main"
            )

    def _validate_origin_readback(self, *, expected_origin_sha: str) -> None:
        if self.query.origin_main_sha() != expected_origin_sha:
            raise CompareAndSwapConflict(
                "origin/main changed during canonical main synchronization"
            )

    def sync(self) -> MainSyncResult:
        origin = self.query.origin_main_sha()
        before = self.query.local_main_sha()
        self._validate_checkout(expected_head_sha=before)
        if before == origin:
            self._validate_origin_readback(expected_origin_sha=origin)
            return MainSyncResult(before, origin, before, False)
        after = self.command.fast_forward_main(
            expected_local_sha=before,
            expected_origin_sha=origin,
        )
        self._validate_origin_readback(expected_origin_sha=origin)
        if after != origin or self.query.local_main_sha() != origin:
            raise PolicyViolation(
                "canonical main fast-forward did not reach origin/main"
            )
        self._validate_checkout(expected_head_sha=origin)
        return MainSyncResult(before, origin, after, True)


class MainPreservationService:
    """Preserve a claimed local main tip before an exact local-main park.

    The preservation branch/worktree and its owner claim must already exist.
    This service never creates, deletes, pushes, or rewrites those assets; it
    only accepts one exact owner-bound claim and then delegates the protected
    canonical-main CAS operation to ``GitCommandPort``.
    """

    def __init__(
        self,
        *,
        canonical_path: Path,
        query: GitQueryPort,
        command: GitCommandPort,
        registry: RegistryQueryPort,
    ) -> None:
        self.canonical_path = canonical_path.resolve()
        self.query = query
        self.command = command
        self.registry = registry

    @staticmethod
    def _text(value: str, field_name: str) -> str:
        if type(value) is not str or not value.strip():
            raise PolicyViolation(f"{field_name} is required")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise PolicyViolation(f"{field_name} contains control characters")
        return value.strip()

    def _validate_request(
        self,
        *,
        expected_local_head: str,
        expected_origin_head: str,
        preservation_branch: str,
        preservation_path: Path,
        owner_thread_id: str,
        external_id: str,
        operator: str,
        reason: str,
    ) -> tuple[str, Path, str, str, str, str]:
        for name, value in (
            ("expected_local_head", expected_local_head),
            ("expected_origin_head", expected_origin_head),
        ):
            if type(value) is not str or _SHA_RE.fullmatch(value) is None:
                raise PolicyViolation(f"{name} must be a lowercase commit SHA")
        if expected_local_head == expected_origin_head:
            raise PolicyViolation(
                "main preservation requires one divergent local commit tip"
            )
        branch = self._text(preservation_branch, "preservation branch")
        if branch == "main" or branch.startswith("-"):
            raise PolicyViolation("preservation branch must not be canonical main")
        path = preservation_path.expanduser().resolve()
        if path == self.canonical_path:
            raise PolicyViolation(
                "preservation worktree must be separate from canonical checkout"
            )
        owner = self._text(owner_thread_id, "owner thread")
        external = self._text(external_id, "external id")
        operator_value = self._text(operator, "operator")
        reason_value = self._text(reason, "reason")
        return (
            branch,
            path,
            owner,
            external,
            operator_value,
            reason_value,
        )

    def _validate_canonical_checkout(self, *, expected_head_sha: str) -> None:
        checkout = self.query.canonical_checkout()
        if checkout.path.resolve() != self.canonical_path:
            raise PolicyViolation("canonical checkout path is not exact")
        if checkout.branch != "main":
            raise PolicyViolation("canonical checkout must be on main")
        if not checkout.clean:
            raise PolicyViolation("canonical checkout must be clean")
        if checkout.head_sha != expected_head_sha:
            raise CompareAndSwapConflict(
                "canonical main HEAD changed during preservation preflight"
            )

    def _validate_registry_claim(
        self,
        *,
        branch: str,
        path: Path,
        owner_thread_id: str,
        external_id: str,
        expected_local_head: str,
        expected_origin_head: str,
    ) -> RegistrySnapshot:
        inventory = self.registry.list_records()
        if inventory.problems:
            raise PolicyViolation("registry inventory is incomplete")
        branch_matches = tuple(
            item for item in inventory.records if item.branch == branch
        )
        path_matches = tuple(
            item for item in inventory.records if item.path.resolve() == path
        )
        exact = tuple(
            item
            for item in inventory.records
            if item.branch == branch and item.path.resolve() == path
        )
        if len(exact) > 1:
            raise PolicyViolation(
                "preservation branch/path has duplicate registry claims"
            )
        if not exact:
            if branch_matches or path_matches:
                raise PolicyViolation(
                    "preservation branch or path has a registry collision"
                )
            raise PolicyViolation(
                "preservation branch/path has no exact owner-bound registry claim"
            )
        if len(branch_matches) != 1 or len(path_matches) != 1:
            raise PolicyViolation(
                "preservation branch or path has a registry collision"
            )
        record = exact[0]
        if record.status != "active":
            raise PolicyViolation("preservation registry claim is not active")
        if len(record.external_ids) != len(set(record.external_ids)):
            raise PolicyViolation("preservation registry external ids are duplicated")
        if record.owner_thread_id != owner_thread_id:
            raise PolicyViolation("preservation registry owner differs from request")
        if external_id not in record.external_ids:
            raise PolicyViolation(
                "preservation registry external id differs from request"
            )
        if record.base_sha != expected_origin_head:
            raise PolicyViolation(
                "preservation registry base differs from expected origin/main"
            )
        if record.handed_back_sha is not None:
            if record.handed_back_sha != expected_local_head:
                raise CompareAndSwapConflict(
                    "preservation registry handback differs from expected local main"
                )
            if (
                not record.handback_valid
                or record.handback_claim_generation != record.claim_generation
            ):
                raise PolicyViolation("preservation registry handback is not exact")
        elif record.handback_valid:
            raise PolicyViolation("preservation registry handback is malformed")
        external_matches = tuple(
            item for item in inventory.records if external_id in item.external_ids
        )
        if len(external_matches) != 1 or external_matches[0] != record:
            raise PolicyViolation("preservation external id has a registry collision")
        return record

    def _validate_preservation_assets(
        self,
        *,
        branch: str,
        path: Path,
        owner_thread_id: str,
        external_id: str,
        expected_local_head: str,
        expected_origin_head: str,
    ) -> int:
        if self.query.local_branch_sha(branch) != expected_local_head:
            raise CompareAndSwapConflict(
                "preservation branch changed from the expected local-only tip"
            )
        if self.query.remote_branch_sha(branch) is not None:
            raise PolicyViolation(
                "preservation branch has a remote ref; remote changes are not allowed"
            )
        worktrees = self.query.list_worktrees()
        matching_path = tuple(item for item in worktrees if item.path.resolve() == path)
        matching_branch = tuple(item for item in worktrees if item.branch == branch)
        if len(matching_path) != 1 or len(matching_branch) != 1:
            raise PolicyViolation(
                "preservation branch/path does not map to one physical worktree"
            )
        duplicate_heads = tuple(
            item
            for item in worktrees
            if item.head_sha == expected_local_head
            and item.path.resolve() not in {self.canonical_path, path}
        )
        if duplicate_heads:
            raise PolicyViolation(
                "preservation local-only tip is bound to a duplicate worktree"
            )
        physical = matching_path[0]
        if (
            physical.branch != branch
            or physical.head_sha != expected_local_head
            or physical.prunable
            or matching_branch[0] != physical
        ):
            raise PolicyViolation(
                "preservation worktree has a duplicate or drifted identity"
            )
        record = self._validate_registry_claim(
            branch=branch,
            path=path,
            owner_thread_id=owner_thread_id,
            external_id=external_id,
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
        )
        snapshot = self.query.inspect_worktree(path, expected_origin_head)
        if (
            snapshot.path.resolve() != path
            or snapshot.branch != branch
            or snapshot.base_sha != expected_origin_head
            or snapshot.head_sha != expected_local_head
            or not snapshot.clean
            or not scope_matches_snapshot(record, snapshot)
        ):
            raise PolicyViolation(
                "preservation worktree must be clean and match the exact local-only tip"
            )
        if not self.query.is_ancestor(expected_origin_head, expected_local_head):
            raise PolicyViolation(
                "preservation local-only tip is not based on expected origin/main"
            )
        return record.claim_generation

    def _state(
        self,
        *,
        expected_local_head: str,
        expected_origin_head: str,
    ) -> tuple[str, str]:
        if self.query.origin_main_sha() != expected_origin_head:
            raise CompareAndSwapConflict("origin/main changed during preservation")
        current_local = self.query.local_main_sha()
        if current_local not in {expected_local_head, expected_origin_head}:
            raise CompareAndSwapConflict("local main changed during preservation")
        self._validate_canonical_checkout(expected_head_sha=current_local)
        return current_local, (
            "already-parked" if current_local == expected_origin_head else "diverged"
        )

    def preserve(
        self,
        *,
        expected_local_head: str,
        expected_origin_head: str,
        preservation_branch: str,
        preservation_path: Path,
        owner_thread_id: str,
        external_id: str,
        operator: str,
        reason: str,
    ) -> MainPreservationResult:
        (
            branch,
            path,
            owner,
            external,
            operator_value,
            reason_value,
        ) = self._validate_request(
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
            preservation_branch=preservation_branch,
            preservation_path=preservation_path,
            owner_thread_id=owner_thread_id,
            external_id=external_id,
            operator=operator,
            reason=reason,
        )
        before_local, state = self._state(
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
        )
        claim_generation = self._validate_preservation_assets(
            branch=branch,
            path=path,
            owner_thread_id=owner,
            external_id=external,
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
        )
        changed = state == "diverged"
        if changed:
            after = self.command.park_main_to_origin(
                expected_local_sha=expected_local_head,
                expected_origin_sha=expected_origin_head,
            )
            if after != expected_origin_head:
                raise PolicyViolation(
                    "canonical main park returned a non-exact origin/main SHA"
                )
        else:
            after = expected_origin_head
        final_local, _ = self._state(
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
        )
        if final_local != expected_origin_head:
            raise PolicyViolation("canonical main did not reach exact origin/main")
        final_claim_generation = self._validate_preservation_assets(
            branch=branch,
            path=path,
            owner_thread_id=owner,
            external_id=external,
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
        )
        if final_claim_generation != claim_generation:
            raise CompareAndSwapConflict(
                "preservation registry claim changed during main reconciliation"
            )
        receipt = MainPreservationReceipt(
            owner_thread_id=owner,
            external_id=external,
            operator=operator_value,
            reason=reason_value,
            preservation_branch=branch,
            preservation_path=str(path),
            preserved_head_sha=expected_local_head,
            expected_local_head=expected_local_head,
            expected_origin_head=expected_origin_head,
            before_local_head=before_local,
            after_local_head=after,
            claim_generation=claim_generation,
        )
        return MainPreservationResult(
            receipt=receipt,
            changed=changed,
            idempotent=not changed,
        )

"""Pure parsing of Git porcelain and ref payloads."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..domain.branch_refs import BranchInventory
from ..domain.observations import (
    FileChange,
    FileOperation,
    MainLandingSnapshot,
    PhysicalWorktree,
)
from .errors import AdapterPayloadError


def parse_worktrees(payload: str) -> tuple[PhysicalWorktree, ...]:
    if not payload:
        return ()
    records: list[PhysicalWorktree] = []
    for block in payload.split("\n\n"):
        fields: dict[str, str] = {}
        flags: set[str] = set()
        for line in block.splitlines():
            key, separator, value = line.partition(" ")
            if separator:
                fields[key] = value
            elif key:
                flags.add(key)
        try:
            path = Path(fields["worktree"])
            head_sha = fields["HEAD"]
        except KeyError as error:
            raise AdapterPayloadError(
                "git worktree porcelain record is incomplete"
            ) from error
        branch_ref = fields.get("branch")
        branch = (
            branch_ref.removeprefix("refs/heads/")
            if branch_ref and branch_ref.startswith("refs/heads/")
            else None
        )
        records.append(
            PhysicalWorktree(
                path=path,
                head_sha=head_sha,
                branch=branch,
                prunable="prunable" in fields or "prunable" in flags,
            )
        )
    return tuple(records)


def parse_parent_sha(payload: str, *, head_sha: str, base_sha: str) -> str:
    fields = payload.split()
    if not fields or fields[0] != head_sha:
        raise AdapterPayloadError("git parent readback differs from worktree HEAD")
    return fields[1] if len(fields) > 1 else base_sha


def parse_changed_files(payload: str) -> tuple[FileChange, ...]:
    """Normalize ``git diff --name-status -z`` into flat changed paths."""

    if not payload:
        return ()
    fields = payload.split("\0")
    if fields[-1] != "":
        raise AdapterPayloadError(
            "git diff name-status payload is not NUL terminated"
        )
    fields.pop()
    changes: list[FileChange] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        status_code = status[:1]
        if status_code in {"A", "M", "T", "D"}:
            if index >= len(fields):
                raise AdapterPayloadError(
                    f"git diff status {status!r} is missing its path"
                )
            path = fields[index]
            index += 1
            operation = {
                "A": FileOperation.ADD,
                "M": FileOperation.MODIFY,
                "T": FileOperation.MODIFY,
                "D": FileOperation.DELETE,
            }[status_code]
            changes.append(FileChange(operation, path))
            continue
        if status_code in {"R", "C"}:
            if index + 1 >= len(fields):
                raise AdapterPayloadError(
                    f"git diff status {status!r} is missing source or destination"
                )
            source = fields[index]
            destination = fields[index + 1]
            index += 2
            if status_code == "R":
                changes.append(FileChange(FileOperation.DELETE, source))
            changes.append(FileChange(FileOperation.ADD, destination))
            continue
        raise AdapterPayloadError(f"unsupported git diff status: {status!r}")

    canonical = tuple(
        sorted(changes, key=lambda item: (item.path, item.operation.value))
    )
    paths = tuple(item.path for item in canonical)
    if len(paths) != len(set(paths)):
        raise AdapterPayloadError(
            "git diff normalization produced duplicate changed paths"
        )
    return canonical


def parse_branch_inventory(
    local_payload: str,
    remote_payload: str,
) -> BranchInventory:
    local: list[tuple[str, str]] = []
    for line in local_payload.splitlines():
        if not line:
            continue
        name, separator, sha = line.partition("\t")
        if not separator:
            raise AdapterPayloadError("local branch inventory row is malformed")
        local.append((name, sha))

    remote: list[tuple[str, str]] = []
    for line in remote_payload.splitlines():
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2 or not fields[1].startswith("refs/heads/"):
            raise AdapterPayloadError("remote branch inventory row is malformed")
        remote.append((fields[1].removeprefix("refs/heads/"), fields[0]))

    return BranchInventory(
        local=tuple(sorted(local)),
        remote=tuple(sorted(remote)),
    )


def parse_remote_branch_sha(payload: str, *, branch: str) -> str | None:
    ref = f"refs/heads/{branch}"
    if not payload:
        return None
    rows = [line.split() for line in payload.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise AdapterPayloadError(f"unexpected remote ref response for {ref}")
    return rows[0][0]


def parse_local_branch_sha(payload: str, *, ref: str) -> str:
    if not payload or len(payload.splitlines()) != 1:
        raise AdapterPayloadError(f"local branch {ref} did not resolve uniquely")
    return payload


def parse_origin_main_sha(payload: str) -> str:
    rows = [line.split() for line in payload.splitlines() if line.strip()]
    if (
        len(rows) != 1
        or len(rows[0]) != 2
        or rows[0][1] != "refs/heads/main"
    ):
        raise AdapterPayloadError("origin/main did not resolve uniquely")
    return rows[0][0]


def parse_first_parent_landings(payload: str) -> tuple[MainLandingSnapshot, ...]:
    records: list[MainLandingSnapshot] = []
    for index, line in enumerate(payload.splitlines()):
        sha, separator, raw_timestamp = line.partition("\t")
        if not separator:
            raise AdapterPayloadError(
                f"first-parent landing[{index}] is missing its timestamp"
            )
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
            records.append(MainLandingSnapshot(sha=sha, landed_at=timestamp))
        except (ValueError, TypeError) as error:
            raise AdapterPayloadError(
                f"first-parent landing[{index}] is malformed"
            ) from error
    return tuple(records)

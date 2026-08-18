"""Normalize the read-only Git/worktree snapshot consumed by KG Board."""
from __future__ import annotations

from typing import Any
import re

try:
    from ops.kg_board.scope import normalise_scope
except ModuleNotFoundError:  # direct launch via the release checkout
    from scope import normalise_scope


SCHEMA = "kg.board.git-tree.v1"
WORKTREE_STATUS_SCHEMA = "kg.board.worktree-status.v1"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and re.fullmatch(r"[0-9a-fA-F]{7,40}", value) else None


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def normalize_worktree_status(payload: Any) -> dict[str, Any]:
    """Normalize the fast, out-of-band dirty-status mirror.

    Dirty state is produced on the machine that owns the worktrees and is sent
    separately from the comparatively expensive commit DAG.  ``None`` means
    unknown; it is never coerced to clean.
    """
    if not isinstance(payload, dict):
        return {
            "schema": WORKTREE_STATUS_SCHEMA,
            "at": None,
            "host": None,
            "complete": False,
            "error": "worktree status mirror is not an object",
            "records": [],
        }

    errors: list[str] = []
    raw_error = payload.get("error")
    if raw_error is not None and not isinstance(raw_error, str):
        errors.append("payload error is not a string")
    elif isinstance(raw_error, str) and raw_error.strip():
        errors.append(raw_error.strip())
    raw_records = payload.get("records")
    if raw_records is not None and not isinstance(raw_records, (list, tuple)):
        errors.append("records is not a list")

    records: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    for raw in _items(raw_records):
        if not isinstance(raw, dict):
            errors.append("worktree status record is not an object")
            continue
        branch = _text(raw.get("branch"))
        if not branch:
            errors.append("worktree status record has no branch")
            continue
        if branch in seen_branches:
            errors.append(f"worktree status branch {branch} is duplicated")
            continue
        seen_branches.add(branch)

        present = raw.get("present")
        if present is not None and not isinstance(present, bool):
            errors.append(f"worktree status {branch} present is not boolean")
            present = None
        dirty = raw.get("dirty")
        if dirty is not None and not isinstance(dirty, bool):
            errors.append(f"worktree status {branch} dirty is not boolean")
            dirty = None

        raw_files = raw.get("dirty_files")
        if raw_files is not None and not isinstance(raw_files, (list, tuple)):
            errors.append(f"worktree status {branch} dirty_files is not a list")
        dirty_files = [path for path in _items(raw_files)
                       if isinstance(path, str) and path]
        if any(not isinstance(path, str) for path in _items(raw_files)):
            errors.append(f"worktree status {branch} dirty_files contains a non-string path")

        file_count = raw.get("dirty_file_count")
        if file_count is not None and (
            not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 0
        ):
            errors.append(f"worktree status {branch} dirty_file_count is not a non-negative integer")
            file_count = None
        if file_count is None and dirty is True:
            file_count = len(dirty_files)

        record = {
            "branch": branch,
            "path": _text(raw.get("path")),
            "present": present,
            "dirty": dirty,
            "dirty_files": sorted(set(dirty_files)),
            "dirty_file_count": file_count,
            "error": _text(raw.get("error")),
        }
        records.append(record)

    return {
        "schema": WORKTREE_STATUS_SCHEMA,
        "at": _text(payload.get("at")),
        "host": _text(payload.get("host")),
        "complete": payload.get("complete") is True and not errors,
        "error": "; ".join(errors) or None,
        "records": sorted(records, key=lambda row: row["branch"]),
    }


def normalize_snapshot(payload: Any) -> dict[str, Any]:
    """Return a stable, bounded shape for a feeder Git snapshot.

    The feeder is outside this repository and older payloads may be absent or
    partially populated. Normalization is intentionally lossless for fields the
    board understands and fail-closed for malformed commit/ref records.
    """
    if not isinstance(payload, dict):
        return {
            "schema": SCHEMA,
            "at": None,
            "host": None,
            "complete": False,
            "error": "git tree mirror is not an object",
            "refs": [],
            "commits": [],
        }

    commits: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    def checked(value: Any, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            errors.append(f"{field} is not a string")
            return None
        return value.strip() or None

    payload_error = checked(payload.get("error"), "payload error")
    if payload_error:
        errors.append(payload_error)
    if payload.get("commits") is not None and not isinstance(payload.get("commits"), (list, tuple)):
        errors.append("commits is not a list")
    if payload.get("refs") is not None and not isinstance(payload.get("refs"), (list, tuple)):
        errors.append("refs is not a list")
    for raw in _items(payload.get("commits")):
        if not isinstance(raw, dict):
            errors.append("commit record is not an object")
            continue
        sha = _sha(raw.get("sha"))
        if not sha:
            errors.append("commit record has invalid sha")
            continue
        raw_parents = raw.get("parents")
        if raw_parents is not None and not isinstance(raw_parents, (list, tuple)):
            errors.append(f"commit {sha} parents is not a list")
        parents = []
        for parent in _items(raw_parents):
            normalized_parent = _sha(parent)
            if normalized_parent is None:
                errors.append(f"commit {sha} has invalid parent")
            else:
                parents.append(normalized_parent)
        raw_files = raw.get("files")
        if raw_files is not None and not isinstance(raw_files, (list, tuple)):
            errors.append(f"commit {sha} files is not a list")
        if any(not isinstance(path, str) for path in _items(raw_files)):
            errors.append(f"commit {sha} files contains a non-string path")
        for key in ("insertions", "deletions"):
            value = raw.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                errors.append(f"commit {sha} {key} is not an integer")
        row = {
            "sha": sha,
            "parents": parents,
            "subject": checked(raw.get("subject"), f"commit {sha} subject") or "(無主旨)",
            "author": checked(raw.get("author"), f"commit {sha} author"),
            "committer": checked(raw.get("committer"), f"commit {sha} committer"),
            "authored_at": checked(raw.get("authored_at"), f"commit {sha} authored_at"),
            "committed_at": checked(raw.get("committed_at"), f"commit {sha} committed_at"),
            "insertions": (raw.get("insertions") if isinstance(raw.get("insertions"), int)
                           and not isinstance(raw.get("insertions"), bool) else None),
            "deletions": (raw.get("deletions") if isinstance(raw.get("deletions"), int)
                          and not isinstance(raw.get("deletions"), bool) else None),
            "files": [path for path in _items(raw.get("files")) if isinstance(path, str) and path],
        }
        prior = commits.get(sha)
        if prior:
            # A commit can arrive through multiple refs. Keep the richer record
            # without allowing one partial record to erase metadata.
            for key in ("parents", "subject", "author", "committer", "authored_at",
                        "committed_at", "insertions", "deletions"):
                if (prior.get(key) not in (None, [], "(無主旨)")
                        and row.get(key) not in (None, [], "(無主旨)")
                        and prior.get(key) != row.get(key)):
                    errors.append(f"commit {sha} has conflicting {key}")
            row = {key: value if value not in (None, [], "(無主旨)") else prior.get(key)
                   for key, value in row.items()}
            row["parents"] = row.get("parents") or prior.get("parents") or []
            row["files"] = sorted(set(row.get("files") or []) | set(prior.get("files") or []))
        commits[sha] = row

    refs: list[dict[str, Any]] = []
    seen_branches: dict[str, str] = {}
    for index, raw in enumerate(_items(payload.get("refs"))):
        if not isinstance(raw, dict):
            errors.append("ref record is not an object")
            continue
        branch = checked(raw.get("branch"), "ref branch")
        head = _sha(raw.get("head"))
        if not branch or not head:
            errors.append("ref record has invalid branch or head")
            continue
        if branch in seen_branches:
            errors.append(f"ref {branch} is duplicated")
            continue
        seen_branches[branch] = head
        tickets = []
        raw_tickets = raw.get("tickets") if raw.get("tickets") is not None else raw.get("backlog")
        if raw_tickets is not None and not isinstance(raw_tickets, (list, tuple)):
            errors.append(f"ref {branch} tickets is not a list")
        for ticket in _items(raw_tickets):
            if isinstance(ticket, dict):
                ticket_id = checked(ticket.get("id"), f"ref {branch} ticket id")
                if ticket_id:
                    tickets.append({
                        "id": ticket_id,
                        "brief": checked(ticket.get("brief"), f"ref {branch} ticket brief"),
                        "severity": checked(ticket.get("severity"), f"ref {branch} ticket severity"),
                    })
                else:
                    errors.append(f"ref {branch} has ticket without id")
            elif isinstance(ticket, str) and checked(ticket, f"ref {branch} ticket"):
                tickets.append({"id": checked(ticket, f"ref {branch} ticket"), "brief": None, "severity": None})
            else:
                errors.append(f"ref {branch} has malformed ticket")
        worktree_present = raw.get("worktree_present")
        if worktree_present is not None and not isinstance(worktree_present, bool):
            errors.append(f"ref {branch} worktree_present is not boolean")
        scope = raw.get("scope") if "scope" in raw else None
        if isinstance(scope, dict):
            try:
                scope = normalise_scope(scope)
            except ValueError as exc:
                errors.append(f"ref {branch} has invalid scope: {exc}")
                scope = None
        raw_dirty = raw.get("dirty")
        if raw_dirty is not None and not isinstance(raw_dirty, bool):
            errors.append(f"ref {branch} dirty is not boolean")
            raw_dirty = None
        raw_dirty_files = raw.get("dirty_files")
        if raw_dirty_files is not None and not isinstance(raw_dirty_files, (list, tuple)):
            errors.append(f"ref {branch} dirty_files is not a list")
        dirty_files = [path for path in _items(raw_dirty_files)
                       if isinstance(path, str) and path]
        if any(not isinstance(path, str) for path in _items(raw_dirty_files)):
            errors.append(f"ref {branch} dirty_files contains a non-string path")
        raw_dirty_count = raw.get("dirty_file_count")
        if raw_dirty_count is not None and (
            not isinstance(raw_dirty_count, int)
            or isinstance(raw_dirty_count, bool)
            or raw_dirty_count < 0
        ):
            errors.append(f"ref {branch} dirty_file_count is not a non-negative integer")
            raw_dirty_count = None
        codex_thread_id = checked(raw.get("codex_thread_id"),
                                  f"ref {branch} codex_thread_id")
        refs.append({
            "id": checked(raw.get("id"), f"ref {branch} id") or f"ref-{index}",
            "branch": branch,
            "kind": checked(raw.get("kind"), f"ref {branch} kind") or "child",
            "base": checked(raw.get("base"), f"ref {branch} base") or "main",
            "base_sha": _sha(raw.get("base_sha")),
            "head": head,
            "path": checked(raw.get("path"), f"ref {branch} path"),
            "host": checked(raw.get("host"), f"ref {branch} host") or checked(payload.get("host"), "payload host"),
            "status": checked(raw.get("status"), f"ref {branch} status") or "active",
            "live_state": checked(raw.get("live_state"), f"ref {branch} live_state") or "unknown",
            "worktree_present": worktree_present if isinstance(worktree_present, bool) else None,
            "integration_owner": checked(raw.get("integration_owner"), f"ref {branch} integration_owner"),
            "claimed_at": checked(raw.get("claimed_at"), f"ref {branch} claimed_at"),
            "handed_back_sha": _sha(raw.get("handed_back_sha")),
            "tickets": tickets,
        })
        if "scope" in raw:
            refs[-1]["scope"] = scope
        if "codex_thread_id" in raw:
            refs[-1]["codex_thread_id"] = codex_thread_id
        if any(key in raw for key in ("dirty", "dirty_files", "dirty_file_count")):
            refs[-1].update({
                "dirty": raw_dirty,
                "dirty_files": sorted(set(dirty_files)),
                "dirty_file_count": raw_dirty_count,
            })
        for key in ("base_sha", "handed_back_sha"):
            if raw.get(key) is not None and _sha(raw.get(key)) is None:
                errors.append(f"ref {branch} has invalid {key}")

    return {
        "schema": SCHEMA,
        "at": checked(payload.get("at"), "payload at"),
        "host": checked(payload.get("host"), "payload host"),
        "complete": (payload.get("complete") is True and not errors),
        "error": "; ".join(errors) or None,
        "refs": refs,
        "commits": sorted(commits.values(), key=lambda row: row["sha"]),
    }


def project_snapshot(
    payload: Any,
    tickets: dict[str, dict[str, Any]] | None = None,
    worktree_status: Any = None,
) -> dict[str, Any]:
    """Project normalized refs and commits for a read-only graph renderer."""
    snapshot = normalize_snapshot(payload)
    tickets = tickets or {}
    status_snapshot = (
        normalize_worktree_status(worktree_status)
        if worktree_status is not None else None
    )
    status_by_branch = {
        row["branch"]: row for row in (status_snapshot or {}).get("records", [])
    }
    commits = {row["sha"]: dict(row) for row in snapshot["commits"]}
    refs = []
    referenced: dict[str, list[str]] = {}
    for ref in snapshot["refs"]:
        row = dict(ref)
        ref_tickets = []
        for ticket in row["tickets"]:
            enriched = dict(ticket)
            source = tickets.get(ticket["id"]) or {}
            enriched["brief"] = enriched.get("brief") or source.get("brief")
            enriched["severity"] = enriched.get("severity") or source.get("severity")
            ref_tickets.append(enriched)
        row["tickets"] = ref_tickets
        status = status_by_branch.get(row["branch"])
        if status is not None:
            row.update({
                "dirty": status["dirty"],
                "dirty_files": status["dirty_files"],
                "dirty_file_count": status["dirty_file_count"],
                "dirty_status_error": status["error"],
            })
        refs.append(row)
        if row["head"] in commits:
            referenced.setdefault(row["head"], []).append(row["branch"])

    missing_parents = sorted({
        parent
        for row in commits.values()
        for parent in row["parents"]
        if parent not in commits
    })
    dangling_refs = sorted({ref["head"] for ref in refs if ref["head"] not in commits})
    parent_cycles: set[str] = set()
    state: dict[str, int] = {}
    for start in commits:
        if state.get(start):
            continue
        stack = [(start, False)]
        while stack:
            sha, exiting = stack.pop()
            if sha not in commits:
                continue
            if exiting:
                state[sha] = 2
                continue
            if state.get(sha) == 1:
                parent_cycles.add(sha)
                continue
            if state.get(sha) == 2:
                continue
            state[sha] = 1
            stack.append((sha, True))
            stack.extend((parent, False) for parent in reversed(commits[sha]["parents"]))
    for sha, branches in referenced.items():
        commits[sha]["refs"] = sorted(set(branches))
    for row in commits.values():
        row.setdefault("refs", [])

    result = {
        "schema": SCHEMA,
        "at": snapshot["at"],
        "host": snapshot["host"],
        "complete": (snapshot["complete"] and not missing_parents and not dangling_refs
                     and not parent_cycles
                     and not snapshot["error"]),
        "error": snapshot["error"],
        "missing_parents": missing_parents,
        "dangling_refs": dangling_refs,
        "parent_cycles": sorted(parent_cycles),
        "refs": refs,
        "commits": sorted(commits.values(), key=lambda row: row["sha"]),
    }
    if status_snapshot is not None:
        result["worktree_status"] = {
            "schema": status_snapshot["schema"],
            "at": status_snapshot["at"],
            "host": status_snapshot["host"],
            "complete": status_snapshot["complete"],
            "error": status_snapshot["error"],
        }
    return result

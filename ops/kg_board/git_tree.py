"""Normalize the read-only Git/worktree snapshot consumed by KG Board."""
from __future__ import annotations

from typing import Any
import re


SCHEMA = "kg.board.git-tree.v1"


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
        row = {
            "sha": sha,
            "parents": parents,
            "subject": _text(raw.get("subject")) or "(無主旨)",
            "author": _text(raw.get("author")),
            "committer": _text(raw.get("committer")),
            "authored_at": _text(raw.get("authored_at")),
            "committed_at": _text(raw.get("committed_at")),
            "insertions": raw.get("insertions") if isinstance(raw.get("insertions"), int) else None,
            "deletions": raw.get("deletions") if isinstance(raw.get("deletions"), int) else None,
            "files": [str(path) for path in _items(raw.get("files")) if path],
        }
        prior = commits.get(sha)
        if prior:
            # A commit can arrive through multiple refs. Keep the richer record
            # without allowing one partial record to erase metadata.
            if prior.get("parents") and row.get("parents") and prior["parents"] != row["parents"]:
                errors.append(f"commit {sha} has conflicting parents")
            row = {key: value if value not in (None, [], "(無主旨)") else prior.get(key)
                   for key, value in row.items()}
            row["parents"] = row.get("parents") or prior.get("parents") or []
            row["files"] = sorted(set(row.get("files") or []) | set(prior.get("files") or []))
        commits[sha] = row

    refs: list[dict[str, Any]] = []
    for index, raw in enumerate(_items(payload.get("refs"))):
        if not isinstance(raw, dict):
            errors.append("ref record is not an object")
            continue
        branch = _text(raw.get("branch"))
        head = _sha(raw.get("head"))
        if not branch or not head:
            errors.append("ref record has invalid branch or head")
            continue
        tickets = []
        raw_tickets = raw.get("tickets") if raw.get("tickets") is not None else raw.get("backlog")
        if raw_tickets is not None and not isinstance(raw_tickets, (list, tuple)):
            errors.append(f"ref {branch} tickets is not a list")
        for ticket in _items(raw_tickets):
            if isinstance(ticket, dict):
                ticket_id = _text(ticket.get("id"))
                if ticket_id:
                    tickets.append({
                        "id": ticket_id,
                        "brief": _text(ticket.get("brief")),
                        "severity": _text(ticket.get("severity")),
                    })
            elif _text(ticket):
                tickets.append({"id": _text(ticket), "brief": None, "severity": None})
        refs.append({
            "id": _text(raw.get("id")) or f"ref-{index}",
            "branch": branch,
            "kind": _text(raw.get("kind")) or "child",
            "base": _text(raw.get("base")) or "main",
            "base_sha": _sha(raw.get("base_sha")),
            "head": head,
            "path": _text(raw.get("path")),
            "host": _text(raw.get("host")) or _text(payload.get("host")),
            "status": _text(raw.get("status")) or "active",
            "live_state": _text(raw.get("live_state")) or "unknown",
            "worktree_present": raw.get("worktree_present"),
            "integration_owner": _text(raw.get("integration_owner")),
            "claimed_at": _text(raw.get("claimed_at")),
            "handed_back_sha": _sha(raw.get("handed_back_sha")),
            "tickets": tickets,
        })

    return {
        "schema": SCHEMA,
        "at": _text(payload.get("at")),
        "host": _text(payload.get("host")),
        "complete": (payload["complete"] if isinstance(payload.get("complete"), bool)
                     else "complete" not in payload),
        "error": _text(payload.get("error")) or "; ".join(errors) or None,
        "refs": refs,
        "commits": sorted(commits.values(), key=lambda row: row["sha"]),
    }


def project_snapshot(payload: Any, tickets: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Project normalized refs and commits for a read-only graph renderer."""
    snapshot = normalize_snapshot(payload)
    tickets = tickets or {}
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
    for sha, branches in referenced.items():
        commits[sha]["refs"] = sorted(set(branches))
    for row in commits.values():
        row.setdefault("refs", [])

    return {
        "schema": SCHEMA,
        "at": snapshot["at"],
        "host": snapshot["host"],
        "complete": (snapshot["complete"] and not missing_parents and not dangling_refs
                     and not snapshot["error"]),
        "error": snapshot["error"],
        "missing_parents": missing_parents,
        "dangling_refs": dangling_refs,
        "refs": refs,
        "commits": sorted(commits.values(), key=lambda row: row["sha"]),
    }

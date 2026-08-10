"""Normalize the read-only Git/worktree snapshot consumed by KG Board."""
from __future__ import annotations

from typing import Any


SCHEMA = "kg.board.git-tree.v1"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _sha(value: Any) -> str | None:
    value = _text(value)
    return value if value and len(value) >= 7 else None


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
    for raw in payload.get("commits") or []:
        if not isinstance(raw, dict):
            continue
        sha = _sha(raw.get("sha"))
        if not sha:
            continue
        parents = [_sha(parent) for parent in raw.get("parents") or []]
        parents = [parent for parent in parents if parent]
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
            "files": [str(path) for path in raw.get("files") or [] if path],
        }
        prior = commits.get(sha)
        if prior:
            # A commit can arrive through multiple refs. Keep the richer record
            # without allowing one partial record to erase metadata.
            row = {key: value if value not in (None, [], "(無主旨)") else prior.get(key)
                   for key, value in row.items()}
            row["parents"] = row.get("parents") or prior.get("parents") or []
            row["files"] = sorted(set(row.get("files") or []) | set(prior.get("files") or []))
        commits[sha] = row

    refs: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("refs") or []):
        if not isinstance(raw, dict):
            continue
        branch = _text(raw.get("branch"))
        head = _sha(raw.get("head"))
        if not branch or not head:
            continue
        tickets = []
        for ticket in raw.get("tickets") or raw.get("backlog") or []:
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
        "complete": bool(payload.get("complete", True)),
        "error": _text(payload.get("error")),
        "refs": refs,
        "commits": sorted(commits.values(), key=lambda row: row["sha"]),
    }

"""Pure validation and projection for campaign-scoped worktree reservations.

This module deliberately knows nothing about the backlog store, git, or the
registry ledger.  Callers provide the current base and the already-read backlog
entries, then persist the validated result under the registry's canonical lock.
"""

from __future__ import annotations

import copy
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "kg.worktree.campaign.v1"
RESERVATION_SCHEMA = "kg.worktree.campaign-reservation.v1"
VALID_MODES = frozenset({"read", "write"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _problem(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "message": message, **extra}


def _as_entries(entries: Iterable[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if isinstance(entries, dict):
        return {str(key): value for key, value in entries.items() if isinstance(value, dict)}
    return {
        str(entry.get("id")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    }


def _normalise_path(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    path = posixpath.normpath(raw)
    if path in {".", ".."} or path.startswith("../") or path.startswith("/"):
        return None
    return path


def _normalise_sites(ticket: dict[str, Any], problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_sites = ticket.get("write_sites")
    if not isinstance(raw_sites, list) or not raw_sites:
        problems.append(_problem("missing-write-sites", "ticket must declare write_sites",
                                 ticket=ticket.get("id")))
        return []
    sites: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sites):
        if not isinstance(raw, dict):
            problems.append(_problem("invalid-write-site", "write site must be an object",
                                     ticket=ticket.get("id"), index=index))
            continue
        path = _normalise_path(raw.get("path"))
        mode = raw.get("mode")
        symbol = raw.get("symbol")
        if path is None:
            problems.append(_problem("unknown-site-path", "write site path is not a safe repo-relative path",
                                     ticket=ticket.get("id"), index=index, path=raw.get("path")))
            continue
        if mode not in VALID_MODES:
            problems.append(_problem("unknown-site-mode", "write site mode must be read or write",
                                     ticket=ticket.get("id"), index=index, mode=mode))
            continue
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
            problems.append(_problem("invalid-site-symbol", "site symbol must be a non-empty string",
                                     ticket=ticket.get("id"), index=index))
            continue
        site = {"path": path, "mode": mode}
        if symbol is not None:
            site["symbol"] = symbol.strip()
        sites.append(site)
    return sites


def _overlap_is_declared(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_id = str(first["id"])
    second_id = str(second["id"])
    first_blocked = set(first.get("blocked_by") or [])
    second_blocked = set(second.get("blocked_by") or [])
    if first_id in second_blocked or second_id in first_blocked:
        return True
    group = first.get("co_land_group")
    return bool(group and group == second.get("co_land_group"))


def _site_pair_conflicts(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first["path"] != second["path"]:
        return False
    if first["mode"] == "read" and second["mode"] == "read":
        return False
    # A symbol is the only evidence that two operations on one file are
    # disjoint.  Missing either symbol is intentionally unsafe.
    return not (
        first.get("symbol")
        and second.get("symbol")
        and first["symbol"] != second["symbol"]
    )


def _reserved_ticket_ids(existing_reservations: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    owners: dict[str, dict[str, Any]] = {}
    for reservation in existing_reservations:
        if not isinstance(reservation, dict):
            continue
        ticket_ids = reservation.get("ticket_ids")
        if ticket_ids is None:
            ticket_ids = [
                ticket_id
                for partition in (reservation.get("partitions") or {}).values()
                for ticket_id in (partition.get("ticket_ids") or [])
            ]
        for ticket_id in ticket_ids or []:
            owners[str(ticket_id)] = reservation
    return owners


def validate_manifest(
    request: dict[str, Any],
    *,
    current_base: str,
    backlog_entries: Iterable[dict[str, Any]] | dict[str, dict[str, Any]],
    existing_reservations: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return named validation problems; an empty list is the only valid result."""
    problems: list[dict[str, Any]] = []
    if not isinstance(request, dict):
        return [_problem("invalid-request", "campaign request must be an object")]
    if request.get("schema") != SCHEMA:
        problems.append(_problem("invalid-schema", f"schema must be {SCHEMA}"))
    campaign_id = request.get("campaign_id")
    if not isinstance(campaign_id, str) or not _ID_RE.fullmatch(campaign_id):
        problems.append(_problem("invalid-campaign-id", "campaign_id is not a safe identifier"))
    coordinator = request.get("coordinator")
    if not isinstance(coordinator, str) or not coordinator.strip():
        problems.append(_problem("invalid-coordinator", "coordinator is required and must be unique per campaign"))
    base = request.get("base")
    if not isinstance(base, str) or not _SHA_RE.fullmatch(base):
        problems.append(_problem("invalid-base", "base must be a full git object id"))
    elif base != current_base:
        problems.append(_problem("stale-base", "campaign base is not the current local base",
                                 expected=current_base, actual=base))

    raw_partitions = request.get("partitions")
    partitions: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_partitions, list) or not raw_partitions:
        problems.append(_problem("missing-partitions", "partitions must be a non-empty list"))
    else:
        for raw in raw_partitions:
            if not isinstance(raw, dict):
                problems.append(_problem("invalid-partition", "partition must be an object"))
                continue
            partition_id = raw.get("id")
            quota = raw.get("quota")
            if not isinstance(partition_id, str) or not _ID_RE.fullmatch(partition_id):
                problems.append(_problem("invalid-partition-id", "partition id is invalid"))
                continue
            if partition_id in partitions:
                problems.append(_problem("duplicate-partition", "partition id appears more than once",
                                         partition=partition_id))
                continue
            if not isinstance(quota, int) or isinstance(quota, bool) or quota <= 0:
                problems.append(_problem("invalid-quota", "partition quota must be a positive integer",
                                         partition=partition_id, quota=quota))
                continue
            partitions[partition_id] = {"id": partition_id, "quota": quota}

    raw_tickets = request.get("tickets")
    if not isinstance(raw_tickets, list) or not raw_tickets:
        problems.append(_problem("missing-tickets", "tickets must be a non-empty list"))
        raw_tickets = []
    entries = _as_entries(backlog_entries)
    tickets: dict[str, dict[str, Any]] = {}
    normalised_sites: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_tickets:
        if not isinstance(raw, dict):
            problems.append(_problem("invalid-ticket", "ticket must be an object"))
            continue
        ticket_id = raw.get("id")
        if not isinstance(ticket_id, str) or not ticket_id:
            problems.append(_problem("invalid-ticket-id", "ticket id is required"))
            continue
        if ticket_id in tickets:
            problems.append(_problem("duplicate-ticket", "ticket id appears more than once", ticket=ticket_id))
            continue
        tickets[ticket_id] = raw
        partition_id = raw.get("partition")
        if partition_id not in partitions:
            problems.append(_problem("unknown-partition", "ticket references an unknown partition",
                                     ticket=ticket_id, partition=partition_id))
        if ticket_id not in entries:
            problems.append(_problem("missing-ticket", "ticket is not present in the backlog store",
                                     ticket=ticket_id))
        else:
            entry = entries[ticket_id]
            if entry.get("status") in {"fixed", "wont-fix"}:
                problems.append(_problem("already-resolved", "reserved ticket is already resolved",
                                         ticket=ticket_id, status=entry.get("status")))
            if not str(entry.get("groomed_by") or "").strip():
                problems.append(_problem("ungroomed-ticket", "reserved ticket has no groom stamp",
                                         ticket=ticket_id))
            # The backlog entry's blocked_by is the executable prerequisite
            # contract.  The request's blocked_by is a campaign declaration
            # used only to prove an intentional cross-partition overlap; it
            # must not turn an otherwise unblocked backlog row into a refusal.
            for blocker in entry.get("blocked_by") or []:
                blocker_entry = entries.get(str(blocker))
                if blocker_entry is not None and blocker_entry.get("status") not in {"fixed", "wont-fix"}:
                    problems.append(_problem("blocked-by-unresolved", "ticket has an unresolved prerequisite",
                                             ticket=ticket_id, blocker=blocker))
        blocked_by = raw.get("blocked_by") or []
        if not isinstance(blocked_by, list) or any(not isinstance(item, str) for item in blocked_by):
            problems.append(_problem("invalid-blocked-by", "blocked_by must be a list of ticket ids",
                                     ticket=ticket_id))
        elif ticket_id in blocked_by:
            problems.append(_problem("self-blocked", "ticket cannot block itself", ticket=ticket_id))
        normalised_sites[ticket_id] = _normalise_sites(raw, problems)

    counts = {partition_id: 0 for partition_id in partitions}
    for raw in tickets.values():
        partition_id = raw.get("partition")
        if partition_id in counts:
            counts[partition_id] += 1
    for partition_id, partition in partitions.items():
        if counts[partition_id] != partition["quota"]:
            problems.append(_problem("quota-mismatch", "partition ticket count must equal quota",
                                     partition=partition_id, quota=partition["quota"],
                                     ticket_count=counts[partition_id]))

    owners = _reserved_ticket_ids(existing_reservations)
    for ticket_id in tickets:
        owner = owners.get(ticket_id)
        if owner is not None and owner.get("campaign_id") != request.get("campaign_id"):
            problems.append(_problem("ticket-already-reserved", "ticket belongs to another campaign",
                                     ticket=ticket_id, owner=owner.get("campaign_id")))

    ticket_list = list(tickets.values())
    for index, first in enumerate(ticket_list):
        for second in ticket_list[index + 1:]:
            if _overlap_is_declared(first, second):
                continue
            for first_site in normalised_sites.get(first["id"], []):
                for second_site in normalised_sites.get(second["id"], []):
                    if _site_pair_conflicts(first_site, second_site):
                        problems.append(_problem(
                            "write-site-collision",
                            "tickets share an unsafe structured write site",
                            tickets=[first["id"], second["id"]],
                            site=first_site["path"],
                        ))
    return problems


def canonical_manifest(request: dict[str, Any]) -> dict[str, Any]:
    """Return a detached, JSON-stable manifest copy for atomic persistence."""
    manifest = copy.deepcopy(request)
    manifest["schema"] = SCHEMA
    manifest["partitions"] = sorted(manifest.get("partitions") or [], key=lambda item: item.get("id", ""))
    manifest["tickets"] = sorted(manifest.get("tickets") or [], key=lambda item: item.get("id", ""))
    for item in manifest["tickets"]:
        item["write_sites"] = sorted(item.get("write_sites") or [],
                                      key=lambda site: (site.get("path", ""), site.get("symbol", ""), site.get("mode", "")))
        item["blocked_by"] = sorted(item.get("blocked_by") or [])
    return manifest


def reservation_record(request: dict[str, Any], manifest_path: str, claimed_at: str) -> dict[str, Any]:
    """Project a validated manifest into the mutable registry reservation view."""
    tickets_by_partition: dict[str, list[str]] = {p["id"]: [] for p in request["partitions"]}
    for item in request["tickets"]:
        tickets_by_partition[item["partition"]].append(item["id"])
    partitions = {
        partition["id"]: {
            "quota": partition["quota"],
            "ticket_ids": sorted(tickets_by_partition[partition["id"]]),
            "claimed": {},
        }
        for partition in request["partitions"]
    }
    ticket_ids = sorted(ticket_id for ids in tickets_by_partition.values() for ticket_id in ids)
    return {
        "schema": RESERVATION_SCHEMA,
        "campaign_id": request["campaign_id"],
        "coordinator": request["coordinator"],
        "base": request["base"],
        "manifest_path": manifest_path,
        "claimed_at": claimed_at,
        "ticket_ids": ticket_ids,
        "partitions": partitions,
    }


def reservation_summary(reservation: dict[str, Any]) -> dict[str, Any]:
    partitions: dict[str, dict[str, Any]] = {}
    for partition_id, raw in (reservation.get("partitions") or {}).items():
        ticket_ids = list(raw.get("ticket_ids") or [])
        claimed = raw.get("claimed") or {}
        partitions[partition_id] = {
            "quota": raw.get("quota"),
            "used": len(claimed),
            "remaining": len(ticket_ids) - len(claimed),
            "ticket_ids": ticket_ids,
        }
    return {
        "campaign_id": reservation.get("campaign_id"),
        "coordinator": reservation.get("coordinator"),
        "base": reservation.get("base"),
        "manifest_path": reservation.get("manifest_path"),
        "partitions": partitions,
        "ticket_ids": list(reservation.get("ticket_ids") or []),
    }


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def campaign_manifest_path(state_path: Path, campaign_id: str) -> Path:
    if not isinstance(campaign_id, str) or not _ID_RE.fullmatch(campaign_id):
        raise ValueError("invalid campaign id")
    return state_path.resolve().parent / "worktree_campaigns" / f"{campaign_id}.json"

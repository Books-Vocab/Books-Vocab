"""Pure validation and projection for campaign-scoped worktree reservations.

This module deliberately knows nothing about the backlog store, git, or the
registry ledger.  Callers provide the current base and the already-read backlog
entries, then persist the validated result under the registry's canonical lock.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "kg.worktree.campaign.v1"
RESERVATION_SCHEMA = "kg.worktree.campaign-reservation.v1"
CHILD_RECEIPT_SCHEMA = "kg.worktree.child-receipt.v1"
PARENT_RESERVATION_SCHEMA = "kg.worktree.parent-reservation.v1"
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


def _reservation_ticket_details(
    reservation: dict[str, Any],
) -> dict[str, dict[str, Any]] | None:
    """Return structured sites for an existing reservation, or None if unknown."""
    raw = reservation.get("ticket_details")
    if not isinstance(raw, dict):
        return None if reservation.get("ticket_ids") else {}
    details: dict[str, dict[str, Any]] = {}
    for ticket_id, detail in raw.items():
        if isinstance(ticket_id, str) and isinstance(detail, dict):
            details[ticket_id] = detail
    return details


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

    # A reservation from another campaign is a write-site owner, not just a set
    # of ticket ids.  Legacy/ordinary active records without structured sites are
    # deliberately unknown and therefore block a new campaign: free-text
    # fix_site cannot prove disjointness.
    requested_tickets = list(tickets.values())
    for reservation in existing_reservations:
        if not isinstance(reservation, dict):
            continue
        if reservation.get("campaign_id") == request.get("campaign_id"):
            continue
        existing_details = _reservation_ticket_details(reservation)
        if existing_details is None:
            if reservation.get("ticket_ids"):
                problems.append(_problem(
                    "existing-sites-unknown",
                    "existing reservation has no structured write sites",
                    owner=reservation.get("campaign_id"),
                ))
            continue
        for existing_id, existing_ticket in existing_details.items():
            existing_ticket = {"id": existing_id, **existing_ticket}
            existing_sites = _normalise_sites(existing_ticket, problems)
            for requested in requested_tickets:
                if _overlap_is_declared(existing_ticket, requested):
                    continue
                for existing_site in existing_sites:
                    for requested_site in normalised_sites.get(requested["id"], []):
                        if _site_pair_conflicts(existing_site, requested_site):
                            problems.append(_problem(
                                "write-site-collision",
                                "ticket collides with an existing reservation write site",
                                tickets=[existing_id, requested["id"]],
                                owner=reservation.get("campaign_id"),
                                site=existing_site["path"],
                            ))

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
    ticket_details = {
        item["id"]: {
            "id": item["id"],
            "partition": item["partition"],
            "write_sites": copy.deepcopy(item.get("write_sites") or []),
            "blocked_by": sorted(item.get("blocked_by") or []),
            "co_land_group": item.get("co_land_group"),
        }
        for item in request["tickets"]
    }
    manifest_digest = hashlib.sha256(json_bytes(canonical_manifest(request))).hexdigest()
    return {
        "schema": RESERVATION_SCHEMA,
        "campaign_id": request["campaign_id"],
        "coordinator": request["coordinator"],
        "base": request["base"],
        "manifest_path": manifest_path,
        "manifest_digest": manifest_digest,
        "claimed_at": claimed_at,
        "ticket_ids": ticket_ids,
        "ticket_details": ticket_details,
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
        "tickets": copy.deepcopy(reservation.get("ticket_details") or {}),
    }


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def campaign_manifest_path(state_path: Path, campaign_id: str) -> Path:
    if not isinstance(campaign_id, str) or not _ID_RE.fullmatch(campaign_id):
        raise ValueError("invalid campaign id")
    return state_path.resolve().parent / "worktree_campaigns" / f"{campaign_id}.json"


# ---------------------------------------------------------------------------
# Parent integration contract
# ---------------------------------------------------------------------------

GREEN_OUTCOME_STATUSES = frozenset({
    "green", "pass", "passed", "ok", "confirmed-fixed", "confirmed_fixed",
})
INTEGRABLE_OUTCOMES = frozenset({"changed", "no-op-existing-fix"})


def _parent_problem(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "message": message, **extra}


def _parent_ticket_ids(reservation: dict[str, Any], partition_id: str) -> list[str]:
    raw = (reservation.get("partitions") or {}).get(partition_id) or {}
    return sorted(str(ticket_id) for ticket_id in (raw.get("ticket_ids") or []))


def _parent_child_outcomes(receipt: dict[str, Any], expected: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the typed closure summary carried by one immutable child receipt."""
    problems: list[dict[str, Any]] = []
    outcomes = receipt.get("outcomes")
    if not isinstance(outcomes, list):
        return [_parent_problem("outcome-seal-missing", "child receipt has no typed outcomes")], []
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for item in outcomes:
        if not isinstance(item, dict):
            problems.append(_parent_problem("outcome-invalid", "child outcome must be an object"))
            continue
        ticket_id = item.get("ticket_id")
        outcome = item.get("outcome")
        acceptance = str(item.get("acceptance_status") or "").strip().lower().replace(" ", "-")
        closure = str(item.get("closure") or "").strip().lower()
        if not isinstance(ticket_id, str) or not ticket_id:
            problems.append(_parent_problem("outcome-ticket-missing", "child outcome has no ticket id"))
            continue
        if ticket_id in seen:
            problems.append(_parent_problem("duplicate-ticket", "ticket appears in more than one child outcome", ticket=ticket_id))
        seen.add(ticket_id)
        if outcome not in INTEGRABLE_OUTCOMES:
            problems.append(_parent_problem("outcome-not-integrable", "child outcome is not integrable", ticket=ticket_id, outcome=outcome))
        if acceptance not in GREEN_OUTCOME_STATUSES:
            problems.append(_parent_problem("acceptance-not-green", "child acceptance is not green", ticket=ticket_id, acceptance_status=acceptance))
        if closure not in {"fixed", "accepted", "closed"}:
            problems.append(_parent_problem("closure-missing", "child outcome has no fixed/accepted closure", ticket=ticket_id))
        normalised.append({
            "ticket_id": ticket_id,
            "outcome": outcome,
            "acceptance_status": acceptance,
            "closure": closure,
        })
    if seen != expected:
        problems.append(_parent_problem(
            "ticket-count-mismatch", "child outcome tickets do not equal its partition",
            expected=sorted(expected), actual=sorted(seen),
        ))
    return problems, sorted(normalised, key=lambda item: item["ticket_id"])


def _parent_handback_seal_problems(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Check the registry seal shape without importing the registry module."""
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        return [_parent_problem("outcome-seal-missing", "child has no hand-back seal",
                                branch=record.get("branch"))]
    digest = seal.get("digest")
    body = {key: value for key, value in seal.items() if key != "digest"}
    problems: list[dict[str, Any]] = []
    if not isinstance(digest, str) or digest != hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest():
        problems.append(_parent_problem("outcome-seal-invalid", "hand-back seal digest is invalid",
                                       branch=record.get("branch")))
    if body.get("schema") != "kg.worktree.handback.v1":
        problems.append(_parent_problem("outcome-seal-invalid", "hand-back seal schema is invalid",
                                       branch=record.get("branch")))
    if body.get("tip_sha") != record.get("handed_back_sha"):
        problems.append(_parent_problem("outcome-seal-tip-mismatch", "seal tip differs from registry tip",
                                       branch=record.get("branch")))
    if body.get("base_sha") != record.get("base_sha"):
        problems.append(_parent_problem("outcome-seal-base-mismatch", "seal base differs from registry base",
                                       branch=record.get("branch")))
    identity = body.get("record")
    expected_identity = {
        "branch": record.get("branch"),
        # Registry seals use its canonical realpath form.  Reproduce that
        # normalization here without importing the mutable registry module so
        # parent preflight remains pure and cross-module stable (notably /tmp
        # is a symlink on macOS).
        "path": os.path.realpath(os.path.abspath(str(record.get("path") or ""))),
        "base": record.get("base"),
        "backlog": sorted(record.get("backlog") or []),
        "claimed_at": record.get("claimed_at"),
    }
    if not isinstance(identity, dict) or identity != expected_identity:
        problems.append(_parent_problem("outcome-seal-invalid", "hand-back seal identity is invalid",
                                       branch=record.get("branch")))
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        problems.append(_parent_problem("outcome-seal-missing", "hand-back seal has no outcomes",
                                       branch=record.get("branch")))
    else:
        sealed = sorted(str(item.get("ticket_id")) for item in outcomes
                        if isinstance(item, dict))
        claimed = sorted(str(item) for item in (record.get("backlog") or []))
        if sealed != claimed:
            problems.append(_parent_problem("outcome-seal-ticket-set-mismatch",
                                            "seal outcomes do not cover child tickets",
                                            branch=record.get("branch"), expected=claimed,
                                            actual=sealed))
    receipt = record.get("child_receipt")
    if isinstance(receipt, dict):
        if receipt.get("outcome_seal_digest") != digest:
            problems.append(_parent_problem(
                "outcome-seal-receipt-mismatch",
                "child receipt does not carry the registry hand-back seal digest",
                branch=record.get("branch"),
            ))
        receipt_outcomes = receipt.get("outcomes")
        if not isinstance(outcomes, list) or not isinstance(receipt_outcomes, list):
            problems.append(_parent_problem(
                "outcome-seal-receipt-mismatch",
                "child receipt and hand-back seal do not both carry outcomes",
                branch=record.get("branch"),
            ))
        else:
            def canonical_outcomes(items: list[Any]) -> list[str]:
                return sorted(
                    json.dumps(item, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False)
                    for item in items if isinstance(item, dict)
                )
            if canonical_outcomes(outcomes) != canonical_outcomes(receipt_outcomes):
                problems.append(_parent_problem(
                    "outcome-seal-receipt-mismatch",
                    "child receipt outcomes differ from the immutable hand-back seal",
                    branch=record.get("branch"),
                ))
    return problems


def parent_child_snapshot(
    reservation: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    campaign_id: str,
    base_sha: str,
) -> dict[str, Any]:
    """Build a fail-closed, immutable input snapshot for parent integration.

    This function is pure: it never marks a child or mutates a reservation.  The
    registry wraps it in its ledger lock and persists the returned parent owner only
    when ``ok`` is true.  A parent can therefore refuse before creating a worktree.
    """
    problems: list[dict[str, Any]] = []
    if not isinstance(reservation, dict) or reservation.get("campaign_id") != campaign_id:
        return {"ok": False, "problems": [_parent_problem(
            "foreign-campaign", "campaign reservation does not match parent request",
            campaign=campaign_id,
        )]}
    expected_base = reservation.get("base")
    if expected_base != base_sha:
        problems.append(_parent_problem("stale-base", "campaign base is not the current parent base",
                                        expected=expected_base, actual=base_sha))
    expected_digest = reservation.get("manifest_digest")
    if not isinstance(expected_digest, str) or not expected_digest:
        problems.append(_parent_problem(
            "manifest-digest-missing",
            "campaign reservation has no immutable manifest digest",
        ))

    expected_partitions = sorted(str(partition_id) for partition_id in (reservation.get("partitions") or {}))
    by_partition: dict[str, list[dict[str, Any]]] = {partition_id: [] for partition_id in expected_partitions}
    foreign: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "active":
            continue
        receipt = record.get("child_receipt") if isinstance(record, dict) else None
        if not isinstance(receipt, dict):
            continue
        if receipt.get("role") != "child":
            problems.append(_parent_problem("child-role-invalid", "child receipt role is not child",
                                            branch=record.get("branch")))
            continue
        if receipt.get("campaign_id") != campaign_id:
            foreign.append(record)
            continue
        if record.get("role") != "child":
            problems.append(_parent_problem(
                "child-record-role-mismatch",
                "registry child record does not carry role=child",
                branch=record.get("branch"),
            ))
            continue
        if record.get("campaign_id") != receipt.get("campaign_id"):
            problems.append(_parent_problem(
                "child-record-campaign-mismatch",
                "registry child record campaign differs from its receipt",
                branch=record.get("branch"),
                record_campaign=record.get("campaign_id"),
                receipt_campaign=receipt.get("campaign_id"),
            ))
            continue
        if record.get("partition_id") != receipt.get("partition_id"):
            problems.append(_parent_problem(
                "child-record-partition-mismatch",
                "registry child record partition differs from its receipt",
                branch=record.get("branch"),
                record_partition=record.get("partition_id"),
                receipt_partition=receipt.get("partition_id"),
            ))
            continue
        partition_id = receipt.get("partition_id")
        if partition_id not in by_partition:
            problems.append(_parent_problem("foreign-partition", "child partition is not in campaign",
                                            partition=partition_id, branch=record.get("branch")))
            continue
        by_partition[partition_id].append(record)
    if foreign:
        problems.append(_parent_problem("foreign-campaign", "active child receipt belongs to another campaign",
                                        branches=sorted(str(item.get("branch")) for item in foreign)))

    children: list[dict[str, Any]] = []
    source_refs: dict[str, str] = {}
    ticket_map: dict[str, dict[str, Any]] = {}
    for partition_id in expected_partitions:
        candidates = by_partition[partition_id]
        if not candidates:
            problems.append(_parent_problem("missing-child", "partition has no handed-back child receipt",
                                            partition=partition_id))
            continue
        if len(candidates) > 1:
            problems.append(_parent_problem("duplicate-partition", "partition has more than one child receipt",
                                            partition=partition_id,
                                            branches=sorted(str(item.get("branch")) for item in candidates)))
            continue
        record = candidates[0]
        receipt = record["child_receipt"]
        branch = receipt.get("branch") or record.get("branch")
        tip_sha = record.get("handed_back_sha")
        if not isinstance(branch, str) or not branch:
            problems.append(_parent_problem("child-branch-missing", "child receipt has no branch", partition=partition_id))
            continue
        if record.get("branch") != branch:
            problems.append(_parent_problem("child-branch-mismatch", "receipt branch differs from registry branch",
                                            partition=partition_id, branch=branch, recorded=record.get("branch")))
        if receipt.get("manifest_head_sha") != tip_sha:
            problems.append(_parent_problem("stale-tip", "child manifest head differs from hand-back tip",
                                            partition=partition_id, branch=branch,
                                            manifest_head=receipt.get("manifest_head_sha"), handed_back=tip_sha))
        actual_campaign_digest = receipt.get("campaign_manifest_digest") \
            or receipt.get("manifest_digest")
        if isinstance(expected_digest, str) and actual_campaign_digest != expected_digest:
            problems.append(_parent_problem("manifest-digest-drift", "child manifest digest differs from campaign",
                                            partition=partition_id, expected=expected_digest,
                                            actual=actual_campaign_digest))
        if record.get("base_sha") != expected_base:
            problems.append(_parent_problem("stale-child-base", "child was not based on campaign base",
                                            partition=partition_id, expected=expected_base,
                                            actual=record.get("base_sha")))
        problems.extend({**problem, "partition": partition_id}
                        for problem in _parent_handback_seal_problems(record))
        if not receipt.get("outcome_seal_digest"):
            problems.append(_parent_problem("outcome-seal-missing", "typed child outcome seal is missing",
                                            partition=partition_id, branch=branch))
        source_branches = receipt.get("source_branches")
        if not isinstance(source_branches, list) or not source_branches \
                or any(not isinstance(item, str) or not item for item in source_branches):
            problems.append(_parent_problem("manifest-sources-missing",
                                            "child manifest has no structured source branch list",
                                            partition=partition_id, branch=branch))
        else:
            claimed = ((reservation.get("partitions") or {}).get(partition_id) or {}).get("claimed") or {}
            allowed_sources = {
                claim.get("branch")
                for claim in claimed.values()
                if isinstance(claim, dict) and isinstance(claim.get("branch"), str)
            }
            source_set = set(source_branches)
            if len(source_set) != len(source_branches):
                problems.append(_parent_problem(
                    "manifest-source-duplicate",
                    "child manifest lists a source branch more than once",
                    partition=partition_id, branch=branch,
                ))
            foreign_sources = sorted(source_set - allowed_sources)
            if foreign_sources:
                problems.append(_parent_problem(
                    "manifest-source-foreign",
                    "child manifest source branch is not claimed by its partition",
                    partition=partition_id, branch=branch,
                    sources=foreign_sources,
                    allowed=sorted(allowed_sources),
                ))
        expected_tickets = set(_parent_ticket_ids(reservation, partition_id))
        actual_tickets = set(str(item) for item in (receipt.get("ticket_ids") or []))
        if actual_tickets != expected_tickets:
            problems.append(_parent_problem("ticket-count-mismatch", "child ticket set differs from partition",
                                            partition=partition_id, expected=sorted(expected_tickets), actual=sorted(actual_tickets)))
        outcome_problems, outcomes = _parent_child_outcomes(receipt, expected_tickets)
        problems.extend({**problem, "partition": partition_id} for problem in outcome_problems)
        child_entry = {
            "partition_id": partition_id,
            "branch": branch,
            "child_sha": tip_sha,
            "manifest_digest": receipt.get("manifest_digest"),
            "campaign_manifest_digest": receipt.get("campaign_manifest_digest"),
            "source_branches": sorted(set(source_branches or [])),
            "ticket_ids": sorted(actual_tickets),
            "outcomes": outcomes,
        }
        children.append(child_entry)
        if branch in source_refs:
            problems.append(_parent_problem("duplicate-branch", "more than one partition uses a child branch",
                                            branch=branch))
        else:
            source_refs[branch] = str(tip_sha or "")
        for outcome in outcomes:
            ticket_id = outcome["ticket_id"]
            if ticket_id in ticket_map:
                problems.append(_parent_problem("duplicate-ticket", "ticket appears in multiple child partitions",
                                                ticket=ticket_id))
            else:
                ticket_map[ticket_id] = {
                    "partition_id": partition_id,
                    "source_branch": branch,
                    "child_sha": tip_sha,
                    **outcome,
                }

    source_owner: dict[str, str] = {}
    for child in children:
        for source_branch in child.get("source_branches") or []:
            owner = source_owner.get(source_branch)
            if owner is not None and owner != child["partition_id"]:
                problems.append(_parent_problem(
                    "duplicate-source-branch",
                    "a child manifest source branch belongs to more than one partition",
                    branch=source_branch, partitions=sorted({owner, child["partition_id"]}),
                ))
            else:
                source_owner[source_branch] = child["partition_id"]

    if set(ticket_map) != set(str(ticket_id) for ticket_id in (reservation.get("ticket_ids") or [])):
        problems.append(_parent_problem(
            "campaign-ticket-set-mismatch", "parent child receipts do not cover campaign tickets",
            expected=sorted(str(ticket_id) for ticket_id in (reservation.get("ticket_ids") or [])),
            actual=sorted(ticket_map),
        ))
    return {
        "ok": not problems,
        "campaign_id": campaign_id,
        "base_sha": base_sha,
        "expected_partitions": expected_partitions,
        "children": sorted(children, key=lambda item: item["partition_id"]),
        "source_refs": dict(sorted(source_refs.items())),
        "ticket_map": dict(sorted(ticket_map.items())),
        "problems": problems,
    }

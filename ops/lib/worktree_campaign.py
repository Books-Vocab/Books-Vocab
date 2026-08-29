"""Pure validation and projection for ticketed campaign worktree claims.

The projection is deliberately read-only.  A caller supplies the already-read
active records and campaign reservations; this module only proves whether one
active r3 ticket can be mapped to one immutable, current campaign manifest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = "kg.worktree.campaign.v1"
RESERVATION_SCHEMA = "kg.worktree.campaign-reservation.v1"
VALID_MODES = frozenset({"read", "write"})
_BASE_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _problem(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "message": message, **extra}


def _as_entries(
    entries: Iterable[dict[str, Any]] | dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if isinstance(entries, dict):
        return {
            str(key): value for key, value in entries.items() if isinstance(value, dict)
        }
    return {
        str(entry.get("id")): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }


def _normalise_path(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    path = posixpath.normpath(raw)
    if path in {".", ".."} or path.startswith(("../", "/")):
        return None
    return path


def _normalise_sites(
    ticket: dict[str, Any], problems: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    raw_sites = ticket.get("write_sites")
    if not isinstance(raw_sites, list) or not raw_sites:
        problems.append(
            _problem(
                "missing-write-sites",
                "ticket must declare write_sites",
                ticket=ticket.get("id"),
            )
        )
        return []
    sites: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sites):
        if not isinstance(raw, dict):
            problems.append(
                _problem(
                    "invalid-write-site",
                    "write site must be an object",
                    ticket=ticket.get("id"),
                    index=index,
                )
            )
            continue
        path = _normalise_path(raw.get("path"))
        mode = raw.get("mode")
        symbol = raw.get("symbol")
        if path is None:
            problems.append(
                _problem(
                    "unknown-site-path",
                    "write site path is not a safe repo-relative path",
                    ticket=ticket.get("id"),
                    index=index,
                    path=raw.get("path"),
                )
            )
            continue
        if mode not in VALID_MODES:
            problems.append(
                _problem(
                    "unknown-site-mode",
                    "write site mode must be read or write",
                    ticket=ticket.get("id"),
                    index=index,
                    mode=mode,
                )
            )
            continue
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
            problems.append(
                _problem(
                    "invalid-site-symbol",
                    "site symbol must be a non-empty string",
                    ticket=ticket.get("id"),
                    index=index,
                )
            )
            continue
        site = {"path": path, "mode": mode}
        if symbol is not None:
            site["symbol"] = symbol.strip()
        sites.append(site)
    return sites


def _ticket_details(
    manifest: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, list[dict[str, Any]]]:
    raw_tickets = manifest.get("tickets")
    if not isinstance(raw_tickets, list) or not raw_tickets:
        return None, [
            _problem("existing-manifest-scope-drift", "manifest has no ticket list")
        ]
    details: dict[str, dict[str, Any]] = {}
    problems: list[dict[str, Any]] = []
    for item in raw_tickets:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            problems.append(
                _problem(
                    "existing-manifest-scope-drift", "manifest has an invalid ticket"
                )
            )
            continue
        ticket_id = item["id"]
        if ticket_id in details:
            problems.append(
                _problem(
                    "existing-manifest-scope-drift",
                    "manifest repeats a ticket",
                    ticket=ticket_id,
                )
            )
            continue
        site_problems: list[dict[str, Any]] = []
        sites = _normalise_sites(item, site_problems)
        if site_problems or not isinstance(item.get("partition"), str):
            problems.append(
                _problem(
                    "existing-manifest-scope-drift",
                    "manifest has invalid ticket or write sites",
                    ticket=ticket_id,
                    details=site_problems,
                )
            )
            continue
        details[ticket_id] = {
            "id": ticket_id,
            "partition": item["partition"],
            "write_sites": sites,
            "blocked_by": sorted(item.get("blocked_by") or []),
            "co_land_group": item.get("co_land_group"),
        }
    return details, problems


def _stored_details(reservation: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    raw = reservation.get("ticket_details")
    if not isinstance(raw, dict):
        return None
    if any(
        not isinstance(ticket_id, str) or not isinstance(detail, dict)
        for ticket_id, detail in raw.items()
    ):
        return None
    return raw


def _persisted_reservation_projection(
    reservation: dict[str, Any], *, current_base: str
) -> tuple[dict[str, dict[str, Any]] | None, list[dict[str, Any]]]:
    """Read and verify the immutable manifest before trusting its write sites."""
    owner = reservation.get("campaign_id")
    manifest_path = reservation.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path:
        return None, [
            _problem(
                "existing-manifest-missing", "manifest path is missing", owner=owner
            )
        ]
    try:
        manifest_bytes = Path(manifest_path).read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError, TypeError) as exc:
        return None, [
            _problem(
                "existing-manifest-missing",
                "manifest is missing or unreadable",
                owner=owner,
                manifest_path=manifest_path,
                detail=str(exc),
            )
        ]
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        return None, [
            _problem(
                "existing-manifest-scope-drift",
                "manifest schema is invalid",
                owner=owner,
            )
        ]
    if manifest.get("campaign_id") != owner:
        return None, [
            _problem(
                "existing-manifest-scope-drift",
                "manifest campaign id differs",
                owner=owner,
            )
        ]
    reservation_base = reservation.get("base")
    manifest_base = manifest.get("base")
    if (
        not isinstance(current_base, str)
        or not _BASE_RE.fullmatch(current_base)
        or reservation_base != current_base
        or manifest_base != reservation_base
    ):
        return None, [
            _problem(
                "existing-manifest-base-drift",
                "manifest base is not the current base",
                owner=owner,
                expected=current_base,
                reservation_base=reservation_base,
                manifest_base=manifest_base,
            )
        ]
    expected_digest = reservation.get("manifest_digest")
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if not isinstance(expected_digest, str) or not _DIGEST_RE.fullmatch(
        expected_digest
    ):
        return None, [
            _problem(
                "existing-manifest-digest-drift",
                "manifest digest is missing",
                owner=owner,
            )
        ]
    if actual_digest != expected_digest:
        return None, [
            _problem(
                "existing-manifest-digest-drift",
                "manifest digest differs",
                owner=owner,
                expected=expected_digest,
                actual=actual_digest,
            )
        ]
    details, problems = _ticket_details(manifest)
    if problems or details is None:
        return None, problems
    stored = _stored_details(reservation)
    if stored is None or stored != details:
        return None, [
            _problem(
                "existing-manifest-scope-drift",
                "stored immutable ticket details differ from manifest",
                owner=owner,
            )
        ]
    return details, []


def _record_ticket_id(record: dict[str, Any]) -> str | None:
    ticket_id = record.get("ticket_id")
    ticket_ids = record.get("ticket_ids")
    if ticket_ids is not None:
        if not (
            isinstance(ticket_ids, list)
            and len(ticket_ids) == 1
            and isinstance(ticket_ids[0], str)
            and ticket_ids[0]
        ):
            return None
        if ticket_id is not None and ticket_id != ticket_ids[0]:
            return None
        return ticket_ids[0]
    return ticket_id if isinstance(ticket_id, str) and ticket_id else None


def _project_active_record(
    record: dict[str, Any],
    reservations: Iterable[dict[str, Any]],
    *,
    current_base: str,
) -> tuple[
    dict[str, dict[str, Any]] | None, dict[str, Any] | None, list[dict[str, Any]]
]:
    """Resolve one active r3 ticket to one immutable campaign reservation."""
    if not isinstance(record, dict) or record.get("status") != "active":
        return (
            None,
            None,
            [
                _problem(
                    "existing-active-provenance-unknown",
                    "record is not an active ticket",
                )
            ],
        )
    if "backlog" in record:
        return (
            None,
            None,
            [
                _problem(
                    "existing-active-provenance-unknown",
                    "legacy active record cannot be used as campaign provenance",
                    owner=record.get("campaign_id"),
                )
            ],
        )
    campaign_id = record.get("campaign_id")
    partition_id = record.get("partition_id")
    ticket_id = _record_ticket_id(record)
    branch = record.get("branch")
    digest = record.get("manifest_digest")
    if (
        not isinstance(campaign_id, str)
        or not _ID_RE.fullmatch(campaign_id)
        or not isinstance(partition_id, str)
        or not _ID_RE.fullmatch(partition_id)
        or not isinstance(ticket_id, str)
        or not ticket_id
        or not isinstance(branch, str)
        or not branch
        or not isinstance(digest, str)
        or not _DIGEST_RE.fullmatch(digest)
    ):
        return (
            None,
            None,
            [
                _problem(
                    "existing-active-provenance-unknown",
                    "active record lacks strict campaign, partition, ticket, branch, or digest provenance",
                    owner=campaign_id,
                )
            ],
        )
    candidates = []
    for reservation in reservations:
        if (
            not isinstance(reservation, dict)
            or reservation.get("schema") != RESERVATION_SCHEMA
        ):
            continue
        if reservation.get("campaign_id") != campaign_id:
            continue
        partitions = reservation.get("partitions")
        claimed = (
            partitions.get(partition_id, {}).get("claimed")
            if isinstance(partitions, dict)
            else None
        )
        claim = claimed.get(ticket_id) if isinstance(claimed, dict) else None
        if isinstance(claim, dict) and claim.get("branch") == branch:
            candidates.append(reservation)
    if len(candidates) != 1:
        return (
            None,
            None,
            [
                _problem(
                    "existing-active-provenance-unknown",
                    "active record does not map to one claimed campaign ticket",
                    owner=campaign_id,
                    branch=branch,
                )
            ],
        )
    reservation = candidates[0]
    details, problems = _persisted_reservation_projection(
        reservation, current_base=current_base
    )
    if problems or details is None:
        return None, reservation, problems
    if record.get("base_sha") is not None and record.get("base_sha") != current_base:
        return (
            None,
            reservation,
            [
                _problem(
                    "existing-manifest-base-drift",
                    "active record base differs from current base",
                    owner=campaign_id,
                    expected=current_base,
                    actual=record.get("base_sha"),
                )
            ],
        )
    if record.get("manifest_digest") != reservation.get("manifest_digest"):
        return (
            None,
            reservation,
            [
                _problem(
                    "existing-manifest-digest-drift",
                    "active record digest differs from reservation",
                    owner=campaign_id,
                    expected=reservation.get("manifest_digest"),
                    actual=record.get("manifest_digest"),
                )
            ],
        )
    projected = details.get(ticket_id)
    if projected is None or projected.get("partition") != partition_id:
        return (
            None,
            reservation,
            [
                _problem(
                    "existing-manifest-scope-drift",
                    "active ticket or partition differs from immutable manifest",
                    owner=campaign_id,
                    ticket=ticket_id,
                    partition=partition_id,
                )
            ],
        )
    record_details = record.get("manifest_details") or record.get("ticket_details")
    if record_details is not None and record_details != {ticket_id: projected}:
        return (
            None,
            reservation,
            [
                _problem(
                    "existing-manifest-scope-drift",
                    "active record ticket details differ from immutable manifest",
                    owner=campaign_id,
                    ticket=ticket_id,
                )
            ],
        )
    return {ticket_id: copy.deepcopy(projected)}, reservation, []


def project_active_record(
    record: dict[str, Any],
    reservations: Iterable[dict[str, Any]],
    *,
    current_base: str,
) -> tuple[
    dict[str, dict[str, Any]] | None, dict[str, Any] | None, list[dict[str, Any]]
]:
    """Public read-only entry point for the unique canonical projection."""
    return _project_active_record(record, reservations, current_base=current_base)


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
    return not (
        first.get("symbol")
        and second.get("symbol")
        and first["symbol"] != second["symbol"]
    )


def validate_manifest(
    request: dict[str, Any],
    *,
    current_base: str,
    backlog_entries: Iterable[dict[str, Any]] | dict[str, dict[str, Any]],
    existing_reservations: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return explicit validation problems; empty is the only usable result."""
    problems: list[dict[str, Any]] = []
    if not isinstance(request, dict):
        return [_problem("invalid-request", "campaign request must be an object")]
    if request.get("schema") != SCHEMA:
        problems.append(_problem("invalid-schema", f"schema must be {SCHEMA}"))
    campaign_id = request.get("campaign_id")
    if not isinstance(campaign_id, str) or not _ID_RE.fullmatch(campaign_id):
        problems.append(_problem("invalid-campaign-id", "campaign id is invalid"))
    base = request.get("base")
    if not isinstance(base, str) or not _BASE_RE.fullmatch(base):
        problems.append(_problem("invalid-base", "base must be a full git object id"))
    elif base != current_base:
        problems.append(
            _problem(
                "stale-base",
                "campaign base is not current",
                expected=current_base,
                actual=base,
            )
        )
    raw_partitions = request.get("partitions")
    partitions: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_partitions, list) or not raw_partitions:
        problems.append(
            _problem("missing-partitions", "partitions must be a non-empty list")
        )
    else:
        for item in raw_partitions:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not _ID_RE.fullmatch(item["id"])
            ):
                problems.append(_problem("invalid-partition", "partition is invalid"))
                continue
            if item["id"] in partitions:
                problems.append(
                    _problem(
                        "duplicate-partition",
                        "partition is duplicated",
                        partition=item["id"],
                    )
                )
                continue
            if (
                not isinstance(item.get("quota"), int)
                or isinstance(item.get("quota"), bool)
                or item["quota"] <= 0
            ):
                problems.append(
                    _problem(
                        "invalid-quota",
                        "partition quota must be positive",
                        partition=item["id"],
                    )
                )
                continue
            partitions[item["id"]] = item
    entries = _as_entries(backlog_entries)
    tickets: dict[str, dict[str, Any]] = {}
    normalised_sites: dict[str, list[dict[str, Any]]] = {}
    for item in (
        request.get("tickets") if isinstance(request.get("tickets"), list) else []
    ):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            problems.append(_problem("invalid-ticket", "ticket is invalid"))
            continue
        ticket_id = item["id"]
        if ticket_id in tickets:
            problems.append(
                _problem("duplicate-ticket", "ticket is duplicated", ticket=ticket_id)
            )
            continue
        tickets[ticket_id] = item
        if item.get("partition") not in partitions:
            problems.append(
                _problem(
                    "unknown-partition", "ticket partition is unknown", ticket=ticket_id
                )
            )
        if ticket_id not in entries:
            problems.append(
                _problem(
                    "missing-ticket", "ticket is absent from backlog", ticket=ticket_id
                )
            )
        site_problems: list[dict[str, Any]] = []
        normalised_sites[ticket_id] = _normalise_sites(item, site_problems)
        problems.extend(site_problems)
    if not tickets:
        problems.append(_problem("missing-tickets", "tickets must be a non-empty list"))
    for partition_id, partition in partitions.items():
        count = sum(item.get("partition") == partition_id for item in tickets.values())
        if count != partition["quota"]:
            problems.append(
                _problem(
                    "quota-mismatch",
                    "partition ticket count must equal quota",
                    partition=partition_id,
                )
            )

    existing = [item for item in existing_reservations if isinstance(item, dict)]
    reservations = [
        item for item in existing if item.get("schema") == RESERVATION_SCHEMA
    ]
    projections: list[tuple[dict[str, Any], dict[str, dict[str, Any]]]] = []
    for reservation in reservations:
        details, projection_problems = _persisted_reservation_projection(
            reservation, current_base=current_base
        )
        problems.extend(projection_problems)
        if details is not None and not projection_problems:
            projections.append((reservation, details))
    for record in (item for item in existing if item.get("status") == "active"):
        details, owner, projection_problems = _project_active_record(
            record, reservations, current_base=current_base
        )
        problems.extend(projection_problems)
        if (
            details is not None
            and owner is not None
            and not any(owner is item[0] for item in projections)
        ):
            projections.append((owner, details))

    for reservation, details in projections:
        if reservation.get("campaign_id") == campaign_id:
            continue
        for existing_id, existing_ticket in details.items():
            existing_ticket = {"id": existing_id, **existing_ticket}
            for requested_id, requested_ticket in tickets.items():
                if _overlap_is_declared(existing_ticket, requested_ticket):
                    continue
                for first_site in existing_ticket.get("write_sites", []):
                    for second_site in normalised_sites.get(requested_id, []):
                        if _site_pair_conflicts(first_site, second_site):
                            problems.append(
                                _problem(
                                    "write-site-collision",
                                    "ticket collides with an existing campaign write site",
                                    tickets=[existing_id, requested_id],
                                    owner=reservation.get("campaign_id"),
                                    site=first_site["path"],
                                )
                            )
    return problems


def canonical_manifest(request: dict[str, Any]) -> dict[str, Any]:
    manifest = copy.deepcopy(request)
    manifest["schema"] = SCHEMA
    manifest["partitions"] = sorted(
        manifest.get("partitions") or [], key=lambda item: item.get("id", "")
    )
    manifest["tickets"] = sorted(
        manifest.get("tickets") or [], key=lambda item: item.get("id", "")
    )
    for item in manifest["tickets"]:
        item["write_sites"] = sorted(
            item.get("write_sites") or [],
            key=lambda site: (
                site.get("path", ""),
                site.get("symbol", ""),
                site.get("mode", ""),
            ),
        )
        item["blocked_by"] = sorted(item.get("blocked_by") or [])
    return manifest


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()


def reservation_record(
    request: dict[str, Any], manifest_path: str, claimed_at: str
) -> dict[str, Any]:
    request = canonical_manifest(request)
    ticket_ids = [item["id"] for item in request["tickets"]]
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
    partitions = {
        partition["id"]: {
            "quota": partition["quota"],
            "ticket_ids": sorted(
                item["id"]
                for item in request["tickets"]
                if item["partition"] == partition["id"]
            ),
            "claimed": {},
        }
        for partition in request["partitions"]
    }
    digest = hashlib.sha256(json_bytes(canonical_manifest(request))).hexdigest()
    return {
        "schema": RESERVATION_SCHEMA,
        "campaign_id": request["campaign_id"],
        "coordinator": request.get("coordinator"),
        "base": request["base"],
        "manifest_path": manifest_path,
        "manifest_digest": digest,
        "claimed_at": claimed_at,
        "ticket_ids": sorted(ticket_ids),
        "ticket_details": ticket_details,
        "partitions": partitions,
    }

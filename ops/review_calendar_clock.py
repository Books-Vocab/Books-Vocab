"""Canonical deterministic review-clock projection for UI World data.

The history plan is the only wall-clock input for the marketing review world.
Consumers must derive the same UTC instant, timezone, and anchor day from this
module; no consumer may invent a second frozen date or call the wall clock.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PLAN_PATH = ROOT / "ops" / "demo" / "ui_world_seed" / "history_plan.json"
PLAN_SCHEMA = "kg.history_plan.v1"
HISTORY_PLAN_SOURCE = "history_plan.anchor_day"
LEGACY_SPEC_HISTORY_SOURCE = "legacy.spec.last_reviewed_at"
UTC = timezone.utc


class ReviewClockPlanError(ValueError):
    """Raised when the canonical history plan cannot produce a clock."""


def production_utc_offset_hours(plan: Mapping[str, Any]) -> int:
    """Return the production calendar offset at the plan's anchor day."""
    try:
        anchor = date.fromisoformat(str(plan["anchor_day"]))
        time_zone = ZoneInfo(str(plan["review_clock_time_zone"]))
        instant = datetime.combine(anchor, datetime.min.time(), tzinfo=time_zone)
        offset = instant.utcoffset()
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ReviewClockPlanError(f"history plan production timezone is invalid: {exc}") from exc
    if offset is None or offset.total_seconds() % 3600 != 0:
        raise ReviewClockPlanError("history plan production timezone offset must be a whole hour")
    return int(offset.total_seconds() // 3600)


def validate_render_geometry(plan: Mapping[str, Any]) -> None:
    """Ensure history rendering uses the same timezone/anchor geometry as iOS."""
    offsets = plan.get("render_utc_offset_hours")
    if not isinstance(offsets, list) or not offsets:
        raise ReviewClockPlanError("history plan render_utc_offset_hours must be a non-empty list")
    try:
        normalized = [int(value) for value in offsets]
    except (TypeError, ValueError) as exc:
        raise ReviewClockPlanError(f"history plan render_utc_offset_hours are invalid: {exc}") from exc
    expected = production_utc_offset_hours(plan)
    if normalized != [expected]:
        raise ReviewClockPlanError(
            "history plan render_utc_offset_hours must equal the production "
            f"review timezone offset at anchor: expected={[expected]!r} got={normalized!r}"
        )


def load_history_plan(path: Path = HISTORY_PLAN_PATH) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewClockPlanError(f"history plan is not readable JSON: {path}") from exc
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ReviewClockPlanError(
            f"history plan schema must be {PLAN_SCHEMA!r}: {path}"
        )
    if not isinstance(plan.get("review_clock_time_zone"), str):
        raise ReviewClockPlanError(
            "history plan must declare review_clock_time_zone; implicit timezone is forbidden"
        )
    try:
        ZoneInfo(plan["review_clock_time_zone"])
    except ZoneInfoNotFoundError as exc:
        raise ReviewClockPlanError(
            f"history plan review_clock_time_zone is invalid: {plan['review_clock_time_zone']!r}"
        ) from exc
    validate_render_geometry(plan)
    return plan


def freeze_from_plan(plan: Mapping[str, Any]) -> datetime:
    """Return anchor local-day end under the plan's canonical render offset."""
    validate_render_geometry(plan)
    try:
        anchor = date.fromisoformat(str(plan["anchor_day"]))
        offsets = plan["render_utc_offset_hours"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewClockPlanError(f"history plan anchor/offsets are invalid: {exc}") from exc
    if not isinstance(offsets, list) or not offsets:
        raise ReviewClockPlanError("history plan render_utc_offset_hours must be a non-empty list")
    try:
        max_offset = max(int(value) for value in offsets)
    except (TypeError, ValueError) as exc:
        raise ReviewClockPlanError(f"history plan render_utc_offset_hours are invalid: {exc}") from exc
    return (
        datetime(anchor.year, anchor.month, anchor.day, tzinfo=UTC)
        + timedelta(hours=24 - max_offset)
        - timedelta(seconds=1)
    )


def clock_from_plan(plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project the plan into the exact ``scenarioContext.reviewClock`` shape."""
    plan = plan or load_history_plan()
    frozen = freeze_from_plan(plan)
    anchor = date.fromisoformat(str(plan["anchor_day"]))
    time_zone_identifier = str(plan["review_clock_time_zone"])
    time_zone = ZoneInfo(time_zone_identifier)
    local_anchor = frozen.astimezone(time_zone).date()
    if local_anchor != anchor:
        raise ReviewClockPlanError(
            "history plan review clock timezone does not preserve anchor_day: "
            f"{local_anchor.isoformat()} != {anchor.isoformat()}"
        )
    return {
        "now": frozen.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozenEpoch": int(frozen.timestamp()),
        "anchorDay": anchor.isoformat(),
        "timeZone": time_zone_identifier,
        "source": HISTORY_PLAN_SOURCE,
    }


def legacy_clock_from_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit legacy-only clock projection for callers outside generic emit.

    This path is retained only as a named compatibility contract. Generic
    emitter and canonical marketing artifacts must use :func:`clock_from_plan`.
    """
    latest: datetime | None = None
    for card in spec.get("cards", []):
        review = card.get("review") or {}
        raw = review.get("last_reviewed_at")
        if not isinstance(raw, str) or not raw.strip():
            continue
        normalized = raw.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ReviewClockPlanError(f"spec last_reviewed_at is invalid: {raw!r}") from exc
        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        latest = parsed if latest is None else max(latest, parsed)
    if latest is None:
        raise ReviewClockPlanError(
            "spec review clock requires at least one last_reviewed_at; null/fallback is forbidden"
        )
    frozen = datetime.combine(latest.date(), datetime.max.time().replace(microsecond=0), tzinfo=UTC)
    return {
        "now": frozen.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozenEpoch": int(frozen.timestamp()),
        "anchorDay": latest.date().isoformat(),
        "timeZone": "UTC",
        "source": LEGACY_SPEC_HISTORY_SOURCE,
    }

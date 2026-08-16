"""Shared helpers for the readonly ops CLI."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any


def _cutoff_iso(hours: int = 24) -> str:
    """回傳 N 小時前的 ISO 8601 UTC 時間字串。"""
    t = datetime.now(UTC) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _parse_day(created_at: str | None) -> date | None:
    """嚴格解析 created_at 前 10 字元為 date;空/畸形/非 ISO 日期一律回 None。"""
    if not created_at or len(created_at) < 10:
        return None
    try:
        return datetime.strptime(created_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _bucket_key_from_date(d: date, bucket: str) -> str | None:
    """date → 桶 key:day→YYYY-MM-DD,month→YYYY-MM,week→YYYY-Www(ISO週)。"""
    if bucket == "day":
        return d.isoformat()
    if bucket == "month":
        return d.strftime("%Y-%m")
    if bucket == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return None


def _bucket_key(created_at: str | None, bucket: str) -> str | None:
    """把 ISO created_at 折成桶 key。"""
    d = _parse_day(created_at)
    return _bucket_key_from_date(d, bucket) if d is not None else None


def _enumerate_buckets(start: date, end: date, bucket: str) -> list[str]:
    """列出 [start, end] 內每日所屬桶 key(去重、時序升冪)。"""
    keys: list[str] = []
    seen: set[str] = set()
    d = start
    while d <= end:
        k = _bucket_key_from_date(d, bucket)
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
        d += timedelta(days=1)
    return keys


def _ops_passthrough_normalize(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """users.json identity normalize。"""
    return users, False


def _flatten_user_config(config: dict[str, Any]) -> dict[str, Any]:
    """攤平 users.json 的 config blob 成機讀 dict。"""
    translation = config.get("translation")
    if not isinstance(translation, dict):
        translation = {}
    clock = config.get("review_clock")
    if not isinstance(clock, dict):
        clock = {}
    mode = config.get("review_mode")
    if not isinstance(mode, dict):
        mode = {}
    vocab_ui = config.get("vocab_ui")
    if not isinstance(vocab_ui, dict):
        vocab_ui = {}
    auto_link = config.get("auto_link")
    if not isinstance(auto_link, dict):
        auto_link = {}
    return {
        "translation": {
            "source_lang": translation.get("source_lang", "en"),
            "target_lang": translation.get("target_lang", "zh-Hant"),
        },
        "review_clock": {
            "is_paused": bool(clock.get("is_paused", False)),
            "paused_at": clock.get("paused_at"),
            "updated_at": clock.get("updated_at"),
        },
        "review_mode": {
            "mode": mode.get("mode", "relaxed"),
            "custom_initial_interval_hours": mode.get("custom_initial_interval_hours", 12),
            "custom_remembered_multiplier": mode.get("custom_remembered_multiplier", 1.9),
            "custom_forgot_multiplier": mode.get("custom_forgot_multiplier", 0.45),
            "custom_minimum_interval_hours": mode.get("custom_minimum_interval_hours", 6),
            "custom_maximum_interval_hours": mode.get("custom_maximum_interval_hours", 1440),
            "updated_at": mode.get("updated_at"),
        },
        "vocab_ui": {
            "active_notebook_id": vocab_ui.get("active_notebook_id", "default"),
            "updated_at": vocab_ui.get("updated_at"),
        },
        "auto_link": {
            "enabled": bool(auto_link.get("enabled", True)),
            "updated_at": auto_link.get("updated_at"),
        },
    }

#!/usr/bin/env python3
"""ops_cli.py — container 內部署的查詢工具。

直接讀 SQLite，不依賴 app 運行狀態。計價走 kg.quota_service.token_cost_usd
（provider-aware，單一真相）；容器內 PYTHONPATH=/app/src 使 import kg.* 可用。
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from kg.admin_cost_summary import (
    VALID_RANGES,
    fold_user_summary,
    query_cost_rows,
    since_iso,
)
from kg.error_signals import JUDGE_AUTO_REJECT_WHERE, PIPELINE_FAILURE_WHERE
from kg.ops_edit_shared import users_file
from kg.ops_shared import (
    assert_readonly_sql,
    connect_ro,
    data_dir,
    emit_json,
    print_table,
    provider_column_expr,
    resolve_uid,
    table_columns,
)
from kg.ops_world_diff import diff_world_state, load_expectation
from kg.ops_world_projection import SCHEMA as WORLD_STATE_SCHEMA
from kg.ops_world_projection import project_user_world
from kg.quota_service import token_cost_usd
from kg.user_store import load_users_from


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
    """把 ISO created_at 折成桶 key。三粒度共用 _parse_day 單一解析路徑 —— 規避 tz/微秒
    變異,且畸形時間戳在 day/month/week 一致回 None(此前 day/month 盲切 [:10]/[:7] 會回
    垃圾桶,僅 week 被 drop)。"""
    d = _parse_day(created_at)
    return _bucket_key_from_date(d, bucket) if d is not None else None


def _enumerate_buckets(start: date, end: date, bucket: str) -> list[str]:
    """列出 [start, end] 內每日所屬桶 key(去重、時序升冪)。供 --fill-zero 補空桶用。

    逐日掃描再對映桶 key,單一邏輯同時涵蓋 day/week/month(範圍至多一年量級,成本可忽略)。
    """
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


# ── 子指令實作 ──────────────────────────────────────────


def cmd_user_quota(args: argparse.Namespace) -> None:
    """24h 額度 + 逐時明細。"""
    uid = resolve_uid(args.uid, data_dir())
    cutoff = _cutoff_iso(24)
    pro_limit = float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30"))
    free_limit = float(os.getenv("FREE_DAILY_LIMIT_USD", "0.03"))

    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        if args.json:
            emit_json({"user_id": uid, "used_usd": 0.0, "pro_limit_usd": pro_limit,
                       "free_limit_usd": free_limit, "hourly": []})
            return
        print(f"token_usage.db not found at {db_path}")
        print(f"User: {uid}  |  Used: $0.000000  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
        return

    conn = connect_ro(db_path)
    provider_col = provider_column_expr(conn)
    rows = conn.execute(
        f"SELECT call_type, input_tokens, output_tokens, created_at, {provider_col} AS provider "
        "FROM token_usage WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
        (uid, cutoff),
    ).fetchall()
    conn.close()

    total = sum(token_cost_usd(r[0], r[1], r[2], provider=r[4]) for r in rows)

    # 逐時彙整
    hourly: dict[str, float] = {}
    for call_type, inp, out, ts, provider in rows:
        hour = ts[:13]  # YYYY-MM-DDTHH
        hourly[hour] = hourly.get(hour, 0.0) + token_cost_usd(call_type, inp, out, provider=provider)

    if args.json:
        emit_json({
            "user_id": uid,
            "used_usd": round(total, 6),
            "pro_limit_usd": pro_limit,
            "free_limit_usd": free_limit,
            "hourly": [{"hour": h, "cost_usd": round(v, 6)} for h, v in sorted(hourly.items())],
        })
        return

    print(f"User: {uid}")
    print(f"24h used: ${total:.6f}  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
    print()

    if not rows:
        print("(no usage in last 24h)")
        return

    print_table(
        ["Hour", "Cost (USD)"],
        [[h, f"${v:.6f}"] for h, v in sorted(hourly.items())],
    )


def cmd_user_stats(args: argparse.Namespace) -> None:
    """單字庫統計。"""
    uid = resolve_uid(args.uid, data_dir())
    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = connect_ro(db_path)
    total = conn.execute("SELECT count(*) FROM card").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM card WHERE is_deleted = 0").fetchone()[0]
    deleted = conn.execute("SELECT count(*) FROM card WHERE is_deleted = 1").fetchone()[0]
    recent = conn.execute(
        "SELECT id, content, updated_at FROM card WHERE is_deleted = 0 ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    conn.close()

    if args.json:
        emit_json({
            "user_id": uid,
            "total": total,
            "active": active,
            "deleted": deleted,
            "recent": [{"id": r[0], "content": r[1], "updated_at": r[2]} for r in recent],
        })
        return

    print(f"User: {uid}")
    print_table(
        ["Metric", "Value"],
        [
            ["Total cards", str(total)],
            ["Active", str(active)],
            ["Deleted", str(deleted)],
        ],
    )
    print()
    if recent:
        print("Recent activity:")
        print_table(["ID", "Content", "Updated"], [[r[0], r[1] or "", r[2] or ""] for r in recent])


def _ops_passthrough_normalize(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """users.json identity normalize（鏡像 ops_edit._passthrough_normalize）：原樣讀，
    不碰 subscription/secret 加密 wiring（那是 app 啟動期的事）。ops_cli 唯讀，永遠只
    load 不 save，故不需 app 的 normalize_users_payload。"""
    return users, False


def _flatten_user_config(config: dict[str, Any]) -> dict[str, Any]:
    """攤平 users.json 的 config blob 成機讀 dict，對齊後端
    `user_handlers._build_user_config_response` 的 group/default 形狀（唯讀重實作，
    不 import FastAPI/Pydantic —— 與 ops_cli connect_ro 唯讀紀律一致）。髒資料
    （某 group 非 dict）退回該 group 預設，不爆。"""
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
    }


def cmd_user_config(args: argparse.Namespace) -> None:
    """單用戶 user config 唯讀檢視（translation / review_clock / review_mode / vocab_ui）。

    config 真相在 users.json 的 `users[uid]["config"]`（非 SQLite，故不走 connect_ro）。
    純 stdlib + user_store 唯讀載入（只 load 不 save），對齊後端 group/default 形狀但不
    耦合 FastAPI/Pydantic。vocab_ui = 全域 active notebook 游標（跨 iOS/chrome/web LWW）。
    """
    dd = data_dir()
    uid = resolve_uid(args.uid, dd)
    users = load_users_from(users_file(dd), _ops_passthrough_normalize)
    record = users.get(uid)
    if record is None:
        print(f"Error: user {uid} not found in users.json", file=sys.stderr)
        sys.exit(1)
    config = record.get("config")
    if not isinstance(config, dict):
        config = {}
    flat = _flatten_user_config(config)

    if args.json:
        emit_json({"user_id": uid, "config": flat})
        return

    tr, rc, rm, vu = flat["translation"], flat["review_clock"], flat["review_mode"], flat["vocab_ui"]
    print(f"User: {uid}")
    print_table(
        ["Group", "Field", "Value"],
        [
            ["translation", "source_lang", str(tr["source_lang"])],
            ["translation", "target_lang", str(tr["target_lang"])],
            ["review_clock", "is_paused", str(rc["is_paused"])],
            ["review_clock", "paused_at", str(rc["paused_at"])],
            ["review_clock", "updated_at", str(rc["updated_at"])],
            ["review_mode", "mode", str(rm["mode"])],
            ["review_mode", "custom_initial_interval_hours", str(rm["custom_initial_interval_hours"])],
            ["review_mode", "custom_remembered_multiplier", str(rm["custom_remembered_multiplier"])],
            ["review_mode", "custom_forgot_multiplier", str(rm["custom_forgot_multiplier"])],
            ["review_mode", "custom_minimum_interval_hours", str(rm["custom_minimum_interval_hours"])],
            ["review_mode", "custom_maximum_interval_hours", str(rm["custom_maximum_interval_hours"])],
            ["review_mode", "updated_at", str(rm["updated_at"])],
            ["vocab_ui", "active_notebook_id", str(vu["active_notebook_id"])],
            ["vocab_ui", "updated_at", str(vu["updated_at"])],
        ],
    )


def cmd_world_state(args: argparse.Namespace) -> None:
    """單用戶 world-state 投影（供 scenario diff / verify 讀 actual state）。"""
    dd = data_dir()
    uid = resolve_uid(args.uid, dd)
    payload = project_user_world(uid, data_root=dd)
    if args.json:
        emit_json(payload)
        return
    print(f"schema: {WORLD_STATE_SCHEMA}")
    print(f"user: {uid}")
    print(
        f"cards={len(payload['cards'])} notebooks={len(payload['notebooks'])} "
        f"graphs={len(payload['graphs'])}"
    )


def cmd_world_diff(args: argparse.Namespace) -> None:
    """用 declarative expectation spec 比對單用戶 world-state。"""
    dd = data_dir()
    uid = resolve_uid(args.uid, dd)
    actual = project_user_world(uid, data_root=dd)
    expected = load_expectation(args.spec)
    payload = diff_world_state(actual, expected)
    payload["user_id"] = uid
    payload["specPath"] = str(args.spec)
    if args.json:
        emit_json(payload)
        return
    verdict = "ok" if payload["ok"] else "mismatch"
    print(f"world-diff: {verdict}")
    print(f"user: {uid}")
    print(f"mismatches: {payload['mismatchCount']}")
    for mismatch in payload["mismatches"][:10]:
        print(f"- {mismatch['path']}: {mismatch['kind']}")


def cmd_quota_overview(args: argparse.Namespace) -> None:
    """全用戶 24h 額度總覽。"""
    cutoff = _cutoff_iso(24)
    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        if args.json:
            emit_json({"count": 0, "users": []})
            return
        print("(no token_usage.db found)")
        return

    conn = connect_ro(db_path)
    provider_col = provider_column_expr(conn)
    rows = conn.execute(
        f"SELECT user_id, call_type, input_tokens, output_tokens, {provider_col} AS provider "
        "FROM token_usage WHERE created_at >= ?",
        (cutoff,),
    ).fetchall()
    conn.close()

    user_costs: dict[str, float] = {}
    user_calls: dict[str, int] = {}
    for uid, call_type, inp, out, provider in rows:
        user_costs[uid] = user_costs.get(uid, 0.0) + token_cost_usd(call_type, inp, out, provider=provider)
        user_calls[uid] = user_calls.get(uid, 0) + 1

    ranked = sorted(
        ({"user_id": uid, "cost_usd": round(cost, 6), "calls": user_calls[uid]}
         for uid, cost in user_costs.items()),
        key=lambda u: u["cost_usd"],
        reverse=True,
    )

    if args.json:
        emit_json({"count": len(ranked), "users": ranked})
        return

    if not user_costs:
        print("(no usage in last 24h)")
        return

    print_table(
        ["User", "Cost (USD)", "Calls"],
        [[u["user_id"], f"${u['cost_usd']:.6f}", str(u["calls"])] for u in ranked],
    )


def cmd_active_users(args: argparse.Namespace) -> None:
    """近 N 小時活躍用戶。"""
    hours = args.hours
    cutoff = _cutoff_iso(hours)
    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        if args.json:
            emit_json({"hours": hours, "count": 0, "users": []})
            return
        print("(no token_usage.db found)")
        return

    conn = connect_ro(db_path)
    rows = conn.execute(
        "SELECT user_id, count(*) as calls, max(created_at) as last_active "
        "FROM token_usage WHERE created_at >= ? GROUP BY user_id ORDER BY last_active DESC",
        (cutoff,),
    ).fetchall()
    conn.close()

    if args.json:
        emit_json({
            "hours": hours,
            "count": len(rows),
            "users": [{"user_id": r[0], "calls": r[1], "last_active": r[2]} for r in rows],
        })
        return

    if not rows:
        print(f"(no active users in last {hours}h)")
        return

    print_table(
        ["User", "Calls", "Last Active"],
        [[r[0], str(r[1]), r[2]] for r in rows],
    )


def cmd_card_find(args: argparse.Namespace) -> None:
    """byte-exact 子字串搜尋 card.content（免寫 SQL、case-insensitive）。

    content 以 repr() 渲染——對齊表格會吃掉 trailing comma / 空白，repr 讓其無所遁形
    （例:`chateau,` vs `chateau` 一眼可辨）。substring 以參數綁定傳入並轉義 LIKE 萬用字元
    （`%` `_` `\\`），故搜尋字串中的這些字元一律當字面處理。比對為 ASCII case-insensitive
    （COLLATE NOCASE 不折疊重音字母,如 café≠CAFÉ）。
    """
    uid = resolve_uid(args.uid, data_dir())
    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    # 轉義 LIKE 特殊字元,使 substring 純當字面比對
    escaped = args.substring.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn = connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT id, content, is_deleted FROM card "
            "WHERE content LIKE ? ESCAPE '\\' COLLATE NOCASE ORDER BY rowid",
            (f"%{escaped}%",),
        ).fetchall()
    finally:
        conn.close()

    if args.json:
        emit_json({
            "user_id": uid,
            "substring": args.substring,
            "count": len(rows),
            "matches": [{"id": r[0], "content": r[1], "is_deleted": r[2]} for r in rows],
        })
        return

    print_table(
        ["id", "content (repr)", "is_deleted"],
        [[r[0], repr(r[1]), r[2]] for r in rows],
    )


def cmd_card_get(args: argparse.Namespace) -> None:
    """單張卡片 byte-exact 完整 dump（垂直 key→value，repr 渲染）。

    key 可為 card id 或精確 content（ASCII case-insensitive）。寬表 SELECT * 橫向難讀,
    本工具改垂直排版,每欄一行,值一律 repr——trailing comma / 空白 / 換行皆可見。
    """
    uid = resolve_uid(args.uid, data_dir())
    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = connect_ro(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM card WHERE id = ? OR content = ? COLLATE NOCASE ORDER BY rowid",
            (args.key, args.key),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        conn.close()

    if args.json:
        emit_json({
            "user_id": uid,
            "key": args.key,
            "count": len(rows),
            "cards": [dict(zip(cols, row, strict=True)) for row in rows],
        })
        return

    if not rows:
        print(f"(no card matching {args.key!r})")
        return

    width = max(len(c) for c in cols)
    for i, row in enumerate(rows):
        if i:
            print("\n" + "─" * 40)
        for col, val in zip(cols, row, strict=True):
            print(f"{col:<{width}}  {val!r}")


def cmd_db_query(args: argparse.Namespace) -> None:
    """對用戶 cards.db 跑任意 SQL。"""
    uid = resolve_uid(args.uid, data_dir())
    # REMAINDER 會把 --json / --schema 連同 SQL 一起吃進來；先剝離旗標
    # （故兩者置於 SQL 前後皆可）。
    raw = list(args.sql)
    json_mode = args.json or "--json" in raw
    schema_mode = "--schema" in raw
    tokens = [t for t in raw if t not in ("--json", "--schema")]
    sql = " ".join(tokens)  # REMAINDER captures split words; rejoin

    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = connect_ro(db_path)
    try:
        # --schema：免寫 SQL 列出各表 DDL（dogfooding：省去盲猜欄位名）。
        if schema_mode:
            tables = conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            if json_mode:
                emit_json({"tables": [{"name": t[0], "sql": t[1]} for t in tables]})
            else:
                for name, ddl in tables:
                    print(f"-- {name}\n{ddl}\n")
            return

        try:
            assert_readonly_sql(sql)
        except ValueError as e:
            print(f"拒絕執行:{e}", file=sys.stderr)
            sys.exit(1)

        cursor = conn.execute(sql)
        headers = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall() if cursor.description else []
        if json_mode:
            emit_json({"sql": sql, "columns": headers,
                       "count": len(rows), "rows": [list(r) for r in rows]})
        elif cursor.description:
            print_table(headers, [list(r) for r in rows])
        else:
            print(f"OK (rows affected: {cursor.rowcount})")
    except sqlite3.Error as e:
        if json_mode:
            emit_json({"sql": sql, "error": str(e)})
            sys.exit(1)
        print(f"SQL error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def cmd_cost(args: argparse.Namespace) -> None:
    """單用戶 cost-by-call_type 拆解（唯讀）。

    查/定價/折疊走 `kg.admin_cost_summary` 共用核心(與 admin 同一語意),
    本命令只 connect_ro + 投影 by_call_type/totals。DB 不存在回全零 summary。
    """
    uid = resolve_uid(args.uid, data_dir())
    range_ = args.range
    since = since_iso(range_)
    db_path = data_dir() / "token_usage.db"

    summary: dict = {
        "user_id": uid,
        "range": range_,
        "since": since,
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "by_call_type": {},
    }

    if db_path.exists():
        # ops 面只負責「怎麼連」(connect_ro 唯讀);查/折交給共用核心,
        # 與 admin 路徑共用同一語意。CLI 只投影 by_call_type + totals。
        conn = connect_ro(db_path)
        folded = fold_user_summary(query_cost_rows(conn, user_id=uid, since=since))
        conn.close()
        summary["total_calls"] = folded["total_calls"]
        summary["total_input_tokens"] = folded["total_input_tokens"]
        summary["total_output_tokens"] = folded["total_output_tokens"]
        summary["total_cost_usd"] = folded["total_cost_usd"]
        summary["by_call_type"] = folded["by_call_type"]

    if args.json:
        emit_json(summary)
        return

    window = f"since {since}" if since else "all-time"
    print(f"User: {uid}  |  Range: {range_} ({window})")
    print(f"Total: ${summary['total_cost_usd']:.6f}  |  {summary['total_calls']} calls")
    print()
    table_rows = sorted(
        [
            [ct, str(b["calls"]), str(b["input_tokens"]), str(b["output_tokens"]),
             f"${b['cost_usd']:.6f}"]
            for ct, b in summary["by_call_type"].items()
        ],
        key=lambda r: float(r[4].replace("$", "")),
        reverse=True,
    )
    print_table(["Call Type", "Calls", "In Tokens", "Out Tokens", "Cost (USD)"], table_rows)


def cmd_cost_overview(args: argparse.Namespace) -> None:
    """全用戶 cost 排名（唯讀）。"""
    range_ = args.range
    since = since_iso(range_)
    db_path = data_dir() / "token_usage.db"

    result: dict = {"range": range_, "since": since, "users": []}

    if db_path.exists():
        # 跨用戶 cost:共用核心查全表(user_id=None),CLI 端按 uid 分組折疊
        # totals —— 定價/欄相容語意與 admin 共用,不重寫。
        conn = connect_ro(db_path)
        rows = query_cost_rows(conn, user_id=None, since=since)
        conn.close()

        by_uid: dict[str, list] = {}
        for row in rows:
            by_uid.setdefault(row[0], []).append(row)
        per_user: dict[str, dict] = {}
        for user_id, urows in by_uid.items():
            f = fold_user_summary(urows)
            per_user[user_id] = {
                "total_calls": f["total_calls"],
                "total_cost_usd": f["total_cost_usd"],
            }

        result["users"] = sorted(
            (
                {"user_id": uid, "total_calls": u["total_calls"],
                 "total_cost_usd": u["total_cost_usd"]}  # fold_user_summary 已 round 6dp
                for uid, u in per_user.items()
            ),
            key=lambda u: u["total_cost_usd"],
            reverse=True,
        )

    if args.json:
        result["count"] = len(result["users"])
        emit_json(result)
        return

    window = f"since {since}" if since else "all-time"
    print(f"Range: {range_} ({window})")
    print()
    print_table(
        ["User", "Calls", "Cost (USD)"],
        [[u["user_id"], str(u["total_calls"]), f"${u['total_cost_usd']:.6f}"]
         for u in result["users"]],
    )


def cmd_analyze(args: argparse.Namespace) -> None:
    """委派給 ops_analyze.py。"""
    import subprocess
    script = Path(__file__).resolve().parent / "ops_analyze.py"
    cmd = [sys.executable, str(script), args.uid, args.level]
    sys.exit(subprocess.call(cmd))


def cmd_sync_trace(args: argparse.Namespace) -> None:
    """用戶 sync 完整時間線 — 合併 cards + token_usage + judge_log + translate_log。"""
    uid = resolve_uid(args.uid, data_dir())
    date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    events: list[dict] = []
    dd = data_dir()

    # 1. Cards 變更
    cards_db = dd / "users" / uid / "cards.db"
    if cards_db.exists():
        conn = connect_ro(cards_db)
        try:
            # 容忍 legacy cards.db 缺欄（mode 不在 schema.py 的 migration 清單；
            # 舊 DB 可能也缺 notebook_id/review_count/next_review_at）— 缺則取 NULL。
            ccols = table_columns(conn, "card")
            def _card_col(name: str) -> str:
                return name if name in ccols else "NULL"
            rows = conn.execute(
                "SELECT id, content, is_deleted, "
                f"{_card_col('notebook_id')}, created_at, updated_at, "
                f"{_card_col('mode')}, {_card_col('review_count')}, {_card_col('next_review_at')} "
                "FROM card WHERE date(created_at) = ? OR date(updated_at) = ? "
                "ORDER BY updated_at",
                (date, date),
            ).fetchall()
            for r in rows:
                created_today = bool(r[4] and r[4][:10] == date)
                event_type = "card_created" if created_today else "card_updated"
                if r[2]:  # is_deleted
                    event_type = "card_deleted"
                events.append({
                    "ts": r[5] or r[4] or "",
                    "type": event_type,
                    "source": "cards",
                    "detail": {
                        "id": r[0],
                        "content": r[1],
                        "notebook_id": r[3],
                        "mode": r[6],
                        "review_count": r[7],
                    },
                })
        finally:
            conn.close()

    # 2. Token usage (API calls)
    token_db = dd / "token_usage.db"
    if token_db.exists():
        conn = connect_ro(token_db)
        try:
            # legacy token_usage.db 可能尚未跑 provider/model migration（見 token_tracker）。
            tcols = table_columns(conn, "token_usage")
            prov = "provider" if "provider" in tcols else "NULL"
            model = "model" if "model" in tcols else "NULL"
            rows = conn.execute(
                f"SELECT call_type, input_tokens, output_tokens, created_at, {prov}, {model} "
                "FROM token_usage WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, date),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[3] or "",
                    "type": f"api_{r[0]}",
                    "source": "token_usage",
                    "detail": {
                        "input_tokens": r[1],
                        "output_tokens": r[2],
                        "provider": r[4],
                        "model": r[5],
                    },
                })
        finally:
            conn.close()

    # 3. Judge log
    judge_db = dd / "judge_log.db"
    if judge_db.exists():
        conn = connect_ro(judge_db)
        try:
            rows = conn.execute(
                "SELECT from_id, to_id, verdict, accepted, reject_reason, created_at "
                "FROM judge_log WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, date),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[5] or "",
                    "type": "judge_accept" if r[3] else "judge_reject",
                    "source": "judge_log",
                    "detail": {
                        "from_id": r[0],
                        "to_id": r[1],
                        "verdict": r[2],
                        "reason": r[4],
                    },
                })
        finally:
            conn.close()

    # 4. Translate log
    translate_db = dd / "translate_log.db"
    if translate_db.exists():
        conn = connect_ro(translate_db)
        try:
            rows = conn.execute(
                "SELECT operation, word, context, latency_ms, created_at "
                "FROM translate_log WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, date),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[4] or "",
                    "type": f"translate_{r[0]}",
                    "source": "translate_log",
                    "detail": {
                        "word": r[1],
                        "context": (r[2] or "")[:50] if r[2] else None,
                        "latency_ms": r[3],
                    },
                })
        finally:
            conn.close()

    # 排序
    events.sort(key=lambda e: e["ts"])

    if args.json:
        emit_json({"user_id": uid, "date": date, "count": len(events), "events": events})
        return

    print(f"Sync Trace for {uid} on {date}")
    print(f"Total events: {len(events)}")
    print()
    for e in events:
        ts = e["ts"][:19] if e["ts"] else "?"
        print(f"{ts}  [{e['source']:12}] {e['type']}")
        for k, v in e["detail"].items():
            if v is not None:
                print(f"  {k}: {v}")
        print()


def cmd_fleet_overview(args: argparse.Namespace) -> None:
    """跨用戶 fleet 體檢 — 每用戶 cards/links/月 cost + FLEET TOTAL。

    合併三個資料源:per-user cards.db(卡數)、per-user graph_*.json(連結數,
    跨 notebook 加總)、全域 token_usage.db(月 cost + 最後活動)。一條命令取代
    逐用戶手動 loop。
    """
    dd = data_dir()
    users_dir = dd / "users"

    # 1. token_usage：月 cost（by user×call_type×provider 各自定價再折回）+
    #    all-time last_active，一次查完，不逐用戶開檔。
    since = since_iso("month")
    month_cost: dict[str, float] = {}
    month_calls: dict[str, int] = {}
    last_active: dict[str, str] = {}
    token_db = dd / "token_usage.db"
    if token_db.exists():
        conn = connect_ro(token_db)
        pcol = provider_column_expr(conn)
        sql = (
            f"SELECT user_id, call_type, {pcol} AS provider, COUNT(*), "
            "SUM(input_tokens), SUM(output_tokens) FROM token_usage"
        )
        params: list = []
        if since is not None:
            sql += " WHERE created_at >= ?"
            params.append(since)
        sql += f" GROUP BY user_id, call_type, {pcol}"
        for uid, call_type, provider, cnt, t_in, t_out in conn.execute(sql, params):
            month_cost[uid] = month_cost.get(uid, 0.0) + token_cost_usd(
                call_type, int(t_in or 0), int(t_out or 0), provider=provider
            )
            month_calls[uid] = month_calls.get(uid, 0) + cnt
        for uid, la in conn.execute(
            "SELECT user_id, max(created_at) FROM token_usage GROUP BY user_id"
        ):
            last_active[uid] = la
        conn.close()

    # 2. per-user cards 計數 + links 計數（glob 跨 notebook 的 graph_*.json）
    user_dirs = (
        sorted((p for p in users_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        if users_dir.exists()
        else []
    )
    user_rows: list[dict] = []
    for ud in user_dirs:
        uid = ud.name
        total = active = 0
        cards_db = ud / "cards.db"
        if cards_db.exists():
            c = connect_ro(cards_db)
            try:
                total = c.execute("SELECT count(*) FROM card").fetchone()[0]
                active = c.execute("SELECT count(*) FROM card WHERE is_deleted = 0").fetchone()[0]
            finally:
                c.close()
        links = 0
        corrupt = 0
        for gp in ud.glob("graph_*.json"):
            # 形狀語意對齊 kg.admin_graph_density._read_graph_links (SoT):list=連結陣列、
            # dict=以 id 為鍵的連結映射(len 同 values 數)、其餘(scalar)視為壞形狀。
            # 直接 len(json.loads(...)) 對 scalar 會 TypeError 崩潰整個 fleet-overview。
            try:
                raw = json.loads(gp.read_text())
            except (json.JSONDecodeError, ValueError, OSError):
                corrupt += 1
                continue
            if isinstance(raw, (list, dict)):
                links += len(raw)
            else:
                corrupt += 1  # 合法 JSON 但非 list/dict(scalar)
        if corrupt:
            print(f"⚠ {uid}: skipped {corrupt} unreadable/bad-shape graph file(s)", file=sys.stderr)
        user_rows.append({
            "user_id": uid,
            "cards_total": total,
            "cards_active": active,
            "cards_deleted": total - active,
            "links": links,
            "last_active": last_active.get(uid),
            "month_cost_usd": round(month_cost.get(uid, 0.0), 6),
            "month_calls": month_calls.get(uid, 0),
        })

    user_rows.sort(key=lambda u: (u["cards_active"], u["month_cost_usd"]), reverse=True)

    totals = {
        "users": len(user_rows),
        "cards_total": sum(u["cards_total"] for u in user_rows),
        "cards_active": sum(u["cards_active"] for u in user_rows),
        "cards_deleted": sum(u["cards_deleted"] for u in user_rows),
        "links": sum(u["links"] for u in user_rows),
        "month_cost_usd": round(sum(u["month_cost_usd"] for u in user_rows), 6),
        "month_calls": sum(u["month_calls"] for u in user_rows),
    }

    if args.json:
        emit_json({"count": len(user_rows), "users": user_rows, "totals": totals})
        return

    print(f"Fleet Overview — {totals['users']} users")
    print(
        f"Cards: {totals['cards_total']} total / {totals['cards_active']} active / "
        f"{totals['cards_deleted']} deleted  |  Links: {totals['links']}  |  "
        f"Month: ${totals['month_cost_usd']:.6f} ({totals['month_calls']} calls)"
    )
    print()
    print_table(
        ["User", "Cards", "Active", "Deleted", "Links", "Last Active", "Month $", "Calls"],
        [[u["user_id"], str(u["cards_total"]), str(u["cards_active"]),
          str(u["cards_deleted"]), str(u["links"]), (u["last_active"] or "-")[:19],
          f"${u['month_cost_usd']:.6f}", str(u["month_calls"])]
         for u in user_rows],
    )


def cmd_timeseries(args: argparse.Namespace) -> None:
    """時間序列趨勢 — token_usage 按 day/week/month 分桶的 cost / calls / active_users。

    三種 metric 同一查詢路徑(只讀 token_usage.db):
      cost         — provider-aware 逐列定價後加總(week 桶用 ISO 週,SQL 難算,故 Python 分桶)
      calls        — 列數
      active_users — 桶內 distinct user_id。**注意語意**:這是「當桶內有觸發 LLM 呼叫的去重
                     用戶數」,只讀/聽 podcast 而不呼叫 LLM 的活躍不在此資料源(token_usage),
                     故對 retention 而言會低估;當作「付費活躍」而非「全活躍」解讀。
    `--uid all`(預設)算全體;指定 uid 則模糊解析後過濾。預設只吐有資料的桶;`--fill-zero`
    補齊區間內所有零值桶(時間軸連續、斷層顯式化),桶 key 升冪。
    """
    metric = args.metric
    bucket = args.bucket
    range_ = args.range
    since = since_iso(range_)
    uid_filter = args.uid

    result: dict = {
        "metric": metric, "bucket": bucket, "range": range_,
        "since": since, "uid": uid_filter, "count": 0, "series": [],
    }

    acc: dict[str, object] = {}  # bucket_key → float | int | set[str]
    min_dt: date | None = None
    max_dt: date | None = None
    db_path = data_dir() / "token_usage.db"
    if db_path.exists():
        conn = connect_ro(db_path)
        pcol = provider_column_expr(conn)
        sql = (
            f"SELECT user_id, call_type, {pcol} AS provider, "
            "input_tokens, output_tokens, created_at FROM token_usage"
        )
        clauses: list[str] = []
        params: list = []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        if uid_filter != "all":
            uid = resolve_uid(uid_filter, data_dir())
            result["uid"] = uid
            clauses.append("user_id = ?")
            params.append(uid)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        for user_id, call_type, provider, t_in, t_out, created_at in rows:
            d = _parse_day(created_at)
            if d is None:
                continue
            key = _bucket_key_from_date(d, bucket)  # d 已解析,避免重複 parse
            if min_dt is None or d < min_dt:
                min_dt = d
            if max_dt is None or d > max_dt:
                max_dt = d
            if metric == "cost":
                acc[key] = float(acc.get(key, 0.0)) + token_cost_usd(
                    call_type, int(t_in or 0), int(t_out or 0), provider=provider
                )
            elif metric == "calls":
                acc[key] = int(acc.get(key, 0)) + 1
            else:  # active_users
                acc.setdefault(key, set()).add(user_id)  # type: ignore[union-attr]

    # 收斂成 bucket→value（active_users 取 len,cost round 6 位）
    observed: dict[str, float | int] = {}
    for key, val in acc.items():
        if metric == "active_users":
            observed[key] = len(val)  # type: ignore[arg-type]
        elif metric == "cost":
            observed[key] = round(float(val), 6)
        else:
            observed[key] = val  # type: ignore[assignment]

    zero: float | int = 0.0 if metric == "cost" else 0
    if args.fill_zero:
        # 補零起點:bounded range 用 since 日;range=all 用首筆資料日。終點取 max(今天, 末筆)。
        start_d = (_parse_day(since) if since is not None else min_dt)
        if start_d is not None:
            end_d = datetime.now(UTC).date()
            if max_dt is not None and max_dt > end_d:
                end_d = max_dt
            series = [{"bucket": k, "value": observed.get(k, zero)}
                      for k in _enumerate_buckets(start_d, end_d, bucket)]
        else:
            series = []  # range=all 且全無資料 → 無起點可補
    else:
        series = [{"bucket": k, "value": observed[k]} for k in sorted(observed)]

    result["series"] = series
    result["count"] = len(series)

    if args.json:
        emit_json(result)
        return

    uid_label = "all users" if uid_filter == "all" else result["uid"]
    print(f"Timeseries — {metric} by {bucket}  |  {uid_label}  |  range={range_}")
    if not series:
        print("(no data)")
        return

    def _fmt(v: float | int) -> str:
        return f"${v:.6f}" if metric == "cost" else str(v)

    baseline = max((s["value"] for s in series), default=0)  # 保留原型別(calls=int)
    max_val = float(baseline)  # bar 比例用 float
    rows_out = []
    for s in series:
        bar = "█" * round((float(s["value"]) / max_val) * 24) if max_val else ""
        rows_out.append([s["bucket"], _fmt(s["value"]), bar])
    print_table(["Bucket", metric.capitalize(), "Trend"], rows_out)
    # 印滿格基準值 —— bar 為組內相對歸一化,常數序列會全滿,基準值供讀者校準絕對量級。
    print(f"\n(trend bar 滿格 = {_fmt(baseline)})")


def _count_by_day_ro(db_path: Path, table: str, ts_col: str, cutoff: str,
                     *, where: str = "", count: str = "COUNT(*)") -> dict[str, int]:
    """唯讀 GROUP BY 日期計數。db 不存在回 {};where 為內部 SQL 字面(非用戶輸入)。"""
    if not db_path.exists():
        return {}
    conn = connect_ro(db_path)
    try:
        rows = conn.execute(
            f"SELECT substr({ts_col},1,10) AS d, {count} FROM {table} "
            f"WHERE {ts_col} >= ?{where} GROUP BY d",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return {d: int(c or 0) for d, c in rows if d}


def cmd_trends(args: argparse.Namespace) -> None:
    """全域監控趨勢 — errors / llm_errors(真火) / active_users / tokens 逐日。

    **業務錯誤**:errors = 失敗 pipeline_runs(error_signals.PIPELINE_FAILURE_WHERE)+ auto-judge rejects
    (degree-cap 除外)。這是 token_usage 看不到的「有沒有東西在壞」訊號。
    **真火錯誤**:llm_errors = 真實 LLM 基礎設施失敗(429/5xx/timeout),獨立於業務拒絕。
    語意對齊 kg.admin_trends(SoT),但此處以 connect_ro 唯讀**重實作** —— 不可 import
    該模組,因其 log 單例 _get_conn 會跑 migration + 把 running→interrupted 的 UPDATE
    (寫入,且會破壞進行中 pipeline 狀態),違反 ops-cli 的唯讀保證。
    """
    window = max(1, min(args.window, 90))
    dd = data_dir()
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=window - 1 - i)).isoformat() for i in range(window)]
    cutoff = days[0]  # date-only;ISO created_at >= 'YYYY-MM-DD' 字串比較涵蓋當日全時刻

    pipe_fail = _count_by_day_ro(dd / "pipeline_runs.db", "pipeline_runs", "started_at",
                                 cutoff, where=f" AND {PIPELINE_FAILURE_WHERE}")
    judge_rej = _count_by_day_ro(dd / "judge_log.db", "judge_log", "created_at", cutoff,
                                 where=f" AND {JUDGE_AUTO_REJECT_WHERE}")
    actives = _count_by_day_ro(dd / "token_usage.db", "token_usage", "created_at", cutoff,
                               count="COUNT(DISTINCT user_id)")

    tokens_map: dict[str, int] = {}
    tdb = dd / "token_usage.db"
    if tdb.exists():
        conn = connect_ro(tdb)
        try:
            for d, ti, to in conn.execute(
                "SELECT substr(created_at,1,10) AS d, SUM(input_tokens), SUM(output_tokens) "
                "FROM token_usage WHERE created_at >= ? GROUP BY d", (cutoff,)
            ):
                if d:
                    tokens_map[d] = int(ti or 0) + int(to or 0)
        finally:
            conn.close()

    errors_per_day = [pipe_fail.get(d, 0) + judge_rej.get(d, 0) for d in days]
    active_users_per_day = [actives.get(d, 0) for d in days]
    tokens_per_day = [tokens_map.get(d, 0) for d in days]
    total_errors = sum(errors_per_day)

    # 真火 — 真實 LLM 基礎設施失敗(429/5xx/timeout),獨立於業務拒絕訊號
    llm_err_map: dict[str, int] = {}
    llm_db = dd / "llm_errors.db"
    if llm_db.exists():
        conn = connect_ro(llm_db)
        try:
            for d, c in conn.execute(
                "SELECT substr(created_at,1,10) AS d, COUNT(*) FROM llm_errors "
                "WHERE created_at >= ? GROUP BY d", (cutoff,)
            ):
                if d:
                    llm_err_map[d] = int(c or 0)
        finally:
            conn.close()
    llm_errors_per_day = [llm_err_map.get(d, 0) for d in days]
    total_llm_errors = sum(llm_errors_per_day)

    result = {
        "window_days": window,
        "days": days,
        "errors_per_day": errors_per_day,
        "llm_errors_per_day": llm_errors_per_day,
        "active_users_per_day": active_users_per_day,
        "tokens_per_day": tokens_per_day,
        "total_errors": total_errors,
        "total_llm_errors": total_llm_errors,
    }

    if args.json:
        emit_json(result)
        return

    print(f"Trends — last {window}d global monitoring (UTC)")
    print(f"Total errors (業務): {total_errors}  (failed pipeline + auto-judge rejects)")
    print(f"Total LLM failures (真火): {total_llm_errors}  (429/5xx/timeout)")
    print()
    max_err = max(errors_per_day) if errors_per_day else 0
    rows_out = []
    for d, e, le, a, tk in zip(days, errors_per_day, llm_errors_per_day, active_users_per_day, tokens_per_day, strict=True):
        bar = "█" * round((e / max_err) * 20) if max_err else ""
        rows_out.append([d, str(e), bar, str(le), str(a), str(tk)])
    print_table(["Date", "Errors", "Err Trend", "LLM-Fail", "Active", "Tokens"], rows_out)


def cmd_llm_errors(args: argparse.Namespace) -> None:
    """真火監控 — 真實 LLM 基礎設施失敗(429/5xx/timeout)逐日與分類。

    讀 llm_errors.db(connect_ro 唯讀,**不 import** llm_error_log 單例)。
    """
    window = max(1, min(args.window, 90))
    dd = data_dir()
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=window - 1 - i)).isoformat() for i in range(window)]
    cutoff = days[0]

    db_path = dd / "llm_errors.db"
    by_day: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_status: dict[str, int] = {}
    recent: list[dict] = []
    total = 0

    if db_path.exists():
        conn = connect_ro(db_path)
        try:
            # by_day
            uid_where = ""
            params: list = [cutoff]
            if args.uid != "all":
                uid_where = " AND user_id = ?"
                params.append(args.uid)
            for d, c in conn.execute(
                f"SELECT substr(created_at,1,10) AS d, COUNT(*) FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} GROUP BY d",
                tuple(params),
            ):
                if d:
                    by_day[d] = int(c or 0)

            # aggregates (same window + uid filter as by_day) — re-use same params
            for ec, c in conn.execute(
                f"SELECT error_class, COUNT(*) FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} GROUP BY error_class",
                tuple(params),
            ):
                by_class[ec] = int(c or 0)

            for prov, c in conn.execute(
                f"SELECT COALESCE(provider,'unknown'), COUNT(*) FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} GROUP BY provider",
                tuple(params),
            ):
                by_provider[prov] = int(c or 0)

            for sc, c in conn.execute(
                f"SELECT COALESCE(CAST(status_code AS TEXT),'none'), COUNT(*) FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} GROUP BY status_code",
                tuple(params),
            ):
                by_status[sc] = int(c or 0)

            # recent ~10
            limit = 10
            for row in conn.execute(
                f"SELECT user_id, call_type, provider, model, error_class, status_code, "
                f"message, substr(created_at,1,19) AS ts FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} ORDER BY created_at DESC LIMIT ?",
                tuple(params + [limit]),
            ):
                recent.append({
                    "user_id": row[0],
                    "call_type": row[1],
                    "provider": row[2],
                    "model": row[3],
                    "error_class": row[4],
                    "status_code": row[5],
                    "message": row[6],
                    "created_at": row[7],
                })

            total = sum(by_day.values())
        finally:
            conn.close()

    per_day = [by_day.get(d, 0) for d in days]

    result = {
        "window_days": window,
        "total": total,
        "by_day": {d: by_day.get(d, 0) for d in days},
        "by_class": by_class,
        "by_provider": by_provider,
        "by_status": by_status,
        "recent": recent,
    }

    if args.json:
        emit_json(result)
        return

    print(f"LLM Errors (真火) — last {window}d")
    print(f"Total: {total}")
    print()

    # trend bar
    max_val = max(per_day) if per_day else 0
    rows_out = []
    for d, v in zip(days, per_day, strict=True):
        bar = "█" * round((v / max_val) * 20) if max_val else ""
        rows_out.append([d, str(v), bar])
    print_table(["Date", "Count", "Trend"], rows_out)
    print()

    # by_class ranking
    if by_class:
        print("By error class:")
        sorted_cls = sorted(by_class.items(), key=lambda x: -x[1])
        print_table(["Class", "Count"], [[k, str(v)] for k, v in sorted_cls[:5]])
        print()

    # by_provider ranking
    if by_provider:
        print("By provider:")
        sorted_prov = sorted(by_provider.items(), key=lambda x: -x[1])
        print_table(["Provider", "Count"], [[k, str(v)] for k, v in sorted_prov[:5]])
        print()

    # by_status
    if by_status:
        print("By status code:")
        sorted_status = sorted(by_status.items(), key=lambda x: -x[1])
        print_table(["Status", "Count"], [[k, str(v)] for k, v in sorted_status[:5]])
        print()

    if recent:
        print(f"Recent {len(recent)} errors:")
        for r in recent:
            sc = f" [{r['status_code']}]" if r['status_code'] is not None else ""
            print(f"  {r['created_at']} {r['error_class']}{sc} — {r['call_type']} "
                  f"(uid={r['user_id']}, provider={r['provider'] or 'unknown'})")


# ── CLI 進入點 ──────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="KG ops CLI — container 內查詢工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # 統一輸出契約：所有 data-query 命令共用 --json 旗標（agent-first 機讀）。
    jp = argparse.ArgumentParser(add_help=False)
    jp.add_argument("--json", action="store_true", help="以 JSON 輸出")

    # user-quota
    p = sub.add_parser("user-quota", parents=[jp], help="24h 額度 + 逐時明細")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_quota)

    # user-stats
    p = sub.add_parser("user-stats", parents=[jp], help="單字庫統計")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_stats)

    # user-config（唯讀 user config：translation / review_clock / review_mode / vocab_ui）
    p = sub.add_parser("user-config", parents=[jp],
                       help="單用戶 user config（含 vocab_ui active notebook）唯讀檢視")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_config)

    p = sub.add_parser("world-state", parents=[jp],
                       help="單用戶 world-state 投影（cards/notebooks/graphs/config）")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_world_state)

    p = sub.add_parser("world-diff", parents=[jp],
                       help="用 expectation spec 比對單用戶 world-state")
    p.add_argument("uid", help="User ID")
    p.add_argument("spec", help="Expectation JSON path (schema=kg.ops_world_expectation.v1)")
    p.set_defaults(func=cmd_world_diff)

    # quota-overview
    p = sub.add_parser("quota-overview", parents=[jp], help="全用戶 24h 額度總覽")
    p.set_defaults(func=cmd_quota_overview)

    # active-users
    p = sub.add_parser("active-users", parents=[jp], help="近 N 小時活躍用戶")
    p.add_argument("hours", nargs="?", type=int, default=24, help="小時數（預設 24）")
    p.set_defaults(func=cmd_active_users)

    # card-find
    p = sub.add_parser("card-find", parents=[jp], help="byte-exact 子字串搜尋 card.content（免寫 SQL）")
    p.add_argument("uid", help="User ID")
    p.add_argument("substring", help="搜尋子字串（ASCII case-insensitive，%% _ 當字面字元）")
    p.set_defaults(func=cmd_card_find)

    # card-get
    p = sub.add_parser("card-get", parents=[jp], help="單卡 byte-exact 垂直 dump（key=id 或精確 content）")
    p.add_argument("uid", help="User ID")
    p.add_argument("key", help="card id 或精確 content（ASCII case-insensitive）")
    p.set_defaults(func=cmd_card_get)

    # db-query（sql 為 REMAINDER，故 --json 也可能被吃進 sql；cmd 內會再剝離）
    p = sub.add_parser("db-query", parents=[jp], help="對用戶 cards.db 跑任意 SQL")
    p.add_argument("uid", help="User ID")
    p.add_argument("sql", nargs=argparse.REMAINDER, help="SQL 查詢語句（不需要引號包覆）")
    p.set_defaults(func=cmd_db_query)

    # analyze（深度報告，非結構化查詢，不納入 --json 契約）
    p = sub.add_parser("analyze", help="深度分析（圖譜拓撲/連結品質/嵌入/異常）")
    p.add_argument("uid", help="User ID")
    p.add_argument("level", nargs="?", default="all", help="1-6 或 all（預設 all）")
    p.set_defaults(func=cmd_analyze)

    # cost
    p = sub.add_parser("cost", parents=[jp], help="單用戶 cost-by-call_type 拆解")
    p.add_argument("uid", help="User ID")
    p.add_argument("--range", choices=list(VALID_RANGES), default="month",
                   help="時間範圍（預設 month）")
    p.set_defaults(func=cmd_cost)

    # fleet-overview
    p = sub.add_parser("fleet-overview", parents=[jp],
                       help="跨用戶體檢（每用戶 cards/links/月 cost + FLEET TOTAL）")
    p.set_defaults(func=cmd_fleet_overview)

    # cost-overview
    p = sub.add_parser("cost-overview", parents=[jp], help="全用戶 cost 排名")
    p.add_argument("--range", choices=list(VALID_RANGES), default="month",
                   help="時間範圍（預設 month）")
    p.set_defaults(func=cmd_cost_overview)

    # sync-trace
    p = sub.add_parser("sync-trace", parents=[jp], help="用戶 sync 完整時間線（cards + API + judge + translate）")
    p.add_argument("uid", help="User ID")
    p.add_argument("--date", help="日期 (YYYY-MM-DD, 預設今天)")
    p.set_defaults(func=cmd_sync_trace)

    # timeseries
    p = sub.add_parser("timeseries", parents=[jp],
                       help="時間序列趨勢（cost/calls/active_users 按 day/week/month 分桶）")
    p.add_argument("metric", choices=["cost", "calls", "active_users"],
                   help="指標（active_users = 觸發 LLM 呼叫的去重用戶，非全活躍）")
    p.add_argument("--bucket", choices=["day", "week", "month"], default="day",
                   help="分桶粒度（預設 day）")
    p.add_argument("--range", choices=list(VALID_RANGES), default="30d",
                   help="時間範圍（預設 30d）")
    p.add_argument("--uid", default="all", help="限定單一用戶（預設 all）")
    p.add_argument("--fill-zero", dest="fill_zero", action="store_true",
                   help="補齊區間內零值桶（時間軸連續、斷層顯式化）；長範圍建議配 "
                        "--bucket week/month，否則 day 桶會產生大片零牆")
    p.set_defaults(func=cmd_timeseries)

    # trends（全域監控:errors/active/tokens 逐日;errors 含業務拒絕+真火獨立欄位）
    p = sub.add_parser("trends", parents=[jp],
                       help="全域監控趨勢（errors/active/tokens 逐日；errors=業務拒絕, llm-fail=真火）")
    p.add_argument("--window", type=int, default=14, help="天數（預設 14，上限 90）")
    p.set_defaults(func=cmd_trends)

    # llm-errors（真火監控 — 429/5xx/timeout）
    p = sub.add_parser("llm-errors", parents=[jp],
                       help="真實 LLM 基礎設施失敗監控（429/5xx/timeout 逐日+分類）")
    p.add_argument("--window", type=int, default=14, help="天數（預設 14，上限 90）")
    p.add_argument("--uid", default="all", help="限定單一用戶（預設 all）")
    p.set_defaults(func=cmd_llm_errors)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

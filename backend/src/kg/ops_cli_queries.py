"""Query-oriented commands for the readonly ops CLI."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

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

from .ops_cli_shared import _cutoff_iso, _flatten_user_config, _ops_passthrough_normalize


def cmd_user_quota(args: argparse.Namespace) -> None:
    """24h 額度 + 逐時明細。"""
    uid = resolve_uid(args.uid, data_dir())
    cutoff = _cutoff_iso(24)
    pro_limit = float(__import__("os").getenv("PRO_DAILY_LIMIT_USD", "0.30"))
    free_limit = float(__import__("os").getenv("FREE_DAILY_LIMIT_USD", "0.03"))

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
    hourly: dict[str, float] = {}
    for call_type, inp, out, ts, provider in rows:
        hour = ts[:13]
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
    print_table(["Hour", "Cost (USD)"], [[h, f"${v:.6f}"] for h, v in sorted(hourly.items())])


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
    print_table(["Metric", "Value"], [["Total cards", str(total)], ["Active", str(active)], ["Deleted", str(deleted)]])
    print()
    if recent:
        print("Recent activity:")
        print_table(["ID", "Content", "Updated"], [[r[0], r[1] or "", r[2] or ""] for r in recent])


def cmd_user_config(args: argparse.Namespace) -> None:
    """單用戶 user config 唯讀檢視。"""
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

    tr, rc, rm, vu, al = (
        flat["translation"], flat["review_clock"], flat["review_mode"],
        flat["vocab_ui"], flat["auto_link"],
    )
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
            ["auto_link", "enabled", str(al["enabled"])],
            ["auto_link", "updated_at", str(al["updated_at"])],
        ],
    )


def cmd_world_state(args: argparse.Namespace) -> None:
    dd = data_dir()
    uid = resolve_uid(args.uid, dd)
    payload = project_user_world(uid, data_root=dd)
    if args.json:
        emit_json(payload)
        return
    print(f"schema: {WORLD_STATE_SCHEMA}")
    print(f"user: {uid}")
    print(f"cards={len(payload['cards'])} notebooks={len(payload['notebooks'])} graphs={len(payload['graphs'])}")


def cmd_world_diff(args: argparse.Namespace) -> None:
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
        ({"user_id": uid, "cost_usd": round(cost, 6), "calls": user_calls[uid]} for uid, cost in user_costs.items()),
        key=lambda u: u["cost_usd"],
        reverse=True,
    )

    if args.json:
        emit_json({"count": len(ranked), "users": ranked})
        return

    if not user_costs:
        print("(no usage in last 24h)")
        return
    print_table(["User", "Cost (USD)", "Calls"], [[u["user_id"], f"${u['cost_usd']:.6f}", str(u["calls"])] for u in ranked])


def cmd_active_users(args: argparse.Namespace) -> None:
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
        emit_json({"hours": hours, "count": len(rows), "users": [{"user_id": r[0], "calls": r[1], "last_active": r[2]} for r in rows]})
        return

    if not rows:
        print(f"(no active users in last {hours}h)")
        return
    print_table(["User", "Calls", "Last Active"], [[r[0], str(r[1]), r[2]] for r in rows])


def cmd_card_find(args: argparse.Namespace) -> None:
    uid = resolve_uid(args.uid, data_dir())
    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

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
        emit_json({"user_id": uid, "substring": args.substring, "count": len(rows), "matches": [{"id": r[0], "content": r[1], "is_deleted": r[2]} for r in rows]})
        return
    print_table(["id", "content (repr)", "is_deleted"], [[r[0], repr(r[1]), r[2]] for r in rows])


def cmd_card_get(args: argparse.Namespace) -> None:
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
        emit_json({"user_id": uid, "key": args.key, "count": len(rows), "cards": [dict(zip(cols, row, strict=True)) for row in rows]})
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
    uid = resolve_uid(args.uid, data_dir())
    raw = list(args.sql)
    json_mode = args.json or "--json" in raw
    schema_mode = "--schema" in raw
    tokens = [t for t in raw if t not in ("--json", "--schema")]
    sql = " ".join(tokens)

    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = connect_ro(db_path)
    try:
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
            emit_json({"sql": sql, "columns": headers, "count": len(rows), "rows": [list(r) for r in rows]})
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


def cmd_analyze(args: argparse.Namespace) -> None:
    # ops_analyze.py 位於 backend/ 根目錄（與 ops_cli.py 同層），非 src/kg/ 內
    script = Path(__file__).resolve().parent.parent.parent / "ops_analyze.py"
    cmd = [sys.executable, str(script), args.uid, args.level]
    sys.exit(subprocess.call(cmd))


def cmd_sync_trace(args: argparse.Namespace) -> None:
    uid = resolve_uid(args.uid, data_dir())
    day = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    events: list[dict] = []
    dd = data_dir()

    cards_db = dd / "users" / uid / "cards.db"
    if cards_db.exists():
        conn = connect_ro(cards_db)
        try:
            ccols = table_columns(conn, "card")

            def _card_col(name: str) -> str:
                return name if name in ccols else "NULL"

            rows = conn.execute(
                "SELECT id, content, is_deleted, "
                f"{_card_col('notebook_id')}, created_at, updated_at, "
                f"{_card_col('mode')}, {_card_col('review_count')}, {_card_col('next_review_at')} "
                "FROM card WHERE date(created_at) = ? OR date(updated_at) = ? "
                "ORDER BY updated_at",
                (day, day),
            ).fetchall()
            for r in rows:
                created_today = bool(r[4] and r[4][:10] == day)
                event_type = "card_created" if created_today else "card_updated"
                if r[2]:
                    event_type = "card_deleted"
                events.append({
                    "ts": r[5] or r[4] or "",
                    "type": event_type,
                    "source": "cards",
                    "detail": {"id": r[0], "content": r[1], "notebook_id": r[3], "mode": r[6], "review_count": r[7]},
                })
        finally:
            conn.close()

    token_db = dd / "token_usage.db"
    if token_db.exists():
        conn = connect_ro(token_db)
        try:
            tcols = table_columns(conn, "token_usage")
            prov = "provider" if "provider" in tcols else "NULL"
            model = "model" if "model" in tcols else "NULL"
            rows = conn.execute(
                f"SELECT call_type, input_tokens, output_tokens, created_at, {prov}, {model} "
                "FROM token_usage WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, day),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[3] or "",
                    "type": f"api_{r[0]}",
                    "source": "token_usage",
                    "detail": {"input_tokens": r[1], "output_tokens": r[2], "provider": r[4], "model": r[5]},
                })
        finally:
            conn.close()

    judge_db = dd / "judge_log.db"
    if judge_db.exists():
        conn = connect_ro(judge_db)
        try:
            rows = conn.execute(
                "SELECT from_id, to_id, verdict, accepted, reject_reason, created_at "
                "FROM judge_log WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, day),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[5] or "",
                    "type": "judge_accept" if r[3] else "judge_reject",
                    "source": "judge_log",
                    "detail": {"from_id": r[0], "to_id": r[1], "verdict": r[2], "reason": r[4]},
                })
        finally:
            conn.close()

    translate_db = dd / "translate_log.db"
    if translate_db.exists():
        conn = connect_ro(translate_db)
        try:
            rows = conn.execute(
                "SELECT operation, word, context, latency_ms, created_at "
                "FROM translate_log WHERE user_id = ? AND date(created_at) = ? "
                "ORDER BY created_at",
                (uid, day),
            ).fetchall()
            for r in rows:
                events.append({
                    "ts": r[4] or "",
                    "type": f"translate_{r[0]}",
                    "source": "translate_log",
                    "detail": {"word": r[1], "context": (r[2] or "")[:50] if r[2] else None, "latency_ms": r[3]},
                })
        finally:
            conn.close()

    events.sort(key=lambda e: e["ts"])
    if args.json:
        emit_json({"user_id": uid, "date": day, "count": len(events), "events": events})
        return
    print(f"Sync Trace for {uid} on {day}")
    print(f"Total events: {len(events)}")
    print()
    for e in events:
        ts = e["ts"][:19] if e["ts"] else "?"
        print(f"{ts}  [{e['source']:12}] {e['type']}")
        for k, v in e["detail"].items():
            if v is not None:
                print(f"  {k}: {v}")
        print()

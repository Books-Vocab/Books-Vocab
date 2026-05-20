#!/usr/bin/env python3
"""ops_cli.py — container 內部署的查詢工具。

直接讀 SQLite，不依賴 app 運行狀態。計價走 kg.quota_service.token_cost_usd
（provider-aware，單一真相）；容器內 PYTHONPATH=/app/src 使 import kg.* 可用。
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kg.admin_cost_summary import VALID_RANGES, since_iso
from kg.ops_shared import (
    connect_ro,
    data_dir,
    emit_json,
    print_table,
    resolve_uid,
    table_columns,
)
from kg.quota_service import token_cost_usd


def _cutoff_iso(hours: int = 24) -> str:
    """回傳 N 小時前的 ISO 8601 UTC 時間字串。"""
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ── 子指令實作 ──────────────────────────────────────────


def cmd_user_quota(args: argparse.Namespace) -> None:
    """24h 額度 + 逐時明細。"""
    uid = resolve_uid(args.uid, data_dir())
    cutoff = _cutoff_iso(24)
    pro_limit = float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30"))
    free_limit = float(os.getenv("FREE_DAILY_LIMIT_USD", "0.03"))

    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        print(f"token_usage.db not found at {db_path}")
        print(f"User: {uid}  |  Used: $0.000000  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
        return

    conn = connect_ro(db_path)
    provider_col = "provider" if "provider" in table_columns(conn, "token_usage") else "NULL"
    rows = conn.execute(
        f"SELECT call_type, input_tokens, output_tokens, created_at, {provider_col} AS provider "
        "FROM token_usage WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
        (uid, cutoff),
    ).fetchall()
    conn.close()

    total = sum(token_cost_usd(r[0], r[1], r[2], provider=r[4]) for r in rows)

    print(f"User: {uid}")
    print(f"24h used: ${total:.6f}  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
    print()

    if not rows:
        print("(no usage in last 24h)")
        return

    # 逐時彙整
    hourly: dict[str, float] = {}
    for call_type, inp, out, ts, provider in rows:
        hour = ts[:13]  # YYYY-MM-DDTHH
        hourly[hour] = hourly.get(hour, 0.0) + token_cost_usd(call_type, inp, out, provider=provider)

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


def cmd_quota_overview(args: argparse.Namespace) -> None:
    """全用戶 24h 額度總覽。"""
    cutoff = _cutoff_iso(24)
    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        print("(no token_usage.db found)")
        return

    conn = connect_ro(db_path)
    provider_col = "provider" if "provider" in table_columns(conn, "token_usage") else "NULL"
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

    if not user_costs:
        print("(no usage in last 24h)")
        return

    table_rows = sorted(
        [[uid, f"${cost:.6f}", str(user_calls[uid])] for uid, cost in user_costs.items()],
        key=lambda r: float(r[1].replace("$", "")),
        reverse=True,
    )
    print_table(["User", "Cost (USD)", "Calls"], table_rows)


def cmd_active_users(args: argparse.Namespace) -> None:
    """近 N 小時活躍用戶。"""
    hours = args.hours
    cutoff = _cutoff_iso(hours)
    db_path = data_dir() / "token_usage.db"
    if not db_path.exists():
        print("(no token_usage.db found)")
        return

    conn = connect_ro(db_path)
    rows = conn.execute(
        "SELECT user_id, count(*) as calls, max(created_at) as last_active "
        "FROM token_usage WHERE created_at >= ? GROUP BY user_id ORDER BY last_active DESC",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"(no active users in last {hours}h)")
        return

    print_table(
        ["User", "Calls", "Last Active"],
        [[r[0], str(r[1]), r[2]] for r in rows],
    )


def cmd_db_query(args: argparse.Namespace) -> None:
    """對用戶 cards.db 跑任意 SQL。"""
    uid = resolve_uid(args.uid, data_dir())
    sql = " ".join(args.sql)  # REMAINDER captures split words; rejoin
    db_path = data_dir() / "users" / uid / "cards.db"
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = connect_ro(db_path)
    try:
        cursor = conn.execute(sql)
        if cursor.description:
            headers = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            print_table(headers, [list(r) for r in rows])
        else:
            print(f"OK (rows affected: {cursor.rowcount})")
    except Exception as e:
        print(f"SQL error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


def cmd_cost(args: argparse.Namespace) -> None:
    """單用戶 cost-by-call_type 拆解（唯讀）。

    GROUP BY call_type + provider,各 provider 切片以自身費率定價後折回
    per-call_type bucket。`token_usage.db` 不存在則回傳全零 summary。
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
        conn = connect_ro(db_path)
        pcol = "provider" if "provider" in table_columns(conn, "token_usage") else "NULL"
        sql = (
            f"SELECT call_type, {pcol} AS provider, COUNT(*), "
            "SUM(input_tokens), SUM(output_tokens) "
            "FROM token_usage WHERE user_id = ?"
        )
        params: list = [uid]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += f" GROUP BY call_type, {pcol}"
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        for call_type, provider, cnt, t_in, t_out in rows:
            ti = int(t_in or 0)
            to = int(t_out or 0)
            cost = token_cost_usd(call_type, ti, to, provider=provider)
            bucket = summary["by_call_type"].setdefault(
                call_type,
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += cnt
            bucket["input_tokens"] += ti
            bucket["output_tokens"] += to
            bucket["cost_usd"] += cost
            summary["total_calls"] += cnt
            summary["total_input_tokens"] += ti
            summary["total_output_tokens"] += to
            summary["total_cost_usd"] += cost

        for bucket in summary["by_call_type"].values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        summary["total_cost_usd"] = round(summary["total_cost_usd"], 6)

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
        conn = connect_ro(db_path)
        pcol = "provider" if "provider" in table_columns(conn, "token_usage") else "NULL"
        sql = (
            f"SELECT user_id, call_type, {pcol} AS provider, COUNT(*), "
            "SUM(input_tokens), SUM(output_tokens) FROM token_usage"
        )
        params: list = []
        if since is not None:
            sql += " WHERE created_at >= ?"
            params.append(since)
        sql += f" GROUP BY user_id, call_type, {pcol}"
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        per_user: dict[str, dict] = {}
        for user_id, call_type, provider, cnt, t_in, t_out in rows:
            cost = token_cost_usd(call_type, int(t_in or 0), int(t_out or 0), provider=provider)
            u = per_user.setdefault(user_id, {"total_calls": 0, "total_cost_usd": 0.0})
            u["total_calls"] += cnt
            u["total_cost_usd"] += cost

        result["users"] = sorted(
            (
                {"user_id": uid, "total_calls": u["total_calls"],
                 "total_cost_usd": round(u["total_cost_usd"], 6)}
                for uid, u in per_user.items()
            ),
            key=lambda u: u["total_cost_usd"],
            reverse=True,
        )

    if args.json:
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


# ── CLI 進入點 ──────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="KG ops CLI — container 內查詢工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # user-quota
    p = sub.add_parser("user-quota", help="24h 額度 + 逐時明細")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_quota)

    # user-stats
    p = sub.add_parser("user-stats", help="單字庫統計")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_stats)

    # quota-overview
    p = sub.add_parser("quota-overview", help="全用戶 24h 額度總覽")
    p.set_defaults(func=cmd_quota_overview)

    # active-users
    p = sub.add_parser("active-users", help="近 N 小時活躍用戶")
    p.add_argument("hours", nargs="?", type=int, default=24, help="小時數（預設 24）")
    p.set_defaults(func=cmd_active_users)

    # db-query
    p = sub.add_parser("db-query", help="對用戶 cards.db 跑任意 SQL")
    p.add_argument("uid", help="User ID")
    p.add_argument("sql", nargs=argparse.REMAINDER, help="SQL 查詢語句（不需要引號包覆）")
    p.set_defaults(func=cmd_db_query)

    # analyze
    p = sub.add_parser("analyze", help="深度分析（圖譜拓撲/連結品質/嵌入/異常）")
    p.add_argument("uid", help="User ID")
    p.add_argument("level", nargs="?", default="all", help="1-6 或 all（預設 all）")
    p.set_defaults(func=cmd_analyze)

    # cost
    p = sub.add_parser("cost", help="單用戶 cost-by-call_type 拆解")
    p.add_argument("uid", help="User ID")
    p.add_argument("--range", choices=list(VALID_RANGES), default="month",
                   help="時間範圍（預設 month）")
    p.add_argument("--json", action="store_true", help="以 JSON 輸出")
    p.set_defaults(func=cmd_cost)

    # cost-overview
    p = sub.add_parser("cost-overview", help="全用戶 cost 排名")
    p.add_argument("--range", choices=list(VALID_RANGES), default="month",
                   help="時間範圍（預設 month）")
    p.add_argument("--json", action="store_true", help="以 JSON 輸出")
    p.set_defaults(func=cmd_cost_overview)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

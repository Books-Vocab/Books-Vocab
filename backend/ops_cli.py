#!/usr/bin/env python3
"""ops_cli.py — container 內部署的查詢工具。

直接讀 SQLite，不依賴 app 運行狀態。純 stdlib，無外部依賴。
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 定價常數（與 quota_service.py 完全一致）
INPUT_PER_M = 0.10
OUTPUT_PER_M = 0.40
EMBED_PER_M = 0.00025

DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent / "data")))


def _token_usage_db() -> Path:
    return DATA_DIR / "token_usage.db"


def _cards_db(uid: str) -> Path:
    return DATA_DIR / "users" / uid / "cards.db"


def _cost_usd(call_type: str, input_tokens: int, output_tokens: int) -> float:
    """計算單筆呼叫的 USD 費用。"""
    if call_type == "embed":
        return input_tokens / 1_000_000 * EMBED_PER_M
    return input_tokens / 1_000_000 * INPUT_PER_M + output_tokens / 1_000_000 * OUTPUT_PER_M


def _cutoff_iso(hours: int = 24) -> str:
    """回傳 N 小時前的 ISO 8601 UTC 時間字串。"""
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """唯讀連線。"""
    if not db_path.exists():
        print(f"Error: DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _print_table(headers: list[str], rows: list[list]) -> None:
    """格式化輸出表格。"""
    if not rows:
        print("(no data)")
        return
    # 計算欄寬
    str_rows = [[str(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in str_rows:
        print(fmt.format(*row))


# ── 子指令實作 ──────────────────────────────────────────


def cmd_user_quota(args: argparse.Namespace) -> None:
    """24h 額度 + 逐時明細。"""
    uid = args.uid
    cutoff = _cutoff_iso(24)
    pro_limit = float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30"))
    free_limit = float(os.getenv("FREE_DAILY_LIMIT_USD", "0.03"))

    db_path = _token_usage_db()
    if not db_path.exists():
        print(f"token_usage.db not found at {db_path}")
        print(f"User: {uid}  |  Used: $0.000000  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
        return

    conn = _connect_ro(db_path)
    rows = conn.execute(
        "SELECT call_type, input_tokens, output_tokens, created_at "
        "FROM token_usage WHERE user_id = ? AND created_at >= ? ORDER BY created_at",
        (uid, cutoff),
    ).fetchall()
    conn.close()

    total = sum(_cost_usd(r[0], r[1], r[2]) for r in rows)

    print(f"User: {uid}")
    print(f"24h used: ${total:.6f}  |  Pro limit: ${pro_limit:.2f}  |  Free limit: ${free_limit:.2f}")
    print()

    if not rows:
        print("(no usage in last 24h)")
        return

    # 逐時彙整
    hourly: dict[str, float] = {}
    for call_type, inp, out, ts in rows:
        hour = ts[:13]  # YYYY-MM-DDTHH
        hourly[hour] = hourly.get(hour, 0.0) + _cost_usd(call_type, inp, out)

    _print_table(
        ["Hour", "Cost (USD)"],
        [[h, f"${v:.6f}"] for h, v in sorted(hourly.items())],
    )


def cmd_user_stats(args: argparse.Namespace) -> None:
    """單字庫統計。"""
    uid = args.uid
    db_path = _cards_db(uid)
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = _connect_ro(db_path)
    total = conn.execute("SELECT count(*) FROM card").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM card WHERE is_deleted = 0").fetchone()[0]
    deleted = conn.execute("SELECT count(*) FROM card WHERE is_deleted = 1").fetchone()[0]
    recent = conn.execute(
        "SELECT id, content, updated_at FROM card WHERE is_deleted = 0 ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    conn.close()

    print(f"User: {uid}")
    _print_table(
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
        _print_table(["ID", "Content", "Updated"], [[r[0], r[1] or "", r[2] or ""] for r in recent])


def cmd_quota_overview(args: argparse.Namespace) -> None:
    """全用戶 24h 額度總覽。"""
    cutoff = _cutoff_iso(24)
    db_path = _token_usage_db()
    if not db_path.exists():
        print("(no token_usage.db found)")
        return

    conn = _connect_ro(db_path)
    rows = conn.execute(
        "SELECT user_id, call_type, input_tokens, output_tokens "
        "FROM token_usage WHERE created_at >= ?",
        (cutoff,),
    ).fetchall()
    conn.close()

    user_costs: dict[str, float] = {}
    user_calls: dict[str, int] = {}
    for uid, call_type, inp, out in rows:
        user_costs[uid] = user_costs.get(uid, 0.0) + _cost_usd(call_type, inp, out)
        user_calls[uid] = user_calls.get(uid, 0) + 1

    if not user_costs:
        print("(no usage in last 24h)")
        return

    table_rows = sorted(
        [[uid, f"${cost:.6f}", str(user_calls[uid])] for uid, cost in user_costs.items()],
        key=lambda r: float(r[1].replace("$", "")),
        reverse=True,
    )
    _print_table(["User", "Cost (USD)", "Calls"], table_rows)


def cmd_active_users(args: argparse.Namespace) -> None:
    """近 N 小時活躍用戶。"""
    hours = args.hours
    cutoff = _cutoff_iso(hours)
    db_path = _token_usage_db()
    if not db_path.exists():
        print("(no token_usage.db found)")
        return

    conn = _connect_ro(db_path)
    rows = conn.execute(
        "SELECT user_id, count(*) as calls, max(created_at) as last_active "
        "FROM token_usage WHERE created_at >= ? GROUP BY user_id ORDER BY last_active DESC",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"(no active users in last {hours}h)")
        return

    _print_table(
        ["User", "Calls", "Last Active"],
        [[r[0], str(r[1]), r[2]] for r in rows],
    )


def cmd_db_query(args: argparse.Namespace) -> None:
    """對用戶 cards.db 跑任意 SQL。"""
    uid = args.uid
    sql = args.sql
    db_path = _cards_db(uid)
    if not db_path.exists():
        print(f"Error: cards.db not found for user {uid}", file=sys.stderr)
        sys.exit(1)

    conn = _connect_ro(db_path)
    try:
        cursor = conn.execute(sql)
        if cursor.description:
            headers = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            _print_table(headers, [list(r) for r in rows])
        else:
            print(f"OK (rows affected: {cursor.rowcount})")
    except Exception as e:
        print(f"SQL error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


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
    p.add_argument("sql", help="SQL 查詢語句")
    p.set_defaults(func=cmd_db_query)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

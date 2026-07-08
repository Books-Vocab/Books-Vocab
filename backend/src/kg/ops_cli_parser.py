"""Parser assembly for the readonly ops CLI."""

from __future__ import annotations

import argparse

from .ops_cli_costs import cmd_cost, cmd_cost_overview, cmd_fleet_overview
from .ops_cli_observability import cmd_llm_errors, cmd_timeseries, cmd_trends
from .ops_cli_queries import (
    cmd_active_users,
    cmd_analyze,
    cmd_card_find,
    cmd_card_get,
    cmd_db_query,
    cmd_quota_overview,
    cmd_sync_trace,
    cmd_user_config,
    cmd_user_quota,
    cmd_user_stats,
    cmd_world_diff,
    cmd_world_export,
    cmd_world_state,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KG ops CLI — container 內查詢工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    jp = argparse.ArgumentParser(add_help=False)
    jp.add_argument("--json", action="store_true", help="以 JSON 輸出")

    p = sub.add_parser("user-quota", parents=[jp], help="24h 額度 + 逐時明細")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_quota)

    p = sub.add_parser("user-stats", parents=[jp], help="單字庫統計")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_stats)

    p = sub.add_parser("user-config", parents=[jp], help="單用戶 user config（含 vocab_ui active notebook）唯讀檢視")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_user_config)

    p = sub.add_parser("world-state", parents=[jp], help="單用戶 world-state 投影（cards/notebooks/graphs/config）")
    p.add_argument("uid", help="User ID")
    p.set_defaults(func=cmd_world_state)

    p = sub.add_parser("world-export", help="單帳號 vocab 層導出成 ops_edit seed 相容 spec（唯讀；stdout 純 JSON）")
    p.add_argument("uid", help="User ID")
    p.add_argument("--out", help="寫入檔案路徑（預設印 stdout）")
    p.set_defaults(func=cmd_world_export)

    p = sub.add_parser("world-diff", parents=[jp], help="用 expectation spec 比對單用戶 world-state")
    p.add_argument("uid", help="User ID")
    p.add_argument("spec", help="Expectation JSON path (schema=kg.ops_world_expectation.v1)")
    p.set_defaults(func=cmd_world_diff)

    p = sub.add_parser("quota-overview", parents=[jp], help="全用戶 24h 額度總覽")
    p.set_defaults(func=cmd_quota_overview)

    p = sub.add_parser("active-users", parents=[jp], help="近 N 小時活躍用戶")
    p.add_argument("hours", nargs="?", type=int, default=24, help="小時數（預設 24）")
    p.set_defaults(func=cmd_active_users)

    p = sub.add_parser("card-find", parents=[jp], help="byte-exact 子字串搜尋 card.content（免寫 SQL）")
    p.add_argument("uid", help="User ID")
    p.add_argument("substring", help="搜尋子字串（ASCII case-insensitive，%% _ 當字面字元）")
    p.set_defaults(func=cmd_card_find)

    p = sub.add_parser("card-get", parents=[jp], help="單卡 byte-exact 垂直 dump（key=id 或精確 content）")
    p.add_argument("uid", help="User ID")
    p.add_argument("key", help="card id 或精確 content（ASCII case-insensitive）")
    p.set_defaults(func=cmd_card_get)

    p = sub.add_parser("db-query", parents=[jp], help="對用戶 cards.db 跑任意 SQL")
    p.add_argument("uid", help="User ID")
    p.add_argument("sql", nargs=argparse.REMAINDER, help="SQL 查詢語句（不需要引號包覆）")
    p.set_defaults(func=cmd_db_query)

    p = sub.add_parser("analyze", help="深度分析（圖譜拓撲/連結品質/嵌入/異常）")
    p.add_argument("uid", help="User ID")
    p.add_argument("level", nargs="?", default="all", help="1-6 或 all（預設 all）")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("cost", parents=[jp], help="單用戶 cost-by-call_type 拆解")
    p.add_argument("uid", help="User ID")
    p.add_argument("--range", choices=["24h", "7d", "30d", "month", "all"], default="month", help="時間範圍（預設 month）")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("fleet-overview", parents=[jp], help="跨用戶體檢（每用戶 cards/links/月 cost + FLEET TOTAL）")
    p.set_defaults(func=cmd_fleet_overview)

    p = sub.add_parser("cost-overview", parents=[jp], help="全用戶 cost 排名")
    p.add_argument("--range", choices=["24h", "7d", "30d", "month", "all"], default="month", help="時間範圍（預設 month）")
    p.set_defaults(func=cmd_cost_overview)

    p = sub.add_parser("sync-trace", parents=[jp], help="用戶 sync 完整時間線（cards + API + judge + translate）")
    p.add_argument("uid", help="User ID")
    p.add_argument("--date", help="日期 (YYYY-MM-DD, 預設今天)")
    p.set_defaults(func=cmd_sync_trace)

    p = sub.add_parser("timeseries", parents=[jp], help="時間序列趨勢（cost/calls/active_users 按 day/week/month 分桶）")
    p.add_argument("metric", choices=["cost", "calls", "active_users"], help="指標（active_users = 觸發 LLM 呼叫的去重用戶，非全活躍）")
    p.add_argument("--bucket", choices=["day", "week", "month"], default="day", help="分桶粒度（預設 day）")
    p.add_argument("--range", choices=["24h", "7d", "30d", "month", "all"], default="30d", help="時間範圍（預設 30d）")
    p.add_argument("--uid", default="all", help="限定單一用戶（預設 all）")
    p.add_argument(
        "--fill-zero",
        dest="fill_zero",
        action="store_true",
        help="補齊區間內零值桶（時間軸連續、斷層顯式化）；長範圍建議配 --bucket week/month，否則 day 桶會產生大片零牆",
    )
    p.set_defaults(func=cmd_timeseries)

    p = sub.add_parser("trends", parents=[jp], help="全域監控趨勢（errors/active/tokens 逐日；errors=業務拒絕, llm-fail=真火）")
    p.add_argument("--window", type=int, default=14, help="天數（預設 14，上限 90）")
    p.set_defaults(func=cmd_trends)

    p = sub.add_parser("llm-errors", parents=[jp], help="真實 LLM 基礎設施失敗監控（429/5xx/timeout 逐日+分類）")
    p.add_argument("--window", type=int, default=14, help="天數（預設 14，上限 90）")
    p.add_argument("--uid", default="all", help="限定單一用戶（預設 all）")
    p.set_defaults(func=cmd_llm_errors)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)

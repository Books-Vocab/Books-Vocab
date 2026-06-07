#!/usr/bin/env -S uv run --project backend python
"""一次性把用戶資料夾回填成合成 SoT 歷史帳本(複習史 + 圖譜史)。

dry-run 預設(只報告不寫);--apply 才動檔(備份只建一次→就地清 card_id NULL 殘渣→灌合成史)。
確定式 + 冪等 + re-run 保留真實事件。詳見 backend/src/kg/sot_history_migrate.py。

--apply 會就地寫入,須先停 API 容器並加 --i-stopped-the-api 顯式聲明(避免與線上併發寫)。

Usage:
    ops/migrate_sot_history.py -u chen                                   # dry-run 單一用戶
    ops/migrate_sot_history.py -u chen --apply --i-stopped-the-api       # 實際回填單一用戶
    ops/migrate_sot_history.py --all                                     # dry-run 全用戶
    ops/migrate_sot_history.py --all --apply --i-stopped-the-api         # 實際回填全用戶
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from kg.ops_shared import data_dir, resolve_uid  # noqa: E402
from kg.sot_history_migrate import MigrationReport, migrate_user  # noqa: E402

DATA = data_dir()
USERS = DATA / "users"


def _print(report: MigrationReport) -> None:
    tag = "DRY-RUN" if report.dry_run else "APPLIED"
    print(f"[{tag}] {report.user_dir.name}")
    print(f"  notebooks            : {', '.join(report.notebooks) or '(none)'}")
    print(f"  review events synth  : {report.review_events_synthesized}")
    print(f"  old review purged    : {report.review_events_old_purged}")
    print(f"  graph events synth   : {report.graph_events_synthesized}")
    print(f"  graph snapshots      : {report.graph_snapshots_taken}")
    if report.backups:
        print(f"  backups              : {', '.join(b.name for b in report.backups)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-u", "--user", help="user id (partial ok)")
    g.add_argument("--all", action="store_true", help="all users under data dir")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    ap.add_argument(
        "--i-stopped-the-api", action="store_true",
        help="acknowledge the API container is stopped (required with --apply)",
    )
    args = ap.parse_args()

    # 併發寫入護欄:--apply 會就地改 review_events.db / graph_events.db。若 API 容器仍在跑,
    # 它與遷移會同時寫同一 per-user SQLite(WAL 下雖不致損毀,但備份快照可能不一致、且兩邊
    # 寫入交錯)。要求顯式聲明已停服務,避免在 live data dir 上盲跑。
    if args.apply and not args.i_stopped_the_api:
        sys.exit(
            "✗ --apply 需同時加 --i-stopped-the-api。\n"
            "  遷移會就地寫入 per-user review_events.db / graph_events.db;請先停掉 API 容器\n"
            "  (見 ops/devops_kg_safe.sh)再回填,避免與線上寫入併發。"
        )

    if args.all:
        # 納入有 cards.db 或任一 graph_*.json 的用戶(graph-only 用戶的圖譜史也要回填)。
        user_dirs = sorted(
            p
            for p in USERS.iterdir()
            if p.is_dir() and ((p / "cards.db").exists() or any(p.glob("graph_*.json")))
        )
    else:
        # resolve_uid 自己接 /users,故傳 data_dir() 而非 USERS,否則 partial 匹配失效。
        uid = resolve_uid(args.user, DATA)
        user_dir = USERS / uid
        if not user_dir.is_dir():
            sys.exit(f"✗ 用戶目錄不存在: {user_dir}（uid {uid!r} 無法解析）")
        if not (user_dir / "cards.db").exists() and not any(user_dir.glob("graph_*.json")):
            sys.exit(f"✗ {user_dir} 無 cards.db 也無 graph_*.json,沒有可回填的資料")
        user_dirs = [user_dir]

    if not args.apply:
        print("※ dry-run（未加 --apply,不寫任何檔）\n")
    for ud in user_dirs:
        _print(migrate_user(ud, apply=args.apply))
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env -S uv run --project backend python
"""一次性把用戶資料夾回填成合成 SoT 歷史帳本(複習史 + 圖譜史)。

dry-run 預設(只報告不寫);--apply 才動檔(備份只建一次後 wipe 舊 review_events,
灌合成史)。確定式 + 冪等。詳見 backend/src/kg/sot_history_migrate.py。

Usage:
    ops/migrate_sot_history.py -u chen              # dry-run 單一用戶
    ops/migrate_sot_history.py -u chen --apply      # 實際回填單一用戶
    ops/migrate_sot_history.py --all                # dry-run 全用戶
    ops/migrate_sot_history.py --all --apply        # 實際回填全用戶
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
    args = ap.parse_args()

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

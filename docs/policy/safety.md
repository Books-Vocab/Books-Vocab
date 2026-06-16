<!-- doc-meta
tier: policy
authority: SoT
update_trigger: manual
scope:
  - ops/
  - backend/
  - docs/runbook/
verified_against: f0d37ca4
-->
# Safety Policy

## Non-Negotiable Rules
1. Production actions must go through project scripts.
2. Every deployment requires backup first.
3. Never run destructive Docker cleanup commands on production.

## Forbidden Commands (Production)
- `docker compose down -v`
- `docker system prune -a`
- `rm -rf /home/ubuntu/*`
- `rm -rf ~` / `rm -rf $HOME`（home 目錄遞迴刪除）
- `delete-user`（用戶資料刪除 CLI）

實作見 `ops/devops_kg_safe.sh` 的 `is_blocked_run`，適用 `run` / `container-run` /
`migrate-run` 三個遠端執行入口。比對前先正規化（lowercase、去引號/反引號、`${HOME}`→`$home`、
折疊重複斜線、把 `; | & ( )` 換成空白），讓等價但寫法不同的毀滅指令無法繞過。涵蓋：
- `docker compose down` / `docker-compose down` / bare `down` 帶 `-v` / `--volume` / `--volumes`（任意位置與長短形）
- `docker (system|volume|image|builder) prune` 與 `docker volume rm`（容器層級資料銷毀）
- 遞迴 `rm`（`-rf` / `-fr` / `-r -f` / `--recursive` / `--no-preserve-root` 任意組合，含 `/bin/rm` 絕對路徑）指向受保護路徑
- `find <受保護路徑> -delete` / `-exec rm`
- redirect / `tee` / `truncate` / `dd of=` 對受保護路徑的覆寫
- `delete-user`（用戶資料刪除 CLI）

受保護路徑：`/`（含 `/*`、`/.` 整機抹除）、`~`、`$HOME`、`/home/ubuntu`、`/app/data`（容器內）、`~/kg-data`（felix host live data，2026-06-16 起 data 移出 worktree）、`/root`、`knowledge_graph_api`、`knowledge-graph-api_data`。

繞過變體（引號路徑、`;` 終止、`//`、`${HOME}`、`/bin/rm`、`rm -rf /*`、`find -delete`、redirect、`tee`、`docker volume rm` 等）
與誤殺防護（`rm -rf ./build`、`/tmp/foo`、非遞迴單檔、`tar`/`grep -r` 讀取等須放行）皆由 `ops/test_devops.sh` 的 Blocklist 段守住。
測試可用 `KG_DEVOPS_BASE=/usr/bin/true` 注入 stub base 以驗證放行路徑不觸發遠端。

**邊界聲明（重要）**：此 guard 是「常見誤觸防護網」，**非完備沙箱**。黑名單無法窮舉所有等價毀滅指令。
以下已知**未涵蓋**、仍依賴人工 review，切勿倚賴 wrapper 攔截：`mv <受保護路徑>`（移走掛載等同銷毀）、
`cp /dev/null <db>` / `shred` 等覆寫、`rsync -a --delete`、`docker rm -fv <container>`（刪匿名 volume）、
`git clean -xfd`、以及任何透過未展開 shell 變數（`rm -rf $DATA_DIR`）指向受保護路徑者（wrapper 在 SSH 前比對字面，無法得知變數值）。

## Required Preflight
1. Confirm remote path (`~/knowledge_graph_api`).
2. Confirm domain (`wordnexus.lol`) and internal port (`8000`).
3. Confirm expected container name (`knowledge-graph-api`).

## Rollback Principle
- If health check fails after deploy, roll back to previous image/tag or previous synced directory snapshot.
- Do not patch production files manually before rollback attempt.

## Incident Logging
- Write incident summary with timestamp, root cause, and mitigation.
- Update relevant runbook before the next deployment.

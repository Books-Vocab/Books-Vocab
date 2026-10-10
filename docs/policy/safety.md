<!-- doc-meta
tier: policy
authority: SoT
update_trigger: manual
scope:
  - ops/
  - backend/
  - docs/runbook/
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
-->
# Safety Policy

## Non-Negotiable Rules
1. Production actions must go through project scripts.
2. Every production data change requires a verified recovery path; the standby deploy path does not perform an inline backup, so scheduled backup health or a documented cold snapshot must be confirmed separately.
3. Never run destructive Docker cleanup commands on production.

## Forbidden Commands (Production)
- `docker compose down -v`
- `docker system prune -a`
- `rm -rf /home/ubuntu/*`
- `rm -rf ~` / `rm -rf $HOME`（home 目錄遞迴刪除）
- `delete-user`（用戶資料刪除 CLI）

實作見 `ops/lib/devops_run_guard.sh` 的 `devops_run_is_blocked`（單一 predicate），適用 `run` / `container-run` /
`migrate-run` 三個遠端執行入口，且**兩個入口都執行**：`ops/devops_kg_safe.sh`（agent 面對的 wrapper）與 base
`devops.sh`（`cmd_run` / `cmd_container_run` / `cmd_migrate_run`，guard 排在 `cmd_backup` 之前）。直接呼叫
`devops.sh run …` 或把 wrapper 指到別的 base 都不會繞過它（2026-10-09 事故後加入，見
[`docs/runbook/incidents/2026-10-09-kg-data-deleted-by-test.md`](../runbook/incidents/2026-10-09-kg-data-deleted-by-test.md)）。
比對前先正規化（lowercase、去引號/反引號/反斜線、`${VAR}`→`$var`、折疊重複斜線、把 `; && || &` 當作子句分隔、
`( ) { } ,` 與管線換成空白），讓等價但寫法不同的毀滅指令無法繞過。涵蓋：
- `docker compose down` / `docker-compose down` / bare `down` 帶 `-v` / `--volume` / `--volumes`（任意位置與長短形）
- `docker (system|volume|image|builder) prune` 與 `docker volume rm`（容器層級資料銷毀）
- 遞迴 `rm`（`-rf` / `-fr` / `-r -f` / `--recursive` / `--no-preserve-root` 任意組合，含 `/bin/rm` 絕對路徑）指向受保護路徑
- `find <受保護路徑> -delete` / `-exec rm`
- redirect / `tee` / `truncate` / `dd of=` 對受保護路徑的覆寫
- `delete-user`（用戶資料刪除 CLI）

**受保護的是名稱，不是路徑寫法**：`kg-data`、`kg-prod`、`/app/data`、`/app` 本身。任何破壞性動詞——`rm` `rmdir`
`unlink` `mv` `truncate` `shred`、`find -delete`、`git clean`、`rsync --delete`（或以其為目的地）、`cp`／`install`／`ln`
的目的地、`tar x`、`chmod`／`chown -R`、`tee`、`>`／`>>`、`dd of=`、`sed -i`、`sqlite3` 寫入、python `rmtree`／
`os.remove`——只要引用它們就擋，不論路徑寫法：絕對、`~`、`~user`、`$HOME`、相對、`..`、glob（`kg-d*`、`~/*`）、brace
expansion，或前一個子句 `cd` 進受保護目錄之後的相對路徑。`container-run` / `migrate-run`（以及任何 `docker exec`）的
cwd 是 `/app`，所以其中的相對路徑 `data`、`.`、`*` 同樣視為受保護。無法解析的變數目標（`rm -rf $DATA_DIR`）直接拒絕。
對這些目錄的**讀取**（`ls`、`du`、`tar czf`、`sqlite3` 查詢、`git log`）照常放行。

受保護路徑（舊式根）：`/`（含 `/*`、`/.` 整機抹除）、`~`、`~user`、`$HOME`、`/home/ubuntu`、`/Users/<user>`、`/root`、`/app/data`（容器內）、`~/kg-data`（felix host live data，2026-06-16 起 data 移出 worktree）、`knowledge_graph_api`、`knowledge-graph-api_data`。

繞過變體（引號路徑、`;` 終止、`//`、`${HOME}`、`/bin/rm`、`rm -rf /*`、`find -delete`、redirect、`tee`、`docker volume rm`、
`~user`、glob、`cd` 後相對路徑、容器內 `/app` 等）與誤殺防護（`rm -rf ./build`、`/tmp/foo`、非遞迴單檔、`tar`/`grep -r`
讀取、對 kg-data／kg-prod 的唯讀命令等須放行）皆由 `ops/test_devops.sh` 的 Blocklist 段守住；base 直接呼叫由同檔
「base devops.sh enforces the same guard」段守住。

**測試不得碰 production（2026-10-09）**：被擋的定義是「命令從未到達 base」。`ops/test_ops.sh` 與 `ops/test_devops.sh`
一律 `KG_OPS_TEST=1` + PATH deny shim（`ssh` `scp` `sftp` `rsync` `aws` → exit 97）+ deny-stub transport seam
（`ops/lib/hermetic_ops_test.sh`）；`ops/test_devops.sh` 的 `KG_DEVOPS_BASE` 預設為留痕的 recording stub，需要真
`devops.sh` 的測試必須明確傳 `KG_DEVOPS_BASE="$KG"` 並搭配假 `KG_SSH_CMD`；`KG_OPS_TEST=1` 時 `devops.sh` 的 transport
tripwire 對真 ssh／scp／rsync／curl 一律 exit 97（`ops/tests/test_devops_transport_tripwire.sh`）；
`ops/tests/test_ops_hermetic_lint.sh` 掃描所有提到 `devops.sh`／`devops_kg_safe.sh` 的測試檔。新增 BYPASS 項目前
先確認 stub base 已就位；紅燈階段也不得對真 base 執行。

上述字串 guard 只涵蓋 `run` / `container-run` / `migrate-run`。`ops-cli`、`ops-edit`、
`ops-edit-batch`、`container-script` 是 argv／script pass-through surface，不套用
`devops_run_is_blocked`；`ops-cli` 是查詢入口，`ops-edit`／`ops-edit-batch` 依各自工具的 dry-run、
`--commit`、備份與 verify 契約，`container-script` 則只接受 `.py`／`.sh` 腳本（另套用下節的
敏感檔讀取 deny-list）。不能把這些 surface 誤讀成已由這個 shell guard 保護。

**邊界聲明（重要）**：此 guard 是「常見誤觸防護網」，**非完備沙箱**。黑名單無法窮舉所有等價毀滅指令。
`mv`／`shred`／`rsync --delete`／`git clean`／`cp` 覆寫／無法解析的 `$VAR` 目標已於 2026-10-09 納入（見上）。
仍**未涵蓋**、依賴人工 review 的：`eval`／base64／變數間接組出的命令、不經破壞性動詞就能刪資料的直譯器
（`sqlite3` 在 `;` 之後另一個子句的 `DELETE`、`python` 的 `open(...,'w')`、`docker rm -fv <container>` 刪匿名 volume），
以及完全不經 devops 的直接 `ssh felix rm …`。第一道牆是「測試與 agent 不碰 production」（hermetic harness + tripwire），
這個 guard 是第二道。

## Sensitive File Reads
`users.json`（`_email_index`、email、subscription、linked_ids）、`.env`、`~/.secrets/` 與私鑰材料
（`*.pem`、`*.p8`、`*.p12`、ssh `id_rsa`／`id_ecdsa`／`id_ed25519`，`.pub` 除外）不得進入 agent 的
transcript 或 log。

- 用戶清單只走 typed `users`：遠端 python 先縮減，只輸出用戶目錄數、真實用戶數（排除 `_` metadata
  與 `_linked_to` alias）與每人一行 `uid provider last_login`。safe wrapper 對 `users` 的任何多餘
  參數 exit 64，沒有整檔 dump 路徑。
- `ops/devops_kg_safe.sh` 的 `is_sensitive_read`（#2134，deny-list）比對 `run`／`container-run`／
  `migrate-run` 的命令字串，以及 `container-script` 的參數與本地腳本內容；比對前 lowercase、去引號／
  反引號／反斜線。命中即 exit 1 並印 `blocked sensitive file read`，命令不送到 remote。攔截變體與
  誤殺防護（`os.environ`、`id_*.pub`、一般 `ls`／`docker logs`、文件化的 `container-script`）由
  `ops/test_devops.sh` 的 sensitive file reads 段守住。
- `logs [n]`／`docker-logs [n]` 的行數會拼進 remote shell 字串，只接受純數字，否則 exit 64 且不送到
  remote；`docker-logs '1; cat …/users.json'` 這類注入因此無法繞過上述兩道 guard。
- 已知誤殺：`*.pem` 也擋公開憑證（`openssl x509 -in …/cert.pem`），`.env` 規則也擋 `.env.example`。
  TLS 憑證到期改看 `health --json` 的 `cert_days_left`。
- **邊界聲明**：這是誤觸防護，**不是安全邊界**。glob（`cat ~/kg-data/u*`）、字串組裝
  （`python3 -c`、base64）、未展開變數與容器內的 `os.environ` 都能繞過；輸出與 `.env` 同值秘密的
  環境傾印也不擋：`container-run env`、`printenv <KEY>`、`docker inspect <container>`、
  `docker compose config`（deny-list 不收它們，因為 `docker inspect -f '{{.State…}}'`、
  `env VAR=x cmd` 這類唯讀用法會被誤殺）。`run` 仍是 owner 等級的逃生口。agent 不得透過任何
  remote 執行入口讀取上述檔案或其等價內容，需要用戶資訊時用 typed command，其餘交 owner。

## Required Preflight
1. Confirm standby production checkout (`~/kg-prod/backend`, or `KG_REMOTE_DIR`); `~/knowledge_graph_api` is historical Lightsail rollback only.
2. Confirm standby data path (`~/kg-data`, or `KG_REMOTE_DATA_DIR`).
3. Confirm domain (`wordnexus.lol`) and internal port (`8000`).
4. Confirm expected container name (`knowledge-graph-api`).

## Rollback Principle
- If health check fails after deploy, roll back to previous image/tag or previous synced directory snapshot.
- Do not patch production files manually before rollback attempt.

## Incident Logging
- Write incident summary with timestamp, root cause, and mitigation.
- Update relevant runbook before the next deployment.

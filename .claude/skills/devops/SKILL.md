---
name: devops
description: "KG 生產環境運維 — 部署、狀態、用戶查詢、額度、遠端操作、系統健康"
allowed-tools: Bash, Read, Grep
---

# KG DevOps Skill

## Identity

> ✅ **2026-06-19 起 `devops_kg_safe.sh` / `devops.sh` 已 retarget 到 standby**（不再寫死 Lightsail，已移除 `KG_ALLOW_LIGHTSAIL` guard）。transport 由 `KG_SERVER` / `KG_REMOTE_DIR` / `KG_REMOTE_DATA_DIR` 控制，default = `chenliangyu@100.118.39.104` / `~/project/kg/backend` / `~/kg-data`（Tailscale 免密碼，不再用 `-i lightsail_kg_prod`）。`deploy/restart/migrate/backup` 直接透傳 standby（破壞性 `run` 仍由 `is_blocked_run` 守護）。權威服務層程序 = `~/butler/docs/kg-backend-deployment.md`。Lightsail instance 已 terminate，僅作冷重建 rollback 備援（見 `docs/reference/host_topology.md §Rollback`）。

| key | value（現役 standby） | rollback（Lightsail，已 terminate） |
|-----|-------|-------|
| host | `chenliangyu@100.118.39.104`（Tailscale，OrbStack；`KG_SERVER`） | `ubuntu@<冷重建新 IP>`（Caddy） |
| repo | `~/project/kg/backend`（git 同步；`KG_REMOTE_DIR`） | `~/knowledge_graph_api` |
| data | `~/kg-data`（`KG_REMOTE_DATA_DIR`） | `~/knowledge_graph_api/data` |
| 對外 | Cloudflare Tunnel `kg-standby`（CF 邊緣終結 TLS） | Caddy（Let's Encrypt） |
| domain | `wordnexus.lol`（hostname 不變） | 同 |
| container | `knowledge-graph-api`（service `kg-api`） | 同 |
| port | `8000` | 同 |

## 安全規則

1. **生產環境操作前**先跑 preflight：`./ops/devops_kg_safe.sh preflight`
2. **deploy / migration 前**再加 backup：`./ops/devops_kg_safe.sh backup`
3. 禁止封鎖指令：`setup` `push-env` `delete-user` `ssh`、破壞性 `run` 字串（`is_blocked_run` 守護）
4. **transport**：`deploy/restart/migrate/backup` 直接打 standby（`KG_SERVER` 等變數，default felix）。Lightsail guard 已移除（2026-06-19）；冷重建 rollback 走 `docs/reference/host_topology.md §Rollback` + `~/butler/docs/kg-backend-deployment.md`。

## 指令參考 **(SoT)**

本段為 `./ops/devops_kg_safe.sh`（與 repo-local shortcut `./devops.sh`）的權威指令清單；`docs/sop/deploy.md` / `docs/sop/debug.md` 內任何 `./devops.sh *` 用法以本表為準。
對 `docker ps`、`df -h` 這類高頻唯讀 debug 查詢，safe wrapper 已提供 typed 子命令，且 raw `run "<cmd>"` 會直接提示改用 typed surface。standby 無 Caddy：`caddy-status` 已改為唯讀檢查 cloudflared tunnel（`pgrep`），`caddyfile` 回 N/A（CF ingress 為 remotely-managed config）；`backup-s3-test` 改為唯讀驗 standby launchd `com.kg.backup`。

### Safe Wrapper（`./ops/devops_kg_safe.sh`）

```bash
./ops/devops_kg_safe.sh preflight
./ops/devops_kg_safe.sh backup
./ops/devops_kg_safe.sh deploy
./ops/devops_kg_safe.sh restart
./ops/devops_kg_safe.sh status
./ops/devops_kg_safe.sh health [--json]
./ops/devops_kg_safe.sh logs [n]
./ops/devops_kg_safe.sh caddy-status
./ops/devops_kg_safe.sh caddyfile
./ops/devops_kg_safe.sh docker-ps
./ops/devops_kg_safe.sh docker-logs [n]
./ops/devops_kg_safe.sh disk-usage
./ops/devops_kg_safe.sh memory-usage
./ops/devops_kg_safe.sh docker-stats
./ops/devops_kg_safe.sh env-check
./ops/devops_kg_safe.sh env-drift
./ops/devops_kg_safe.sh migrate
./ops/devops_kg_safe.sh users
./ops/devops_kg_safe.sh user-info <id>
./ops/devops_kg_safe.sh run "<cmd>"
./ops/devops_kg_safe.sh container-run "<cmd>"
./ops/devops_kg_safe.sh migrate-run "<cmd>"
./ops/devops_kg_safe.sh ops-cli <subcommand> [args]
./ops/devops_kg_safe.sh ops-edit <subcommand> [args]
./ops/devops_kg_safe.sh ops-edit-batch <plan.json> [runner args]
./ops/devops_kg_safe.sh container-script <script> [args]
```

### ops-cli 子指令

```bash
ops-cli user-quota <uid>                  # 24h 額度 + 逐時明細
ops-cli user-stats <uid>                  # 單字庫統計
ops-cli user-config <uid>                 # user config 唯讀（translation/review_clock/review_mode/vocab_ui active notebook/auto_link）
ops-cli quota-overview                     # 全用戶 24h 額度總覽
ops-cli active-users [hours]              # 近 N 小時活躍用戶
ops-cli card-find <uid> <substring>       # byte-exact 子字串搜尋 card.content（免寫 SQL；ASCII case-insensitive；repr 顯示，trailing comma/空白可見）
ops-cli card-get <uid> <id|content>       # 單卡 byte-exact 垂直 dump 全欄（寬表 SELECT * 難讀時用）
ops-cli db-query <uid> SQL...             # 唯讀查用戶 DB（只放行單一 SELECT/WITH/EXPLAIN）
ops-cli db-query <uid> --schema           # 免寫 SQL 列出各表 DDL（先看 schema 再查，省盲猜欄位）
ops-cli analyze <uid> [level]            # 深度分析（1-6 或 all）
ops-cli cost <uid> [--range R]            # 單用戶 cost-by-call_type 拆解（provider-aware）
ops-cli cost-overview [--range R]         # 全用戶 cost 排名
ops-cli fleet-overview                     # 跨用戶體檢：每用戶 cards/links/月cost + FLEET TOTAL（免逐用戶 loop）
ops-cli sync-trace <uid> [--date YYYY-MM-DD] # 用戶單日 sync 時間線（cards+API+judge+translate 合併按時間排序；預設今天）
ops-cli world-state <uid>                  # 穩定投影 actual world（config/notebooks/cards/graph_*.json）
ops-cli world-diff <uid> <spec.json>       # 用 kg.ops_world_expectation.v1 比對 actual，拿穩定 mismatch path
ops-cli world-export <uid> [--out <path>]  # 帳號 vocab 層 → ops-edit seed 相容 spec（kg.seed_spec.v1，唯讀、確定式排序、stdout 純 JSON；不可重放資料走 stderr warning）
ops-cli timeseries <metric> [--bucket day|week|month] [--range R] [--uid all|<uid>] [--fill-zero]
                                           # 時間序列趨勢；metric=cost|calls|active_users（預設 bucket=day, range=30d, uid=all）
                                           # --fill-zero：補齊區間內零值桶，時間軸連續、斷層顯式化（找「哪幾天/週沒人用」必加）
                                           # ⚠ active_users = 該桶內「觸發 LLM 呼叫」的去重用戶數，非全活躍；只讀/聽 podcast 不呼叫 LLM 者不計入
ops-cli trends [--window N]                # 全域監控:errors/llm-fail/active/tokens 逐日（預設 14d，上限 90）
                                           # errors = 業務拒絕(失敗 pipeline + auto-judge rejects, degree-cap 除外)
                                           # llm-fail = 真火(429/5xx/timeout)——獨立欄位,真當機時不會被業務噪音淹沒
                                           # 唯讀重實作，語意對齊 kg.admin_trends（不 import 它—其 _get_conn 會寫入/中斷進行中 run）
ops-cli llm-errors [--window N] [--uid all|<uid>]  # 真火監控——真實 LLM 基礎設施失敗(429/5xx/timeout)逐日+分類
                                           # by_class/by_provider/by_status 排名 + recent 最近 10 筆
                                           # 預設 window=14d;uid=all 看全體,uid=<id> 看單用戶
ops-cli dictionary-health [--window <hours>]  # 字典全域面(讀 lexical_cache.db,不分用戶)
                                           # cache 組成 positive/negative/fresh/expired + 上游每小時預算餘裕
                                           # lookups.by_outcome 印全套詞彙(零顯示 0 而非消失)+ p50/p95/max 延遲
                                           # 三種 429 分開:throttled=我方 per-user 限流 / rate_limited=上游 429
                                           #              / budget_exhausted=我方每小時預算擋下
                                           # ⚠ 這三種只在「沒有可用快取」時記到自己名下。手上有 entry 時
                                           #    (lexical.py `_search`/`_resolve_entry` 的 except 分支)一律降級回
                                           #    cache_status=stale,所以 budget_exhausted/rate_limited=0 不代表
                                           #    沒發生節流——快取愈溫愈會被吸收進 stale。stale 竄高就交叉看
                                           #    provider_budget 餘裕,別直接歸咎上游。failure_rate 不受影響
                                           #    (stale 本來就在分子裡)。
                                           # 回滾後看 by_outcome 的 blocked 是否如預期出現
ops-cli dictionary-cards [uid]             # 字典卡面(預設 all;讀 users/<uid>/cards.db)
                                           # 字典卡數 + active/archived/deleted/reader_hidden 拆分、staged sidecar
                                           # totals.operations_in_flight = lexical_operations status≠completed
                                           #   → **不歸零就是 materialize saga 卡死的簽名**,回滾後必看
                                           # totals.promotion_failures + 逐筆 error_code/retryable/attempt
                                           # ⚠ 明示的 uid 打錯時 totals 全零但 exit 0——先確認 totals.users>0 再讀數字

# ⚠ 字典的 runbook 一律走上面兩個 typed 子指令,**禁止用 db-query 手拼 SQL 當正式流程**
#   (見 docs/reference/tech_index.md;回滾檢查清單見 docs/sop/deploy.md「字典卡（V1）rollout 開關」)。

# 統一輸出契約：以上所有 data-query 命令（analyze 除外，它是人讀報告）皆支援 --json，
#   吐結構化結果供 agent 機讀；db-query 的 --json 可置於 SQL 前後皆可。
#   診斷 banner（[Preflight]/▶progress）一律走 stderr，stdout 只有純 JSON，
#   可直接 `... --json 2>/dev/null | jq`（或 json.loads）。
#   list 類命令（card-find/active-users/quota-overview/cost-overview/sync-trace/db-query）
#   的 JSON 皆含頂層 count，免自己 len()。
# --range: 24h | 7d | 30d | month | all（預設 month）
```

### ops-edit 子指令（**寫入**;dry-run 預設,`--commit` 才落地）

`ops-cli` 唯讀查詢的可寫對應面。每個寫操作:**dry-run 預設**(只印 plan)→ `--commit`
寫前自動 tar 備份 user_dir（並內嵌該 uid 的 `users.json` record/email-index snapshot）→ 寫後讀回 verify → append `_ops_edit_audit.jsonl`。
寫入複用 app 的 `CardStore`/`GraphStore`/`NotebookStore`(SoT)。皆支援 `--json`。

```bash
ops-edit user-create <uid> [--email E] [--provider google|apple|demo] [--allow-existing]
ops-edit card-add <uid> <content> --meaning M [--pos] [--example ...] [--collocation ...]
                                   [--note] [--difficulty] [--mode] [--notebook] [--review new|due|reviewed] [--interval H]
ops-edit card-update <uid> <id|content> --set field=value ...   # 白名單欄位;value 走 JSON 解析;改 content 驗本內衝突
ops-edit card-set-review <uid> <id|content> --state new|due|reviewed [--interval H]
ops-edit card-delete <uid> <id|content>                          # 軟刪
ops-edit card-move <uid> <id|content> --to-notebook|--notebook <id|name>   # 跨本搬卡(驗目標本無同 content;硬刪原本跨本 link)
ops-edit card-import <uid> <csv> [--notebook]                    # card_format.md 格式;CSV 可帶 review_state 欄
ops-edit notebook-create <uid> <name> [--color] [--cover]
ops-edit user-config-set <uid> [--translation-source L] [--translation-target L]
                         [--review-clock paused|running] [--paused-at ISO]
                         [--review-mode relaxed|intensive|custom]
                         [--custom-initial-interval-hours H]
                         [--custom-remembered-multiplier X]
                         [--custom-forgot-multiplier X]
                         [--custom-minimum-interval-hours H]
                         [--custom-maximum-interval-hours H]
                         [--active-notebook <id|name>]           # settings/active notebook 行銷造景
                         [--auto-link on|off]                    # judge pipeline 自動連結開關
ops-edit notebook-update <uid> <id|name> [--name] [--color] [--cover] [--sort-order N]
ops-edit notebook-delete <uid> <id|name> [--cascade]             # 軟刪(default 不可刪;非空須 --cascade 一併軟刪卡,否則拒絕)
ops-edit link-add <uid> <from> <to> --kind contrasts_with|shares_usage --confidence C --reason R [--notebook] [--if-exists keep|update]
ops-edit link-update <uid> <link_id> [--confidence] [--reason] [--kind] [--notebook]   # 改既有 link(link-add 撞既有回 idempotent 不改值)
ops-edit link-list <uid> [--notebook]                            # 列連結(id+兩端 content),供 link-update/delete 查 id
ops-edit link-delete <uid> <link_id> [--notebook]
ops-edit seed <uid> <spec.json>                                  # 一次灌整套 demo(notebooks+cards+links);冪等可重跑
ops-edit clone-demo <source_uid> <target_uid> [--expect-source-fingerprint SHA256]  # 高保真複製來源帳號 vocab 層;可 pin 來源避免漂移
ops-edit list-backups <uid>                                      # 列自動備份(最新在前)
ops-edit restore <uid> [--backup <path>]                         # 從備份還原(預設取最新;commit 前先備份當前狀態;會一起回復該 uid 的 users.json config/identity snapshot)
ops-edit world-snapshot [--label LABEL]                          # 建立整個 data_dir world snapshot（users.json + users/* + root DB）
ops-edit world-restore [--snapshot <path>]                       # 回滾整個 world（commit 前先做 pre-restore world backup）

# 高頻 shaping / demo materialize（一次上傳本地 plan，由 runner 在 container 內批次執行）
ops-edit-batch <plan.json>                                      # plan schema=kg.ops_edit_batch.v1；ops 為 argv list

# 所有 --notebook / --to-notebook 接受 notebook id 或 name(自動 name→id 解析,杜絕孤兒卡)。
# link 嚴格 per-notebook:兩端 card 必須與 link 同本(seed/link-add 跨本連結會被擋並提示)。
# scenario 驗證要查 graph 時，讀磁碟 `graph_*.json`，不要信進程內 GraphStore cache。

# seed spec JSON:
#   {"review_anchor"?: "2026-06-06T00:00:00Z",
#    "notebooks":[{"name","color"?,"cover_pattern"?,"sort_order"?,"is_default"?}],
#    "cards":[{"content","meaning","pos"?,"examples"?,"collocations"?,"note"?,"difficulty"?,
#              "mode"?,"root_form"?,"inflections"?,"is_archived"?,"notebook"?,"source"?: VocabSource,
#              "review"?:{"state","interval"?,"anchor"?}                    # legacy：語意態 + anchor 推導時間
#                       |{review_count,review_streak?,lapse_count?,review_interval_hours?,
#                         next_review_at?,last_reviewed_at?,last_review_feedback?}}],  # 計數器直設（world-export 重放面）
#    "links":[{"from","to","kind","confidence","reason","notebook"?}]}      # from/to 用 card content 參照
# review_anchor/anchor 固定 seed 的複習時鐘,行銷 demo 重跑不會因今天日期不同而漂移。
# review 計數器形式：review_count>0 必帶 last_reviewed_at，seed 會用 synthesize_many 確定式合成
# review_events.db（uuid5 去重、重跑冪等）；不可與 state 形式混用。is_default:true 映到既存預設本（改名不增殖）。
# ops-cli world-export 的產物即此 schema：seed→export→seed(新沙盒)→export 兩份 export 相等（可復現地基）。
# 內建行銷 seed: ops/seeds/marketing_demo.json
```

### data_inspect（本地用）

```bash
python3 ops/data_inspect.py [command]
# overview / sample N / gaps / graph / notes / search <keyword> / card <id> / sql "..."
```

## Deploy 機制（standby）

> ✅ `deploy` 已 retarget standby（2026-06-19）。**不再 rsync、不再 fast/full 偵測**。
> ⚠️ `--force-recreate` 在那次 retarget 一併掉了，實為回歸，已於 2026-08-04 回補（IMP-0052）：`/api/system/info` 的版本是 import 時快取的，不強制 recreate 就會出現 VERSION 宣稱新版、容器仍自報舊版的游標分岔。

`deploy` 流程（透傳 `KG_SERVER`）：遠端 `git pull --ff-only` → 寫 `VERSION`（`git rev-parse --short HEAD`，`/api/system/info` 讀此）→ `docker compose up -d --build --force-recreate` → 容器內 health（`api/system/info`）→ 外部 smoke verify（公網三層，非通過自動中止）。

- **migration**：app 啟動自動跑（`migration_version` 暴露於 `/api/system/info`）；`migrate` 子命令降為手動 fallback，deploy 不再自動 migrate/backup。
- `./ops/devops_kg_safe.sh restart` = `docker compose restart`（不 rebuild，程式碼未變時用；health 改打 `api/system/info`）。
- `.env` 改動不能只 restart，容器讀不到新值，需 `deploy`（含 `--build`）。
- 完整服務層程序見 `~/butler/docs/kg-backend-deployment.md` §4.2。

## 高頻操作範例

```bash
# 查用戶額度
./ops/devops_kg_safe.sh ops-cli user-quota <uid>

# 全用戶概覽
./ops/devops_kg_safe.sh ops-cli quota-overview

# 近 24h 活躍用戶
./ops/devops_kg_safe.sh ops-cli active-users 24

# 找含某字串的卡片，byte-exact（首選；免寫 SQL、免處理引號）
./ops/devops_kg_safe.sh ops-cli card-find <uid> chateau

# 對用戶 DB 跑任意 SQL —— transport 已 %q 安全序列化，引號/括號/% 一律可用，
# SQL 字串字面建議用單引號包覆（如 LIKE '%x%'、WHERE word = 'foo'）
./ops/devops_kg_safe.sh ops-cli db-query <uid> "SELECT content, notebook_id FROM card LIMIT 5"

# 單用戶當月 cost by call_type（judge/enrich/translate 拆解，provider-aware）
./ops/devops_kg_safe.sh ops-cli cost <uid> --range month --json

# 全用戶 24h cost 排名
./ops/devops_kg_safe.sh ops-cli cost-overview --range 24h

# 跨用戶一眼體檢（卡數/連結/月花費，含 FLEET TOTAL；--json 2>/dev/null | jq 可機讀）
./ops/devops_kg_safe.sh ops-cli fleet-overview

# 用戶單日 sync 時間線（debug 同步問題：何時建卡/呼叫 API/judge/translate，按時序合併）
./ops/devops_kg_safe.sh ops-cli sync-trace <uid> --date 2026-06-05

# 趨勢：本月成本逐日走勢（文字輸出附 █ trend bar + 滿格基準值；換 calls / active_users 看量能與活躍）
./ops/devops_kg_safe.sh ops-cli timeseries cost --bucket day --range month
# 找斷層：近 30 天哪幾天完全沒人用（--fill-zero 補零，零活動日不再消失）
./ops/devops_kg_safe.sh ops-cli timeseries calls --bucket day --range 30d --fill-zero
./ops/devops_kg_safe.sh ops-cli timeseries active_users --bucket week --range 30d --json 2>/dev/null | jq

# 監控：業務層有沒有東西在壞（errors=失敗 pipeline + judge reject）
./ops/devops_kg_safe.sh ops-cli trends --window 14
./ops/devops_kg_safe.sh ops-cli trends --window 30 --json 2>/dev/null | jq '.total_errors'

# 真火監控：AI 供應商是不是真的壞了（429/5xx/timeout）
./ops/devops_kg_safe.sh ops-cli llm-errors --window 14
./ops/devops_kg_safe.sh ops-cli llm-errors --window 7 --json 2>/dev/null | jq '.total'

# 臨時分析腳本
./ops/devops_kg_safe.sh container-script /tmp/my_script.py

# 部署（自動偵測 fast/full）
./ops/devops_kg_safe.sh deploy

# Logs 台北時區
KG_LOG_TZ=Asia/Taipei ./ops/devops_kg_safe.sh logs 50

# iOS 測試
./ops/ios_test.sh -g "sanitize"     # 跑含 "sanitize" 的 test
./ops/ios_test.sh                    # 跑 unit target
./ops/ios_test.sh --ui --file BooksAndVocabUITests   # .swift 可省；裸型別名亦可
./ops/ios_test.sh --all-targets --timeout 1200  # scheme 全量: unit + UI
./ops/ios_test.sh --unit --lease    # 並行 agent: 自動租 pool 模擬器, 結束釋放
./ops/ios_test.sh --unit --device <udid|name>   # 指定模擬器 (手動並行)
```

## 機器層健康巡檢（infra-health）

`status` 只給單一 HTTP code；要一眼看「機器本身」健不健康（系統資源 + 容器 + Caddy + TLS 憑證 + HTTPS 端點 + 近期錯誤）用 `health`。全唯讀，補 ops-cli（讀業務 DB）看不到的 host 層盲區。

```bash
./ops/devops_kg_safe.sh health          # 人讀：全部指標 + ✓/⚠/✗ + 整體判斷
./ops/devops_kg_safe.sh health --json   # 機讀：純 JSON（診斷走 stderr）
```

- 涵蓋：磁碟/inode/記憶體/Swap、容器健康+重啟+運行時長、CPU/記憶體佔比、**Cloudflare Tunnel 對外入口**（macOS 上沒有 Caddy）、**HTTPS 端點 200 探針**（一次驗 DNS+TLS+Tunnel+FastAPI）、近1h log 錯誤、**TLS 憑證剩餘天數**、資料目錄大小。
- **部署漂移組（IMP-0022）**：`deploy_drift`（生產 clone HEAD vs `origin/prod`，**永不 crit**——release 到 reconciler 收斂之間的 drift 是正常瞬態；`backend/VERSION` 只當 value 裡的資訊欄，因為 ff-only 路徑刻意不寫它）、`reconciler_tick_age_s`（reconciler 心跳年齡，停擺才紅）、`reconciler_poison_active`（最近 poison 是否仍在冷卻窗）。這三項答的是「生產有沒有收斂、自動部署還活著沒」，原本只存在於 launchd err log。整組可由 `KG_HEALTH_DEPLOY_DRIFT=0` 關閉——**`kg_reconcile.sh` 自我 gate 時必須關**，否則構成「release 瞬態 drift → 回滾一次健康部署」的迴圈。
- 刻意**不指標數寫死**：指標筆數隨開關與容器 uptime 是否可解析而變（原文寫死的「14 指標」在加入漂移組後就過期了）。
- 每筆 metric 含 `key/label/value(人讀)/raw(數值，供二次判斷)/status`；頂層 `overall=ok|warn|crit`。
- **exit code 反映嚴重度**：0=ok 1=warn 2=crit → cron 告警直接 `if ! health --json >/tmp/h.json 2>/dev/null; then alert; fi`。
- 閾值可由 env 覆寫（免改腳本）：`KG_HEALTH_DISK_WARN/CRIT`、`..._CERT_WARN/CRIT`、`..._SWAP_WARN/CRIT`、`KG_HEALTH_TICK_WARN/CRIT`（心跳年齡秒，預設 600/1800）等；另有 `KG_HEALTH_DEPLOY_DRIFT`（1/0 開關）、`KG_PROD_REPO`（生產 clone 路徑，由 safe wrapper 注入）、`KG_RECON_POISON_COOLDOWN`（與 reconciler 共用）。

## 快速診斷流程

```bash
./ops/devops_kg_safe.sh health   # 機器層一眼總覽（先跑這個）
./ops/devops_kg_safe.sh status   # HTTP code 決定根因
./ops/devops_kg_safe.sh logs 50
```

```
HTTP 200 → API OK，問題在 iOS App 或 DNS
HTTP 502 → CF 邊緣可達但回源失敗（cloudflared 或 standby 容器 down）→ 三層分層定位
HTTP 000 → DNS / CF 邊緣不可達
DNS fail → DNS issue（注意 NS 遷移期 resolver 快取，見 ~/butler/docs/kg-backend-deployment.md §8）
```

> ⚠ 現役 prod 是 **standby + CF Tunnel**（無 Caddy）。502 分層：先 `--resolve wordnexus.lol:443:104.21.85.113` 直打 CF 邊緣驗服務本身（回 200=只是本機 DNS 快取）；再 `ssh chenliangyu@100.118.39.104` 查容器(`docker ps`)與隧道(`pgrep -lf cloudflared`)。完整除錯走 `docs/sop/debug.md`。下方 `caddy-status`/`caddyfile` 等 typed 指令僅對 Lightsail rollback 有意義。

### 常用 Debug 指令

```bash
# Caddy
./ops/devops_kg_safe.sh caddy-status
./ops/devops_kg_safe.sh caddyfile

# Docker
./ops/devops_kg_safe.sh docker-ps
./ops/devops_kg_safe.sh docker-logs 100

# Resources
./ops/devops_kg_safe.sh disk-usage
./ops/devops_kg_safe.sh memory-usage
./ops/devops_kg_safe.sh docker-stats

# Database
./ops/devops_kg_safe.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db '.tables'"
```

## 緊急恢復（現役 = standby）

```bash
# 標準資料還原走 ops-edit world-restore / restore（容器內，免手動搬檔）。
# 整機級災難（standby 容器/資料壞）→ 從 S3 拉每日備份還原：

# 1. 停容器
ssh chenliangyu@100.118.39.104 'cd ~/project/kg/backend && docker compose stop'

# 2. 備份當前壞資料（標時間戳）
ssh chenliangyu@100.118.39.104 'tar czf ~/broken_data_$(date +%Y%m%d_%H%M).tgz -C ~ kg-data'

# 3. 從 S3 拉某日備份還原（kg-backup-agent 是 PutObject-only，讀取需另一把有 GetObject 的 key）
#    解開到 ~/kg-data/（2026-06-16 移出 worktree），細節見 docs/sop/backup_restore.md

# 4. 起容器 + 驗
ssh chenliangyu@100.118.39.104 'cd ~/project/kg/backend && docker compose up -d && curl -s http://localhost:8000/api/system/info'
```

> 完整還原 SOP（S3 拉取 / WAL 一致性 / 跨主機指令對照）見 `docs/sop/backup_restore.md`。
> Lightsail rollback（起舊站 + DNS 切回）見 `~/butler/docs/kg-backend-deployment.md` §6。

## Scope 邊界(不屬本 skill)

本 skill 只管 **KG backend 生產環境**(`knowledge-graph-api` 容器 / 業務 DB / 用戶 / 額度 / host)。**podcast pipeline 是獨立的 production surface**(本地 `lab/podcast/` workspaces + podcast S3 catalog),不走 `devops_kg_safe.sh`:

- podcast 運維/觀測(workspace 狀態瀑布、failed 根因、逐集 gate、cost、`logs`、workspace↔S3 reconcile)→ **headless `ops/podcast_ops.py`**(免起 dashboard;`status` exit 0/1/2、不存在 dir exit 3),用法見 `docs/sop/podcast_pipeline.md` §5「Headless 觀測 CLI」。
- podcast 生成管線(EPUB→TTS→字幕 15 階段)→ 觸發 `podcast` skill。
- **iOS / App Store Connect 發版**(archive / 文案 metadata / TestFlight / 送審 / 被拒處理)不屬本 skill → 見 `docs/sop/ios.md §發版` + `ops/ios_release.sh`(出 build)+ `ops/asc.sh`(查詢/改文案逐欄)+ `ops/asc_text_bundle.py`(整包文案:`dump -o asc.json` 拉全部文案/審查/訂閱/截圖摘要,編輯後 `apply asc.json [--yes]` dry-run diff→PATCH 低風險文字欄位;不送審/不改價格/不傳截圖)。

## Deep Reference

- 完整部署指南：`docs/sop/deploy.md`
- 除錯指南：`docs/sop/debug.md`

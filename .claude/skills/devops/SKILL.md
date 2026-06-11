---
name: devops
description: "KG 生產環境運維 — 部署、狀態、用戶查詢、額度、遠端操作、系統健康"
allowed-tools: Bash, Read, Grep
---

# KG DevOps Skill

## Identity

| key | value |
|-----|-------|
| server | `ubuntu@13.193.212.134` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |

## 安全規則

1. **生產環境操作前**先跑 preflight：`./ops/devops_kg_safe.sh preflight`
2. **deploy / migration 前**再加 backup：`./ops/devops_kg_safe.sh backup`
3. 禁止封鎖指令：`setup` `push-env` `delete-user` `ssh`、破壞性 `run` 字串

## 指令參考 **(SoT)**

本段為 `./ops/devops_kg_safe.sh`（與 repo-local shortcut `./devops.sh`）的權威指令清單；`docs/sop/deploy.md` / `docs/sop/debug.md` 內任何 `./devops.sh *` 用法以本表為準。
對 `docker ps`、`sudo systemctl status caddy`、`df -h` 這類高頻唯讀 debug 查詢，safe wrapper 已提供 typed 子命令，且 raw `run "<cmd>"` 會直接提示改用 typed surface。

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
ops-cli user-config <uid>                 # user config 唯讀（translation/review_clock/review_mode/vocab_ui active notebook）
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
#    "notebooks":[{"name","color"?,"cover_pattern"?}],
#    "cards":[{"content","meaning","pos"?,"examples"?,"collocations"?,"note"?,"difficulty"?,
#              "mode"?,"notebook"?,"source"?: VocabSource,
#              "review"?:{"state","interval"?,"anchor"?}}],
#    "links":[{"from","to","kind","confidence","reason","notebook"?}]}      # from/to 用 card content 參照
# review_anchor/anchor 固定 seed 的複習時鐘,行銷 demo 重跑不會因今天日期不同而漂移。
# 內建行銷 seed: ops/seeds/marketing_demo.json
```

### data_inspect（本地用）

```bash
python3 ops/data_inspect.py [command]
# overview / sample N / gaps / graph / notes / search <keyword> / card <id> / sql "..."
```

## Deploy 機制

`deploy` 自動偵測改動範圍，決定路徑：

| 偵測結果 | 路徑 | 耗時 |
|----------|------|------|
| 只有 .py / .html / 靜態檔 | **fast**: rsync → restart → health | ~15s |
| Dockerfile / docker-compose / pyproject.toml | **full**: backup（rsync 增量）→ env-check → rsync → build → migrate → health → env-drift | ~2min |
| 無上次 deploy 記錄 / sha 不存在 | **full** | ~2min |

偵測依據：`git diff <last_deploy_sha>..HEAD -- backend/`，last_deploy_sha 來自 `deploy.log`。

- `DEPLOY_FULL=1 ./ops/devops_kg_safe.sh deploy` — 強制完整部署
- `./ops/devops_kg_safe.sh restart` — 最快，僅重啟容器不 rsync（程式碼未變時用）

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
./ops/devops_kg_safe.sh health          # 人讀：14 指標 + ✓/⚠/✗ + 整體判斷
./ops/devops_kg_safe.sh health --json   # 機讀：純 JSON（診斷走 stderr）
```

- 涵蓋：磁碟/inode/記憶體/Swap、容器健康+重啟+運行時長、CPU/記憶體佔比、Caddy、**HTTPS 端點 200 探針**（一次驗 DNS+TLS+Caddy+FastAPI）、近1h log 錯誤、**TLS 憑證剩餘天數**、資料目錄大小。
- 每筆 metric 含 `key/label/value(人讀)/raw(數值，供二次判斷)/status`；頂層 `overall=ok|warn|crit`。
- **exit code 反映嚴重度**：0=ok 1=warn 2=crit → cron 告警直接 `if ! health --json >/tmp/h.json 2>/dev/null; then alert; fi`。
- 閾值可由 env 覆寫（免改腳本）：`KG_HEALTH_DISK_WARN/CRIT`、`..._CERT_WARN/CRIT`、`..._SWAP_WARN/CRIT` 等。

## 快速診斷流程

```bash
./ops/devops_kg_safe.sh health   # 機器層一眼總覽（先跑這個）
./ops/devops_kg_safe.sh status   # HTTP code 決定根因
./ops/devops_kg_safe.sh logs 50
```

```
HTTP 200 → API OK，問題在 iOS App 或 DNS
HTTP 502 → Caddy OK，FastAPI down → 查 Docker logs
HTTP 000 → Caddy down 或 firewall blocking
DNS fail → DNS issue
```

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

## 緊急恢復

```bash
# 1. Stop container
./ops/devops_kg_safe.sh run "cd ~/knowledge_graph_api && docker compose stop"

# 2. Backup broken data
scp -i ~/.ssh/lightsail_default.pem -r \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data \
  ~/Desktop/broken_data_$(date +%Y%m%d_%H%M)

# 3. Restore good backup
scp -i ~/.ssh/lightsail_default.pem -r \
  ~/kg/backups/data_<date> \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data

# 4. Restart
./ops/devops_kg_safe.sh restart
./ops/devops_kg_safe.sh status
```

## Scope 邊界(不屬本 skill)

本 skill 只管 **KG backend 生產環境**(`knowledge-graph-api` 容器 / 業務 DB / 用戶 / 額度 / host)。**podcast pipeline 是獨立的 production surface**(本地 `lab/podcast/` workspaces + podcast S3 catalog),不走 `devops_kg_safe.sh`:

- podcast 運維/觀測(workspace 狀態瀑布、failed 根因、逐集 gate、cost、`logs`、workspace↔S3 reconcile)→ **headless `ops/podcast_ops.py`**(免起 dashboard;`status` exit 0/1/2、不存在 dir exit 3),用法見 `docs/sop/podcast_pipeline.md` §5「Headless 觀測 CLI」。
- podcast 生成管線(EPUB→TTS→字幕 15 階段)→ 觸發 `podcast` skill。
- **iOS / App Store Connect 發版**(archive / 文案 metadata / TestFlight / 送審 / 被拒處理)不屬本 skill → 見 `docs/sop/ios.md §發版` + `ops/ios_release.sh`(出 build)+ `ops/asc.sh`(查詢/改文案逐欄)+ `ops/asc_text_bundle.py`(整包文案:`dump -o asc.json` 拉全部文案/審查/訂閱/截圖摘要,編輯後 `apply asc.json [--yes]` dry-run diff→PATCH 低風險文字欄位;不送審/不改價格/不傳截圖)。

## Deep Reference

- 完整部署指南：`docs/sop/deploy.md`
- 除錯指南：`docs/sop/debug.md`

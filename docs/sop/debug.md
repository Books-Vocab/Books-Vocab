<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - backend/
  - ops/
  - .claude/skills/devops/
verified_against: 2d9f6fdbebca9fe0f2aa9a790f1498dded80050d
-->
# 伺服器排障指南

> ⚠️ **生產禁用指令邊界**：所有 ops 與診斷動作受 [`docs/policy/safety.md`](../policy/safety.md) 約束。`docker compose down -v`、`docker system prune -a`、`rm -rf` 涉及 data dir 一律禁止；診斷可讀不可破壞性清理。
>
> **現況**：正式站是 felix standby，經 Cloudflare Tunnel 對外。host、tunnel、資料與災難重建只以 [`docs/reference/host_topology.md`](../reference/host_topology.md) 及 butler host SOP 為準；本文件只負責排障判讀。

## 現役排障面

服務拓樸與 host identity 不在本文件重複；先讀 host topology，再用
`ops/devops_kg_safe.sh` 的 typed read-only surface。任何需要 restart、deploy、
資料或外部設定的動作都轉交對應 SOP／Release operator。

## Debug evidence contract

先把 failure 分成 static、behavioral/performance、UI/timing 或 infrastructure；能由
code、test、stack、fixture 或 current health 判定的先靜態定位，只有實際行為無法由
靜態資料決定時才加量測。根因證據至少要能連起：reproducer → source/call path 或
measurement → failure signature → 最小修復與 regression test；「看起來應該好了」不是
證據。

行為量測固定走：

1. 寫一條可證偽假設與一個成功簽名，另寫至少兩個失敗簽名及各自下一步。
2. 先只加觀測，不在同一輪同時改行為；由 log、build、simulator/device 或 API health
   取得真實結果。
3. 逐條比對預測；任一 mismatch 就修正模型，不得把 agent 推理當成實測。
4. 兩次推理未命中就停止猜測，轉成可量測的 reproducer；修復仍走 RED → minimal fix → GREEN。

iOS 行為／效能觀測的 code SoT 是
`ios/BooksAndVocab/Services/PerfLog.swift`：高頻事件用 `tick`、狀態邊界用 `mark`、
耗時用 `measure`／`interval`；category 與開關以該實作為準。這些 log 是可重用的
DEBUG-gated evidence infrastructure，不因一次 bug 修好就刪除。Simulator、真機、
backend 與 infra 的具體 capture 命令分別以各 domain SOP／safe wrapper 為準。

非同步測試等待實際條件（event、state、file、health 或 marker），不要用未解釋的
固定 sleep；若測試的就是 timing，才保留有明確理由、上限與 failure signature 的
timeout。多個獨立假說可平行驗證，但每個 agent 必須有不重疊 Scope、自己的 evidence
與結論，不共享未驗證的推測。

資料會跨 entry、domain、environment 或 external boundary 時，在每個安全關卡做必要
驗證，並以測試證明 bypass 會 fail closed。debug receipt 只交付 reproducer、exact
HEAD、commands／exit status、evidence identity、root cause、regression result、
deviation 與下一步；不保存 raw UI video，除非 assignment 明確要求。

---

## 30 秒快速診斷

```bash
# 最快：不需 SSH、不需 auth
curl -s https://wordnexus.lol/api/system/info | uv run --python 3.13 python -m json.tool

# DNS 卡舊 IP 時繞過快取直打 CF 邊緣驗服務本身（回 200 + server:cloudflare + cf-ray = CF→tunnel→standby 全鏈健康）
curl -sD - --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info -o /dev/null

# 直連 standby（繞過 CF，分層定位）
./ops/devops_kg_safe.sh health --json
./ops/devops_kg_safe.sh docker-ps
```

```
公網 HTTP 200 → API 正常，問題在 iOS App 或 DNS 傳播
公網 502/530 但 local:8000 健康 → cloudflared 隧道斷（連接器掛/重連中）
public + local:8000 都掛 → 容器掛 → 看 docker logs
public 失敗但 --resolve 直打 CF 邊緣 OK → 純 DNS 傳播問題（見下方 §DNS）
```

---

## 症狀 → 診斷 → 修復（primary）

### HTTPS 連線失敗（iOS 無法連線）

分層定位：CF 邊緣 → cloudflared 隧道 → 容器。

```bash
# 1. DNS 解析（期望 CF anycast）
dig wordnexus.lol @8.8.8.8 +short        # 應回 104.21.85.113 / 172.67.204.212（CF）
dig wordnexus.lol @1.1.1.1 +short

# 2. 服務本身（繞過 DNS，直打 CF 邊緣）
curl -sD - --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info -o /dev/null
#   回 200 + cf-ray → CF→tunnel→standby 全鏈 OK，問題純在 DNS 傳播
#   回 502/530 → 隧道斷或容器掛，往下查

# 3. host、container、tunnel 的聚合健康
./ops/devops_kg_safe.sh health --json
```

**修復：cloudflared 隧道斷**（local:8000 健康但公網 502/530）
先保存 `health --json` 與 public probe 證據，再依 host／Cloudflare SOP 由
Release operator 或 ops authority 執行；一般 agent 不自行操作 daemon。

**修復：容器掛**（local:8000 不回）
先用 `./ops/devops_kg_safe.sh docker-logs 100` 保存日誌；若需重啟，依
[`docs/sop/deploy.md`](deploy.md) 的批准與 wrapper 邊界執行
`./ops/devops_kg_safe.sh restart`。

> TLS 與 tunnel 的外部設定由 host topology／Cloudflare SOP 承載，本文件不複製設定命令。

---

### API 無回應（HTTP 502 / 530）

```bash
# 先分層：是隧道斷還是容器掛？
./ops/devops_kg_safe.sh health --json
```
- `local:8000` 健康但公網 502/530 → tunnel／edge 路徑問題；保存 health 與 public probe，轉交 host／Cloudflare SOP。
- `local:8000` 也掛 → 先保存 `./ops/devops_kg_safe.sh docker-logs 100`，再依 deploy SOP 判斷 restart、release 或 rollback。

---

### DNS 問題

```bash
dig wordnexus.lol @8.8.8.8 +short
# 期望：CF anycast 104.21.85.113 / 172.67.204.212
# 若回傳非 CF anycast → DNS／Cloudflare route drift，依 host topology 與 Cloudflare SOP 追查
```
- NS 已從 Porkbun 移到 CF（`damien/gabriella.ns.cloudflare.com`）。遷移初期「服務健康但部分用戶 502」多為**純 DNS 委派傳播**（舊 Porkbun NS 殘留舊 apex A，最久卡 24h）。成因鏈與緩解手段（強刷 resolver 快取、`/etc/hosts` 釘 CF IP）見 butler `~/butler/docs/kg-backend-deployment.md §8`。
- **驗服務本身排除 DNS 干擾**：永遠用 `--resolve wordnexus.lol:443:104.21.85.113` 直打 CF 邊緣。

---

## Disaster recovery pointer

排障只能保存 evidence；host 或資料故障的 recovery 依
[`docs/reference/host_topology.md`](../reference/host_topology.md)、
[`docs/sop/backup_restore.md`](backup_restore.md) 與 release SOP 執行。本文件不
提供 recovery、跨主機傳輸或 destructive command。

---

## 症狀 → 診斷 → 修復（平台無關）

> 以下 pipeline／用戶管理／DB 直查統一經 `./ops/devops_kg_safe.sh`；不要繞過 wrapper 直接操作 host。

### Pipeline 卡住

Pipeline 有 per-user `asyncio.Lock`，crash 後可能鎖住。

```bash
./ops/devops_kg_safe.sh restart       # 需依 production safety／批准邊界執行
./ops/devops_kg_safe.sh logs 100       # 找 "pipeline started/completed/locked"
```

**各 Step 常見錯誤**：
```
Step 1 Enrich → Gemini API key 無效/額度用完
  → ./ops/devops_kg_safe.sh env-check

Step 2 Embed+Judge → pending_judge 積累 / judge 全 reject
  → 查 `./ops/devops_kg_safe.sh ops-cli analyze <id> 2` 與 `ops-cli db-query` 的唯讀輸出
  → 查 acceptance rate：admin dashboard 或 /api/admin/stats

```

**Pipeline Telemetry 查詢**：
```bash
# 讀取使用者的分析結果與 pipeline 狀態摘要
./ops/devops_kg_safe.sh ops-cli analyze <id> 2

# 讀取跨資料庫的同步／翻譯追蹤；不要把這些表當成 cards.db 的 db-query
./ops/devops_kg_safe.sh ops-cli sync-trace <id> --json
```

---

## 用戶管理

```bash
./ops/devops_kg_safe.sh users
./ops/devops_kg_safe.sh user-info <user_id>
```

刪除帳號、刪除用戶資料或保留帳號清空資料都不是一般 debug 命令；safe wrapper 預設阻擋。這類不可逆操作必須走對應批准／backup／rollback SOP，由 production authority 執行，不在本文件提供可複製的 destructive command。

---

## 資源診斷

```bash
./ops/devops_kg_safe.sh disk-usage                 # 磁碟
./ops/devops_kg_safe.sh memory-usage --json        # Felix macOS 記憶體 / swap
./ops/devops_kg_safe.sh docker-stats               # 容器資源
./ops/devops_kg_safe.sh docker-ps                  # 所有容器

# 深度日誌
./ops/devops_kg_safe.sh docker-logs 200
./ops/devops_kg_safe.sh logs 200
```

---

## 資料庫直接操作

```bash
./ops/devops_kg_safe.sh ops-cli db-query <uid> "--schema"
./ops/devops_kg_safe.sh ops-cli db-query <uid> "SELECT COUNT(*) FROM card;"
./ops/devops_kg_safe.sh ops-cli user-config <uid> --json
```

---

## Docker 操作

```bash
./ops/devops_kg_safe.sh docker-ps
./ops/devops_kg_safe.sh env-check
./ops/devops_kg_safe.sh status
./ops/devops_kg_safe.sh deploy       # 只有 release／deploy authority 可執行
```

---

## 緊急恢復 SOP

先用 `./ops/devops_kg_safe.sh health --json`、`logs`、`backup` 保存現況；資料恢復依 [`docs/sop/backup_restore.md`](backup_restore.md) 執行，服務／版本回退依 [`docs/sop/deploy.md`](deploy.md) 與 [`docs/reference/host_topology.md`](../reference/host_topology.md) 執行。本文件不提供跨主機 `scp` 或直接刪／覆寫 production data 的命令。

---

## 重要檔案位置

### primary（standby，macOS）
| 檔案 | 路徑 |
|------|------|
| API 代碼 / compose | `~/kg-prod/backend/`（user `chenliangyu`；生產 checkout） |
| API .env | `~/kg-prod/backend/.env` |
| 資料庫 | `~/kg-data/`（felix；2026-06-16 移出 git worktree） |
| cloudflared daemon | `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` |
| backup launchd | `~/Library/LaunchAgents/com.kg.backup.plist`（源 `ops/launchd/com.kg.backup.plist`） |
| TLS 憑證 | 無（CF 邊緣託管） |

> production checkout、data root 與 host path 以 host topology 為準；不要在 dev checkout 執行 production compose。

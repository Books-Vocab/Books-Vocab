---
name: billing
description: "KG 成本/帳單管理 — 月度盤點、cost drift 偵測、Lightsail 升降級評估、Gemini/DeepSeek/AWS 三源對齊。當使用者問「這月花多少」「Gemini 漲了沒」「該降 bundle 嗎」「token 燒多少錢」「帳單」「cost」「billing」「spend」時觸發。read-only 分析+建議,執行交給 devops。"
allowed-tools: Bash, Read, Grep
---

# KG Billing Skill

## Identity

| key | value |
|-----|-------|
| AWS account | `967512079054` |
| GCP billing account(Gemini) | `011E6D-6EE0E0-B1F479` |
| DeepSeek 入口 | `https://platform.deepseek.com/usage`(無 CLI) |
| Lightsail instance | `booksbrowser-kg-api-2gb` @ `small_3_0`(月費 → `cost_baseline.md §1`) |
| Object Storage | `kg-podcasts-prod` @ `medium_1_0`(月費 → `cost_baseline.md §1`)|
| Backup bucket | `kg-backups-prod-967512079054`(S3 Standard) |
| Pricing SoT | `backend/src/kg/llm/providers.py:REGISTRY`(快照在 `cost_baseline.md §2`) |
| Baseline SoT | `docs/reference/cost_baseline.md` |

## 範圍邊界(關鍵)

| 我做 | 我不做 → 找誰 |
|---|---|
| 抓 cost、對 baseline、算 drift、給升降級建議 | **執行** bundle update / restart / 部署 → `devops` |
| LLM 內部 USD 歸因(token×price)、provider 拆解 | 用戶**用量分佈/閾值調優**(產品決策)→ `data-analysis` |
| reconciliation(內部 vs 外部對齊) | 修 token_usage missing rows / providers.py 加 entry → 一般工程 task |
| 月度盤點 SOP 跑完 | CloudWatch alarm 實際設定 → `cost_review.md §4`(ops 動作) |
| 建議「降 small_1_0 省一級」 | 真的去 delete+recreate bucket → `devops` |
| 拉單一用戶 cost 細項(我要寫 reconciliation report) | 跑 `ops-cli cost <uid>` 拆單用戶 → `devops` 已有 |

**核心原則**:本 skill **read-only**,不寫 prod、不改 bundle、不 rotate key。所有建議落地都切 devops 或人工。

### 禁用 verb(任何 prompt 都不該誘導)

`aws lightsail update-bucket-bundle` / `aws lightsail delete-*` / `aws s3 rb` / `aws s3 rm` / `aws iam *` / `aws cloudwatch put-*` / `gcloud billing accounts update` / 任何 `--force` / `--delete`。看到計畫要跑 → 立即停,切 `devops` 並要使用者授權。

## 三類問題的解答 path

### A. 「這月 / 上月花多少?」→ 全棧盤點

完整 SOP 在 `docs/sop/cost_review.md §1`。最小 5 步:

```bash
# 1. Lightsail fixed
aws lightsail get-instances --query 'instances[].[name,bundleId]' --output table
aws lightsail get-buckets   --query 'buckets[].[name,bundleId]'   --output table

# 2. AWS usage-based(只看 S3 / data transfer,Lightsail 在 CE 是 $0)
aws ce get-cost-and-usage --time-period Start=YYYY-MM-01,End=YYYY-MM-01 \
  --granularity MONTHLY --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[*].[Keys[0],Metrics.BlendedCost.Amount]' --output table

# 3. 內部 LLM USD —— 全用戶排名
./ops/devops_kg_safe.sh ops-cli cost-overview --range month --json
# 單用戶細項(reconciliation 用)
curl -fsS "https://wordnexus.lol/api/admin/user-cost-summary?user_id=<uid>&range=month" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# 4. Gemini 外部(GCP 帳單)
gcloud billing accounts list  # 確認 open;細項走 console.cloud.google.com/billing

# 5. DeepSeek 手動(無 CLI)→ 跳 dashboard URL 給使用者
echo "→ 開 https://platform.deepseek.com/usage 抄當月用量"
```

對 `cost_baseline.md §1` 核對 → 用 `§2 回報模板`(cost_review.md)輸出。

### B. 「X 漲了沒?」→ 單服務 drift 偵測

對 baseline §3 表格判斷 soft($20)/hard($25)閾值,或單供應商 > 預期 50%。

```bash
# AWS usage 拆 service 月對月(BSD date,Mac;Linux 用 date -d 對應改)
aws ce get-cost-and-usage --time-period Start=2026-04-01,End=2026-05-01 \
  --granularity MONTHLY --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[*].[Keys[0],Metrics.BlendedCost.Amount]' --output table
aws ce get-cost-and-usage --time-period Start=2026-05-01,End=2026-06-01 \
  --granularity MONTHLY --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[*].[Keys[0],Metrics.BlendedCost.Amount]' --output table
# 月對月推下個窗口時手動換 Start/End,避免跨年算術 bug

# 內部 LLM 月對月(全用戶總額)
./ops/devops_kg_safe.sh ops-cli cost-overview --range 30d --json | jq '.totals // .'
./ops/devops_kg_safe.sh ops-cli cost-overview --range 7d  --json | jq '.totals // .'
```

drift > 閾值 → 切到 `cost_review.md §3 異常追`(service → user → day → endpoint)。

### C. 「該升 / 降 bundle 嗎?」→ 用量 vs bundle 閾值

判準(對 cost_baseline.md §1):

| 訊號 | 動作 |
|---|---|
| Object Storage 連 3 個月用量 < 50% bundle 容量 | 建議降一級;**注意** AWS 月度 bundle 變更上限 1 次,bundle 變動方向錯了要用 delete+recreate workaround |
| Object Storage 任何月 > 80% 容量 | 建議升一級 |
| Instance CPU burst credit 連續壓榨 | 建議升 `small_3_0` → `medium_3_0`($24/mo)|
| Instance disk > 70% 60GB | 同上 |

抓現況:

```bash
# Lightsail bundle 容量
aws lightsail get-buckets --query 'buckets[].[name,bundleId,objectVersioning,resourcesReceivingAccess]' --output table

# Bucket 真實用量
aws s3 ls s3://kg-podcasts-prod/ --recursive --summarize | tail -2
```

**建議的本質**:給出「省 / 多花 $X/mo」+「風險(容量上限、AWS bundle 月變更限制)」+「動作交接點(切 devops 執行)」。

## Reconciliation:內部 vs 外部

`billing` skill 真正的價值。對 baseline §4 表格 — 兩本帳算完 `|drift|`:

- `> 10%` 健康異常 → review `providers.py:REGISTRY` 是否離真實費率太遠 / `token_usage.provider` 是否漏記
- `≤ 10%` → 健康,動作 = 無

不直接寫 db。發現 missing data → 開單給一般工程。

## Graceful fallback

| 失敗模式 | fallback |
|---|---|
| `aws ce` `DataUnavailableException`(剛 enable 24h 內) | 跳過 CE,只用 §A 1+3+4 三源,output 註明「AWS usage 暫不可得」 |
| `gcloud billing` 沒授權 | 跳該步,輸出告訴使用者「需 `gcloud auth login` 或 BigQuery export」 |
| `ADMIN_TOKEN` 未設 | 提示 `cat backend/.env | grep ADMIN_TOKEN`,但**不**自動 echo 出 token |
| DeepSeek 用量需要 | 永遠手動(dashboard URL),不嘗試 scrape |

## 輸出格式

問「花多少」回 `cost_review.md §2 回報模板` 表格。
問「該升降級」回三段:**現況 / 建議 / 風險與交接**。
問「X 漲了沒」回:**baseline / 實際 / drift / 收斂步驟**(若 drift 觸發)。

## Deep Reference

- `docs/reference/cost_baseline.md` **(SoT)** — 月費分解、預算閾值、變更歷史、reconciliation 表
- `docs/sop/cost_review.md` — 完整月度盤點 / 異常追 / CloudWatch alarm SOP
- `backend/src/kg/llm/providers.py` — pricing SoT
- `backend/src/kg/admin_cost_summary.py` — service mapping SoT
- `.claude/skills/devops/SKILL.md` — 執行交接(bundle update 等)

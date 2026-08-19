<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - .claude/skills/billing/
  - docs/reference/cost_baseline.md
verified_against: 2d9f6fdbebca9fe0f2aa9a790f1498dded80050d
-->
# Cost Review SOP — 月度盤點 / drift 觸發 / 異常追

事件觸發 SOP。Baseline 數字、閾值、變更歷史 → `docs/reference/cost_baseline.md` **(SoT)**。本檔只寫**怎麼做**。

## 1. 月度盤點 checklist(月初 < 10 min)

按順序跑,每步對照 `cost_baseline.md`:

### 1.1 Fixed bundle 沒被默默改

正式站運算在 felix standby（CF Tunnel），AWS 固定成本目前只包含仍在用的
Object Storage；standby 運算與 CF Tunnel 不列入 AWS／CE 帳。完整 baseline 以
[`cost_baseline.md`](../reference/cost_baseline.md) 為準。

```bash
aws lightsail get-buckets    --query 'buckets[].[name,bundleId]'   --output table
aws lightsail get-instances --query 'instances[].[name,bundleId,state.name]' --output table
```

期望：provider inventory 與 baseline 一致；bucket bundle 不符或新增固定資源，
都要對照 baseline 變更歷史並追查。

### 1.2 AWS usage-based(僅 S3 backup / data transfer)

```bash
# 上個月 by service
aws ce get-cost-and-usage \
  --time-period Start=<YYYY-MM-01>,End=<下月-MM-01> \
  --granularity MONTHLY --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[*].[Keys[0],Metrics.BlendedCost.Amount]' \
  --output table
```

固定 bundle 不一定會呈現 usage-based 金額；以 provider inventory 與 baseline
對帳，不用 CE 單一來源判斷固定資源。

### 1.3 內部 LLM 歸因

```bash
# 全用戶排名(provider × call_type × USD)
./ops/devops_kg_safe.sh ops-cli cost-overview --range month --json
# 單用戶細項(reconciliation / 異常追用)
curl -fsS "https://wordnexus.lol/api/admin/user-cost-summary?user_id=<uid>&range=month" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

兩個入口分工:cost-overview 排名找「誰吃最兇」;cost-summary endpoint 拆單一 user 的 service/model breakdown。

### 1.4 Gemini 外部帳單(GCP)

```bash
gcloud billing accounts list   # 確認 011E6D-6EE0E0-B1F479 仍是 open
# 該帳號當月 BigQuery export(若有設):查 export 表
# 否則直接 console.cloud.google.com/billing 看
```

### 1.5 DeepSeek 外部帳單(無 CLI)

登 `https://platform.deepseek.com/usage` 抄當月用量。**不寫進 cost_baseline.md**(那是 baseline doc 不是月度日誌);**只用於對齊 1.6 reconciliation**。drift > 10% 才追,否則記在當次 review 報告即可,過月即棄。**判斷寫 scraper 的條件**:連續 3 個月內部歸因與 dashboard 差 > 20% 才值得;否則手填 30 秒搞定。

### 1.6 Reconciliation

對照 cost_baseline.md §4 表格:

```
內部歸因(§1.3 jq 加總)vs 外部帳單(§1.2 + §1.4 + §1.5)
```

`|drift| ≤ 10%` 健康,結束。
`|drift| > 10%` → §3「異常追」。

## 2. 回報模板(skill 跑完盤點時 output)

```
## Cost Review YYYY-MM

| 服務 | Baseline | 實際 | drift |
|---|---:|---:|---:|
| Object Storage    | $3.00  | $X | … |
| S3 backup         | ~$0    | $X | … |
| Gemini (內部)     | —      | $X | — |
| DeepSeek (內部)   | —      | $X | — |
| Gemini (GCP 帳單) | —      | $X | … |
| **總計**          | **$Y** | **$Y'** | … |

Reconciliation: 內部 $A vs 外部 $B,drift Δ%(<10% = 健康)

## 動作
- [ ] baseline 仍對齊?是 / 否
- [ ] 任何 drift > 閾值?是 / 否(若是,列追蹤項)
```

## 3. 異常追:某項突然漲怎麼收斂

**順序**:服務維度 → 用戶維度 → 時間維度 → endpoint。

### 3.1 哪個 service 漲?

```bash
# 全用戶排名(看哪個 call_type 總體在漲)
./ops/devops_kg_safe.sh ops-cli cost-overview --range 30d --json | jq '.by_service // .'
# 鎖定可疑 user 後拆細
curl -fsS "https://wordnexus.lol/api/admin/user-cost-summary?user_id=<uid>&range=30d" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.by_service'
```

### 3.2 哪個用戶吃最兇?

```bash
./ops/devops_kg_safe.sh ops-cli cost-overview --range month --json
```

(走 devops skill;billing 不直連 prod)

### 3.3 哪天開始漲?

```bash
./ops/devops_kg_safe.sh ops-cli db-query <uid> \
  "SELECT date(created_at) d, call_type, sum(input_tokens+output_tokens) t \
   FROM token_usage WHERE created_at >= date('now','-30 days') \
   GROUP BY d, call_type ORDER BY d, t DESC"
```

### 3.4 哪個 endpoint?

`call_type` 已映射到 service(`_SERVICE_MAP`)— 對應 router 看 `docs/reference/tech_index.md §Backend API Routers`。

## 4. Billing alarm

本專案目前沒有在 billing skill 內建立或修改外部 alarm。若要新增 alarm，
先建立 GitHub Issue／assignment，交由 devops／帳號 owner 依外部 provider
SOP 執行；本 read-only review 不提供可直接貼上的 SNS／CloudWatch 寫入命令。

## 5. 與其他 SOP 的關係

- **執行**(provider／host／secret／retention 變更)走對應 release／devops／backup SOP。本 SOP 只決定**該不該做**。
- **backup cost** 走 `docs/sop/backup_restore.md` 的 retention policy，本檔不重複。
- **用戶配額調整**(額度上限)不在 cost 範疇,走 `data-analysis` skill。

<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - .claude/skills/billing/
  - docs/reference/cost_baseline.md
verified_against: 23521f39
-->
# Cost Review SOP — 月度盤點 / drift 觸發 / 異常追

事件觸發 SOP。Baseline 數字、閾值、變更歷史 → `docs/reference/cost_baseline.md` **(SoT)**。本檔只寫**怎麼做**。

## 1. 月度盤點 checklist(月初 < 10 min)

按順序跑,每步對照 `cost_baseline.md`:

### 1.1 Lightsail fixed bundle 沒被默默改

> **過渡狀態（2026-06-15 起）**：正式站運算已遷到家用 standby（CF Tunnel）。Lightsail instance **STOP 未 terminate**，**STOP 期間仍計 fixed bundle $12/mo**，故下方查詢仍會列到 `booksbrowser-kg-api-2gb`，且仍要盤點（過渡期 baseline 仍含此 row）。standby 運算/CF Tunnel 不在 AWS/CE 帳（家用沉沒成本，見 `cost_baseline.md §1`）。**Lightsail terminate 後** instance row 會消失、fixed 小計降到 $3——屆時對照 `cost_baseline.md` 已更新的下修值，不要把「instance 消失」誤判為異常。

```bash
aws lightsail get-instances --query 'instances[].[name,bundleId,state.name]' --output table
aws lightsail get-buckets    --query 'buckets[].[name,bundleId]'   --output table
```

期望(過渡期):`booksbrowser-kg-api-2gb=small_3_0`(state `stopped`) / `kg-podcasts-prod=medium_1_0`。bundle **不一致 = baseline §5 沒記錄的變更,立刻追**;instance 已 terminate 且 baseline §5 已記錄遷移 = 正常。

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

**Lightsail 在 CE 回 $0 是正常的**(fixed bundle 不走 usage-based);只看 `Amazon Simple Storage Service` / `AWS Data Transfer`。

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
| Lightsail Instance | $12.00 | $X | … |
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

## 4. CloudWatch billing alarm(尚未設定 — TODO)

設定步驟(下次盤點時做掉):

```bash
# 1. 在 us-east-1(billing metric 唯一所在 region)建 SNS topic
aws sns create-topic --name kg-billing-alert --region us-east-1

# 2. 訂閱 email
aws sns subscribe --topic-arn <ARN> --protocol email \
  --notification-endpoint max970228@gmail.com --region us-east-1

# 3. 確認郵件(收件匣按 Confirm subscription)

# 4. 建 alarm @ $25 hard
aws cloudwatch put-metric-alarm --region us-east-1 \
  --alarm-name kg-monthly-cost-25 \
  --metric-name EstimatedCharges --namespace AWS/Billing \
  --statistic Maximum --period 21600 --evaluation-periods 1 \
  --threshold 25 --comparison-operator GreaterThanThreshold \
  --dimensions Name=Currency,Value=USD \
  --alarm-actions <SNS_ARN>
```

確認 alarm:`aws cloudwatch describe-alarms --alarm-names kg-monthly-cost-25 --region us-east-1`

## 5. 與其他 SOP 的關係

- **執行**(bundle 升降、key rotate、刪 snapshot)走 `docs/sop/deploy.md` / `devops` skill。本 SOP 只決定**該不該做**。
- **backup cost**(年度清舊版 ~$3/年動作門檻 $10/月)走 `docs/sop/backup_restore.md §7`,本檔不重複。
- **用戶配額調整**(額度上限)不在 cost 範疇,走 `data-analysis` skill。

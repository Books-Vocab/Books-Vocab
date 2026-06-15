<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - .claude/skills/billing/
  - docs/sop/cost_review.md
  - backend/src/kg/llm/providers.py
verified_against: d67bed12
-->
# Cost Baseline (Single Source of Truth)

每月各服務基準月費 + 預算上限 + drift 閾值。**任何 bundle 升降級、新供應商接入、定價變動,同 PR 必須更新此檔**。skill `billing` 與 SOP `cost_review.md` 對照本檔判斷是否漂移。

> **過渡狀態（2026-06-15 起）**：正式站運算層遷到家用常駐機 `standby`（電力/網路為家用沉沒成本，不計入本表）。Lightsail instance **STOP 未 terminate**（保留 1-2 週當 rollback），**STOP 期間仍計 fixed bundle ~$12/mo**（terminate 才停 billing）。故過渡期實際 fixed 月費 = $15（沿用下表，instance 仍計費）+ standby 家用電費（不入帳）。terminate Lightsail 後 fixed 小計 → $3（僅 Object Storage）。**過渡窗仍走下表，不下修**——下修時機 = Lightsail terminate 決策落地時，屆時同 PR 更新 §1 與 §5。

## 1. 月度基準成本表(2026-06，過渡期)

| 服務 | 帳戶 / SKU | 規格 | 月費 (USD) | 計費模型 | 查詢入口 |
|---|---|---|---:|---|---|
| Lightsail Instance | AWS `967512079054` / `booksbrowser-kg-api-2gb` | `small_3_0`(2 GB RAM / 60 GB SSD / 3 TB transfer)；**STOP/rollback，仍計費** | **$12.00** | Fixed bundle | `aws lightsail get-instances` |
| Lightsail Object Storage | AWS `967512079054` / `kg-podcasts-prod` | `medium_1_0`(100 GB / 250 GB transfer) | **$3.00** | Fixed bundle | `aws lightsail get-buckets` |
| S3 backup | AWS `967512079054` / `kg-backups-prod-967512079054` | Standard,daily tar+gz（**現由 standby launchd 跑**，bucket 不變） | **~$0** | Usage(預估首年 < $1/月,容量極小)| `aws s3 ls --summarize` / `aws ce` |
| standby 運算 | 家用 `chenliangyusAir`（M3）+ Cloudflare Tunnel（free tier） | 自託管 | **不入帳**（家用電費沉沒成本；CF Tunnel free） | — | — |
| Gemini LLM | GCP billing `011E6D-6EE0E0-B1F479` | Per-token usage | **變動,見 §2 內部歸因** | Usage,無 fixed | `gcloud billing` / 自家 `/api/admin/user-cost-summary` |
| DeepSeek LLM | DeepSeek dashboard | Per-token usage | **變動,見 §2 內部歸因** | Usage,無 fixed | Dashboard 手動(無 CLI) |
| **Fixed 小計（過渡期）** | | | **$15.00** | | terminate Lightsail 後 → **$3.00** |

**$15/月 = 過渡期月底之前一定會繳的底**（Lightsail STOP 仍計費）。terminate Lightsail 後降到 $3/月（僅 Object Storage）。LLM 是「用越多繳越多」,單獨追蹤(§2)。

### Lightsail 不走 Cost Explorer 的陷阱

`aws ce get-cost-and-usage` 對 Lightsail fixed bundles 回 **$0**(usage-based 才會出現)。這是 AWS 設計,不是 bug。要看 Lightsail 帳要走 `get-instances` / `get-buckets` 對照本表,**不要**靠 CE。

## 2. LLM 內部歸因(自家算的 USD)

| Provider | Pricing 快照(USD per M tokens) | 來源 |
|---|---|---|
| Gemini | input **$0.10** / output **$0.40** / embed **$0.00025** | `backend/src/kg/llm/providers.py:REGISTRY` |
| DeepSeek | input **$0.14** / output **$0.28** / embed n/a | 同上 |

**SoT 在 `backend/src/kg/llm/providers.py:REGISTRY`**。改價必須同 PR 同步此快照(`update_trigger: code-change` 覆蓋此項)。

查當月內部歸因:

```bash
curl -fsS https://wordnexus.lol/api/admin/user-cost-summary?range=month \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
# 或對單用戶
curl -fsS "https://wordnexus.lol/api/admin/user-cost-summary?user_id=<uid>&range=month" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

Service mapping(call_type → service):`backend/src/kg/admin_cost_summary.py:_SERVICE_MAP` SoT,目前 `translate / judge / pipeline / other`。

## 3. 預算上限與告警閾值

| 觸發 | 閾值 (月度,USD) | 動作 |
|---|---:|---|
| Soft watch(調查) | **$20** | 跑 `cost_review.md` 完整盤點,找 drift 來源 |
| Hard alert(立即) | **$25** | 暫停所有 LLM provider 任務,進 prod 抓 24h cost-overview |
| 任何單一供應商 > 預期 50% | — | 內部 vs 外部 reconciliation(見 §4) |
| 新供應商月費 > $1 | — | 開單評估 ROI,baseline 加 row |

**$25 hard alert 目前靠人工月度盤點,CloudWatch alarm 尚未設定**;設定步驟見 `docs/sop/cost_review.md §4`。在 alarm 上線前,本檔 §3 的閾值僅作為盤點時的判斷基準,不會自動觸發任何告警。

## 4. Reconciliation:內部 vs 外部對齊

`billing` skill 的核心:兩本帳對得起來才能信任數字。

```
內部帳  = sum(token_usage rows × REGISTRY pricing)  ← curl /api/admin/user-cost-summary
外部帳  = aws ce + gcloud billing                    ← CLI
```

| Drift | 含義 | 動作 |
|---|---|---|
| `內部 > 外部 + 10%` | over-estimate,REGISTRY 費率高於實際(供應商有 free tier / 折扣) | review `providers.py` |
| `內部 < 外部 - 10%` | 漏記 — 某 provider 沒寫 `provider` column,或基礎設施 cost 沒納入 | 補 baseline non-LLM 段 / 補 `token_usage.provider` |
| `\|drift\| ≤ 10%` | 健康 | 不動 |

## 5. 變更歷史

每次 bundle 動 / 新供應商 / 定價變動,append 一行(永不刪除,讓未來 drift 追溯可追)。

| 日期 | 變更 | 月費影響 | 原因 / commit |
|---|---|---:|---|
| 2026-06-15 | 正式站運算遷到家用 standby（Cloudflare Tunnel）；Lightsail instance **STOP 未 terminate** 當 1-2 週 rollback | 過渡期 **$0**（STOP 仍計 $12，terminate 後才 -$12 → fixed 降到 $3）；standby 電費不入帳 | 自託管降本 + 脫離 Lightsail；S3 backup 改 standby launchd（bucket 不變）。host topology SoT 見 `host_topology.md` |
| 2026-06-01 | Object Storage 由 `small_1_0`($1)→ `medium_1_0`($3) | +$2 | Track B 上線,5 GB 太緊。**delete+recreate workaround**(AWS 月度 bundle 變更限制)|
| 2026-06-01 | Lightsail 手動 snapshot `kg-upgrade-20260412` 刪除 | -$2 | 對應已不存在的 `micro_3_0` instance,屬殘留 |
| 2026-05-30 | S3 backup bucket 上線(versioning + MFA Delete,無 lifecycle)| ~$0 起步,**約 1-2 年後手動清** | 替代 server 端 rm-rf 風險;見 `backup_restore.md §7` |

## 6. 未涵蓋(known gaps)

- **DeepSeek 無 CLI**:外部帳單只能 dashboard 看(`https://platform.deepseek.com/`),月初手動填入本檔附錄(若值得追)
- **GCP 非 Gemini 服務**:目前無;若未來加 Vertex AI / Cloud Run,在 §1 開 row
- **OpenAI / Anthropic**:目前未接;接入時 `providers.py:REGISTRY` 加 entry + 本檔 §2 加 row
- **iOS App Store 收入**:不在 cost 範疇,billing skill 不處理

## 相關

- `.claude/skills/billing/SKILL.md` — 查詢/盤點/reconciliation 工作流
- `docs/sop/cost_review.md` — 月度盤點 SOP / 異常處理
- `backend/src/kg/llm/providers.py` — pricing SoT
- `backend/src/kg/admin_cost_summary.py` — service mapping SoT
- `docs/sop/backup.md` — L3 S3 cost 互引本檔

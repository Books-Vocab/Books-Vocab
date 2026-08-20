<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/app_middleware.py
  - backend/src/kg/routers/external_api.py
  - backend/src/kg/external_api_keys.py
  - backend/src/kg/external_api_rate_limit.py
  - backend/src/kg/api_models/external_api.py
verified_against: c879c37d916f57db87179ba35ca61db345a7ff87
-->
# External API v1

這是 Pro 使用者的外部整合面。它共用 `CardStore`、既有 vocab handlers、review service 與 pipeline runner；不直接暴露 `ops_cli`／`ops_edit`。後兩者是內部 control plane，可跨使用者查詢、dry-run、backup、restore 或改寫 users/world，不是使用者權限模型。

## Authentication

先用正常 JWT 呼叫 `POST /api/v1/api-keys` 建立 key：

```json
{"label":"reader automation"}
```

plaintext `apiKey` 只在建立回應出現一次；伺服器只保存雜湊。之後所有 v1 card/enrich request 使用：

```http
X-KG-API-Key: kg_<key-id>.<secret>
```

建立與使用都即時檢查 Pro entitlement。Pro 到期後既有 key 也不能使用；`DELETE /api/v1/api-keys/{key_id}` 仍允許用 JWT 撤銷 key。

## Reader queue and upload

閱讀器選字先建立本地 `pending + add` card，不會因此出現在外部 API 或伺服器。推薦 client 行為：

1. 使用者按「上傳」時立即送一批，或本地佇列累積 5 張／最長 60 秒自動 flush。
2. 每筆帶穩定的 `clientId`；伺服器回傳同一筆的 `clientId` 與權威 `card.id`。
3. 只有收到 `card.id` 才把本地項目標成 `synced` 並出列；網路錯誤、429、5xx 保持 pending/failed，下一輪重試。
4. 重試依 `(content, notebookId)` 去重；同一張卡已存在時回 `created: false` 與既有 `card.id`，不靠文字比對收斂。

`POST /api/v1/cards` 是單筆上傳；`POST /api/v1/cards/batch` 一次最多 100 筆。`meaning` 可以是空字串，代表先捕捉、之後再 enrich。欄位是 plain text，不需要 template，也不解析 Markdown。

## Endpoints

| Method | Path | 用途 |
|---|---|---|
| POST/GET | `/api/v1/api-keys` | 建立／列出自己的外部 key（JWT） |
| DELETE | `/api/v1/api-keys/{key_id}` | 撤銷自己的 key（JWT） |
| GET/POST | `/api/v1/notebooks` | 列出／建立自己的 notebook |
| PATCH/DELETE | `/api/v1/notebooks/{notebook_id}` | 修改／刪除自己的 notebook |
| POST | `/api/v1/cards` | 單筆 capture/upload |
| POST | `/api/v1/cards/batch` | 本地佇列批次 upload |
| GET | `/api/v1/cards` | 分頁／`since` 拉取卡片 |
| GET | `/api/v1/cards/{card_id}` | 讀取 enrich 後的完整卡片與 links |
| PATCH | `/api/v1/cards/{card_id}` | 修改 meaning、pos、note、examples、collocations、mode |
| POST | `/api/v1/cards/{card_id}/archive` | 封存／取消封存 |
| DELETE | `/api/v1/cards/{card_id}` | soft delete |
| POST | `/api/v1/cards/{card_id}/review` | 推送一筆 SRS/review state |
| GET/POST | `/api/v1/links` | 讀取／建立手動 graph link |
| PATCH/DELETE | `/api/v1/links/{link_id}` | hide、unhide 或刪除 link |
| POST | `/api/v1/enrich` | 排入 notebook 的 enrich → embed → judge → difficulty pipeline |
| GET | `/api/v1/operations/{operation_id}` | 查詢一次 enrich operation |
| GET | `/api/v1/enrich/runs` | 查詢最近 enrich runs |

## Enrich lifecycle

`POST /api/v1/enrich` 回 `202` 與 `operationId`。pipeline 開始後，operation ID 同時是既有 `pipeline_runs.run_id`，所以 client 可以查到 `running`、`succeeded`、`failed`、`quota_exhausted` 或 `interrupted`，不需要解析 log；pipeline 尚未開始時會先回 `queued`。目前 queue 狀態是單一 process 的短期記憶，若服務在 background task 開始前重啟，client 應把該批視為未確認並依 `clientId` 重試。enrich 完成後，client 通常依序：

1. `GET /api/v1/operations/{operation_id}` 確認 terminal status。
2. `GET /api/v1/cards/{card_id}` 或用 `GET /api/v1/cards?since=...` 取得 meaning/pos/note/collocations/difficulty/links。
3. 用 `PATCH` 修正內容；用 archive/delete 控制卡片生命週期；用 review endpoint 同步複習狀態。

## Rate limits

每支 API key、每個類別使用 process-local sliding window；回應包含 `X-RateLimit-Limit`、`X-RateLimit-Remaining`、`Retry-After`。預設值：read 120/60s、write 30/60s、enrich 5/300s；手動建立 graph link 也屬於 enrich 類別，因為會呼叫 LLM judge。可用 `KG_EXTERNAL_API_*` 環境值調整；目前部署是 single-worker，未來多 worker 前必須改 shared limiter。

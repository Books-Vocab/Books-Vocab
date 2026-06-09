# Books & Vocab Backend — FastAPI 服務

這是一個以 SQLite 為核心的單字學習系統後端，整合了知識圖譜 (Knowledge Graph)、LLM 增強內容 (Gemini 2.5 Flash Lite)、向量編碼 (Embeddings)、以及自動化難度標記系統。支援多用戶沙盒隔離、背景 Pipeline、增量同步機制。

## Backend Layout

- `src/kg/api.py`: app composition root + legacy compatibility surface
- `src/kg/route_registration.py`: 集中 router wiring，降低 `api.py` 組裝噪音
- `src/kg/route_registration.py`: 集中 route registration，避免 handler 與 decorator 混在一起
- `src/kg/*_service.py`: translate / auth / vocab / pipeline / billing 等業務邏輯
- `tests/test_api_module_compat.py`、`tests/test_api_startup_smoke.py`、`tests/test_route_registration.py`: 重構遷移的 guardrails

> 💡 **後端開發入口**：部署、測試、格式規範與 debug 路徑，請先看：[👉 `../docs/sop/backend.md`](../docs/sop/backend.md)
>
> 💡 **完整系統架構**：有關 Books & Vocab backend 如何與 iOS 前端 (Books & Vocab app) 透過 REST API 進行離線同步、多帳號授權、與帳戶隔離的技術細節，請參見：[👉 `../docs/sop/architecture.md`](../docs/sop/architecture.md)

## 快速啟動

```bash
# 複製 .env 範本並填入系統層必要變數（例如 GEMINI_API_KEY）
cp .env.example .env

# 本地開發（需要 Python 3.11+）
python -m venv .venv
source .venv/bin/activate  # or `activate` on Windows
pip install -r requirements.txt
uvicorn src.kg.api:app --reload --port 8000

# Docker 部署（推薦用於生產環境）
docker compose up -d --build
```

詳細部署步驟請見 [`../docs/sop/deploy.md`](../docs/sop/deploy.md)。

## API 與多用戶架構 (Multi-User)

為了支援多設備與多人共用伺服器，本系統已經支援**多帳戶資料隔離 (User Sandboxing)**。

### 認證機制

所有 API 端點都要求在 HTTP Header 中傳入 `Authorization: Bearer <user_id>`：
```
Authorization: Bearer chen  # 自訂 User ID
Authorization: Bearer google-oauth2|1234567890  # Google Sign-In ID
```

後端透過 `get_current_user` 依賴注入攔截所有請求，並自動：
1. 驗證 Token 非空
2. 建立 `data/users/<user_id>/` 沙盒目錄
3. 在該用戶的資料目錄內執行所有操作（資料庫、圖譜、嵌入向量等）

### 用戶目錄結構

```
data/users/
├── users.json                    # 全域用戶索引與 per-user config
├── chen/
│   ├── cards.db                 # SQLite 卡片資料庫
│   ├── graph.json               # 知識圖譜連結
│   ├── candidates.json          # 待評估的相似度候選對
│   ├── embeddings.npy           # 向量嵌入矩陣
│   └── card_ids.json            # 向量 ID 映射表
└── alice/
    └── [同樣的結構]
```

### 後台任務管理

`/api/pipeline` 採用 **Fire-and-Forget** 模式：
- 呼叫後**立即回傳** `{"status": "queued"}`
- 伺服器在背景獨立處理三步 Pipeline（Enrich → Link → Difficulty）
- 每個用戶有專屬的 `asyncio.Lock` 確保同時只有一個 Pipeline 在執行，避免競態
- 目前沒有對外暴露 SSE pipeline step stream；前端以本地同步步驟為主，遠端處理完成後再透過 pull 合併結果

## 資料庫架構 (SQLite 遷移)

### 從 JSON 到 SQLite

自 `2026-02-24` 起，本系統已完全遷移至 **SQLite**：

| 層面 | 舊架構 (JSON) | 新架構 (SQLite) | 優勢 |
|------|-------------|----------------|------|
| **卡片儲存** | `cards.json` | `cards.db` | 支援複雜查詢、效能更佳、避免全量載入 |
| **欄位** | 扁平的 JSON 物件 | 結構化 SQLModel | 強型別、易於版本遷移 |
| **軟刪除** | 無法精確追蹤 | `is_deleted` 布林欄位 | 精確同步刪除狀態 |
| **時間戳** | `updated_at` 紀錄不完整 | 每次修改自動更新 | 支援增量同步 |

### Card 資料模型

```python
class Card(SQLModel, table=True):
    id: str = Field(primary_key=True)
    content: str  # 單字
    meaning: str  # 中文意思
    pos: str | None  # 詞性
    note: str | None  # 筆記
    examples: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    difficulty: float | None  # Zipf 值
    mode: str = "recognition"  # recognition | production
    is_deleted: bool = False  # 軟刪除標記
    created_at: datetime
    updated_at: datetime  # 用於增量同步
```

### 5. Difficulty Scoring (難度分級)

傳統的固定 Zipf 閾值 (5.0/4.0/3.0) 會導致不均勻分布（rare 和 advanced 佔絕大多數）。本系統採取以下優化策略：

#### 策略：校準後的固定閾值 (Calibrated Static Thresholds)
為了兼顧「分布均勻」與「標籤穩定性」，我們不採用每秒都在變動的動態計算，而是定期進行校準並寫死閾值：
1.  **校準 (Calibration)**: 對現有字庫計算 25th / 50th / 75th 百分位數。
2.  **固定 (Static)**: 將校準結果寫入 `difficulty.py` 的 `TIERS` 設定中。
3.  **效益**: 確保四個 tier 分布接近 1:1:1:1，同時保證新增單字時，不會因為字庫分布微調而導致數百張舊卡的標籤在同步時發生變動。

**目前校準值 (2026-02-24, 基於 191 詞庫):**
*   `rare`: < 2.55
*   `advanced`: 2.55 ~ 3.01
*   `intermediate`: 3.01 ~ 3.44
*   `core`: ≥ 3.44

> **注意**: 這反映的是**相對難度**。如果你希望手動重新校準，可執行 `kg difficulty --dynamic` 獲取建議值並手動更新。


## REST API 端點參考

### 認證 & 基礎

```
GET /api/health
```
傳回伺服器狀態、該用戶的卡片數量、圖譜連結數等。

### 生詞管理

```
GET /api/vocab[?since=<ISO8601>]           # 列出所有卡片，可選增量同步
GET /api/vocab/{word}                      # 查詢單字
POST /api/vocab                            # 批量新增卡片（自動計算嵌入向量）
DELETE /api/vocab/{word}                   # 刪除卡片
```

### 翻譯端點（新增）

```
POST /api/translate/quick
  Request: {"word": "evoke", "context": "..."}
  Response: {"t": "喚起", "p": "v."}

POST /api/translate/explain
  Request: {"word": "evoke", "context": "..."}
  Response: {"e": "在語境中意思是..."}
```

這兩個端點由 iOS 前端直接呼叫，透過 Gemini API 進行翻譯。

### 知識圖譜

```
GET /api/graph/links                       # 取得所有圖譜連結（用於視覺化）
POST /api/pipeline                         # 觸發背景 Pipeline
```

`/api/graph/links` 回傳所有 `status == "active"` 的連結，結構如下：
```json
{
  "id": "link_uuid",
  "fromId": "card_id_1",
  "toId": "card_id_2",
  "kind": "synonym|confusion|etymology",
  "confidence": 0.85,
  "reason": "兩個單字都與金錢相關..."
}
```

## Development

*   **API 伺服器**: `src/kg/api.py` - FastAPI 端點與多用戶隔離邏輯。
*   **Difficulty**: `src/kg/difficulty.py` - Zipf 評分 + 動態百分位計算。
*   **Enrich & Judges**: `src/kg/enrich.py` & `src/kg/judge.py` - LLM Prompt (使用 `gemini-2.5-flash-lite`, batch 20, 5 workers)。
*   **Embedding**: `src/kg/embeddings.py` - 使用 `gemini-embedding-001` (768維) 進行語意相似度檢索。

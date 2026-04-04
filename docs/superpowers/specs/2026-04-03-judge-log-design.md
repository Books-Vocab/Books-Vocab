# Judge Log — 設計文件

## 問題

Pipeline 的 judge 階段只保留「通過」的連結（寫入 graph JSON），被拒絕的決策完全消失。這導致：

1. **Confidence 分布不完整** — 只看得到 ≥ 0.7 的，無法評估門檻是否合理
2. **拒絕率只能間接推算** — `token_usage` judge call count - graph link count，不精確
3. **閾值調優無法回測** — 無法回答「如果門檻從 0.7 降到 0.6 會多幾條連結」
4. **無法做回播動畫** — 缺少被拒 pair 的時間戳和 similarity

## 決策

| 決策 | 選項 | 理由 |
|------|------|------|
| token_usage 是否加 notebook_id | **不加**（方案 B） | token_usage 的核心用途是額度計費（per-user），分析重點在 judge 決策 |
| 存儲方式 | SQLite 新表 | 與 token_usage.db 一致，支援 SQL 查詢 |
| 放哪個 DB | `judge_log.db`（獨立） | 避免與計費 DB 耦合，可獨立備份/清理 |
| 記錄哪些 judge | 自動 + 手動 | ManualLinkJudge 也記，always accepted 但有 kind/reason 分析價值 |

## Schema

```sql
CREATE TABLE judge_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    from_id TEXT NOT NULL,       -- card ID
    to_id TEXT NOT NULL,         -- card ID
    similarity REAL,             -- embedding cosine similarity（candidate 階段）
    verdict TEXT NOT NULL,        -- 'contrasts_with' | 'shares_usage' | 'not_applicable'
    confidence REAL NOT NULL,     -- judge 原始分數 0.0-1.0
    accepted INTEGER NOT NULL,    -- 1=寫入 graph, 0=被拒
    reject_reason TEXT,           -- 'low_confidence' | 'not_applicable' | 'parse_error' | NULL
    reason TEXT,                  -- judge 的繁中解釋（通過時才有）
    source TEXT NOT NULL DEFAULT 'auto',  -- 'auto' | 'manual'
    created_at TEXT NOT NULL
);

CREATE INDEX idx_jl_user_nb ON judge_log(user_id, notebook_id);
CREATE INDEX idx_jl_created ON judge_log(created_at);
```

## 改動範圍（基於 382a2cb batch mode）

### 1. 新增 `judge_log.py`

- Singleton pattern（同 token_tracker），獨立 DB `judge_log.db`
- `record(*, user_id, notebook_id, from_id, to_id, similarity, verdict, confidence, accepted, reject_reason, reason, source)` 函數
- `get_log(user_id, *, notebook_id=None, limit=1000)` 查詢
- Thread-safe（`threading.Lock`）、WAL mode、busy_timeout

### 2. 修改 `judge.py`（batch mode）

**`_parse_batch_response(content, candidates, raw_decisions=None)`**：
- 新增 optional `raw_decisions: list[dict] | None` side-channel 輸出參數
- 在每個決策點（accept / not_applicable / low_confidence / parse_error / no_response / invalid_kind），if `raw_decisions is not None`，append `{to_id, verdict, confidence, accepted, reject_reason, reason}`
- **回傳值不變**

**`Judge.__init__`** 新增 `user_id`, `notebook_id` keyword-only args。

**`Judge._call_batch` / `evaluate_batch`** 新增 `from_id`, `similarities` 參數：
- 在 `_call_batch` 內用 `raw_decisions=[]` 呼叫 `_parse_batch_response`
- Parse 完後 iterate raw_decisions，呼叫 `judge_log.record()`
- similarity 從 `similarities` dict 查對應 to_id

**`Judge.evaluate`**（thin wrapper）轉發 `from_id`, `to_id`, `similarity`。

**`ManualLinkJudge.__init__`** 新增 `user_id`, `notebook_id`。
**`ManualLinkJudge.evaluate`** 新增 `from_id`, `to_id`，每個 return 前 log（source='manual'）。

### 3. 修改 callers

**`pipeline_service.py:175`**：Judge 建構傳入 `user_id=uid, notebook_id=notebook_id`
**`pipeline_service.py:214`**：`evaluate_batch` 傳入 `from_id=from_id, similarities=sims`
**`vocab_handlers.py:284`**：ManualLinkJudge 建構傳入 `user_id`, `notebook_id`
**`vocab_graph_ops.py:43`**：`judge.evaluate` 傳入 `from_id`, `to_id`

## 不改的

- `token_usage.db` — 不動
- `token_tracker.py` — 不動
- `tracked_llm.py` — 不動
- `graph.py` — 不動
- API endpoints — 不新增（分析靠 container-script 或未來 admin API）

## 啟用的分析能力

| 分析 | SQL 範例 |
|------|----------|
| 完整 confidence 分布 | `SELECT confidence FROM judge_log WHERE user_id=? ORDER BY confidence` |
| 拒絕率 | `SELECT accepted, COUNT(*) FROM judge_log GROUP BY accepted` |
| 閾值模擬 | `SELECT COUNT(*) FROM judge_log WHERE confidence >= ? AND verdict != 'not_applicable'` |
| similarity vs confidence | `SELECT similarity, confidence FROM judge_log WHERE similarity IS NOT NULL` |
| kind 分布含被拒 | `SELECT verdict, COUNT(*) FROM judge_log GROUP BY verdict` |
| 每 notebook judge 通過率 | `SELECT notebook_id, AVG(accepted) FROM judge_log GROUP BY notebook_id` |
| 回播用資料 | `SELECT * FROM judge_log WHERE user_id=? ORDER BY created_at` |

## 風險

| 風險 | 緩解 |
|------|------|
| judge_log 磁碟成長 | 每筆 ~200 bytes，10K judges = ~2MB，長期可加 retention policy |
| Judge 建構簽名變更 | 所有 call site 都在本 repo 內，可一次改完 |
| parse_error 時缺 confidence | 記 confidence=0.0, verdict='not_applicable' |

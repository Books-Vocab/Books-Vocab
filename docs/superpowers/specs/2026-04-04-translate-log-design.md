# Translate Log — Design Spec

## Problem

translate/explain 的 LLM 調用是黑洞：token_usage 只記花費，不記 input/output 內容。無法回溯品質、debug prompt、或避免重複調用。

## Solution

新增 `translate_log.db`，記錄每次 LLM 翻譯調用的完整 input/output，並在調用前做 cache lookup 避免重複打 Gemini。

## Schema

```sql
CREATE TABLE IF NOT EXISTS translate_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    operation   TEXT NOT NULL,        -- translate_quick / translate_phrase / translate_explain
    word        TEXT NOT NULL,
    context     TEXT,
    context_hash TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    response_raw TEXT NOT NULL,        -- LLM 原始 JSON
    latency_ms  INTEGER,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tl_cache
    ON translate_log(word, context_hash, source_lang, target_lang, operation);
CREATE INDEX IF NOT EXISTS idx_tl_user
    ON translate_log(user_id, created_at);
```

## Cache 策略

- **Key**: `(word, context_hash, source_lang, target_lang, operation)`
- **跨用戶共享**：翻譯結果不是個人資料，相同查詢回傳相同結果
- **user_id 不參與 cache key**，僅用於 audit
- **Cache hit 不寫新行**
- **context_hash**: SHA256 前 16 hex chars，對 `_context_around_word(context, word)` 的輸出計算（已截斷+strip）
- **word 正規化**: cache lookup 前 `word.strip().lower()`，確保 "Hello" 與 "hello" 命中同一條
- **空 context**: `_context_around_word("", word)` 回傳空字串 → `sha256(b"")` → 固定 hash，行為一致

## 插入點

`translate_service.py` 的 `_run_llm_translate`：

```
_run_llm_translate
├── resolve langs
├── compute context_hash
├── translate_log.lookup(word, context_hash, source_lang, target_lang, operation)
│   └── hit → parse response_raw → return（跳過 LLM + token tracking）
├── start = time.monotonic()
├── llm.chat_async (原有)
├── latency_ms = (time.monotonic() - start) * 1000
├── parse JSON (原有)
├── translate_log.record(user_id, operation, word, context, context_hash, langs, response_raw, latency_ms)
└── return
```

### Cache hit 行為

命中時完全跳過 `llm.chat_async`，因此：
- token_usage **不會**有新紀錄（正確 — 沒花 token）
- quota **不會**被扣（正確 — 沒消耗資源）
- response 從 translate_log 的 `response_raw` 解析，走同一個 `_parse_json_payload`

## 模組設計

`translate_log.py` — ��循 judge_log.py / pipeline_log.py 的 singleton pattern：
- `_get_conn()`: SQLite WAL, threading.Lock，**DB_PATH 在 `_get_conn()` 內 lazy 計算**（非模組層級常數），確保測試 monkeypatch `KG_DATA_DIR` 生效
- `lookup(word, context_hash, source_lang, target_lang, operation) → str | None`: 回傳 response_raw 或 None
- `record(*, user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms) → None`
- `get_log(user_id, *, limit) → list[dict]`: admin 查詢用
- `_reset()`: 測試用

## 不做的事

- 不存 token 數字（token_usage 管）
- 不記 cache hit（保持 log 乾淨）
- 不加 admin endpoint（本期不做，未來按需加）
- 不改 iOS 端（iOS 已有本地詞彙庫命中機制）
- 不加 TTL / eviction（SQLite 表小，flash-lite 輸出穩定，不需要過期）

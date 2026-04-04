# TrackedLLM：統一 LLM Token 追蹤架構

## 問題

Token 追蹤是 opt-in 設計（各呼叫點自行 `token_tracker.record()`），導致：
1. `Judge.evaluate()` retry 路徑（`judge.py:110`）漏記 token
2. `ManualLinkJudge.evaluate()`（`judge.py:188`）因 `user_id` 未傳遞，tracking 為死碼
3. 未來新增 LLM 呼叫點仍可能遺漏

根因：追蹤邏輯是 cross-cutting concern，卻散落在業務邏輯層。

## 解決方案

新增 `tracked_llm.py`，提供 `TrackedLLM` wrapper：
- 建構時綁定 `user_id`（per-request / per-pipeline-run）
- 所有 LLM 呼叫（chat / embed）自動記錄 token
- 取代所有直接使用 `client.chat.completions.create()` 的呼叫

## 設計

### Sync / Async 策略

`TrackedLLM` 是 duck-typed wrapper，同時提供 `chat()` 和 `chat_async()`。
**Caller 約定**（非 runtime 強制）：

- Sync callers（judge / enrich / embed）：傳入 `OpenAI` → 使用 `.chat()` / `.embed()`
- Async callers（translate）：傳入 `AsyncOpenAI` → 使用 `.chat_async()`

不拆兩個 class，因為記錄邏輯完全相同，拆開只是無謂的重複。

### Threading 安全性

`enrich_cards_stream` 在 `ThreadPoolExecutor` worker thread 中呼叫 `_call_enrich_llm`。
改用 `TrackedLLM` 後，`token_tracker.record()` 會在 worker thread 被呼叫。
這是安全的：`record()` 使用 `threading.Lock` + `sqlite3.Connection(check_same_thread=False)`。

現行設計是將 usage 透過 `asyncio.Queue` 傳回 main thread 再記錄；改後在 worker thread 當場記錄，語義等價、更簡潔。

### Class 定義

```python
class TrackedLLM:
    def __init__(self, client, user_id: str):
        self._client = client
        self.user_id = user_id

    def chat(self, call_type: str, **kwargs):
        """同步 chat completion（搭配 OpenAI client）。"""
        resp = self._client.chat.completions.create(**kwargs)
        self._record(call_type, resp)
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        """非同步 chat completion（搭配 AsyncOpenAI client）。"""
        resp = await self._client.chat.completions.create(**kwargs)
        self._record(call_type, resp)
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
        """Embedding 呼叫（同步）。"""
        resp = self._client.embeddings.create(**kwargs)
        self._record_embed(call_type, resp)
        return resp

    def _record(self, call_type, resp):
        if not getattr(resp, "usage", None):
            return
        from .token_tracker import record
        record(self.user_id, call_type,
               getattr(resp.usage, "prompt_tokens", 0) or 0,
               getattr(resp.usage, "completion_tokens", 0) or 0)

    def _record_embed(self, call_type, resp):
        if not getattr(resp, "usage", None):
            return
        from .token_tracker import record
        record(self.user_id, call_type,
               getattr(resp.usage, "prompt_tokens", 0) or getattr(resp.usage, "total_tokens", 0) or 0,
               0)
```

## 受影響的呼叫點

| 模組 | 現行 | 改後 |
|------|------|------|
| `judge.py` Judge | `self.client.chat.completions.create()` + 手動 record | `self.llm.chat("judge", ...)` |
| `judge.py` Judge retry | 第二次 create，漏記 | `self.llm.chat("judge", ...)` — 自動記 |
| `judge.py` ManualLinkJudge | create + record 死碼 | `self.llm.chat("manual_link_judge", ...)` |
| `enrich.py` | `client.chat.completions.create()` + 手動 record | `llm.chat("enrich", ...)` |
| `embeddings.py` | `self.client.embeddings.create()` + 手動 record | `self.llm.embed(...)` |
| `translate_service.py` | `await client.chat.completions.create()` + `track_usage()` | `await llm.chat_async(operation, ...)` |

## 建構點（user_id 綁定處）

| 場景 | 模組 | 改動 |
|------|------|------|
| Pipeline enrich | `pipeline_service._step_enrich()` | `TrackedLLM(gemini_client_factory(), uid)` → 傳給 enrich |
| Pipeline link | `pipeline_service._step_link()` | `TrackedLLM(gemini_client_factory(), uid)` → 傳給 Judge |
| Pipeline embed | `service_factories.create_embedding_store()` | 接收 `TrackedLLM` 而非 raw client + user_id |
| 手動連結 | `vocab_handlers.create_manual_link_response()` | `TrackedLLM(gemini_client_factory(), user["id"])` → ManualLinkJudge |
| 翻譯 | `translate_handlers._safe_translate()` | `TrackedLLM(async_gemini_client, user["id"])` → `.chat_async()` |

## 刪除的程式碼

- `translate_service.track_usage()` 函式
- `judge.py` 所有 `from .token_tracker import record` + 手動 `record()` 呼叫
- `enrich.py` 所有手動 token 記錄邏輯（`enrich_cards` 和 `enrich_cards_stream` 中的 usage tracking）
- `embeddings.py` 手動 token 記錄邏輯
- `judge.py` Judge.evaluate / ManualLinkJudge.evaluate 的 `user_id` 參數
- `enrich.py` enrich_cards / enrich_cards_stream 的 `user_id` 參數
- `embeddings.py` EmbeddingStore.__init__ 的 `user_id` 參數
- `service_factories.py` create_embedding_store 的 `user_id` + `gemini_client_factory` 參數（改為 `llm: TrackedLLM`）
- `pipeline_service.py` _step_link 中 `judge.evaluate(..., user_id=uid)` 的 `user_id=uid`

## 不在範圍內

- 手動連結 endpoint 的額度前置檢查（`_check_quota`）— 獨立修復
- Pipeline 的額度前置檢查 — 背景任務，設計上允許
- Migration script（離線一次性工具）

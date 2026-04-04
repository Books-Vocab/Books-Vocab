# TrackedLLM Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 統一 LLM token 追蹤，消除遺漏，結構性保證所有 LLM 呼叫自動記錄。
**Architecture:** 新增 `TrackedLLM` wrapper，per-request 綁定 user_id，取代所有直接 client 呼叫。
**Tech Stack:** Python, OpenAI SDK (sync + async)

---

### Task 1: TrackedLLM 核心模組

**Files:**
- Create: `backend/src/kg/tracked_llm.py`
- Test: `backend/tests/test_tracked_llm.py`

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_tracked_llm.py
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from kg.tracked_llm import TrackedLLM


def _mock_client(prompt_tokens=10, completion_tokens=20):
    client = MagicMock()
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=30)
    choice = SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))
    resp = SimpleNamespace(choices=[choice], usage=usage)
    client.chat.completions.create.return_value = resp
    return client, resp


def _mock_embed_client(prompt_tokens=5, total_tokens=5):
    client = MagicMock()
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=total_tokens)
    data = [SimpleNamespace(embedding=[0.1, 0.2], index=0)]
    resp = SimpleNamespace(data=data, usage=usage)
    client.embeddings.create.return_value = resp
    return client, resp


class TestTrackedLLMChat:
    @patch("kg.tracked_llm.record")
    def test_chat_records_token_usage(self, mock_record):
        client, _ = _mock_client(prompt_tokens=15, completion_tokens=25)
        llm = TrackedLLM(client, user_id="u1")
        resp = llm.chat("judge", model="m", messages=[])
        mock_record.assert_called_once_with("u1", "judge", 15, 25)
        assert resp.choices[0].message.content == '{"ok": true}'

    @patch("kg.tracked_llm.record")
    def test_chat_no_usage_skips_record(self, mock_record):
        client = MagicMock()
        resp = SimpleNamespace(choices=[], usage=None)
        client.chat.completions.create.return_value = resp
        llm = TrackedLLM(client, user_id="u1")
        llm.chat("judge", model="m", messages=[])
        mock_record.assert_not_called()

    @patch("kg.tracked_llm.record")
    def test_multiple_calls_each_recorded(self, mock_record):
        client, _ = _mock_client()
        llm = TrackedLLM(client, user_id="u1")
        llm.chat("judge", model="m", messages=[])
        llm.chat("judge", model="m", messages=[])
        assert mock_record.call_count == 2


class TestTrackedLLMEmbed:
    @patch("kg.tracked_llm.record")
    def test_embed_records_prompt_tokens(self, mock_record):
        client, _ = _mock_embed_client(prompt_tokens=5, total_tokens=5)
        llm = TrackedLLM(client, user_id="u1")
        llm.embed("embed", input=["hello"], model="m")
        mock_record.assert_called_once_with("u1", "embed", 5, 0)

    @patch("kg.tracked_llm.record")
    def test_embed_falls_back_to_total_tokens(self, mock_record):
        client = MagicMock()
        usage = SimpleNamespace(prompt_tokens=0, total_tokens=8)
        resp = SimpleNamespace(data=[], usage=usage)
        client.embeddings.create.return_value = resp
        llm = TrackedLLM(client, user_id="u1")
        llm.embed("embed", input=["hi"], model="m")
        mock_record.assert_called_once_with("u1", "embed", 8, 0)


class TestTrackedLLMChatAsync:
    @pytest.mark.asyncio
    @patch("kg.tracked_llm.record")
    async def test_chat_async_records_usage(self, mock_record):
        client = MagicMock()
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20)
        choice = SimpleNamespace(message=SimpleNamespace(content="{}"))
        resp = SimpleNamespace(choices=[choice], usage=usage)

        async def mock_create(**kwargs):
            return resp
        client.chat.completions.create = mock_create

        llm = TrackedLLM(client, user_id="u1")
        result = await llm.chat_async("translate_quick", model="m", messages=[])
        mock_record.assert_called_once_with("u1", "translate_quick", 10, 20)
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_tracked_llm.py -v`
Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: 寫最小實作**
```python
# backend/src/kg/tracked_llm.py
"""Unified LLM wrapper with automatic token usage tracking."""
from __future__ import annotations

from .token_tracker import record


class TrackedLLM:
    """Per-request LLM wrapper. Binds user_id at construction, auto-records on every call."""

    __slots__ = ("_client", "user_id")

    def __init__(self, client, user_id: str) -> None:
        self._client = client
        self.user_id = user_id

    def chat(self, call_type: str, **kwargs):
        resp = self._client.chat.completions.create(**kwargs)
        self._record_chat(call_type, resp)
        return resp

    async def chat_async(self, call_type: str, **kwargs):
        resp = await self._client.chat.completions.create(**kwargs)
        self._record_chat(call_type, resp)
        return resp

    def embed(self, call_type: str = "embed", **kwargs):
        resp = self._client.embeddings.create(**kwargs)
        self._record_embed(call_type, resp)
        return resp

    def _record_chat(self, call_type: str, resp) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        record(
            self.user_id,
            call_type,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    def _record_embed(self, call_type: str, resp) -> None:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        record(
            self.user_id,
            call_type,
            prompt or getattr(usage, "total_tokens", 0) or 0,
            0,
        )
```

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_tracked_llm.py -v`

- [ ] **Step 5: Commit**

---

### Task 2: 遷移 judge.py

**Files:**
- Modify: `backend/src/kg/judge.py`
- Modify: `backend/tests/test_judge.py`
- Modify: `backend/tests/test_manual_link_judge.py`

- [ ] **Step 1: 更新 test，Judge 和 ManualLinkJudge 接收 TrackedLLM**
```python
# test_judge.py: 改 _judge_with 和 _make_client
from kg.tracked_llm import TrackedLLM

def _make_client(content):
    mock_client = MagicMock()
    # ... same mock setup ...
    return mock_client

def _judge_with(content):
    return Judge(llm=TrackedLLM(_make_client(content), "test_user"))

# test_manual_link_judge.py: 同理
def _make_client(response_json):
    # ... same ...
    return client

# Usage:
judge = ManualLinkJudge(TrackedLLM(client, "test_user"))
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_judge.py tests/test_manual_link_judge.py -v`

- [ ] **Step 3: 重寫 judge.py**
- `Judge.__init__` 改為接收 `llm: TrackedLLM`
- `evaluate()` 移除 `user_id` 參數
- 所有 `self.client.chat.completions.create(...)` → `self.llm.chat("judge", ...)`
- 移除手動 `token_tracker.record()` 呼叫
- retry 路徑同樣用 `self.llm.chat("judge", ...)`
- `ManualLinkJudge` 同理，call_type = `"manual_link_judge"`

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_judge.py tests/test_manual_link_judge.py -v`

- [ ] **Step 5: Commit**

---

### Task 3: 遷移 enrich.py

**Files:**
- Modify: `backend/src/kg/enrich.py`
- Modify: `backend/tests/test_enrich.py`

- [ ] **Step 1: 更新 test，enrich_cards 接收 TrackedLLM**
- `enrich_cards(llm, cards)` 替代 `enrich_cards(client, cards, user_id=...)`
- `_call_enrich_llm(llm, batch, model)` 替代 `_call_enrich_llm(client, batch, model)`

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 重寫 enrich.py**
- `_call_enrich_llm` 改為接收 `TrackedLLM`，用 `llm.chat("enrich", ...)`
- `enrich_cards` 移除 `user_id` 參數，移除手動 record
- `enrich_cards_stream` 移除 `user_id` 參數
- 移除 queue handler 中的 usage tracking（`if user_id and msg.get("usage"): record(...)`），因 `_call_enrich_llm` 已在 ThreadPoolExecutor worker thread 中自動記錄
- 移除 `_process_batch_with_retry` 中的 `usage_data` 收集（不再需要透過 queue 傳遞 usage）
- **Threading 安全**：`token_tracker.record()` 使用 `threading.Lock`，在 worker thread 呼叫是安全的

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit**

---

### Task 4: 遷移 embeddings.py + service_factories + deps

**注意**: 此 task 同時改 `service_factories.py` 和 `deps.py`，避免中間 broken state。

**Files:**
- Modify: `backend/src/kg/embeddings.py`
- Modify: `backend/src/kg/service_factories.py` (create_embedding_store)
- Modify: `backend/src/kg/deps.py` (_embedding_store)
- Modify: `backend/tests/test_embedding_batch.py`

- [ ] **Step 1: 更新 test**
- `EmbeddingStore.__init__` 改為接收 `llm: TrackedLLM` 而非 `client + user_id`

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 重寫**
- `EmbeddingStore.__init__` 接收 `llm: TrackedLLM`，移除 `client` + `user_id` 參數
- `_embed()` 用 `self.llm.embed(...)` 取代 `self.client.embeddings.create()` + 手動 record
- `_embed()` 的 retry loop 保留，但 LLM 呼叫改用 `self.llm.embed()`
- `create_embedding_store` 改為接收 `llm: TrackedLLM` 而非 `gemini_client_factory + user_id`
- `deps._embedding_store` 同步更新簽章

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit**

---

### Task 5: 遷移 translate_service.py

**Files:**
- Modify: `backend/src/kg/translate_service.py`
- Modify: `backend/src/kg/translate_handlers.py`
- Modify: `backend/tests/test_translate_service.py`
- Modify: `backend/tests/test_async_translate.py`

- [ ] **Step 1: 更新 test**
- `_run_llm_translate` 接收 `llm: TrackedLLM` 而非 `client`
- `run_quick_translate` 等函式同理

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 重寫**
- `_run_llm_translate` 改為接收 `llm: TrackedLLM`（取代 `client: Any`），用 `await llm.chat_async(operation, ...)` 取代直接呼叫
- 移除 `track_usage()` 函式
- `run_quick/phrase/explain_translate` 參數名 `client` → `llm`
- `translate_handlers._safe_translate`:
  - `client = gemini_client_factory()` 改為 `llm = TrackedLLM(gemini_client_factory(), user["id"])`
  - `kw["client"] = client` 改為 `kw["llm"] = llm`
  - 注意：此處的 `gemini_client_factory` 回傳 `AsyncOpenAI`，用 `llm.chat_async()` 是正確的

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit**

---

### Task 6: 更新呼叫鏈（pipeline + handlers）

**Files:**
- Modify: `backend/src/kg/pipeline_service.py`
- Modify: `backend/src/kg/vocab_handlers.py`
- Modify: `backend/tests/test_pipeline_service.py`
- Modify: `backend/tests/test_pipeline_integration.py`
- Modify: `backend/tests/test_pipeline_resilience.py`
- Modify: `backend/tests/test_manual_link.py` (if affected)

注意：`vocab_graph_ops.py` 不需改動（`judge.evaluate()` 的 `user_id` 參數移除後，現有呼叫 `judge.evaluate(a, b, c, d)` 本來就沒傳 `user_id`）。
注意：`deps.py` 已在 Task 4 同步更新。

- [ ] **Step 1: 更新 pipeline tests**

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 重寫呼叫鏈**
- `_step_enrich`: `llm = TrackedLLM(gemini_client_factory(), uid)` → 傳給 `enrich_cards_stream(llm, ...)`
- `_step_link` (`pipeline_service.py:167-191`):
  - `llm = TrackedLLM(gemini_client_factory(), uid)` → `Judge(llm, ...)`
  - 移除 `:191` 的 `user_id=uid`：`judge.evaluate(a.content, a.meaning, b.content, b.meaning)`
- `_step_embed`: `embedding_store_factory` 傳入時已包含 `TrackedLLM`（由 `deps._embedding_store` 處理）
- `vocab_handlers.create_manual_link_response` (`vocab_handlers.py:307`): `ManualLinkJudge(TrackedLLM(gemini_client_factory(), user["id"]))`

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd backend && python -m pytest -x -v`

- [ ] **Step 5: Commit**

---

### Task 7: 全量回歸測試

- [ ] **Step 1: 跑全部測試**
Run: `cd backend && python -m pytest --tb=short -q`

- [ ] **Step 2: iOS build 確認**
Run: `./ops/ios_build.sh`

- [ ] **Step 3: 最終 Commit + PR**

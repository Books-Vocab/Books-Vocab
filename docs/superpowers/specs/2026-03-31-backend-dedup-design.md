# Backend 共用 Pattern 抽取重構 — Design Spec

## 問題

後端有 5 類系統性重複，增加維護成本和出錯風險。

## 重構項目

### A. vocab_handlers notebook 驗證 + store 建構（13 處）

**現狀**：每個 handler 都有 4 行固定 boilerplate：
```python
if notebook_id is not None and notebook_store_factory is not None:
    validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
cards = card_store_factory(user["dir"])
graph = graph_store_factory(user["dir"], notebook_id=...) if graph_store_factory is not None else None
```

**方案**：抽取 `_resolve_stores(user, notebook_id, *, card_store_factory, graph_store_factory, notebook_store_factory)` helper 到 `vocab_handlers.py` 頂部。回傳 `tuple[CardStore, GraphStore | None]`。

不用 FastAPI Depends 是因為 handler 函數不是直接掛在 router 上，而是透過 `vocab_wiring.py` 包裝，factory 已經在那裡注入。保持現有 DI 架構不變，只抽取重複邏輯。

`move_words_response` 特殊情況（雙重驗證 source + target）用額外調用處理。

### B. admin require_admin 改 Depends（10+10 處）

**現狀**：
- `admin_handlers.py`：10 個函數各自接收 `token, admin_token, authorization, cookie_token` 四參數 + 手動調用 `require_admin()`
- `admin_wiring.py`：10 個 closure 各自聲明 `Header(None)` + `Cookie(None)` + 透傳 `admin_token`

**方案**：
1. 在 `deps.py` 新增 `get_admin_user` dependency：封裝 `require_admin()` 邏輯，從 request 取 token/header/cookie
2. `admin_wiring.py` 的 closure 不再傳四個 auth 參數
3. `admin_handlers.py` 每個函數移除四個 auth 參數，改接收 `admin_verified: bool`（或無需接收，dependency 只負責 gate）

### C. GraphStore.cleanup_for_card()（5 處）

**現狀**：`vocab_service.py` 5 處重複呼叫 `deprecate_links_for + remove_candidates_for [+ remove_blocked_pairs_for]`。

**方案**：在 `GraphStore` 上新增：
```python
def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
    dep_count = self.deprecate_links_for(card_id)
    cand_count = self.remove_candidates_for(card_id)
    blocked_count = 0
    if remove_blocked:
        self.remove_blocked_pairs_for(card_id)  # 目前回傳 None，不取回傳值
    return {"deprecated": dep_count, "candidates_removed": cand_count}
```
呼叫端改為 `graph.cleanup_for_card(card.id, remove_blocked=is_delete)`。

### D. translate_service 泛型化（3 函數）

**現狀**：`run_quick_translate`、`run_phrase_translate`、`run_explain_translate` 結構 95% 相同。

**方案**：抽取私有泛型函數：
```python
async def _run_llm_translate(
    *, req, user, client, model, prompt_fn, parse_fn, operation: str, logger=None
) -> Any:
```
- `prompt_fn(req, source_lang, target_lang) -> str`：產生 prompt
- `parse_fn(data: dict, req) -> response`：從 parsed JSON 組裝回傳值

三個公開函數變成薄 wrapper：定義各自的 `prompt_fn` + `parse_fn`，其餘全委派。

### E. HTTPException → KGError 統一（9 處）

**現狀**：
- `routers/notebook.py`：4 處直接拋 `HTTPException(400/404)`
- `deps_quota.py`：2 處拋 `HTTPException(429)` 而非用已定義的 `QuotaExceededError`
- `admin_handlers.py`：3 處拋 `HTTPException(403)`（在 `require_admin()` 函數內，若 B 項先完成則這 3 處會在新 dependency 中處理）

**注意**：B 項和 E 項的 admin 403 部分有隱含依賴——E 項的 admin 403 在 B 項的新 `get_admin_user` dependency 中一併處理。其餘檔案的 HTTPException（billing、auth、user_context 等）暫不處理，留待後續獨立重構。

**方案**：
1. `exceptions.py` 新增 `ForbiddenError(KGError, 403)`
2. `QuotaExceededError` 擴充支援 `headers` 欄位（讓全域 handler 能回傳 rate limit headers）
3. 替換所有 9 處 `HTTPException` 為對應 `KGError` 子類別
4. 全域 exception handler 增加 headers 支援

## 不做的事

- 不改 router/wiring 的 DI 架構（A 項只抽 helper，不改 Depends 流程）
- 不改 handler 函數簽名以外的邏輯
- 不重構 `vocab_service.py` 的檔案拆分（超出 scope）
- 不動測試（只確保現有測試全過）

## 驗證標準

- 所有現有 backend test 通過（`pytest backend/tests/ -x`）
- 無新增 public API 變更（行為完全等價）

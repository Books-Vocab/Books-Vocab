# Backend 共用 Pattern 抽取重構 — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 消除後端 5 類系統性重複（共 ~45 處），降低維護成本。
**Architecture:** 純內部重構，不改 public API 行為。每個 task 獨立可測。
**Tech Stack:** Python / FastAPI / Pydantic

## 執行順序

```
Task 1 (C: GraphStore)     ─┐
Task 2 (A: vocab_handlers)  ├─ 可平行
Task 3 (D: translate)       │
Task 4 (B: admin Depends)  ─┘
Task 5 (E: HTTPException → KGError) ─→ 依賴 Task 4 完成
Task 6: 全量回歸
```

---

### Task 1: GraphStore.cleanup_for_card() [C]

**Files:**
- Modify: `backend/src/kg/graph.py:365` — 新增方法
- Modify: `backend/src/kg/vocab_service.py:284,300,339,380,418` — 替換 5 處

- [ ] **Step 1: 在 `GraphStore` 新增 `cleanup_for_card`（graph.py ~L420 之後）**
```python
def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
    """Deprecate links + remove candidates (+ blocked pairs if deleting)."""
    dep_count = self.deprecate_links_for(card_id)
    cand_count = self.remove_candidates_for(card_id)
    if remove_blocked:
        self.remove_blocked_pairs_for(card_id)  # returns None
    return {"deprecated": dep_count, "candidates_removed": cand_count}
```

- [ ] **Step 2: 替換 vocab_service.py 5 處**

| 行號 | 場景 | 替換前 | 替換後 |
|------|------|--------|--------|
| `:284-285` | archive_vocab_word | `deprecate + remove_candidates` | `graph.cleanup_for_card(card.id)` |
| `:300-302` | delete_vocab_word | `deprecate + remove_candidates + remove_blocked` | `graph.cleanup_for_card(card.id, remove_blocked=True)` |
| `:339-341` | batch_delete | 同上 | `graph.cleanup_for_card(card.id, remove_blocked=True)` |
| `:380-381` | batch_archive | `deprecate + remove_candidates` | `graph.cleanup_for_card(card.id)` |
| `:418-419` | move | `deprecate + remove_candidates` on source_graph | `source_graph.cleanup_for_card(card.id)` |

- [ ] **Step 3: 跑測試**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`

---

### Task 2: vocab_handlers _resolve_stores [A]

**Files:**
- Modify: `backend/src/kg/vocab_handlers.py` — 新增 helper + 替換調用

**函數完整清單（14 個）：**

| 函數 | 行號 | 分類 |
|------|------|------|
| `list_vocab_response` | :48 | 標準 |
| `lookup_word_response` | :71 | 標準 |
| `archive_word_response` | :94 | 標準 |
| `delete_word_response` | :133 | 標準 |
| `batch_delete_response` | :151 | 標準 |
| `batch_archive_response` | :167 | 標準 |
| `create_manual_link_response` | :258 | 標準 |
| `delete_graph_link_response` | :289 | 標準 |
| `hide_graph_link_response` | :305 | 標準 |
| `unhide_graph_link_response` | :321 | 標準 |
| `get_graph_links_response` | :183 | **特殊：只需 graph，不需 cards** |
| `add_vocab_response` | :194 | **特殊：需額外 embeddings** |
| `move_words_response` | :109 | **特殊：雙 notebook 驗證 + 雙 graph，不使用 helper** |
| `push_review_response` | :219 | **不適用：無 notebook 驗證，不改** |

- [ ] **Step 1: 新增 `_resolve_stores` helper**
```python
def _resolve_stores(
    user: dict[str, Any],
    notebook_id: str,
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
) -> tuple[Any, Any]:
    """Validate notebook access and construct card + graph stores."""
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id) if graph_store_factory is not None else None
    return cards, graph
```

- [ ] **Step 2: 替換 10 個標準函數**
每個函數將 3-4 行 boilerplate 替換為：
```python
cards, graph = _resolve_stores(user, notebook_id, card_store_factory=card_store_factory, graph_store_factory=graph_store_factory, notebook_store_factory=notebook_store_factory)
```

- [ ] **Step 3: 處理 `get_graph_links_response`**
使用 helper 做 notebook 驗證，但只取 graph：
```python
_, graph = _resolve_stores(user, notebook_id, card_store_factory=card_store_factory, graph_store_factory=graph_store_factory, notebook_store_factory=notebook_store_factory)
```
（card_store 建構成本極低——只是 Path wrapper，trade-off 可接受）

- [ ] **Step 4: 處理 `add_vocab_response`**
用 helper 做驗證 + cards 建構，graph 和 embeddings 仍手動建（因為 embeddings 需額外參數）：
```python
cards, _ = _resolve_stores(user, notebook_id, card_store_factory=card_store_factory, notebook_store_factory=notebook_store_factory)
# graph and embeddings still manual
```

- [ ] **Step 5: `move_words_response` 保持不變**
其模式（雙 notebook 驗證、guard 條件 `if notebook_store_factory is not None` 而非 `notebook_id is not None`、雙 graph 建構）與 helper 不相容。保持原樣。

- [ ] **Step 6: 跑測試**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`

---

### Task 3: translate_service 泛型化 [D]

**Files:**
- Modify: `backend/src/kg/translate_service.py:122-176`

**三個函數差異矩陣：**

| | `run_quick_translate` :122 | `run_phrase_translate` :143 | `run_explain_translate` :161 |
|---|---|---|---|
| prompt_fn | `quick_translate_prompt` | `phrase_translate_prompt` | `explain_translate_prompt` |
| operation | `"translate_quick"` | `"translate_phrase"` | `"translate_explain"` |
| logger | 必填 `Logger` | `Logger \| None` | `Logger \| None` |
| parse → return | `QuickTranslateResponse(t=, p=_normalize_pos(), r=)` | `{"t": data.get("t", "")}` | `ExplainResponse(e=)` |

- [ ] **Step 1: 抽取 `_run_llm_translate`（插入 :120 之前）**
```python
async def _run_llm_translate(
    *,
    req: TranslateRequest,
    user: dict[str, Any],
    client: Any,
    model: str,
    prompt_fn: Callable,
    operation: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Common LLM translate flow: resolve langs → call → parse → track."""
    source_lang, target_lang = resolve_translation_langs(req, user)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt_fn(req, source_lang, target_lang)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    if not response.choices:
        if logger:
            logger.error("%s: Gemini returned empty choices. Full response: %s", operation, response)
        raise ExternalServiceError("Gemini returned empty response")
    track_usage(user["id"], operation, response)
    return _parse_json_payload(response.choices[0].message.content)
```

- [ ] **Step 2: 改寫三個公開函數為薄 wrapper**

```python
async def run_quick_translate(req, user, *, client, logger, model="gemini-2.5-flash-lite"):
    data = await _run_llm_translate(req=req, user=user, client=client, model=model, prompt_fn=quick_translate_prompt, operation="translate_quick", logger=logger)
    return QuickTranslateResponse(t=data.get("t", ""), p=_normalize_pos(data.get("p")), r=data.get("r"))

async def run_phrase_translate(req, user, *, client, logger=None, model="gemini-2.5-flash-lite"):
    data = await _run_llm_translate(req=req, user=user, client=client, model=model, prompt_fn=phrase_translate_prompt, operation="translate_phrase", logger=logger)
    return {"t": data.get("t", "")}

async def run_explain_translate(req, user, *, client, logger=None, model="gemini-2.5-flash-lite"):
    data = await _run_llm_translate(req=req, user=user, client=client, model=model, prompt_fn=explain_translate_prompt, operation="translate_explain", logger=logger)
    return ExplainResponse(e=data.get("e", ""))
```

- [ ] **Step 3: 跑測試**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`

---

### Task 4: admin auth 改 Depends [B]

**Files:**
- Modify: `backend/src/kg/exceptions.py` — 新增 `ForbiddenError`
- Modify: `backend/src/kg/deps.py` — 新增 `get_admin_user`
- Modify: `backend/src/kg/admin_handlers.py` — 移除 auth 參數 + `require_admin` 調用
- Modify: `backend/src/kg/admin_wiring.py` — 移除 auth 參數透傳
- Modify: `backend/src/kg/routers/admin.py:23` — router 加 `dependencies=[Depends(get_admin_user)]`

- [ ] **Step 1: `exceptions.py` 新增 `ForbiddenError`（L61 之後）**
```python
class ForbiddenError(KGError):
    """Access denied."""
    status_code = 403
```

- [ ] **Step 2: `deps.py` 新增 `get_admin_user`**
```python
from fastapi import Cookie, Header, Query, Request
from .admin_handlers import require_admin
from .exceptions import ForbiddenError

async def get_admin_user(
    request: Request,
    token: str | None = Query(None),
    authorization: str | None = Header(None),
    admin_session: str | None = Cookie(None),
):
    admin_token = request.app.state.kg_settings.admin_token
    try:
        require_admin(token, admin_token=admin_token, authorization=authorization, cookie_token=admin_session)
    except HTTPException:
        raise ForbiddenError("Admin authentication required")
```

- [ ] **Step 3: `routers/admin.py` — router 加 dependency**
```python
from ..deps import get_admin_user
from fastapi import Depends

router = APIRouter(dependencies=[Depends(get_admin_user)])
```
所有掛在此 router 的 endpoint 自動受 admin auth 保護。

- [ ] **Step 4: `admin_wiring.py` — 10 個 closure 移除 auth 參數**
每個 closure 從：
```python
def admin_xxx(token=None, authorization=Header(None), admin_session=Cookie(None)):
    return admin_xxx_response(token, admin_token=..., authorization=..., cookie_token=...)
```
改為：
```python
def admin_xxx():
    return admin_xxx_response(...)
```
（只保留業務參數如 `user_id`, `req`, `n`, `level` 等）

- [ ] **Step 5: `admin_handlers.py` — 10 個函數移除 auth 參數 + require_admin 調用**
每個函數移除 `token`, `admin_token`, `authorization`, `cookie_token` 四個參數，刪除 `require_admin(...)` 調用行。同時將 2 處 `HTTPException(404, "User not found")` 改為 `NotFoundError("User", user_id)`。

- [ ] **Step 6: 跑測試**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`

---

### Task 5: HTTPException → KGError（notebook + quota）[E]

**Files:**
- Modify: `backend/src/kg/exceptions.py` — KGError 加 headers、QuotaExceededError 加 headers
- Modify: `backend/src/kg/api.py:~288` — 全域 handler 回傳 headers
- Modify: `backend/src/kg/routers/notebook.py:37,67,70,81` — 4 處
- Modify: `backend/src/kg/deps_quota.py:21,37` — 2 處

- [ ] **Step 1: `exceptions.py` — KGError 加 `headers` 屬性**
保持現有 class attribute pattern，只在 `__init__` 加 `headers`：
```python
class KGError(Exception):
    """Base for all KG domain errors."""
    status_code: int = 500

    def __init__(self, *args, headers: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers = headers or {}

    def to_detail(self) -> dict:
        return {"code": type(self).__name__, "detail": str(self)}
```
同步修改 `QuotaExceededError.__init__` 接收並傳遞 `headers`：
```python
class QuotaExceededError(KGError):
    status_code = 429
    def __init__(self, reset_seconds: int, *, headers: dict | None = None):
        self.reset_seconds = reset_seconds
        super().__init__(f"Quota exceeded, resets in {reset_seconds}s", headers=headers)
```
確認所有子類別的 `super().__init__` 調用不受影響（`NotFoundError` 用 positional arg 傳 msg，OK）。

- [ ] **Step 2: `api.py` 全域 handler 加 headers**
在 `kg_error_handler` 中：
```python
return JSONResponse(status_code=exc.status_code, content=..., headers=exc.headers if exc.headers else None)
```

- [ ] **Step 3: `routers/notebook.py` 替換 4 處**
```python
# L37: HTTPException(400, "Invalid since timestamp") → BadRequestError("Invalid since timestamp")
# L67: HTTPException(400, "No fields to update") → BadRequestError("No fields to update")
# L70: HTTPException(404, "Notebook not found") → NotFoundError("Notebook", nb_id)
# L81: HTTPException(400, "Cannot delete...") → BadRequestError("Cannot delete: notebook not found or is default")
```

- [ ] **Step 4: `deps_quota.py` 替換 2 處**
```python
# L21-25 和 L37-42:
raise QuotaExceededError(quota["reset_seconds"], headers={"X-Quota-Fraction": str(quota["fraction"])})
```

- [ ] **Step 5: 跑測試**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`

---

### Task 6: 全量回歸驗證

- [ ] **Step 1: 全量 pytest**
Run: `cd /Users/chenliangyu/kg && python -m pytest backend/tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 2: Commit**

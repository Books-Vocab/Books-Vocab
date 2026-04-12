# Critical Bugfix Sweep Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 6 CRITICAL and top HIGH issues identified by the 10-agent deep scan, prioritized by user-facing impact (data loss > silent failure > security).

**Architecture:** Backend fixes are independent Python changes with tests. iOS fixes are independent Swift changes. Each task produces a single commit. Tasks are grouped so backend tasks can run in parallel with each other, and iOS tasks can run in parallel with each other.

**Tech Stack:** Python 3.12 / FastAPI / SQLModel / SQLite; Swift / SwiftUI / SwiftData

---

## File Map

| Task | Create | Modify | Test |
|------|--------|--------|------|
| T1: Mochi sync lock | — | `backend/src/kg/mochi_sync.py` | `backend/tests/test_mochi_sync_lock.py` |
| T2: Delete transaction | — | `backend/src/kg/vocab_service.py`, `backend/src/kg/cards.py` | `backend/tests/test_vocab_service.py` (extend) |
| T3: Error message leakage | — | `backend/src/kg/billing_handlers.py`, `google_auth.py`, `apple_auth.py` | `backend/tests/test_error_leakage.py` |
| T4: Notebook ownership | — | `backend/src/kg/vocab_handlers.py`, `backend/src/kg/notebook.py` | `backend/tests/test_notebook_ownership.py` |
| T5: 401 → logout (iOS) | — | `ios/BooksBrowser/Services/KGService+Sync.swift` | Manual / UI test |
| T6: lastReviewedAt guard (iOS) | — | `ios/BooksBrowser/Services/BackgroundSyncActor.swift` | Manual / unit test |
| T7: GraphWebView leak (iOS) | — | `ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift` | Manual |

---

## Task 1: Mochi sync — 加入 FileLock 防止並發寫入

**Files:**
- Modify: `backend/src/kg/mochi_sync.py:72-77` (_save), `:45-71` (_load), `:103-212` (sync)
- Create: `backend/tests/test_mochi_sync_lock.py`

**Context:** `mochi_sync.py` 使用 `_save()` 寫 JSON（tmp → rename），但多個 pipeline 可同時觸發 sync，無 lock 保護。專案已有 `filelock` 依賴（`user_store.py` 使用）。

- [ ] **Step 1: Write failing test — concurrent sync corrupts map**

```python
# backend/tests/test_mochi_sync_lock.py
"""Verify MochiSync file operations are protected by a lock."""
import threading, json, time
from pathlib import Path
from unittest.mock import MagicMock, patch

from kg.mochi_sync import MochiSync


def test_concurrent_save_no_corruption(tmp_path):
    """Two threads saving simultaneously must not lose entries."""
    sync_path = tmp_path / "mochi_sync.json"
    sync_path.write_text(json.dumps({"map": {}, "state": {}}))

    errors = []

    def writer(sync: MochiSync, card_id: str, mochi_id: str):
        try:
            sync._map[card_id] = mochi_id
            sync._save()
        except Exception as e:
            errors.append(e)

    from filelock import FileLock
    lock = FileLock(str(sync_path) + ".lock", timeout=30)

    sync_a = MochiSync.__new__(MochiSync)
    sync_a._sync_path = sync_path
    sync_a._file_lock = lock
    sync_a._map = {"card_a": "mochi_a"}
    sync_a._state = {}

    sync_b = MochiSync.__new__(MochiSync)
    sync_b._sync_path = sync_path
    sync_b._file_lock = lock
    sync_b._map = {"card_b": "mochi_b"}
    sync_b._state = {}

    t1 = threading.Thread(target=writer, args=(sync_a, "card_a", "mochi_a"))
    t2 = threading.Thread(target=writer, args=(sync_b, "card_b", "mochi_b"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors
    data = json.loads(sync_path.read_text())
    # With a lock, the last writer wins cleanly (no corruption)
    assert isinstance(data["map"], dict)
```

- [ ] **Step 2: Run test — verify it passes or reveals race**

```bash
cd backend && python -m pytest tests/test_mochi_sync_lock.py -v
```

- [ ] **Step 3: Add FileLock to _save and _load**

In `mochi_sync.py`, add lock around file I/O:

```python
# At top of file, add import
from filelock import FileLock

# In __init__ (or _load), initialize lock path
self._file_lock = FileLock(str(self._sync_path) + ".lock", timeout=30)

# Wrap _save:
def _save(self) -> None:
    """Atomically write map + state as a single JSON file."""
    with self._file_lock:
        self._sync_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._sync_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps({"map": self._map, "state": self._state}, indent=2))
        tmp_path.replace(self._sync_path)

# Wrap _load:
def _load(self) -> None:
    with self._file_lock:
        # ... existing load logic ...
```

- [ ] **Step 4: Run test — verify pass**

```bash
cd backend && python -m pytest tests/test_mochi_sync_lock.py -v
```

- [ ] **Step 5: Run full test suite — no regression**

```bash
cd backend && python -m pytest --timeout=60 -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/mochi_sync.py backend/tests/test_mochi_sync_lock.py
git commit -m "api: mochi sync 加 FileLock 防止並發寫入導致卡片重複"
```

---

## Task 2: delete_vocab_word — 三步操作加 transaction 保護

**Files:**
- Modify: `backend/src/kg/vocab_service.py:222-232`
- Modify: `backend/tests/test_vocab_service.py` (extend)

**Context:** `delete_vocab_word` 依序呼叫 `cards_store.delete()` → `graph.deprecate_links_for()` → `graph.remove_candidates_for()`，中途失敗產生孤立記錄。`cards_store.delete()` 內部用 SQLModel session，graph 操作是 JSON 檔案。需確保 graph 操作失敗時 card delete 也 rollback。

- [ ] **Step 1: Write failing test — graph failure leaves card deleted**

```python
# Append to backend/tests/test_vocab_service.py

def test_delete_rolls_back_on_graph_failure(tmp_path):
    """If graph operations fail, card deletion must be rolled back."""
    from kg.vocab_service import delete_vocab_word

    from kg.cards import CardStore
    cards_store = CardStore(tmp_path / "cards.db")
    card = cards_store.add("testword", meaning="test meaning", notebook_id="default")
    card_id = card.id

    class _FailingGraph:
        def deprecate_links_for(self, cid):
            raise RuntimeError("graph write failed")
        def remove_candidates_for(self, cid):
            pass

    with pytest.raises(RuntimeError):
        delete_vocab_word("testword", cards_store=cards_store, graph=_FailingGraph())

    # Card should NOT be deleted since graph failed
    assert cards_store.get(card_id) is not None
```

- [ ] **Step 2: Run test — verify it fails (card IS deleted despite graph error)**

```bash
cd backend && python -m pytest tests/test_vocab_service.py::test_delete_rolls_back_on_graph_failure -v
```
Expected: FAIL — card is deleted but graph operation failed.

- [ ] **Step 3: Wrap delete in try/except, rollback on graph failure**

In `vocab_service.py`, modify `delete_vocab_word`:

```python
def delete_vocab_word(
    word: str,
    *,
    cards_store,
    graph=None,
    notebook_id: str | None = None,
) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise HTTPException(status_code=422, detail="Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise HTTPException(404, f"Word '{word}' not found")

    # Soft-delete first, then graph ops; restore if graph fails
    cards_store.delete(card.id)
    if graph is not None:
        try:
            graph.deprecate_links_for(card.id)
            graph.remove_candidates_for(card.id)
        except Exception:
            cards_store.restore(card.id)
            raise
    return {"deleted": word, "id": card.id}
```

Note: 需確認 `cards_store` 是否支援 `restore()`。若 delete 是軟刪除（`is_deleted=True`），restore 只需設回 `False`。檢查 `cards.py` 的 `delete` 方法：它設定 `is_deleted=True` + `updated_at`，所以 restore 是可行的。需在 `cards.py` 新增 `restore` 方法。

- [ ] **Step 3b: Add restore method to CardStore**

In `backend/src/kg/cards.py`, add after `delete` method:

```python
def restore(self, card_id: str) -> None:
    """Undo a soft-delete. Used when a dependent operation fails."""
    with Session(self.engine) as session:
        card = session.get(Card, card_id)
        if card:
            card.is_deleted = False
            card.updated_at = _now()
            session.commit()
```

- [ ] **Step 4: Run test — verify pass**

```bash
cd backend && python -m pytest tests/test_vocab_service.py::test_delete_rolls_back_on_graph_failure -v
```

- [ ] **Step 5: Run full test suite**

```bash
cd backend && python -m pytest --timeout=60 -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/cards.py backend/src/kg/vocab_service.py backend/tests/test_vocab_service.py
git commit -m "api: delete_vocab_word 加 rollback — graph 失敗時復原卡片"
```

---

## Task 3: 錯誤訊息洩漏 — 移除 str(exc) 回傳

**Files:**
- Modify: `backend/src/kg/billing_handlers.py:55,57,95,97,174,176,178,180`
- Modify: `backend/src/kg/google_auth.py:41`
- Modify: `backend/src/kg/apple_auth.py:39,119`
- Create: `backend/tests/test_error_leakage.py`

- [ ] **Step 1: Write failing test — error response must not contain exception details**

```python
# backend/tests/test_error_leakage.py
"""Verify error responses do not leak internal exception details."""
import re
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


def _get_client():
    from kg.api import create_app
    app = create_app()
    return TestClient(app)


SENSITIVE_PATTERNS = [
    re.compile(r"Traceback"),
    re.compile(r"File \""),
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"\.py\", line \d+"),
]


def _assert_no_leak(detail: str):
    for pat in SENSITIVE_PATTERNS:
        assert not pat.search(detail), f"Leaked internal info: {detail!r}"
```

- [ ] **Step 2: Run test to verify setup works**

```bash
cd backend && python -m pytest tests/test_error_leakage.py -v
```

- [ ] **Step 3: Fix billing_handlers.py — replace str(exc) with generic messages**

Replace all `detail=str(exc)` and `detail=f"...{exc}"` with generic messages. Keep `logger.error(...)` for internal logging.

Changes in `billing_handlers.py`:
- Line 55: `detail="App Store configuration error"` (was `str(exc)`)
- Line 57: `detail="Transaction verification failed"` (was `str(exc)`)
- Line 95: same pattern
- Line 97: same pattern
- Line 174: `detail="App Store service error"`
- Line 176: `detail="Invalid transaction response"`
- Line 178: keep as-is (only exposes HTTP status code, not sensitive)
- Line 180: `detail="App Store service unavailable"`

Add `logger.error("...: %s", exc)` before each raise if not already present.

- [ ] **Step 4: Fix google_auth.py — line 41**

```python
except ValueError as e:
    logger.warning("Google token validation failed: %s", e)
    raise HTTPException(status_code=401, detail="Invalid token")
```

- [ ] **Step 5: Fix apple_auth.py — lines 39, 119**

```python
# Line 39
except (httpx.HTTPError, ValueError, KeyError) as e:
    logger.error("Failed to fetch Apple keys: %s", e)
    if not _apple_public_keys:
        raise HTTPException(status_code=500, detail="Authentication service unavailable")

# Line 119
except jwt.PyJWTError as e:
    logger.warning("Apple token validation failed: %s", e)
    raise HTTPException(status_code=401, detail="Invalid token")
```

- [ ] **Step 6: Run tests**

```bash
cd backend && python -m pytest --timeout=60 -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/src/kg/billing_handlers.py backend/src/kg/google_auth.py backend/src/kg/apple_auth.py backend/tests/test_error_leakage.py
git commit -m "api: 移除錯誤回應中的內部資訊洩漏"
```

---

## Task 4: Notebook ownership 驗證

**Files:**
- Modify: `backend/src/kg/vocab_handlers.py` (add validation at entry points)
- Modify: `backend/src/kg/notebook.py` (add ownership check helper)
- Create: `backend/tests/test_notebook_ownership.py`

**Context:** `vocab_handlers.py` 的所有 handler 接收 `notebook_id` 但不驗證該 notebook 是否屬於當前使用者。notebook 清單在 `user["dir"] / "notebooks.json"` 或由 `notebook.NotebookStore` 管理。

- [ ] **Step 1: Research — 確認 notebook ownership 資料來源**

Read `backend/src/kg/notebook.py` to find how notebooks are stored per user, and what method lists a user's notebooks.

- [ ] **Step 2: Write failing test**

```python
# backend/tests/test_notebook_ownership.py
"""Verify vocab endpoints reject notebook_id not belonging to user."""
import pytest

def test_vocab_list_rejects_foreign_notebook(user_env):
    """GET /api/vocab?notebook_id=foreign should return 403."""
    client, headers, _ = user_env
    resp = client.get("/api/vocab?notebook_id=nonexistent_notebook", headers=headers)
    assert resp.status_code == 403
```

- [ ] **Step 3: Add validation helper**

In `notebook.py`, add `exists()` method to `NotebookStore` and a validation helper.

Note: `NotebookStore.__init__` takes a DB file path (not a directory). The factory in `service_factories.py` constructs it via `notebook_store_factory(user["dir"])` which builds the correct path. Follow the same factory pattern.

```python
# Add to NotebookStore class:
def exists(self, notebook_id: str) -> bool:
    """Check if a non-deleted notebook exists."""
    nb = self.get(notebook_id)
    return nb is not None and not nb.is_deleted

# Add as module-level helper:
from fastapi import HTTPException

def validate_notebook_access(notebook_store, notebook_id: str) -> None:
    """Raise 403 if notebook_id does not belong to this user."""
    if not notebook_store.exists(notebook_id):
        raise HTTPException(403, "Notebook access denied")
```

- [ ] **Step 4: Wire validation into vocab_handlers.py**

At the top of each handler function that accepts `notebook_id`, use the existing notebook_store from service factories:

```python
if notebook_id:
    from kg.notebook import validate_notebook_access
    notebook_store = notebook_store_factory(user["dir"])
    validate_notebook_access(notebook_store, notebook_id)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_notebook_ownership.py -v
cd backend && python -m pytest --timeout=60 -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/notebook.py backend/src/kg/vocab_handlers.py backend/tests/test_notebook_ownership.py
git commit -m "api: notebook_id 所有權驗證 — 防止跨使用者存取"
```

---

## Task 5: iOS — backgroundSync 401 觸發 logout

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Sync.swift:164-192`

**Context:** 目前 backgroundSync 捕捉所有錯誤只記錄 failure name，401 不會觸發 session invalidation。`healthCheck` 已有 logout 邏輯可參考。

- [ ] **Step 1: Read healthCheck logout pattern**

Check `KGService+Sync.swift` for the existing `healthCheck` method that handles 401 → logout.

- [ ] **Step 2: Add 401 detection in backgroundSync catch blocks**

In the catch blocks around pushReviewStates, pullCards etc., detect `KGError.unauthorized`:

```swift
// In backgroundSync, after each catch block, add 401 detection.
// KGService owns `sessionInvalidator: any SessionInvalidating`.
// Use idiomatic Swift pattern matching:
} catch KGError.unauthorized {
    // Token expired — signal logout instead of silent failure
    await sessionInvalidator.logout(modelContainer: container, reason: "backgroundSync_401")
    lastBackgroundSyncError = "Session expired"
    return
} catch {
    failures.append("pushReview")
}
```

Apply same pattern to all try blocks in backgroundSync. Reference `healthCheck` method in the same file for the existing logout pattern using `sessionInvalidator`.

- [ ] **Step 3: Build**

```bash
cd /Users/chenliangyu/kg && ./ops/ios_build.sh
```

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Sync.swift
git commit -m "ios: backgroundSync 401 → 登出 — 避免 token 過期靜默失敗"
```

---

## Task 6: iOS — lastReviewedAt nil guard 修復

**Files:**
- Modify: `ios/BooksBrowser/Services/BackgroundSyncActor.swift:192`

**Context:** `buildReviewStatePushPayload()` 中 `guard let lastReviewed = entry.lastReviewedAt else { continue }` 導致 reviewCount > 0 但 lastReviewedAt 為 nil 的卡片永遠不會 push。

- [ ] **Step 1: Fix the guard — use fallback date for nil lastReviewedAt**

```swift
// Replace line 192:
// OLD: guard let lastReviewed = entry.lastReviewedAt else { continue }
// NEW:
let lastReviewed = entry.lastReviewedAt ?? entry.dateAdded
```

This uses `dateAdded` as fallback (VocabularyEntry 沒有 `createdAt`，有 `dateAdded: Date`) — if a card has reviews but no `lastReviewedAt`, the add date is a safe lower bound.

- [ ] **Step 2: Build**

```bash
cd /Users/chenliangyu/kg && ./ops/ios_build.sh
```

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Services/BackgroundSyncActor.swift
git commit -m "ios: lastReviewedAt nil fallback — 新卡片 review state 不再靜默跳過"
```

---

## Task 7: iOS — GraphWebView Coordinator 記憶體洩漏

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift:169-223`

**Context:** `Coordinator` 持有 `onNodeTap: (String) -> Void` 強 closure，且 `DispatchQueue.main.async { self.onNodeTap(nodeId) }` 捕捉 self。WKWebView 的 scriptMessageHandler 持有 Coordinator → 循環引用。

- [ ] **Step 1: Break the retain cycle with dismantleUIView + weak closure**

The real cycle is: WKWebView → WKUserContentController → Coordinator (via scriptMessageHandler, strong ref). `deinit` never fires because the cycle keeps Coordinator alive. Fix requires two changes:

**A) Add `dismantleUIView` to GraphWebView (UIViewRepresentable):**

```swift
static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
    webView.configuration.userContentController.removeScriptMessageHandler(forName: "graphBridge")
    coordinator.onNodeTap = nil
}
```

**B) Make onNodeTap optional + weak self in dispatch:**

```swift
class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var graphBridgeReady = false
    var pendingPayload: String? = nil
    weak var webView: WKWebView?
    var onNodeTap: ((String) -> Void)?  // Change to optional

    // In userContentController:
    case "nodeClick":
        if let nodeId = body["nodeId"] as? String {
            DispatchQueue.main.async { [weak self] in
                self?.onNodeTap?(nodeId)
            }
        }
    }
}
```

Also update `makeCoordinator` and `updateUIView` to match optional type.

- [ ] **Step 2: Build**

```bash
cd /Users/chenliangyu/kg && ./ops/ios_build.sh
```

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/GraphWebView.swift
git commit -m "ios: GraphWebView Coordinator 改 weak closure — 修復記憶體洩漏"
```

---

## Execution Strategy

**Backend tasks (T1–T4)** 彼此獨立，可用 4 個 subagent 並行在各自 worktree 執行。

**iOS tasks (T5–T7)** 共用 Xcode build，建議在同一 worktree 依序執行（因 ios_build.sh 有 shlock 排隊鎖但不必要地佔 DerivedData）。

```
Parallel group A (backend):  T1  T2  T3  T4
Parallel group B (iOS):      T5 → T6 → T7
```

完成後在 main 合併所有分支，跑完整 backend test suite 驗證無 regression。

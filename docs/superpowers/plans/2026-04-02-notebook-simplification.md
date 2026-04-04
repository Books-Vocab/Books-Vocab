# Notebook 簡化 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 移除移動功能、將 notebook 刪除從遷移改為硬刪，消除所有跨 notebook graph 操作。
**Architecture:** 純刪碼 + notebook delete endpoint 行為變更。Backend 和 iOS 平行處理。
**Tech Stack:** Python/FastAPI, Swift/SwiftUI

---

### Task 1: Backend — 新增 `CardStore.soft_delete_by_notebook`

**Files:**
- Modify: `backend/src/kg/cards.py:338` (在 `reassign_notebook` 之前插入)
- Test: `backend/tests/test_cards.py`

- [ ] **Step 1: 寫 failing test**
```python
# test_cards.py — 加在檔案末尾
class TestSoftDeleteByNotebook:
    def test_soft_deletes_all_cards_in_notebook(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        store.add(content="apple", meaning="蘋果", notebook_id="nb1")
        store.add(content="banana", meaning="香蕉", notebook_id="nb1")
        store.add(content="cherry", meaning="櫻桃", notebook_id="nb2")
        count = store.soft_delete_by_notebook("nb1")
        assert count == 2
        # nb1 cards are deleted
        assert store.all(notebook_id="nb1") == []
        # nb2 untouched
        assert len(store.all(notebook_id="nb2")) == 1

    def test_skips_already_deleted(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        c = store.add(content="apple", meaning="蘋果", notebook_id="nb1")
        store.delete(c.id)
        count = store.soft_delete_by_notebook("nb1")
        assert count == 0

    def test_empty_notebook_returns_zero(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        count = store.soft_delete_by_notebook("nonexistent")
        assert count == 0
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_cards.py::TestSoftDeleteByNotebook -v`
Expected: FAIL (AttributeError: 'CardStore' object has no attribute 'soft_delete_by_notebook')

- [ ] **Step 3: 寫最小實作**
在 `cards.py` 的 `reassign_notebook` 方法之前加入：
```python
def soft_delete_by_notebook(self, notebook_id: str) -> int:
    """Soft-delete all non-deleted cards in a notebook. Returns count."""
    now = datetime.now(UTC)
    with Session(self.engine) as session:
        cards = session.exec(
            select(Card).where(
                Card.notebook_id == notebook_id,
                Card.is_deleted.is_(False),
            )
        ).all()
        for card in cards:
            card.is_deleted = True
            card.updated_at = now
            session.add(card)
        session.commit()
        return len(cards)
```

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_cards.py::TestSoftDeleteByNotebook -v`

- [ ] **Step 5: Commit**
`api: add CardStore.soft_delete_by_notebook`

---

### Task 2: Backend — 改寫 notebook delete endpoint

**Files:**
- Modify: `backend/src/kg/routers/notebook.py:77-104`
- Modify: `backend/src/kg/service_factories.py` (新增 cache eviction helper)
- Test: `backend/tests/test_notebook_api.py`

- [ ] **Step 1: 寫 failing test**
在 `test_notebook_api.py` 新增或修改 delete test，驗證新行為：
```python
def test_delete_notebook_deletes_cards(self):
    """Delete notebook should soft-delete cards, not reassign to default."""
    # 建立 notebook + cards
    nb = self.client.post("/api/notebooks", json={"name": "temp"}).json()
    nb_id = nb["id"]
    self.client.post(f"/api/vocab?notebook_id={nb_id}", json={"word": "test", "meaning": "測試"})
    # Delete
    resp = self.client.delete(f"/api/notebooks/{nb_id}")
    data = resp.json()
    assert data["cardsDeleted"] == 1
    assert "cardsReassigned" not in data
    # Cards in default should NOT have increased
    default_cards = self.client.get("/api/vocab?notebook_id=default").json()
    assert not any(c["word"] == "test" for c in default_cards)
```

- [ ] **Step 2: 跑 test 確認失敗**
Expected: FAIL (response 仍含 `cardsReassigned`)

- [ ] **Step 3: 寫實作**

`service_factories.py` — 新增 eviction helper：
```python
def evict_notebook_cache(user_dir: Path, notebook_id: str) -> None:
    """Remove cached graph and embedding stores for a deleted notebook."""
    with _STORE_CACHE_LOCK:
        for prefix in ("graph", "embedding"):
            key = f"{prefix}:{user_dir}:{notebook_id}"
            store = _STORE_CACHE.pop(key, None)
            if store is not None:
                _close_store(store)
```

`routers/notebook.py` — 改寫 `delete_notebook`：
```python
@router.delete("/api/notebooks/{nb_id}")
def delete_notebook(nb_id: str, user: dict = Depends(get_current_user)):
    store = _notebook_store(user["dir"])
    cards = _card_store(user["dir"])
    result = store.delete(nb_id)
    if result is False:
        raise BadRequestError("Cannot delete: notebook not found or is default")
    cards_deleted = 0
    if result is True:
        cards_deleted = cards.soft_delete_by_notebook(nb_id)
        # Delete graph files
        for pattern in [
            f"graph_{nb_id}.json", f"candidates_{nb_id}.json", f"blocked_{nb_id}.json",
        ]:
            for suffix in ("", ".bak", ".tmp"):
                (user["dir"] / (pattern + suffix)).unlink(missing_ok=True)
        # Delete embedding files
        for pattern in [f"embeddings_{nb_id}.npy", f"card_ids_{nb_id}.json"]:
            for suffix in ("", ".bak", ".tmp"):
                (user["dir"] / (pattern + suffix)).unlink(missing_ok=True)
        # Evict cached stores
        from ..service_factories import evict_notebook_cache
        evict_notebook_cache(user["dir"], nb_id)
    return {"deleted": nb_id, "cardsDeleted": cards_deleted}
```

移除舊的 import：`TrackedLLM`、`_embedding_store`、`_gemini_client`（如果不再被其他函數使用）。

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_notebook_api.py -v`

- [ ] **Step 5: Commit**
`api: notebook delete — hard-delete cards instead of reassign`

---

### Task 3: Backend — 刪除 move API 及相關程式碼

**Files:**
- Modify: `backend/src/kg/routers/vocab.py:157-169` (刪除 endpoint)
- Modify: `backend/src/kg/vocab_handlers.py:134-156` (刪除 `move_words_response`)
- Modify: `backend/src/kg/vocab_crud.py:181-221` (刪除 `move_vocab_words`)
- Modify: `backend/src/kg/cards.py:355-377` (刪除 `CardStore.move_cards`)
- Modify: `backend/src/kg/api_models.py:408-414` (刪除 `MoveWordsRequest` / `MoveWordsResponse`)
- Delete: `backend/tests/test_move_cards.py`
- Modify: `backend/tests/test_vocab_service.py` (刪除 move 相關 classes)
- Modify: `backend/tests/test_cards.py` (刪除 `TestMoveVocabWordsNoExtraScan`)

- [ ] **Step 1: 刪除 endpoint + handler + service + model + card method**
按以下順序刪除：
1. `routers/vocab.py` — 刪除 `move_words` endpoint 及其 import（`MoveWordsRequest`, `MoveWordsResponse`, `move_words_response`）
2. `vocab_handlers.py` — 刪除 `move_words_response` 函數及其 import（`MoveWordsRequest`, `move_vocab_words`）
3. `vocab_crud.py` — 刪除 `move_vocab_words` 函數，更新 module docstring
4. `cards.py` — 刪除 `move_cards` 方法
5. `api_models.py` — 刪除 `MoveWordsRequest` 和 `MoveWordsResponse`

- [ ] **Step 2: 刪除 tests**
1. 刪除整個 `test_move_cards.py`
2. `test_vocab_service.py` — 刪除 `_FakeMoveCardsStore` 和 `TestMoveVocabWordsNoNPlusOne`
3. `test_cards.py` — 刪除 `TestMoveVocabWordsNoExtraScan`

- [ ] **Step 3: 跑全部 backend tests 確認無破壞**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/ -v --tb=short`

- [ ] **Step 4: Commit**
`api: remove move vocabulary API and all related code`

---

### Task 4: Backend — 刪除 merge_from 及 reassign_notebook 死程式碼

**Files:**
- Modify: `backend/src/kg/graph.py:482-524` (刪除 `merge_from`)
- Modify: `backend/src/kg/embeddings.py:167-197` (刪除 `merge_from`)
- Modify: `backend/src/kg/cards.py:338-353` (刪除 `reassign_notebook`)
- Delete: `backend/tests/test_notebook_delete_cleanup.py`
- Modify: `backend/tests/test_hide_link.py` (刪除 `merge_from` 相關 tests)

- [ ] **Step 1: 刪除 `GraphStore.merge_from`**
刪除 `graph.py` 的 `merge_from` 方法（含 `# Merge` section header）

- [ ] **Step 2: 刪除 `EmbeddingStore.merge_from`**
刪除 `embeddings.py` 的 `merge_from` 方法

- [ ] **Step 3: 刪除 `CardStore.reassign_notebook`**
刪除 `cards.py` 的 `reassign_notebook` 方法

- [ ] **Step 4: 刪除相關 tests**
1. 刪除整個 `test_notebook_delete_cleanup.py`
2. `test_hide_link.py` — 找到並刪除 `merge_from` 相關 test functions

- [ ] **Step 5: 跑全部 backend tests**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/ -v --tb=short`

- [ ] **Step 6: Commit**
`api: remove merge_from and reassign_notebook dead code`

---

### Task 5: iOS — 移除移動功能

**Files:**
- Delete: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookPickerSheet.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/SelectionToolbar.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabCoordinator.swift`
- Modify: `ios/BooksBrowser/Services/KGServing.swift`
- Modify: `ios/BooksBrowser/Services/KGService+VocabCRUD.swift`

- [ ] **Step 1: 刪除 `NotebookPickerSheet.swift`**

- [ ] **Step 2: 修改 `SelectionToolbar.swift`**
移除 `onMove` 參數和移動按鈕：
```swift
struct SelectionToolbar: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

    let selectionCount: Int
    let onArchive: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            toolbarButton(
                label: "封存".localized,
                systemImage: "archivebox",
                tone: vocabSkin.palette.quaternaryText,
                action: onArchive
            )
            toolbarButton(
                label: "刪除".localized,
                systemImage: "trash",
                tone: appTheme.palette.destructive,
                action: onDelete
            )
        }
        // ... 其餘不變
    }
    // ... toolbarButton 不變，Preview 移除 onMove
}
```

- [ ] **Step 3: 修改 `KGVocabView.swift`**
1. 移除 `@State private var showNotebookPicker = false`
2. `SelectionToolbar` 呼叫移除 `onMove` 參數
3. 移除 `.toastSheet(isPresented: $showNotebookPicker)` block（190-194 行）
4. 移除 `handleBatchMove(to:)` 函數（311-329 行）
5. 移除 `NotebookPickerSheet` 的 import（如果是顯式 import）

- [ ] **Step 4: 修改 `KGVocabCoordinator.swift`**
1. Protocol `KGVocabCoordinating`：移除 `handleBatchMove` 宣告（第 17 行）
2. Class `KGVocabCoordinator`：移除 `handleBatchMove` 實作（187-205 行）

- [ ] **Step 5: 修改 `KGServing.swift` + `KGService+VocabCRUD.swift`**
1. `KGServing.swift`：移除 `moveCards` protocol 宣告（第 37 行）
2. `KGService+VocabCRUD.swift`：移除 `moveCards` 實作（77-85 行）

- [ ] **Step 6: Build 驗證**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && ./ops/ios_build.sh`

- [ ] **Step 7: Commit**
`ios: remove move vocabulary feature`

---

### Task 6: iOS — 更新 notebook 刪除確認文字

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:195`

- [ ] **Step 1: 修改確認 dialog 文字**
```swift
// 舊
Text("單字本內的單字不會被刪除，將移至預設單字本。".localized)
// 新
Text("此單字本及所有單字將被永久刪除，無法復原。".localized)
```

- [ ] **Step 2: Build 驗證**
Run: `cd /Users/chenliangyu/MPSO/projects/kg && ./ops/ios_build.sh`

- [ ] **Step 3: Commit**
`ios: update notebook delete confirmation — warn permanent deletion`

---

## 執行順序

```
Task 1 (CardStore 新方法)
  └→ Task 2 (notebook delete 改寫) ──→ Task 4 (刪死程式碼)
Task 3 (刪 move API) ─── 可與 Task 1-2 平行
Task 5 (iOS 刪移動) ──── 可與 backend 全部平行
Task 6 (iOS 改文字) ──── 接在 Task 5 之後或合併
```

Backend: 1 → 2 → 3 → 4（3 可平行）
iOS: 5 → 6（可與 backend 平行）

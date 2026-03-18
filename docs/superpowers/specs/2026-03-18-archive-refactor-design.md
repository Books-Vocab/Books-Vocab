# 封存重構設計

## 問題

封存入口位於個別單字本內部（`VocabularyListView` toolbar），語意上卻是跨單字本的操作。封存後的單字仍保留圖譜連結（僅視覺標為 `archived` tier），不符合「封存 = 完全抽離活躍狀態」的預期。

## 設計目標

封存的單字只能被主動瀏覽，不會被動出現在任何地方：
- 不出現在知識庫列表
- 不出現在復習排程
- 不出現在知識圖譜
- 不被 Reader 畫底線

## 變更

### 1. UI 入口搬遷

**移除**：`VocabularyListView+Toolbar` 中的封存按鈕及 badge 計數。

**新增**：`NotebookListView` toolbar 右上角 archivebox icon，位於 `+` 按鈕左邊。無 badge。點擊開啟 `ArchivedVocabSheet`（現有元件，已是跨單字本 query）。

涉及檔案：
- `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift` — 新增 toolbar item
- `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift` — 移除封存按鈕
- `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift` — 移除 `showArchiveList` state 及相關 sheet
- `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift` — 移除 ArchivedVocabSheet 綁定

### 2. Backend — 封存時管理圖譜連結

修改 `vocab_service.archive_vocab_word`，增加 `graph` 參數：

- **封存**（`archived=true`）：呼叫 `graph.deprecate_links_for(card_id)` + `graph.remove_candidates_for(card_id)`。連結資料保留在 JSON 中（`status="deprecated"`），不硬刪除。
- **解封存**（`archived=false`）：呼叫新方法 `graph.restore_links_for(card_id, cards_store)`。

涉及檔案：
- `backend/src/kg/vocab_service.py` — `archive_vocab_word` 增加 graph 參數及邏輯
- `backend/src/kg/vocab_handlers.py` — `archive_word_response` 傳入 graph
- `backend/src/kg/routers/vocab.py` — route handler 傳入 graph factory
- `backend/src/kg/graph.py` — 新增 `restore_links_for` 方法

### 3. GraphStore.restore_links_for

新增方法於 `graph.py`：

```python
def restore_links_for(self, card_id: str, cards_store) -> int:
    """Restore deprecated links for a card. Only restores links where the
    other end is alive (!is_deleted and !is_archived). Returns count restored."""
    link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
    count = 0
    for lid in list(link_ids):
        lk = self._links.get(lid)
        if lk and lk.status == "deprecated":
            other_id = lk.to_id if lk.from_id == card_id else lk.from_id
            other_card = cards_store.get(other_id)
            if other_card and not other_card.is_deleted and not other_card.is_archived:
                lk.status = "active"
                count += 1
    if count:
        self._save_links()
    return count
```

### 4. iOS 圖譜視覺化 — 移除封存節點

修改 `KnowledgeGraphPresentation`：封存的 entry 直接 `return nil`，不再渲染為 `"archived"` tier 節點。

涉及檔案：
- `ios/BooksBrowser/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift`

### 5. 不需變更的部分

| 項目 | 原因 |
|------|------|
| 復習排程 | `shouldAppearInKnowledgeList` 已排除 `isArchived`，所有 due/review entries 過濾鏈已正確 |
| Reader 底線 | `shouldAppearInReader` 已排除 `isArchived` |
| `ArchivedVocabSheet` UI | 已是跨單字本的 `@Query(filter: isArchived == true)`，無需改動 |
| API 端點路徑 | `PATCH /api/vocab/{word}/archive` 不變 |
| iOS `kgService.archiveCard` | 呼叫方式不變 |
| 同步邏輯 | `BackgroundSyncActor` 已正確同步 `isArchived` 欄位 |

## 邊界情況

1. **A↔B 連結，B 被封存後又被刪除，再解封存 A**：`restore_links_for` 檢查對端 `!is_deleted`，此連結不會被恢復，保持 `deprecated`。正確行為。

2. **A↔B 連結，A 和 B 都被封存**：兩者各自 deprecate 一次（冪等，已 deprecated 的不重複計數）。先解封存 A 時，B 仍是 archived，A↔B 不恢復。B 也解封存後，restore 時 A 已 active，連結恢復。正確行為。

3. **封存後該卡片有新的 candidates 產生**（其他新卡片 embedding 相似）：`remove_candidates_for` 只移除當下的 candidates。新 pipeline 跑的時候，`embed_and_link_new_cards` 會查 `cards.all()` — 需確認此方法是否排除 archived 卡片，否則封存卡片仍會被選為候選目標。

### 6. Embedding pipeline 過濾封存卡片

`embed_and_link_new_cards`（`vocab_graph.py`）中 `embeddings.find_similar` 可能回傳封存卡片的 ID。需在 `add_candidate` 前檢查對端卡片 `!is_archived`。

涉及檔案：
- `backend/src/kg/vocab_graph.py` — `embed_and_link_new_cards` 增加過濾

具體改動：在 `for other_id, score in similar` 迴圈中，取出 `other_card = cards.get(other_id)`，跳過 `is_archived` 的卡片。

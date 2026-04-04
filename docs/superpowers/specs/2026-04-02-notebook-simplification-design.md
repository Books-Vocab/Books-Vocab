# Notebook 簡化設計：拿掉移動、硬刪 notebook

## 動機

移動單字跨 notebook 時必須處理 graph link 遷移、embedding 轉移、candidate 重建、blocked pair 轉移等問題，複雜度遠超其價值。Notebook 刪除時的 merge 邏輯同樣複雜且脆弱。

根本原因：graph 跟 notebook 綁定，每個跨 notebook 操作都變成 graph 遷移問題。

## 設計決策

**Notebook = 硬邊界。**

| 操作 | 新行為 |
|------|--------|
| **移動單字** | 功能移除。使用者在 A 刪掉、在 B 重新加。 |
| **刪除 notebook** | 確認後硬刪：cards soft-delete + graph/embedding 檔案刪除。不遷移到 default。 |

## 砍掉的東西

### Backend

1. **Move API endpoint** — `PATCH /api/vocab/move`
   - `routers/vocab.py:157-169`（endpoint）
   - `vocab_handlers.py:134-156`（`move_words_response`）
   - `vocab_crud.py:181-221`（`move_vocab_words`）
   - `cards.py:355-377`（`CardStore.move_cards`）
   - `api_models.py:408-414`（`MoveWordsRequest` / `MoveWordsResponse`）

2. **Notebook delete 的 merge 邏輯** — `routers/notebook.py:86-103`
   - `GraphStore.merge_from`（`graph.py:482-524`）
   - `EmbeddingStore.merge_from`（`embeddings.py:167-197`）
   - `CardStore.reassign_notebook`（`cards.py:338-353`）

3. **Tests**
   - `test_move_cards.py`（整個檔案）
   - `test_vocab_service.py` 中 move 相關 class（`_FakeMoveCardsStore`, `TestMoveVocabWordsNoNPlusOne`）
   - `test_cards.py` 中 `TestMoveVocabWordsNoExtraScan`
   - `test_notebook_delete_cleanup.py`（整個檔案）
   - `test_hide_link.py` 中 `merge_from` 相關 tests

### iOS

1. **Move 功能**
   - `KGService+VocabCRUD.swift:77-85`（`moveCards` API call）
   - `KGServing.swift:37`（protocol `moveCards` 宣告）
   - `KGVocabCoordinator.swift:17`（protocol `handleBatchMove` 宣告）
   - `KGVocabCoordinator.swift:187-205`（`handleBatchMove` 實作）
   - `KGVocabView.swift:144`（`onMove` wiring）
   - `KGVocabView.swift:190-194`（NotebookPicker sheet）
   - `KGVocabView.swift:311-329`（`handleBatchMove(to:)` private func）
   - `SelectionToolbar.swift`（移除 `onMove` 參數，只留封存/刪除）
   - `NotebookPickerSheet.swift`（整個檔案刪除）

2. **Notebook 刪除確認文字** — `NotebookListView.swift:195`
   - 從「單字本內的單字不會被刪除，將移至預設單字本。」
   - 改為「此單字本及所有單字將被永久刪除，無法復原。」

## 改動的東西

### Backend — Notebook 刪除改為硬刪

`routers/notebook.py` — `delete_notebook` endpoint：

```
舊：reassign cards to default → merge graph → merge embedding
新：soft-delete notebook 裡所有 cards → 刪除 graph/embedding 檔案 → evict cache
```

具體流程：
1. `notebook_store.delete(nb_id)` — soft-delete notebook（現有邏輯不變）
2. `cards_store.soft_delete_by_notebook(nb_id)` — 新方法：批次 soft-delete 該 notebook 所有卡片
3. 刪除 graph 檔案：`graph_{nb_id}.json`、`candidates_{nb_id}.json`、`blocked_{nb_id}.json` + `.bak`
4. 刪除 embedding 檔案：`embeddings_{nb_id}.npy`、`card_ids_{nb_id}.json` + `.bak`
5. Evict 相關 cache entries（`service_factories.py` 的 `_cache`）

Cards 用 soft-delete（`is_deleted=True`）以支援 iOS incremental sync — client 拉到 `is_deleted` 就本地刪除。

### CardStore 新方法

```python
def soft_delete_by_notebook(self, notebook_id: str) -> int:
    """Soft-delete all non-deleted cards in a notebook. Returns count."""
```

### API response 變更

```
舊：{"deleted": nb_id, "cardsReassigned": 5}
新：{"deleted": nb_id, "cardsDeleted": 5}
```

### iOS — NotebookListCoordinator

`deleteNotebook` 現有邏輯已足夠（call DELETE API → mark local notebook isDeleted → 下次 sync 處理 cards）。改動：
- 確認 dialog 文字更新
- 下次 pullCardsToLocal 時，server 回傳的 deleted cards 會自動被 iOS 本地清除

### 一併刪除的死程式碼

- `GraphStore.merge_from`（`graph.py:482-524`）— 唯一 caller 是 notebook delete 的 merge 邏輯，已砍
- `EmbeddingStore.merge_from`（`embeddings.py:167-197`）— 同上
- `CardStore.reassign_notebook`（`cards.py:338-353`）— 同上

### 保留不動

- `GraphStore.cleanup_for_card` — 仍被 archive/delete 使用
- `GraphStore.restore_links_for` — 仍被 unarchive 使用

## 遷移考量

無需資料遷移。這是純砍功能 + 行為變更。

## 風險

1. **使用者想搬單字** — 需要在 A 刪 + 在 B 加，review 歷史歸零。這是有意的取捨：簡單 > 方便。
2. **刪 notebook 不可逆** — 確認 dialog 要夠醒目。Backend 的 card soft-delete 理論上可 restore，但不對外暴露。

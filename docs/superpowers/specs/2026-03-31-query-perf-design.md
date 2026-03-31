# Query Performance Optimization — Design Spec

## Problem

使用者在查詢詞彙時感到延遲。根因分析：

1. **增量 sync 載全表**：`list_vocab_cards(since=...)` 呼叫 `all_as_dict(include_deleted=True)` 撈全部 card 進記憶體，即使只有少數 card 更新。已存在 `get_modified_since()` 方法但未被使用。
2. **`get_tier()` 無快取**：每次 response 組裝對每張 card 呼叫 `wordfreq.zipf_frequency()`，無快取。
3. **iOS `sortAndFilter` 先排序後過濾**：搜尋時對全量排序後才過濾，浪費。

## Solution

### P0: 增量查詢兩階段載入

**現狀**（`vocab_service.py:143-160`）：
```python
cards_by_id = cards_store.all_as_dict(include_deleted=True)  # 全表
cards = [c for c in cards_by_id.values() if c.updated_at > since]  # Python filter
```

**改為**：
- `since` 路徑：`get_modified_since()` 取變更 card → 逐一 `graph.get_links_for(card_id)` 收集鄰居 ID（graph 是 in-memory，N 次呼叫可接受）→ `CardStore.get_batch(neighbour_ids)` 一次 SQL 批次取鄰居 → 合併為 `cards_by_id`
- 全量路徑：`all_as_dict(include_deleted=False)`（deleted card 不在 dict 中時 `build_links_by_kind` 走 `if not other_card` 跳過，行為與原本 `other_card.is_deleted` 被跳過一致）

**新增方法**：`CardStore.get_batch(card_ids: set[str]) -> dict[str, Card]` — SQL `WHERE id IN (...)`，**不過濾 notebook_id**（link resolution 可跨 notebook，`build_links_by_kind` 只檢查 `is_deleted`/`is_archived`）

### P1: `get_zipf` LRU cache

`difficulty.py` 的 `get_zipf(word, lang)` 加 `@lru_cache(maxsize=4096)`。

### P2: iOS filter-before-sort

`VocabularyEntryPresentation.sortAndFilter` 當 `searchText` 非空時先 filter 再 sort。

## Non-goals

- GraphStore JSON → SQLite 遷移（太大，獨立專案）
- 寫入路徑 N+1 修復（本次只修讀取路徑）
- iOS debounce（已確認 `KGVocabView` 已用 `debouncedSearchText`）

## Risk

- P0 改變了 `list_vocab_cards` 的 `cards_by_id` 內容範圍（從全表→子集）。`build_links_by_kind` 中若鄰居不在 dict 中會被跳過（`if not other_card`），行為與原本 deleted/archived 被跳過一致。需在程式碼中加 comment 標註 `cards_by_id` 是子集，避免未來其他 consumer 誤假設全表。
- P0 `since` 路徑中，回傳的 card 只有 modified cards，鄰居 card 只在 link resolution dict 中，不出現在 response 中。這與現有行為一致。
- P1 `lru_cache` 是 process-global，但 word→zipf 映射是確定性的，無 invalidation 需求。cache key 是 `(word, lang)` 整個 phrase，非個別 token。

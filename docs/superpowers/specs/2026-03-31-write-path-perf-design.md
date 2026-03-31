# Write Path Performance Optimization — Design Spec

## Problem

寫入路徑多處存在 N+1 pattern：迴圈內逐筆 DB query 或逐筆磁碟寫入。

## Fixes

1. **`add_vocab_entries`** — duplicate 路徑逐筆 `find_by_content` → 改用 `{norm_word: card}` dict
2. **`embed_and_link_new_cards`** — 兩處逐筆 `cards.get()` → 預載 `get_batch()`
3. **`_step_link`** — 逐筆 `cards.get()` ×2 → 預載 `get_batch()`
4. **`push_review_states`** — 逐筆 `cards_store.get()` → 預載 `get_batch()`
5. **`move_vocab_words`** — 逐筆 `add_candidate` → 已有 `batch_add_candidates`

## Non-goals

- GraphStore JSON → SQLite（獨立專案）
- `deprecate_links_for` batch 化（需新 API，另案）

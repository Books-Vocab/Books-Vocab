# Write Path Performance Optimization — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 消除寫入路徑的 N+1 DB query 和逐筆磁碟寫入。
**Architecture:** 迴圈內逐筆操作 → 迴圈外批次預載/寫入，使用已有的 `get_batch()` 和 `batch_add_candidates()`。
**Tech Stack:** Python/SQLModel

---

### Task 1: add_vocab_entries — dict lookup 取代 find_by_content

**Files:**
- Modify: `backend/src/kg/vocab_service.py` (add_vocab_entries, ~L477-533)
- Test: `backend/tests/test_vocab_service.py`

改動：在建 `existing` set 的同時，建 `{normalized_content: card}` dict。duplicate 路徑直接查 dict 取 card ID，不呼叫 `find_by_content`。

---

### Task 2: embed_and_link_new_cards — get_batch 預載

**Files:**
- Modify: `backend/src/kg/vocab_graph.py` (embed_and_link_new_cards, ~L15-62)
- Test: `backend/tests/test_vocab_service.py`

改動：
- L28-31：`cards.get_batch(set(card_ids.values()))` 預載所有 entry card
- L55：先收集所有 `find_similar` 結果的 `other_id`，`cards.get_batch(all_other_ids)` 一次查，再用 dict

---

### Task 3: _step_link — get_batch 預載 candidate cards

**Files:**
- Modify: `backend/src/kg/pipeline_service.py` (_step_link, ~L145-205)

改動：迴圈前收集所有 `candidate.from_id` + `candidate.to_id`，`cards.get_batch(all_ids)` 一次取。

---

### Task 4: push_review_states — get_batch 預載

**Files:**
- Modify: `backend/src/kg/vocab_service.py` (push_review_states, ~L174-250)

改動：收集所有 `entry.card_id`（非 None），`cards_store.get_batch(ids)` 一次取，建 dict。

---

### Task 5: move_vocab_words — batch_add_candidates

**Files:**
- Modify: `backend/src/kg/vocab_service.py` (move_vocab_words, ~L387-425)

改動：收集所有 `(card_id, other_id, 0.0)` tuple，一次呼叫 `target_graph.batch_add_candidates(pairs)`。

---

### Task 6: Regression

- Backend: `python -m pytest tests/ -v`
- iOS: `./ops/ios_build.sh`
- 開 PR

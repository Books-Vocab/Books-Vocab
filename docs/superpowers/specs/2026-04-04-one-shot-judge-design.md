# One-Shot Judge — 設計文件

## 問題

1. **Candidate 佇列是不必要的中間層** — pair 粒度、持久化、pop/requeue 加複雜度但無價值
2. **Judge 無法比較候選** — 獨立判斷每個 pair，語義密集群的詞全部通過 → hub 問題（cowering = 9 links）
3. **無度數上限** — 後端完全沒有 max degree 檢查

## 設計目標

- 每張新卡 embed 後 **一次性** batch judge，完事不回頭
- ≥5 candidates 時用 **selective prompt**（挑最好的 top-N，不是全部判）
- 加 **max degree cap** 防止 hub
- **砍掉 candidate 佇列**（candidates_*.json）

## 架構變更

### Before

```
新卡 → embed → find_similar → candidates_*.json → (pipeline) pop → judge → links
                                    ↑
                            pair 粒度，持久佇列
```

### After

```
新卡 → embed → pending_judge set → (pipeline) for each card:
                                       find_similar → filter → batch judge → links
                                                         ↑
                                              ≥5: selective prompt
                                              <5: standard prompt
                                              degree cap 檢查
```

## 詳細設計

### 1. GraphStore: pending_judge 替代 candidates

**取代方式：** `candidates_*.json`（pair list）→ `pending_judge_*.json`（card ID set）

GraphStore 新增：
```python
# 新屬性
self._pending_judge: set[str] = set()
self.pending_judge_path: Path  # pending_judge_<notebook>.json

# 新方法
def add_pending_judge(self, card_ids: list[str]) -> None
def pop_pending_judge(self) -> list[str]
def remove_pending_judge_for(self, card_id: str) -> None
```

**不動的：** links、blocked pairs 完全不變。

**Candidate 方法處理：**

| 方法 | 處理 |
|------|------|
| `batch_add_candidates` | 改為呼叫 `add_pending_judge` (只取 from_id) |
| `add_candidate` | 同上 |
| `pop_candidates` | 用 `pop_pending_judge` 替代 |
| `requeue_candidates` | 用 `add_pending_judge` 替代 |
| `remove_candidates_for` | 用 `remove_pending_judge_for` 替代 |
| `candidate_count` | 改為 `len(self._pending_judge)` |

**原子式切換（非漸進遷移）：** Pipeline 步驟必須原子切換——同一 commit 中移除 `_step_link`、加入 `_step_embed_and_judge`。不能保留兩者同時存在。

**Candidate 方法處理策略：**
- GraphStore 保留 `candidate_count()` 回傳 `len(self._pending_judge)`（health API 向後相容）
- `cleanup_for_card` 改呼叫 `remove_pending_judge_for`
- `batch_add_candidates` / `pop_candidates` / `requeue_candidates` / `add_candidate` 保留但標記 deprecated，pipeline 不再呼叫
- 測試中直接引用 candidate 方法的：逐一更新

**舊 candidates 遷移：** GraphStore `_load()` 時，若 `candidates_*.json` 存在且非空，提取 unique `from_id` 集合寫入 `pending_judge`，然後清空 candidates file。一次性自動遷移，無需手動操作。

### 2. Selective Prompt

新增 `SELECTIVE_BATCH_SYSTEM_PROMPT`（judge.py）：

```
Judge vocabulary relationships for the TARGET word.
You have {n} candidates. Select at most {max_links} with the MOST valuable learning relationships.

Prioritize:
- Genuine contrasts (opposite meanings, different nuances of similar concept)
- Strong usage pairs (fill same grammatical role, appear in same contexts)
- Reject vague connections (both are "body movements" is too weak)

For the best candidates: {"link": "contrasts_with" or "shares_usage", "confidence": ..., "reason": "..."}
For the rest: {"link": "not_applicable", "confidence": 0.0, "reason": ""}
```

**切換邏輯（在 `_call_batch` 或新 helper）：**
- `len(candidates) >= 5` → `SELECTIVE_BATCH_SYSTEM_PROMPT` with `max_links` 參數
- `len(candidates) < 5` → 現有 `BATCH_SYSTEM_PROMPT`

### 3. Max Degree Cap

**常數：** `MAX_DEGREE = 6`（`vocab_graph.py`）

**檢查時機：**

| 檢查點 | 位置 | 邏輯 |
|--------|------|------|
| **Judge 前** | `_step_embed_and_judge` | 跳過已達上限的卡 |
| **Candidate 過濾** | `_step_embed_and_judge` | 過濾掉對方已達上限的 pair |
| **Link 建立前** | `graph.add_link` / `batch_add_links` | 最終安全網：雙方度數 < MAX_DEGREE 才建立 |

**度數計算：** `len(graph.get_links_for(card_id))`（已有方法，回傳 active + hidden links）

**ManualLinkJudge 不受限** — 用戶手動建立的連結不受 max degree 限制。

### 4. Pipeline 重構

**合併 `_step_embed` + `_step_link` → `_step_embed_and_judge`**

```python
async def _step_embed_and_judge(uid, user, *, ...):
    # Phase 1: Embed（同現有 _step_embed）
    cards = card_store_factory(user["dir"])
    embeddings = embedding_store_factory(...)
    graph = graph_store_factory(...)
    missing = [card for card in cards.all(notebook_id=...) if not embeddings.has(card.id) and not card.is_archived]
    if missing:
        # embed missing cards (same as _sync_embed_loop but without candidate logic)
        # add their IDs to pending_judge
        graph.add_pending_judge([c.id for c in successfully_embedded])

    # Phase 2: Judge（替代 _step_link）
    pending = graph.pop_pending_judge()
    if not pending:
        return

    judge = Judge(llm, model=gemini_model, user_id=uid, notebook_id=notebook_id)
    # Pre-fetch all pending cards
    cards_cache = cards.get_batch(set(pending))

    processed = 0
    try:
      for card_id in pending:
        card = cards_cache.get(card_id)
        if not card or card.is_deleted or card.is_archived:
            continue

        current_degree = len(graph.get_links_for(card_id))
        if current_degree >= MAX_DEGREE:
            continue

        available = MAX_DEGREE - current_degree
        similar = embeddings.find_similar(card_id, k=CANDIDATE_K)
        filtered = []
        for other_id, score in similar:
            if score <= SIMILARITY_THRESHOLD:
                continue
            if graph.has_link(card_id, other_id):
                continue
            other = cards_cache.get(other_id)
            if not other or other.is_deleted or other.is_archived:
                continue
            if len(graph.get_links_for(other_id)) >= MAX_DEGREE:
                continue
            filtered.append((other_id, other.content, other.meaning, score))

        if not filtered:
            continue

        # Build batch candidates
        batch_cands = [(oid, w, m) for oid, w, m, _ in filtered]
        sims = {oid: s for oid, _, _, s in filtered}

        # Judge (selective if ≥5)
        results = judge.evaluate_batch(
            card.content, card.meaning, batch_cands,
            from_id=card_id, similarities=sims,
            max_links=available,  # 新參數，控制 selective prompt
        )

        # Create links
        links_to_add = []
        for other_id, judgement in results.items():
            if judgement and len(graph.get_links_for(other_id)) < MAX_DEGREE:
                links_to_add.append((card_id, other_id, LinkKind(judgement.link), judgement.confidence, judgement.reason))
        if links_to_add:
            graph.batch_add_links(links_to_add)
        processed += 1
    except (OpenAIError, OSError, ValueError, RuntimeError):
      # Requeue unprocessed cards
      unprocessed = pending[processed:]
      if unprocessed:
          graph.add_pending_judge(unprocessed)
      raise
```

**Pipeline step 順序變更：**

| Before | After |
|--------|-------|
| 1. Enrich | 1. Enrich |
| 2. Embed（+ queue candidates）| 2. Embed + Judge（合併）|
| 3. Link（pop candidates + judge）| ~~刪除~~ |
| 4. Difficulty | 3. Difficulty |
| 5. ExternalSync | 4. ExternalSync |

### 5. Intake 路徑修改

`vocab_graph.py: embed_and_link_new_cards` 改為 `embed_new_cards`：
- 只做 embed + `graph.add_pending_judge(new_card_ids)`
- **不再 find_similar，不再產生 candidate pairs**
- Judge 完全由 pipeline 背景處理

### 6. 受影響的外部接口

| 接口 | 變更 |
|------|------|
| `HealthResponse.pendingCandidates` | 改為 `pendingJudge`（pending_judge set 大小）|
| iOS client | 需同步更新 health response parsing（或保持舊欄位名 + 新語意）|
| `notebook.py:86` 刪除 notebook | 加 `pending_judge_{nb_id}.json` 到刪除清單 |
| `cleanup_for_card` | 呼叫 `remove_pending_judge_for` 替代 `remove_candidates_for` |

**iOS 相容性：** 保持 `pendingCandidates` 欄位名（回傳 pending_judge count），避免 iOS 更新。

### 7. evaluate_batch 新增 max_links 參數

```python
def evaluate_batch(
    self, target_word, target_meaning, candidates,
    *, from_id="", similarities=None, max_links: int | None = None,
):
```

- `max_links is None` or `len(candidates) < 5` → 現有 `BATCH_SYSTEM_PROMPT`
- `max_links is not None` and `len(candidates) >= 5` → `SELECTIVE_BATCH_SYSTEM_PROMPT`（填入 max_links）

## 風險

| 風險 | 緩解 |
|------|------|
| 21 個 test 檔案引用 candidate | 漸進遷移：保持舊方法簽名，內部改寫 |
| Pipeline 合併步驟的 error recovery | embed 失敗不影響已 pending 的 judge；judge 失敗 requeue pending IDs |
| find_similar 在 judge 時重算（vs 之前 candidate 已存） | 成本低（numpy 矩陣乘法 < 1ms），且結果更新鮮 |
| Selective prompt 品質 | 有 judge_log 可監控，隨時調 prompt |
| 舊 candidates_*.json 殘留 | Pipeline 第一次跑時 pop 並處理完畢，之後 pending_judge 接管 |
| MAX_DEGREE 影響已有 hub 節點 | 不回溯清理，只限制新連結 |
| Degree cap TOCTOU | Pipeline 持 user lock，manual link 可能超 1 但不嚴重 |
| `recover_candidates.py` ops 腳本 | 更新或移除，已列入改動清單 |
| `_sync_embed_loop` 消失 | embed 邏輯整合進 `_step_embed_and_judge`，不再獨立存在 |

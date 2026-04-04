# One-Shot Judge Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 砍掉 candidate 佇列，每張新卡一次性 batch judge，加 selective prompt + max degree cap。
**Architecture:** GraphStore pending_judge 替代 candidates → pipeline _step_embed_and_judge 合併 → Judge selective prompt → degree cap。
**Tech Stack:** 純 backend Python，無 iOS 變更。

**Spec:** `docs/superpowers/specs/2026-04-04-one-shot-judge-design.md`

---

## Task 依賴關係

```
Task 1 (GraphStore pending_judge) ──→ Task 3 (Pipeline 合併)
Task 2 (Selective prompt + degree) ──→ Task 3 (Pipeline 合併)
Task 4 (Intake 路徑) depends on Task 1
Task 5 (Cleanup + tests) depends on Task 3, Task 4
```

Task 1 和 Task 2 可**平行**。Task 3 依賴 1+2。Task 4 依賴 1。Task 5 最後。

---

### Task 1: GraphStore — pending_judge 替代 candidates

**Files:**
- Modify: `backend/src/kg/graph.py`
- Test: `backend/tests/test_graph_pending_judge.py`（新）

#### Step 1: 寫 failing test

```python
# backend/tests/test_graph_pending_judge.py

def test_add_and_pop_pending_judge(tmp_path):
    """Add card IDs to pending_judge, pop returns them, set is empty after pop."""
    graph = GraphStore(
        links_path=tmp_path / "graph.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
        pending_judge_path=tmp_path / "pending_judge.json",
    )
    graph.add_pending_judge(["c1", "c2", "c3"])
    assert graph.pending_judge_count() == 3

    popped = graph.pop_pending_judge()
    assert set(popped) == {"c1", "c2", "c3"}
    assert graph.pending_judge_count() == 0

def test_pending_judge_dedup(tmp_path):
    """Adding same ID twice doesn't duplicate."""
    graph = GraphStore(...)
    graph.add_pending_judge(["c1", "c2"])
    graph.add_pending_judge(["c2", "c3"])
    assert graph.pending_judge_count() == 3

def test_pending_judge_persistence(tmp_path):
    """pending_judge survives GraphStore reload."""
    graph = GraphStore(pending_judge_path=tmp_path / "pj.json", ...)
    graph.add_pending_judge(["c1"])
    # Reload
    graph2 = GraphStore(pending_judge_path=tmp_path / "pj.json", ...)
    assert graph2.pending_judge_count() == 1

def test_remove_pending_judge_for(tmp_path):
    """Removing a card ID from pending_judge."""
    graph = GraphStore(...)
    graph.add_pending_judge(["c1", "c2"])
    graph.remove_pending_judge_for("c1")
    assert graph.pending_judge_count() == 1

def test_migrate_candidates_to_pending(tmp_path):
    """If candidates.json has data on load, extract from_ids into pending_judge."""
    import json
    # Pre-populate candidates.json with old-format data
    candidates_data = [
        {"from_id": "c1", "to_id": "c2", "similarity": 0.85, "created_at": "2026-01-01T00:00:00"},
        {"from_id": "c1", "to_id": "c3", "similarity": 0.80, "created_at": "2026-01-01T00:00:00"},
        {"from_id": "c4", "to_id": "c5", "similarity": 0.75, "created_at": "2026-01-01T00:00:00"},
    ]
    (tmp_path / "candidates.json").write_text(json.dumps(candidates_data))
    (tmp_path / "pending_judge.json").write_text("[]")

    graph = GraphStore(
        links_path=tmp_path / "graph.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
        pending_judge_path=tmp_path / "pending_judge.json",
    )
    # Old candidates from_ids should be in pending_judge
    assert graph.pending_judge_count() == 2  # c1, c4 (unique from_ids)
    # Candidates should be cleared
    assert graph.candidate_count() == 0
```

#### Step 2: 跑 test 確認失敗
Run: `python -m pytest backend/tests/test_graph_pending_judge.py -v`
Expected: TypeError（GraphStore 不接受 pending_judge_path）

#### Step 3: 實作 GraphStore 變更

**3a. `__init__` 新增 `pending_judge_path` 參數**

```python
def __init__(self, links_path, candidates_path, blocked_path=None,
             pending_judge_path=None):
    # ... existing init ...
    self.pending_judge_path = pending_judge_path
    self._pending_judge: set[str] = set()
    self._pending_judge_write_lock = threading.Lock()
    self._load()  # already called, will now also load pending_judge
```

**3b. `_load()` 擴充** — 在現有 load 邏輯之後加：

```python
# Load pending_judge
if self.pending_judge_path and self.pending_judge_path.exists():
    data = json.loads(self.pending_judge_path.read_text())
    self._pending_judge = set(data)

# Migration: candidates → pending_judge
# ONLY when pending_judge_path is set (production).
# Scripts that construct GraphStore without pending_judge_path won't trigger migration.
if self.pending_judge_path and self._candidates:
    migrated_ids = {c.from_id for c in self._candidates}
    self._pending_judge.update(migrated_ids)
    self._candidates.clear()
    self._candidate_set.clear()
    self._save_pending_judge()
    self._save_candidates()  # clear candidates file
```

**3c. 新方法**

```python
def add_pending_judge(self, card_ids: list[str]) -> None:
    """Add card IDs that need graph judging."""
    with self._lock:
        before = len(self._pending_judge)
        self._pending_judge.update(card_ids)
        if len(self._pending_judge) == before:
            return  # no change
        snapshot = sorted(self._pending_judge)
    self._flush_pending_judge(snapshot)

def pop_pending_judge(self) -> list[str]:
    """Get and clear all pending judge card IDs."""
    with self._lock:
        result = sorted(self._pending_judge)
        self._pending_judge.clear()
    self._flush_pending_judge([])
    return result

def remove_pending_judge_for(self, card_id: str) -> None:
    """Remove a card from pending judge (on delete/archive)."""
    with self._lock:
        self._pending_judge.discard(card_id)
        snapshot = sorted(self._pending_judge)
    self._flush_pending_judge(snapshot)

def pending_judge_count(self) -> int:
    return len(self._pending_judge)

def _save_pending_judge(self) -> None:
    if self.pending_judge_path:
        self._flush_pending_judge(sorted(self._pending_judge))

def _flush_pending_judge(self, snapshot: list[str]) -> None:
    if self.pending_judge_path is None:
        return
    with self._pending_judge_write_lock:
        self._atomic_json_write(self.pending_judge_path, snapshot, indent=None)
```

**3d. `cleanup_for_card` 更新**

```python
def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
    dep_count = self.deprecate_links_for(card_id)
    cand_count = self.remove_candidates_for(card_id)  # 保留（清理舊 candidates）
    self.remove_pending_judge_for(card_id)  # 新增
    if remove_blocked:
        self.remove_blocked_pairs_for(card_id)
    return {"deprecated": dep_count, "candidates_removed": cand_count}
```

**3e. `candidate_count` 相容性**

```python
def candidate_count(self) -> int:
    """Return pending items count (backward compat for health API)."""
    return len(self._pending_judge) + len(self._candidates)
```

#### Step 4: 跑 test 確認通過

#### Step 5: 跑全部既有 graph test 確認無 regression
Run: `python -m pytest backend/tests/test_graph*.py -v`

注意：所有現有 GraphStore 建構都沒有 `pending_judge_path`，所以它們預設 None 不會受影響。

#### Step 6: 修改 `service_factories.py:104-111` 傳入 pending_judge_path

**這是整個方案的命脈。** 漏了 = pending_judge 不會持久化。

現有（`backend/src/kg/service_factories.py:104-111`）：
```python
def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path, blocked_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("graph_{nb}.json", "graph.json"),
        ("candidates_{nb}.json", "candidates.json"),
        ("blocked_{nb}.json", "blocked.json"),
    ])
    return _get_cached(key, lambda: GraphStore(links_path, candidates_path, blocked_path))
```

改為：
```python
def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    links_path, candidates_path, blocked_path = _resolve_notebook_paths(user_dir, notebook_id, [
        ("graph_{nb}.json", "graph.json"),
        ("candidates_{nb}.json", "candidates.json"),
        ("blocked_{nb}.json", "blocked.json"),
    ])
    # pending_judge 不走 legacy migration（新檔案）
    pj_path = user_dir / f"pending_judge_{notebook_id}.json"
    return _get_cached(key, lambda: GraphStore(links_path, candidates_path, blocked_path, pending_judge_path=pj_path))
```

**注意：** `_get_cached` 會快取 GraphStore 實例。已有快取的 GraphStore 不會被重新建構。部署後第一次建構才會帶 pending_judge_path。需確認 deploy 時 container restart 清空快取（是的，container restart = process restart = 快取清空）。

**其他 GraphStore 建構點：**
- `backend/scripts/migrate_graph_reasons.py:66` — migration script，加 `pending_judge_path=None` 明確傳入。此檔的 GraphStore 不需要 pending_judge 功能。
- 所有 test 中直接建構的 GraphStore — `pending_judge_path` 預設 None，不受影響

#### Step 7: Commit
`api: add pending_judge to GraphStore, migrate old candidates`

---

### Task 2: Selective Prompt + Max Degree 常數

**Files:**
- Modify: `backend/src/kg/judge.py`
- Modify: `backend/src/kg/vocab_graph.py`（加 MAX_DEGREE）
- Test: `backend/tests/test_selective_judge.py`（新）

#### Step 1: 寫 failing test

```python
# backend/tests/test_selective_judge.py
from unittest.mock import MagicMock
from kg.judge import Judge, SELECTIVE_BATCH_SYSTEM_PROMPT, BATCH_SYSTEM_PROMPT

def _mock_response(content):
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    mock.usage.prompt_tokens = 100
    mock.usage.completion_tokens = 50
    return mock

def test_selective_prompt_used_when_5_or_more(tmp_path, monkeypatch):
    """When ≥5 candidates and max_links provided, selective prompt is used."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import importlib
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()

    llm = MagicMock()
    # Return 2 accepted, 3 not_applicable
    llm.chat.return_value = _mock_response(json.dumps([
        {"word": "w1", "link": "shares_usage", "confidence": 0.9, "reason": "好"},
        {"word": "w2", "link": "contrasts_with", "confidence": 0.85, "reason": "對比"},
        {"word": "w3", "link": "not_applicable", "confidence": 0.0, "reason": ""},
        {"word": "w4", "link": "not_applicable", "confidence": 0.0, "reason": ""},
        {"word": "w5", "link": "not_applicable", "confidence": 0.0, "reason": ""},
    ]))

    judge = Judge(llm, user_id="u1", notebook_id="nb1")
    candidates = [("c1", "w1", "m1"), ("c2", "w2", "m2"), ("c3", "w3", "m3"),
                   ("c4", "w4", "m4"), ("c5", "w5", "m5")]
    results = judge.evaluate_batch("target", "意思", candidates, max_links=3)

    # Verify selective prompt was used (check the system message)
    call_args = llm.chat.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    assert "at most" in system_msg.lower() or "最多" in system_msg

    # Verify results
    accepted = {k: v for k, v in results.items() if v is not None}
    assert len(accepted) <= 3

def test_standard_prompt_when_less_than_5():
    """When <5 candidates, standard prompt is used regardless of max_links."""
    llm = MagicMock()
    llm.chat.return_value = _mock_response(json.dumps([
        {"word": "w1", "link": "shares_usage", "confidence": 0.9, "reason": "好"},
    ]))
    judge = Judge(llm)
    results = judge.evaluate_batch("target", "意思", [("c1", "w1", "m1")], max_links=3)

    call_args = llm.chat.call_args
    system_msg = call_args.kwargs["messages"][0]["content"]
    # Should NOT contain selective language
    assert "at most" not in system_msg.lower()
```

#### Step 2: 跑 test 確認失敗
Expected: AttributeError（SELECTIVE_BATCH_SYSTEM_PROMPT 不存在）

#### Step 3: 實作

**3a. `vocab_graph.py` 加常數**

```python
MAX_DEGREE = 6  # 每張卡最多連結數
```

**3b. `judge.py` 新增 selective prompt**

```python
SELECTIVE_BATCH_SYSTEM_PROMPT = """Judge vocabulary relationships for the TARGET word.
You have {n} candidates but should select at most {max_links} with the MOST valuable learning relationships.

Selection criteria (in order):
1. Genuine contrasts — opposite or clearly different nuances of a similar concept
2. Strong usage pairs — consistently fill the same grammatical role or appear in the same contexts
3. REJECT vague connections — "both are body movements" or "both are adjectives" is NOT enough

For the best {max_links} candidates, respond:
{{"word": "<candidate>", "link": "contrasts_with" or "shares_usage", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}}

For the rest, respond:
{{"word": "<candidate>", "link": "not_applicable", "confidence": 0.0, "reason": ""}}

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.
Respond as a JSON array, one object per candidate (in order)."""
```

**3c. `_call_batch` 修改** — 根據 candidate 數和 max_links 選擇 prompt

在 `_call_batch` 簽名加 `max_links: int | None = None`：

```python
def _call_batch(self, target_word, target_meaning, candidates,
                *, from_id="", similarities=None, max_links=None):
    # Choose prompt
    if max_links is not None and len(candidates) >= 5:
        system_prompt = SELECTIVE_BATCH_SYSTEM_PROMPT.format(
            n=len(candidates), max_links=max_links,
        )
    else:
        system_prompt = BATCH_SYSTEM_PROMPT

    # ... rest of existing _call_batch, replacing hardcoded BATCH_SYSTEM_PROMPT with system_prompt ...
```

**3d. `evaluate_batch` 簽名加 `max_links`**

```python
def evaluate_batch(self, target_word, target_meaning, candidates,
                   *, from_id="", similarities=None, max_links=None):
    # ... existing chunk logic ...
    # Pass max_links to _call_batch
    merged.update(self._call_batch(..., max_links=max_links))
```

**3e. `evaluate` (thin wrapper) 也轉發 max_links**

#### Step 4: 跑 test 確認通過

#### Step 5: 跑全部 judge test 確認無 regression
Run: `python -m pytest backend/tests/test_judge*.py backend/tests/test_batch_judge*.py -v`

#### Step 6: Commit
`api: add selective judge prompt and MAX_DEGREE constant`

---

### Task 3: Pipeline 合併 — _step_embed_and_judge

**Files:**
- Modify: `backend/src/kg/pipeline_service.py`（重寫核心）
- Modify: `backend/src/kg/vocab_graph.py`（移除 CANDIDATE_K 的使用）
- Test: `backend/tests/test_pipeline_one_shot.py`（新）
- Modify: `backend/tests/test_pipeline_service.py`（更新）

**依賴：** Task 1（pending_judge）+ Task 2（selective prompt + MAX_DEGREE）

#### Step 1: 寫 failing test

```python
# backend/tests/test_pipeline_one_shot.py
"""Test the merged _step_embed_and_judge pipeline step."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

def test_embed_and_judge_creates_links():
    """New card is embedded, judged, and links created in one step."""
    # Setup: one card without embedding, 3 existing cards with embeddings
    # Mock: embeddings.find_similar returns 3 candidates
    # Mock: judge.evaluate_batch approves 2
    # Assert: 2 links created, pending_judge cleared

def test_embed_and_judge_selective_prompt_for_many_candidates():
    """When ≥5 candidates above threshold, selective prompt is used."""
    # Setup: 1 new card, 6 existing similar cards
    # Assert: evaluate_batch called with max_links parameter

def test_embed_and_judge_respects_max_degree():
    """Cards at MAX_DEGREE are skipped, candidates at MAX_DEGREE are filtered."""
    # Setup: card_a already has MAX_DEGREE links
    # Assert: card_a is skipped entirely

def test_embed_and_judge_error_recovery():
    """If judge fails midway, unprocessed cards are requeued."""
    # Setup: 3 pending cards, judge fails on 2nd
    # Assert: 3rd card is requeued to pending_judge

def test_embed_and_judge_migrates_old_candidates():
    """If old candidates exist, they're migrated to pending_judge on load."""
    # This is covered by Task 1 test, but verify pipeline handles it
```

#### Step 2: 跑 test 確認失敗

#### Step 3: 實作 `_step_embed_and_judge`

**完整實作（取代 _step_embed + _step_link）：**

```python
async def _step_embed_and_judge(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
) -> None:
    """Combined embed + judge step. Replaces _step_embed + _step_link."""
    from .judge import Judge
    from .tracked_llm import TrackedLLM
    from .vocab_graph import CANDIDATE_K, MAX_DEGREE, SIMILARITY_THRESHOLD

    cards = card_store_factory(user["dir"])
    llm = TrackedLLM(gemini_client_factory(), uid)
    embeddings = embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id)
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)

    # ── Phase 1: Embed missing cards ──
    missing = [
        card for card in cards.all(notebook_id=notebook_id)
        if not embeddings.has(card.id) and not card.is_archived
    ]
    newly_embedded: list[str] = []
    if missing:
        logger.info("[%s] Embedding %d cards", uid, len(missing))
        items = [(card.id, card.embed_text()) for card in missing]
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, embeddings.add_batch, items)
            newly_embedded = [card.id for card in missing if embeddings.has(card.id)]
        except (OpenAIError, OSError, ValueError) as exc:
            logger.warning("[%s] Batch embedding failed: %s", uid, exc)

        # Add newly embedded cards to pending_judge
        if newly_embedded:
            graph.add_pending_judge(newly_embedded)
            logger.info("[%s] Embedded %d cards, added to pending judge", uid, len(newly_embedded))

    # ── Phase 2: Judge pending cards ──
    pending = graph.pop_pending_judge()
    if not pending:
        logger.info("[%s] No pending cards to judge", uid)
        return

    logger.info("[%s] Judging %d pending cards", uid, len(pending))
    judge = Judge(llm, model=gemini_model, user_id=uid, notebook_id=notebook_id)

    # Pre-fetch pending cards
    cards_cache = cards.get_batch(set(pending))

    all_links: list[tuple[str, str, Any, float, str]] = []

    # ── Phase 2a: Prepare judge tasks (filter candidates per card) ──
    judge_tasks: list[tuple[str, Any, list, dict, int | None]] = []
    # (card_id, card, batch_cands, sims, max_links)
    for card_id in pending:
        card = cards_cache.get(card_id)
        if not card or card.is_deleted or card.is_archived:
            continue

        current_degree = len(graph.get_links_for(card_id))
        if current_degree >= MAX_DEGREE:
            continue
        available = MAX_DEGREE - current_degree

        # Find similar cards (numpy dot product, < 1ms)
        similar = embeddings.find_similar(card_id, k=CANDIDATE_K)

        # First pass: collect other_ids needing card fetch
        other_ids_needed: set[str] = set()
        for other_id, score in similar:
            if score <= SIMILARITY_THRESHOLD:
                continue
            if graph.has_link(card_id, other_id):
                continue
            other_ids_needed.add(other_id)

        if not other_ids_needed:
            continue

        # Batch fetch other cards
        others = cards.get_batch(other_ids_needed)
        filtered: list[tuple[str, str, str, float]] = []
        for other_id, score in similar:
            if other_id not in other_ids_needed:
                continue
            other = others.get(other_id)
            if not other or other.is_deleted or other.is_archived:
                continue
            if len(graph.get_links_for(other_id)) >= MAX_DEGREE:
                continue
            filtered.append((other_id, other.content, other.meaning, score))

        if not filtered:
            continue

        batch_cands = [(oid, w, m) for oid, w, m, _ in filtered]
        sims = {oid: s for oid, _, _, s in filtered}
        max_links = available if len(filtered) >= 5 else None
        judge_tasks.append((card_id, card, batch_cands, sims, max_links))

    if not judge_tasks:
        logger.info("[%s] No cards need judging after filtering", uid)
        return

    # ── Phase 2b: Parallel judge (ThreadPoolExecutor, like old _step_link) ──
    executor = ThreadPoolExecutor(max_workers=8)
    loop = asyncio.get_running_loop()

    futures: list[tuple[str, asyncio.Future]] = []
    for card_id, card, batch_cands, sims, max_links in judge_tasks:
        futures.append((
            card_id,
            loop.run_in_executor(
                executor,
                lambda c=card, bc=batch_cands, s=sims, ml=max_links, fid=card_id: judge.evaluate_batch(
                    c.content, c.meaning, bc,
                    from_id=fid, similarities=s, max_links=ml,
                ),
            ),
        ))

    processed = 0
    try:
        for card_id, fut in futures:
            results = await fut
            processed += 1
            for other_id, judgement in results.items():
                if judgement is None:
                    continue
                if len(graph.get_links_for(other_id)) >= MAX_DEGREE:
                    continue
                all_links.append((
                    card_id, other_id,
                    link_kind_enum(judgement.link),
                    judgement.confidence,
                    judgement.reason,
                ))
    except Exception:
        # Requeue unprocessed cards
        unprocessed_ids = [cid for cid, _ in futures[processed:]]
        if unprocessed_ids:
            graph.add_pending_judge(unprocessed_ids)
        logger.warning("[%s] Judge interrupted at %d/%d, requeued %d",
                      uid, processed, len(futures), len(unprocessed_ids))
        if all_links:
            graph.batch_add_links(all_links)
        raise
    finally:
        executor.shutdown(wait=False)

    # Batch create all links
    created = graph.batch_add_links(all_links) if all_links else []
    logger.info("[%s] Created %d links from %d cards", uid, len(created), len(pending))
```

**3b. `run_pipeline_background` 更新** — 移除 _step_embed + _step_link，加入 _step_embed_and_judge

現有（pipeline_service.py:371-400）：
```python
await _run_step(uid, "Embed", lambda: _step_embed(...), ...)
await _run_step(uid, "Link", lambda: _step_link(...), ...)
```

改為：
```python
await _run_step(uid, "EmbedAndJudge", lambda: _step_embed_and_judge(
    uid, user,
    card_store_factory=card_store_factory,
    graph_store_factory=graph_store_factory,
    embedding_store_factory=embedding_store_factory,
    gemini_client_factory=gemini_client_factory,
    logger=logger,
    link_kind_enum=link_kind_enum,
    notebook_id=notebook_id,
    gemini_model=gemini_model,
), logger=logger, retry=True)
```

**3c. 刪除 `_sync_embed_loop`** — 邏輯已整合進 `_step_embed_and_judge`

**3d. 保留 `_step_embed`、`_step_link`、`_sync_embed_loop` 函數體** — 加 `# DEPRECATED` 註解。Pipeline 不再呼叫它們，但 test 可能直接 import。Task 5 清理時再決定是否刪除。

#### Step 4: 跑 test 確認通過

#### Step 5: 更新 `test_pipeline_service.py`

現有 test 直接 mock `pop_candidates` 等。需要更新：
- Mock `pop_pending_judge` 替代 `pop_candidates`
- Mock `add_pending_judge` 替代 `batch_add_candidates`
- 更新 step name assertions（"EmbedAndJudge" vs "Embed"/"Link"）
- 更新 FakeJudge 如果需要

#### Step 6: 跑全部 test
Run: `python -m pytest backend/tests/ -x -q`

#### Step 7: Commit
`api: merge embed+link into one-shot _step_embed_and_judge`

---

### Task 4: Intake 路徑修改

**Files:**
- Modify: `backend/src/kg/vocab_graph.py`
- Modify: `backend/src/kg/vocab_intake.py`（間接，因為 call signature 不變）
- Test: `backend/tests/test_vocab_service.py`（更新 stubs）

#### Step 1: 修改 `embed_and_link_new_cards` → 只 embed + add_pending_judge

現有（vocab_graph.py:15-72）：embed → find_similar → batch_add_candidates

改為：
```python
def embed_and_link_new_cards(
    *, cards, embeddings, graph, card_ids, entries, logger,
) -> None:
    """Embed new cards and mark them for graph judging."""
    # Phase 1: Collect and embed (unchanged)
    batch_items = [...]
    embeddings.add_batch(batch_items)

    # Phase 2: Mark for pending judge (replaces candidate generation)
    embedded_ids = [card.id for card in batch_cards if embeddings.has(card.id)]
    if embedded_ids:
        graph.add_pending_judge(embedded_ids)
```

**大幅簡化：** 移除 find_similar、CANDIDATE_K/SIMILARITY_THRESHOLD 使用、all_similar/all_other_ids/candidate_items 邏輯。函數從 ~50 行縮減到 ~20 行。

**函數名保持不變**（`embed_and_link_new_cards`）避免改 caller。

#### Step 2: 更新 test stubs

`test_vocab_service.py` 中 stub 了 `batch_add_candidates`。改為 stub `add_pending_judge`。

#### Step 3: 跑 test
Run: `python -m pytest backend/tests/test_vocab_service.py -v`

#### Step 4: Commit
`api: simplify intake — embed only, defer judge to pipeline`

---

### Task 5: 清理 + 全量 test

**Files:**
- Modify: `backend/src/kg/routers/notebook.py:85-89`（加 pending_judge 到刪除清單）
- Modify: `backend/src/kg/user_handlers.py:206`（candidate_count 已相容，但驗證）
- ~~`backend/scripts/recover_candidates.py` 不存在，無需處理~~
- Modify: `backend/tests/test_pipeline_resilience.py`（更新 stubs）
- Modify: `backend/tests/test_user_handlers.py`（驗證 health endpoint）
- Modify: 其他引用 candidates 的 test（逐一檢查更新）

#### Step 1: notebook.py 加 pending_judge 到刪除清單

```python
for pattern in [
    f"graph_{nb_id}.json", f"candidates_{nb_id}.json",
    f"blocked_{nb_id}.json", f"pending_judge_{nb_id}.json",  # 新增
]:
```

#### Step 2: 逐一修復 failing tests

**所有引用 candidate 的 test 檔案（20 個）：**

高優先（直接呼叫 candidate 方法）：
1. `test_graph_index.py` — batch_add_candidates, candidate_count, persistence
2. `test_graph_lock_opt.py` — add_candidate dedup, _candidate_set, remove_candidates_for, requeue
3. `test_graph_concurrency.py` — concurrent add_candidate
4. `test_manual_link.py` — add_candidate skips hidden pair
5. `test_hide_link.py` — add_candidate skips blocked pair
6. `test_pipeline_service.py` — mock pop_candidates, requeue_candidates
7. `test_pipeline_resilience.py` — stub pop_candidates, add_candidate, batch_add_candidates
8. `test_vocab_service.py` — stub add_candidate, batch_add_candidates, remove_candidates_for
9. `test_user_handlers.py` — mock candidate_count for health
10. `test_observability.py` — mock candidate_count

中優先（間接引用或 stub）：
11. `test_cards.py` — batch_add_candidates in SimpleNamespace stub
12. `test_pipeline_integration.py`
13. `test_judge_log_integration.py`
14. `test_batch_judge_live.py`
15. `test_batch_judge_30pairs.py`
16. `test_robustness.py`
17. `test_graph_orphan.py`
18. `test_data_safety_fixes.py`
19. `test_settings.py`

策略：
- candidate 方法保留但 deprecated，所以直接測 candidate 方法的 test（1-5）**仍應通過**
- mock/stub candidate 方法的 test（6-10）需要更新為 mock pending_judge 方法
- 間接引用的（11-19）逐一確認是否因 pipeline 改動而 break

**必須跑 `python -m pytest backend/tests/ -v` 確認 ALL PASS。**

#### Step 4: 跑全量 test
Run: `python -m pytest backend/tests/ -v`
**必須全部通過。**

#### Step 5: Commit
`api: cleanup — update notebook deletion, tests, and scripts for one-shot judge`

---

### Task 6: Deploy & Verify

- [ ] **preflight** — `./ops/devops_kg_safe.sh preflight`
- [ ] **backup** — `./ops/devops_kg_safe.sh backup`
- [ ] **deploy**
- [ ] **驗證：** 新增一張卡，確認：
  1. `pending_judge_default.json` 出現該卡 ID
  2. Pipeline 跑完後 `pending_judge_default.json` 清空
  3. `judge_log.db` 有新紀錄
  4. `graph_default.json` 有新連結
  5. 連結數 ≤ MAX_DEGREE
  6. Admin dashboard judge 通過率更新
- [ ] **驗證 selective prompt：** 新增一張有很多 similar words 的卡（如另一個動作詞），確認 judge_log 顯示只通過了 ≤ available 條

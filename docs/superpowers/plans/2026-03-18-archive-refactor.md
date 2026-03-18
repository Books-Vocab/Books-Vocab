# 封存重構 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 封存功能重構 — 入口搬至根層級、封存時從圖譜移除連結（可逆）、pipeline 排除封存卡片。

**Architecture:** Backend 的 `archive_vocab_word` 增加 graph 操作（deprecate/restore），新增 `GraphStore.restore_links_for`。iOS 端將封存入口從 `VocabularyListView` toolbar 搬至 `NotebookListView` toolbar。Pipeline 各步驟加入 `is_archived` 過濾。

**Tech Stack:** Python/FastAPI (backend), Swift/SwiftUI/SwiftData (iOS), SQLite (cards), JSON (graph)

**Spec:** `docs/superpowers/specs/2026-03-18-archive-refactor-design.md`

---

## Task 1: GraphStore.restore_links_for

**Files:**
- Modify: `backend/src/kg/graph.py:219` (after `remove_candidates_for`)
- Test: `backend/tests/test_graph_index.py`

- [ ] **Step 1: Write failing tests**

在 `backend/tests/test_graph_index.py` 末尾新增：

```python
class TestRestoreLinksFor:
    def test_restores_deprecated_links(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("card_a")
        assert store.get_links_for("card_a") == []

        cards_store = type("S", (), {"get": lambda self, cid: type("C", (), {"is_deleted": False, "is_archived": False})()})()
        count = store.restore_links_for("card_a", cards_store)
        assert count == 1
        assert len(store.get_links_for("card_a")) == 1

    def test_skips_deleted_other_end(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("card_a")

        cards_store = type("S", (), {"get": lambda self, cid: type("C", (), {"is_deleted": True, "is_archived": False})()})()
        count = store.restore_links_for("card_a", cards_store)
        assert count == 0
        assert store.get_links_for("card_a") == []

    def test_skips_archived_other_end(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("card_a")

        cards_store = type("S", (), {"get": lambda self, cid: type("C", (), {"is_deleted": False, "is_archived": True})()})()
        count = store.restore_links_for("card_a", cards_store)
        assert count == 0

    def test_skips_missing_other_card(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("card_a")

        cards_store = type("S", (), {"get": lambda self, cid: None})()
        count = store.restore_links_for("card_a", cards_store)
        assert count == 0

    def test_no_deprecated_links_returns_zero(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        cards_store = type("S", (), {"get": lambda self, cid: type("C", (), {"is_deleted": False, "is_archived": False})()})()
        count = store.restore_links_for("card_a", cards_store)
        assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_graph_index.py::TestRestoreLinksFor -v`
Expected: FAIL — `AttributeError: 'GraphStore' object has no attribute 'restore_links_for'`

- [ ] **Step 3: Implement restore_links_for**

在 `backend/src/kg/graph.py` 的 `remove_candidates_for` 方法之後（第 219 行後）新增：

```python
    def restore_links_for(self, card_id: str, cards_store) -> int:
        """Restore deprecated links for a card, only if the other end is alive."""
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_graph_index.py::TestRestoreLinksFor -v`
Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/graph.py backend/tests/test_graph_index.py
git commit -m "api: GraphStore.restore_links_for — 解封存時恢復有效連結"
```

---

## Task 2: archive_vocab_word 整合圖譜操作

**Files:**
- Modify: `backend/src/kg/vocab_service.py:212-219` — `archive_vocab_word` 增加 graph 參數
- Modify: `backend/src/kg/vocab_service.py:60-68` — `build_links_by_kind` 過濾 archived
- Modify: `backend/src/kg/vocab_handlers.py:79-90` — `archive_word_response` 傳入 graph
- Modify: `backend/src/kg/routers/vocab.py:110-112` — route handler 傳入 graph factory
- Test: `backend/tests/test_vocab_service.py`

- [ ] **Step 0: 補齊 test fixtures**

在 `backend/tests/test_vocab_service.py` 的 `_FakeCard` dataclass 新增欄位：
```python
    is_archived: bool = False
```

在 `_FakeCardsStore` 新增 `update` 方法：
```python
    def update(self, card_id, **kwargs):
        for card in self._cards:
            if card.id == card_id:
                for k, v in kwargs.items():
                    setattr(card, k, v)
                return
```

- [ ] **Step 1: Write failing tests**

在 `backend/tests/test_vocab_service.py` 新增 import `archive_vocab_word` 並在檔案末尾新增：

```python
from kg.vocab_service import archive_vocab_word


class _FakeGraph:
    def __init__(self):
        self.deprecated_for = []
        self.removed_candidates_for = []
        self.restored_for = []

    def deprecate_links_for(self, card_id):
        self.deprecated_for.append(card_id)
        return 1

    def remove_candidates_for(self, card_id):
        self.removed_candidates_for.append(card_id)
        return 0

    def restore_links_for(self, card_id, cards_store):
        self.restored_for.append(card_id)
        return 1


class TestArchiveVocabWord:
    def test_archive_deprecates_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeGraph()
        result = archive_vocab_word("hello", archived=True, cards_store=cards, graph=graph)
        assert result["archived"] is True
        assert graph.deprecated_for == ["c1"]
        assert graph.removed_candidates_for == ["c1"]

    def test_unarchive_restores_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeGraph()
        result = archive_vocab_word("hello", archived=False, cards_store=cards, graph=graph)
        assert result["archived"] is False
        assert graph.restored_for == ["c1"]

    def test_archive_without_graph_still_works(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        result = archive_vocab_word("hello", archived=True, cards_store=cards)
        assert result["archived"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_vocab_service.py::TestArchiveVocabWord -v`
Expected: FAIL — `archive_vocab_word() got an unexpected keyword argument 'graph'`

- [ ] **Step 3: Modify archive_vocab_word**

修改 `backend/src/kg/vocab_service.py:212-219`：

```python
def archive_vocab_word(word: str, *, archived: bool, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise HTTPException(status_code=422, detail="Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise HTTPException(404, f"Word '{word}' not found")
    cards_store.update(card.id, is_archived=archived)
    if graph is not None:
        if archived:
            graph.deprecate_links_for(card.id)
            graph.remove_candidates_for(card.id)
        else:
            graph.restore_links_for(card.id, cards_store)
    return {"word": word, "id": card.id, "archived": archived}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_vocab_service.py::TestArchiveVocabWord -v`
Expected: all 3 PASS

- [ ] **Step 5: Modify build_links_by_kind to filter archived**

修改 `backend/src/kg/vocab_service.py:66`，將：
```python
        if not other_card or other_card.is_deleted:
```
改為：
```python
        if not other_card or other_card.is_deleted or other_card.is_archived:
```

- [ ] **Step 6: Modify vocab_handlers.py — archive_word_response**

修改 `backend/src/kg/vocab_handlers.py:79-90`：

```python
def archive_word_response(
    word: str,
    req: ArchiveWordRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_id: str | None = None,
) -> dict[str, str]:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id or "default") if graph_store_factory is not None else None
    return archive_vocab_word(word, archived=req.archived, cards_store=cards, graph=graph, notebook_id=notebook_id)
```

- [ ] **Step 7: Modify routers/vocab.py — pass graph factory**

修改 `backend/src/kg/routers/vocab.py:111-112`：

```python
@router.patch("/api/vocab/{word}/archive")
def archive_word(word: str, req: ArchiveWordRequest, notebook_id: str = Query("default"), user: dict = Depends(get_current_user)):
    return archive_word_response(word, req, user, require_pro_access=_require_pro_access, card_store_factory=_card_store, graph_store_factory=_graph_store, notebook_id=notebook_id)
```

- [ ] **Step 8: Run full test suite**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/ -x -q`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add backend/src/kg/vocab_service.py backend/src/kg/vocab_handlers.py backend/src/kg/routers/vocab.py backend/tests/test_vocab_service.py
git commit -m "api: archive 整合圖譜操作 — deprecate/restore 連結 + build_links 過濾 archived"
```

---

## Task 3: Pipeline 過濾封存卡片

**Files:**
- Modify: `backend/src/kg/pipeline_service.py:116` — `_step_embed` 過濾 archived
- Modify: `backend/src/kg/pipeline_service.py:160` — `_step_link` 過濾 archived
- Modify: `backend/src/kg/vocab_graph.py:33` — `embed_and_link_new_cards` 過濾 archived
- Test: `backend/tests/test_pipeline_service.py`

- [ ] **Step 1: Modify _step_embed**

修改 `backend/src/kg/pipeline_service.py:116`，將：
```python
    missing = [card for card in cards.all(notebook_id=notebook_id) if not embeddings.has(card.id)]
```
改為：
```python
    missing = [card for card in cards.all(notebook_id=notebook_id) if not embeddings.has(card.id) and not card.is_archived]
```

- [ ] **Step 2: Modify _step_link**

修改 `backend/src/kg/pipeline_service.py:160`，將：
```python
            if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted:
```
改為：
```python
            if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted or card_a.is_archived or card_b.is_archived:
```

- [ ] **Step 3: Modify embed_and_link_new_cards**

修改 `backend/src/kg/vocab_graph.py:33-35`，將：
```python
                similar = embeddings.find_similar(card.id, k=CANDIDATE_K)
                for other_id, score in similar:
                    if score > SIMILARITY_THRESHOLD:
                        graph.add_candidate(card.id, other_id, score)
```
改為：
```python
                similar = embeddings.find_similar(card.id, k=CANDIDATE_K)
                for other_id, score in similar:
                    if score > SIMILARITY_THRESHOLD:
                        other_card = cards.get(other_id)
                        if other_card and not other_card.is_archived:
                            graph.add_candidate(card.id, other_id, score)
```

- [ ] **Step 4: Run existing pipeline tests**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/test_pipeline_service.py -x -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/pipeline_service.py backend/src/kg/vocab_graph.py
git commit -m "api: pipeline 排除封存卡片 — embed/link/candidate 全鏈過濾"
```

---

## Task 4: iOS — 封存入口搬至 NotebookListView

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift:88-97` — 新增 archivebox toolbar item + sheet
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift:27,61,66,74-79` — 移除 archive 相關 state 和參數
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Toolbar.swift:14,19,87-94` — 移除 archive 按鈕和參數
- Modify: `ios/BooksBrowser/Views/Vocabulary/VocabularyListView+Sheets.swift:10,22-24` — 移除 archive sheet binding
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift:27,113-115` — 移除 archive sheet binding

- [ ] **Step 1: NotebookListView — 新增 toolbar item 和 sheet**

在 `NotebookListView.swift` 新增 state：
```swift
@State private var showArchiveList = false
```

修改 toolbar section（第 88-97 行），在 `+` 按鈕前加入 archivebox：
```swift
.toolbar {
    ToolbarItem(placement: .topBarTrailing) {
        Button {
            showArchiveList = true
        } label: {
            Image(systemName: "archivebox")
        }
    }

    ToolbarItem(placement: .topBarTrailing) {
        Button {
            showCreateSheet = true
        } label: {
            Image(systemName: "plus")
        }
        .disabled(!authManager.isLoggedIn)
    }
}
```

在 `.fullScreenCover(item: $activeReviewSession)` 之後加上：
```swift
.sheet(isPresented: $showArchiveList) {
    ArchivedVocabSheet()
}
```

- [ ] **Step 2: VocabularyListView+Toolbar — 移除 archive 按鈕**

修改 `VocabularyListView+Toolbar.swift`：
- 移除 `let archivedCount: Int`（第 14 行）
- 移除 `let onShowArchive: () -> Void`（第 19 行）
- 移除第 87-94 行的 archive ToolbarItem：
```swift
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(action: onShowArchive) {
                            VocabToolbarGlyph(
                                systemImage: "archivebox",
                                badge: archivedCount > 0 ? "\(archivedCount)" : nil
                            )
                        }
                    }
```

- [ ] **Step 3: VocabularyListView+Sheets — 移除 archive sheet**

修改 `VocabularyListView+Sheets.swift`：
- 移除 `@Binding var showArchiveList: Bool`（第 10 行）
- 移除第 22-24 行：
```swift
            .sheet(isPresented: $showArchiveList) {
                ArchivedVocabSheet()
            }
```

- [ ] **Step 4: VocabularyListView — 移除 archive state 和參數**

修改 `VocabularyListView.swift`：
- 移除 `@State var showArchiveList = false`（第 27 行）
- 在 `VocabularyListToolbar` 呼叫中移除 `archivedCount:` 和 `onShowArchive:` 參數（第 61, 66 行）
- 在 `VocabularyListSheets` 呼叫中移除 `showArchiveList:` 參數（第 76 行）

- [ ] **Step 5: KGVocabView — 移除 archive sheet**

修改 `KGVocabView.swift`：
- 移除 `@State private var showArchiveList = false`（第 27 行）
- 移除第 113-115 行：
```swift
        .sheet(isPresented: $showArchiveList) {
            ArchivedVocabSheet()
        }
```
- 保留 `handleArchiveTap`（swipe-to-archive 功能）

- [ ] **Step 6: Build**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 7: Commit**

```bash
git add ios/
git commit -m "ios: 封存入口搬至 NotebookListView toolbar — 跨單字本統一入口"
```

---

## Task 5: iOS — 圖譜視覺化移除封存節點

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift:49-52`

- [ ] **Step 1: 移除 archived tier 邏輯**

修改 `KnowledgeGraphPresentation.swift:49-52`，將：
```swift
            if entry.isArchived {
                tier = "archived"
                colorHex = nil
                nodeRatio = nil
            } else if entry.reviewCount == 0 {
```
改為：
```swift
            if entry.isArchived {
                return nil
            } else if entry.reviewCount == 0 {
```

（刪除 `tier`/`colorHex`/`nodeRatio` 賦值，直接 `return nil` 跳過封存節點。）

- [ ] **Step 2: Build**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Presentation/KnowledgeGraphPresentation.swift
git commit -m "ios: 圖譜視覺化完全移除封存節點"
```

---

## Task 6: 全面驗證

- [ ] **Step 1: 後端完整測試**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && python -m pytest backend/tests/ -x -q`
Expected: all pass

- [ ] **Step 2: iOS build**

Run: `cd /Users/chenliangyu/MPSO/projects/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: 移除 VocabularyListView+State 中的 archivedCount**

`VocabularyListView+State.swift:83` 有 `archivedCount` computed property，Task 4 移除了 toolbar 對應參數後此屬性變成 dead code。移除該 property 定義。

- [ ] **Step 4: 最終 commit（如有清理）**

```bash
git add -A && git commit -m "api+ios: 封存重構清理 — 移除殘留引用"
```

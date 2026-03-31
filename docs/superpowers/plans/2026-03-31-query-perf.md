# Query Performance Optimization — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 修復查詢路徑三個效能瓶頸，讓增量 sync 從 O(total_cards) 降為 O(changed_cards + neighbours)。
**Architecture:** CardStore 新增 batch_get；vocab_service 增量路徑改為兩階段載入；difficulty 加 LRU cache；iOS sortAndFilter 先 filter 再 sort。
**Tech Stack:** Python/SQLModel, functools.lru_cache, Swift

---

### Task 1: CardStore.get_batch — 批次查詢方法

**Files:**
- Modify: `backend/src/kg/cards.py:290` (在 `all_as_dict` 之後新增)
- Test: `backend/tests/test_cards.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_get_batch_returns_matching_cards(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    c1 = store.add("hello", meaning="你好")
    c2 = store.add("world", meaning="世界")
    c3 = store.add("foo", meaning="富")

    result = store.get_batch({c1.id, c3.id})
    assert set(result.keys()) == {c1.id, c3.id}
    assert result[c1.id].content == "hello"

def test_get_batch_empty_set(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    assert store.get_batch(set()) == {}

def test_get_batch_missing_ids(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    c1 = store.add("hello", meaning="你好")
    result = store.get_batch({c1.id, "nonexistent"})
    assert set(result.keys()) == {c1.id}
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_cards.py::test_get_batch_returns_matching_cards tests/test_cards.py::test_get_batch_empty_set tests/test_cards.py::test_get_batch_missing_ids -v`
Expected: FAIL (AttributeError: 'CardStore' has no attribute 'get_batch')

- [ ] **Step 3: 寫最小實作**
在 `cards.py` 的 `all_as_dict` 方法之後新增：
```python
def get_batch(self, card_ids: set[str]) -> dict[str, "Card"]:
    """Fetch multiple cards by ID in a single query."""
    if not card_ids:
        return {}
    with Session(self.engine) as session:
        statement = select(Card).where(Card.id.in_(card_ids))
        return {card.id: card for card in session.exec(statement).all()}
```

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit** `api: add CardStore.get_batch for batch ID lookup`

---

### Task 2: list_vocab_cards 增量查詢優化

**Files:**
- Modify: `backend/src/kg/vocab_service.py:143-160`
- Test: `backend/tests/test_vocab_service.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_incremental_query_does_not_load_all_cards(tmp_path):
    """Incremental sync should use get_modified_since, not all_as_dict."""
    from unittest.mock import MagicMock, patch
    from datetime import datetime, timedelta
    from kg.vocab_service import list_vocab_cards

    # Setup: mock cards_store with tracking
    cards_store = MagicMock()
    now = datetime(2026, 3, 31, 12, 0, 0)
    modified_card = MagicMock()
    modified_card.id = "card1"
    modified_card.is_deleted = False
    modified_card.content = "test"
    modified_card.updated_at = now

    cards_store.get_modified_since.return_value = [modified_card]
    cards_store.get_batch.return_value = {}

    graph = MagicMock()
    graph.get_links_for.return_value = []

    builder = MagicMock(return_value=MagicMock())

    since = (now - timedelta(hours=1)).isoformat() + "Z"
    list_vocab_cards(since=since, cards_store=cards_store, graph=graph,
                     card_response_builder=builder, notebook_id=None)

    # Assert: get_modified_since was called, all_as_dict was NOT called
    cards_store.get_modified_since.assert_called_once()
    cards_store.all_as_dict.assert_not_called()
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_vocab_service.py::test_incremental_query_does_not_load_all_cards -v`
Expected: FAIL (all_as_dict was called)

- [ ] **Step 3: 寫最小實作**
修改 `vocab_service.py:143-160` 的 `list_vocab_cards`：
```python
def list_vocab_cards(*, since: str | None, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> list[CardResponse]:
    if since:
        parsed_since = parse_datetime(since)
        if parsed_since is None:
            raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.")
        naive_since = parsed_since.replace(tzinfo=None) if parsed_since.tzinfo else parsed_since
        # Phase 1: only fetch modified cards
        modified = cards_store.get_modified_since(naive_since, notebook_id=notebook_id)
        modified_by_id: dict[str, Any] = {c.id: c for c in modified}
        # Phase 2: collect neighbour IDs needed for link resolution
        neighbour_ids: set[str] = set()
        for card in modified:
            if card.is_deleted:
                continue
            for link in graph.get_links_for(card.id):
                other_id = link.to_id if link.from_id == card.id else link.from_id
                if other_id not in modified_by_id:
                    neighbour_ids.add(other_id)
        neighbours = cards_store.get_batch(neighbour_ids) if neighbour_ids else {}
        cards_by_id = modified_by_id | neighbours
        cards = modified
    else:
        # Full sync: all non-deleted cards. Deleted neighbours are skipped by build_links_by_kind.
        cards_by_id = cards_store.all_as_dict(include_deleted=False, notebook_id=notebook_id)
        cards = list(cards_by_id.values())

    return [card_response_builder(card, graph, cards_by_id) for card in cards]
```

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: 寫整合測試驗證 link resolution 正確性**
```python
def test_incremental_query_resolves_neighbour_links(tmp_path):
    """Incremental query should correctly resolve links to non-modified neighbour cards."""
    from kg.cards import CardStore
    from kg.graph import GraphStore
    from kg.vocab_service import list_vocab_cards, card_response
    from kg.difficulty import get_tier
    from kg.types import LinkKind
    from datetime import datetime, timedelta
    import time

    cards = CardStore(tmp_path / "cards.db")
    old_card = cards.add("apple", meaning="蘋果")
    time.sleep(0.05)
    since_dt = datetime.utcnow()
    time.sleep(0.05)
    new_card = cards.add("fruit", meaning="水果")

    graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        tmp_path / "blocked.json",
    )
    graph.batch_add_links([(new_card.id, old_card.id, LinkKind.thematic, 0.9, "fruit→apple")])

    link_kinds = list(LinkKind)
    link_labels = {k: k.value for k in LinkKind}
    def builder(card, g, cards_by_id):
        return card_response(card, graph=g, cards_by_id=cards_by_id,
                             tier_getter=get_tier, link_kinds=link_kinds, link_labels=link_labels)

    since_str = since_dt.isoformat() + "Z"
    results = list_vocab_cards(since=since_str, cards_store=cards, graph=graph,
                               card_response_builder=builder, notebook_id=None)

    assert len(results) == 1
    assert results[0].content == "fruit"
    # Verify link to neighbour "apple" is resolved correctly
    assert "thematic" in results[0].linksByKind
    assert results[0].linksByKind["thematic"][0].word == "apple"
```

- [ ] **Step 6: 跑整合測試確認通過**
Run: `cd backend && python -m pytest tests/test_vocab_service.py::test_incremental_query_resolves_neighbour_links -v`

- [ ] **Step 7: Commit** `api: optimize incremental vocab query to avoid full table load`

---

### Task 3: get_zipf LRU cache

**Files:**
- Modify: `backend/src/kg/difficulty.py:28`
- Test: `backend/tests/test_difficulty.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_get_zipf_is_cached():
    from kg.difficulty import get_zipf
    # Warm cache
    result1 = get_zipf("hello")
    # Check cache info shows hits
    info_before = get_zipf.cache_info()
    result2 = get_zipf("hello")
    info_after = get_zipf.cache_info()
    assert result1 == result2
    assert info_after.hits > info_before.hits
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_difficulty.py::test_get_zipf_is_cached -v`
Expected: FAIL (AttributeError: 'function' has no attribute 'cache_info')

- [ ] **Step 3: 寫最小實作**
```python
from functools import lru_cache

@lru_cache(maxsize=4096)
def get_zipf(word: str, lang: str = "en") -> float:
    """Get Zipf frequency for a word. Higher = more common."""
    tokens = word.strip().split()
    if len(tokens) > 1:
        return min(zipf_frequency(t, lang) for t in tokens)
    return zipf_frequency(word, lang)
```

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit** `api: cache get_zipf with LRU to avoid repeated wordfreq lookups`

---

### Task 4: iOS sortAndFilter — filter before sort

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/VocabularyEntryPresentation.swift:120-150`
- Test: `ios/BooksBrowserTests/BooksBrowserTests.swift`

- [ ] **Step 1: 寫 failing test 確認現有行為**
在 `BooksBrowserTests.swift` 新增：
```swift
func testSortAndFilterResultIsStable() {
    // Given: fixed entries with known words/translations
    // When: sortAndFilter with searchText
    // Then: result contains only matching entries, sorted correctly
    // (This test passes before AND after refactor — guards behavior equivalence)
}
```

- [ ] **Step 2: 修改 sortAndFilter**
```swift
static func sortAndFilter(
    _ entries: [VocabularyEntry],
    searchText: String,
    sortOption: KGVocabSortOption = .default,
    now: Date
) -> [VocabularyEntry] {
    // Filter first to reduce sort input size
    let base = searchText.isEmpty ? entries : entries.filter {
        $0.word.localizedCaseInsensitiveContains(searchText) ||
        $0.translation.localizedCaseInsensitiveContains(searchText)
    }

    switch sortOption {
    case .default:
        return base.sorted { compareKnowledgeEntries($0, $1, now: now) }
    case .alphabetical:
        return base.sorted {
            $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
        }
    case .dateAdded:
        return base.sorted { $0.dateAdded > $1.dateAdded }
    case .difficulty:
        return base.sorted { lhs, rhs in
            let lhsTier = tierPriority(lhs.difficultyTier)
            let rhsTier = tierPriority(rhs.difficultyTier)
            if lhsTier != rhsTier { return lhsTier < rhsTier }
            return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
        }
    }
}
```

- [ ] **Step 3: iOS build + test 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit** `ios: optimize sortAndFilter to filter before sort`

---

### Task 5: Regression — 全量測試

- [ ] **Step 1: Backend 全量測試**
Run: `cd backend && python -m pytest tests/ -v`
Expected: 全部通過

- [ ] **Step 2: iOS build**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: 開 PR**

# Hide Links + Hard Delete Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 新增「隱藏連結」功能（淡化顯示、可恢復），並將現有軟刪除改為硬刪除 + blocked pairs 防護。

**Architecture:** Backend GraphStore 新增 `hidden` status、`_blocked_pairs` set、`blocked_{nb}.json` 持久化。移除 `rejected` status，自動遷移為 blocked pairs。iOS 新增隱藏/恢復/硬刪除的 optimistic UI 操作。API 新增 hide/unhide endpoints。

**Tech Stack:** Python/FastAPI, Pydantic, SwiftUI, SwiftData

---

## File Map

### Backend — New
| File | Responsibility |
|------|---------------|
| `backend/tests/test_hide_link.py` | 隱藏/恢復/硬刪除/blocked pairs 測試 |

### Backend — Modify
| File | Changes |
|------|---------|
| `backend/src/kg/graph.py` | `hidden` status、`_blocked_pairs`、`hard_delete_link`、`hide_link`、`unhide_link`、rejected 遷移 |
| `backend/src/kg/api_models.py` | `CardLinkSummaryResponse` + `hidden: bool` |
| `backend/src/kg/vocab_service.py` | `hide_graph_link`、`unhide_graph_link`、`delete_graph_link`（硬刪）、`build_links_by_kind` 改含 hidden、`create_manual_link` 適配 |
| `backend/src/kg/vocab_handlers.py` | hide/unhide/delete handler |
| `backend/src/kg/routers/vocab.py` | PATCH hide/unhide routes |
| `backend/src/kg/vocab_graph.py` | `graph_links_payload` 確認排除 hidden |
| `backend/src/kg/service_factories.py` | `create_graph_store` 傳入 `blocked_path` |

### iOS — Modify
| File | Changes |
|------|---------|
| `ios/BooksBrowser/Models/SharedTypes.swift` | `KGCardLinkSummary` + `hidden: Bool?` |
| `ios/BooksBrowser/Views/Vocabulary/Components/WordDetailComponents.swift` | hidden row 視覺、context menu 改為隱藏/恢復/刪除 |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift` | `handleHideLink`、`handleUnhideLink` |
| `ios/BooksBrowser/Views/Vocabulary/Presentation/CardPresentation.swift` | `activeLinkGroups`、`totalLinkCount` 排除 hidden |
| `ios/BooksBrowser/Services/KGService+Graph.swift` | `hideLink`、`unhideLink` API 呼叫 |
| `ios/BooksBrowser/Services/KGServing.swift` | protocol 新增方法 |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewState.swift` | 用 `activeLinkGroups` |
| `ios/BooksBrowser/Views/Vocabulary/Presentation/WordDetailPresentation.swift` | `totalLinkCount` 用 active only |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift` | 傳遞 onHide/onUnhide callbacks 到 link rows |

---

## Task 1: GraphStore — `_blocked_pairs` 持久化 + `hidden` status

**Files:**
- Modify: `backend/src/kg/graph.py`
- Modify: `backend/src/kg/service_factories.py`
- Test: `backend/tests/test_hide_link.py`

- [ ] **Step 1: 寫 failing tests — blocked pairs 基礎操作**

```python
# backend/tests/test_hide_link.py
from __future__ import annotations
import pytest
from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


class TestBlockedPairs:
    def test_is_blocked_after_hard_delete(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.is_blocked("a", "b") is True
        assert store.is_blocked("b", "a") is True  # 雙向

    def test_hard_delete_removes_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.get_links_for("a") == []
        assert store.link_count() == 0

    def test_hard_delete_returns_endpoints(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        from_id, to_id = store.hard_delete_link(lk.id)
        assert {from_id, to_id} == {"a", "b"}

    def test_hard_delete_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.hard_delete_link("nonexistent")

    def test_blocked_pairs_persist_across_reload(self, tmp_path):
        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)

        store2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert store2.is_blocked("a", "b") is True

    def test_has_link_checks_blocked(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.has_link("a", "b") is True  # blocked pair counts

    def test_candidate_skipped_for_blocked_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        store.add_candidate("a", "b", 0.95)
        assert store.candidate_count() == 0

    def test_remove_blocked_pairs_for_card(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        store.remove_blocked_pairs_for("a")
        assert store.is_blocked("a", "b") is False

    def test_unblock_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        store.unblock_pair("a", "b")
        assert store.is_blocked("a", "b") is False
```

- [ ] **Step 2: 跑 test 確認全部失敗**
Run: `cd backend && python -m pytest tests/test_hide_link.py -v`
Expected: ALL FAIL

- [ ] **Step 3: 實作 `_blocked_pairs` — `__init__`, `_load`, `_save_blocked`, `is_blocked`, `hard_delete_link`, `remove_blocked_pairs_for`, `unblock_pair`**

Key implementation notes:
- `__init__` 新增 `blocked_path: Path` 參數
- `_blocked_pairs: set[tuple[str, str]]`，pair 正規化為 `tuple(sorted([a, b]))`
- `_save_blocked` 同 `_save_links` 三階段原子寫入
- `_load` 新增 blocked 載入
- `hard_delete_link(link_id) -> tuple[str, str]`：lock 內操作，`_unindex_link` + `del _links[id]` + `_blocked_pairs.add` + save both
- `_has_link_unlocked` 新增 `_blocked_pairs` 檢查
- `add_candidate` / `batch_add_candidates` 的 `has_link` 調用已自動覆蓋

- [ ] **Step 4: 跑 test 確認全部通過**
Run: `cd backend && python -m pytest tests/test_hide_link.py -v`

- [ ] **Step 5: 更新 `service_factories.py` — 傳入 `blocked_path`**

```python
# service_factories.py create_graph_store 內新增：
blocked_path = user_dir / f"blocked_{nb}.json"
# 傳入 GraphStore(..., blocked_path=blocked_path)
```

- [ ] **Step 6: 修正所有既有測試的 GraphStore constructor**

`blocked_path` 是新的必填參數。以下測試檔案的所有 `GraphStore(...)` 呼叫都需加上 `blocked_path=tmp_path / "blocked.json"`：
- `backend/tests/test_manual_link.py`
- `backend/tests/test_graph_index.py`
- `backend/tests/test_graph_orphan.py`
- `backend/tests/test_graph_concurrency.py`
- `backend/tests/test_notebook_delete_cleanup.py`

- [ ] **Step 7: 跑既有測試確認 constructor 修正無 regression**
Run: `cd backend && python -m pytest tests/test_graph_index.py tests/test_graph_orphan.py tests/test_graph_concurrency.py tests/test_notebook_delete_cleanup.py -v`

- [ ] **Step 8: Commit**
Message: `api: add blocked pairs persistence to GraphStore for hard delete support`

---

## Task 2: GraphStore — `hidden` status + 遷移 `rejected`

**Files:**
- Modify: `backend/src/kg/graph.py`
- Test: `backend/tests/test_hide_link.py`

- [ ] **Step 1: 寫 failing tests — hidden status 行為**

```python
class TestHiddenStatus:
    def test_hide_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        assert lk.status == "hidden"

    def test_unhide_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        store.unhide_link(lk.id)
        assert lk.status == "active"

    def test_get_links_for_includes_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        links = store.get_links_for("a")
        assert len(links) == 1
        assert links[0].status == "hidden"

    def test_has_link_true_for_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        assert store.has_link("a", "b") is True

    def test_find_link_between_returns_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.status == "hidden"

    def test_candidate_skipped_for_hidden_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        store.add_candidate("a", "b", 0.95)
        assert store.candidate_count() == 0

    def test_link_count_excludes_hidden(self, store):
        store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = store.add_link("c", "d", LinkKind.SHARES_USAGE, 0.8, "r2")
        store.hide_link(lk2.id)
        assert store.link_count() == 1  # only active

    def test_hide_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.hide_link("nonexistent")


class TestRejectedMigration:
    def test_rejected_links_migrated_to_blocked(self, tmp_path):
        """Pre-populate a graph file with a rejected link, verify migration."""
        import json
        links_data = [{
            "id": "lk1", "from_id": "a", "to_id": "b",
            "kind": "contrasts_with", "confidence": 0.9, "reason": "r",
            "created_at": "2026-01-01T00:00:00Z", "status": "rejected"
        }]
        (tmp_path / "links.json").write_text(json.dumps(links_data))

        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert store.link_count() == 0  # rejected link removed
        assert store.is_blocked("a", "b") is True  # migrated to blocked
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd backend && python -m pytest tests/test_hide_link.py::TestHiddenStatus tests/test_hide_link.py::TestRejectedMigration -v`

- [ ] **Step 3: 實作 `hide_link`, `unhide_link`, status 變更, rejected 遷移**

Key implementation:
- `GraphLink.status` Literal 改為 `"candidate", "active", "deprecated", "hidden"`
- `hide_link(link_id)`: lock → status = "hidden" → save
- `unhide_link(link_id)`: lock → status = "active" → save
- `get_links_for`: 過濾改為 `status in ("active", "hidden")`
- `_has_link_unlocked`: 過濾改為 `status in ("active", "hidden")`
- `find_link_between`: 過濾改為 `status in ("active", "hidden")`
- `link_count`: 維持只計 `active`
- `_load` 遷移：遇到 `status == "rejected"` 的 link → 加入 `_blocked_pairs` + 不載入

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd backend && python -m pytest tests/test_hide_link.py -v`

- [ ] **Step 5: 跑全部既有 graph 測試確認無 regression**
Run: `cd backend && python -m pytest tests/test_manual_link.py tests/test_graph_index.py tests/test_graph_orphan.py tests/test_graph_concurrency.py -v`

注意：Task 1 已修正所有 fixture 的 constructor signature，此處只會遇到 `rejected` 語意變更的 failures。

- [ ] **Step 6: 修正因 `rejected` 移除導致的 test failures**

既有測試影響：
- `test_manual_link.py::TestRejectedStatus` — 整個 class 需重寫為 `TestHiddenStatus`（hide 替代 reject）
- `test_manual_link.py::TestFindLinkBetween::test_finds_rejected_link` — 改為 `test_finds_hidden_link`
- `test_manual_link.py::TestCreateManualLink::test_revives_rejected_link` — 改為 `test_unhides_hidden_link`（unhide 不呼叫 LLM）
- `test_manual_link.py::TestRejectGraphLink` — 改為 `TestDeleteGraphLink`（硬刪除 + blocked）
- `test_graph_index.py::TestBatchAddCandidates::test_skips_existing_links` — 確認仍通過

- [ ] **Step 7: 跑全部測試確認綠燈**
Run: `cd backend && python -m pytest tests/ -v`

- [ ] **Step 8: Commit**
Message: `api: add hidden status, rejected→blocked migration, hard delete`

---

## Task 3: Backend API — hide/unhide endpoints + service 層

**Files:**
- Modify: `backend/src/kg/api_models.py`
- Modify: `backend/src/kg/vocab_service.py`
- Modify: `backend/src/kg/vocab_handlers.py`
- Modify: `backend/src/kg/routers/vocab.py`
- Modify: `backend/src/kg/vocab_graph.py`
- Test: `backend/tests/test_hide_link.py`

- [ ] **Step 1: 寫 failing tests — API 層**

```python
# Import helpers from test_manual_link.py
from tests.test_manual_link import FakeCard, FakeCardsStore, _make_judge
from kg.vocab_service import hide_graph_link, unhide_graph_link, delete_graph_link, create_manual_link, build_links_by_kind
from kg.graph import LinkKind


class TestHideGraphLinkService:
    """Tests for hide/unhide/delete service functions."""

    def test_hide_sets_status_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        hide_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        found = store.find_link_between("a", "b")
        assert found.status == "hidden"

    def test_hide_touches_both_cards(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        hide_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        assert "a" in cards.touched and "b" in cards.touched

    def test_unhide_sets_status_active(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        unhide_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        found = store.find_link_between("a", "b")
        assert found.status == "active"

    def test_delete_hard_deletes_and_blocks(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        delete_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        assert store.find_link_between("a", "b") is None
        assert store.is_blocked("a", "b") is True

    def test_create_manual_link_unhides_hidden(self, store):
        """Hidden link exists → unhide it, do NOT call LLM."""
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "original reason")
        store.hide_link(lk.id)
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        judge = _make_judge()  # should NOT be called
        result = create_manual_link(
            from_id="a", to_id="b", graph=store, cards_store=cards, judge=judge
        )
        assert result.status == "active"
        assert result.reason == "original reason"  # preserved, not re-generated

    def test_create_manual_link_unblocks_and_creates(self, store):
        """Blocked pair → unblock, call LLM, create new link."""
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        judge = _make_judge()
        result = create_manual_link(
            from_id="a", to_id="b", graph=store, cards_store=cards, judge=judge
        )
        assert result is not None
        assert store.is_blocked("a", "b") is False


class TestBuildLinksIncludesHidden:
    def test_hidden_links_have_hidden_flag(self, store):
        """build_links_by_kind includes hidden links with hidden=True."""
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        cards_by_id = {"a": FakeCard("a", content="word_a"), "b": FakeCard("b", content="word_b")}
        result = build_links_by_kind(
            "a", graph=store, cards_by_id=cards_by_id,
            link_kinds=list(LinkKind), link_labels={LinkKind.CONTRASTS_WITH: "對比", LinkKind.SHARES_USAGE: "相關"},
        )
        all_links = [l for group in result.values() for l in group]
        assert len(all_links) == 1
        assert all_links[0].hidden is True

    def test_active_links_have_hidden_false(self, store):
        store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        cards_by_id = {"a": FakeCard("a", content="word_a"), "b": FakeCard("b", content="word_b")}
        result = build_links_by_kind(
            "a", graph=store, cards_by_id=cards_by_id,
            link_kinds=list(LinkKind), link_labels={LinkKind.CONTRASTS_WITH: "對比", LinkKind.SHARES_USAGE: "相關"},
        )
        all_links = [l for group in result.values() for l in group]
        assert len(all_links) == 1
        assert all_links[0].hidden is False
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 實作 api_models + service + handlers + routes**

`api_models.py`:
- `CardLinkSummaryResponse` 新增 `hidden: bool = False`

`vocab_service.py`:
- `build_links_by_kind()`: `get_links_for` 現在回傳 active + hidden，設 `hidden=(link.status == "hidden")`
- `hide_graph_link(link_id, graph, cards_store)`: graph.hide_link + touch both cards
- `unhide_graph_link(link_id, graph, cards_store)`: graph.unhide_link + touch both cards
- `delete_graph_link` (改名自 `reject_graph_link`): graph.hard_delete_link + touch both cards
- `create_manual_link` 修改（三個新分支，全部在 `judge.evaluate()` 之前檢查）:
  - `find_link_between` 回傳 hidden → 直接 `graph.unhide_link(existing.id)` + touch + return，**跳過 LLM 呼叫**
  - `find_link_between` 回傳 active → 409 Conflict（不變）
  - `graph.is_blocked(from_id, to_id)` → `graph.unblock_pair(from_id, to_id)` + 正常流程建立新 link

`vocab_handlers.py`:
- `hide_graph_link_response`、`unhide_graph_link_response`
- `delete_graph_link_response` 改用 `delete_graph_link`

`routers/vocab.py`:
- `PATCH /api/graph/links/{link_id}/hide`
- `PATCH /api/graph/links/{link_id}/unhide`

`vocab_graph.py`:
- `graph_links_payload()` 已只回傳 active，確認無需改動

- [ ] **Step 4: 跑全部 test 確認通過**
Run: `cd backend && python -m pytest tests/ -v`

- [ ] **Step 5: Commit**
Message: `api: add hide/unhide endpoints, hard delete, hidden flag in card response`

---

## Task 3.5: Backend — `merge_from` + `delete_vocab_word` blocked pairs 整合

**Files:**
- Modify: `backend/src/kg/graph.py` (`merge_from`)
- Modify: `backend/src/kg/vocab_service.py` (`delete_vocab_word`, `batch_delete_vocab_words`)
- Test: `backend/tests/test_hide_link.py`

- [ ] **Step 1: 寫 failing tests**

```python
class TestMergeFromBlockedPairs:
    def test_merge_copies_blocked_pairs(self, tmp_path):
        src = GraphStore(
            links_path=tmp_path / "src_links.json",
            candidates_path=tmp_path / "src_cand.json",
            blocked_path=tmp_path / "src_blocked.json",
        )
        dst = GraphStore(
            links_path=tmp_path / "dst_links.json",
            candidates_path=tmp_path / "dst_cand.json",
            blocked_path=tmp_path / "dst_blocked.json",
        )
        lk = src.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        src.hard_delete_link(lk.id)
        dst.merge_from(src)
        assert dst.is_blocked("a", "b") is True


class TestDeleteWordClearsBlockedPairs:
    def test_remove_blocked_pairs_for_card(self, store):
        """After deleting a card, its blocked pairs are cleaned up."""
        lk1 = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = store.add_link("a", "c", LinkKind.SHARES_USAGE, 0.8, "r2")
        store.hard_delete_link(lk1.id)
        store.hard_delete_link(lk2.id)
        assert store.is_blocked("a", "b") is True
        assert store.is_blocked("a", "c") is True
        store.remove_blocked_pairs_for("a")
        assert store.is_blocked("a", "b") is False
        assert store.is_blocked("a", "c") is False

    def test_remove_blocked_pairs_preserves_unrelated(self, store):
        lk1 = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = store.add_link("c", "d", LinkKind.SHARES_USAGE, 0.8, "r2")
        store.hard_delete_link(lk1.id)
        store.hard_delete_link(lk2.id)
        store.remove_blocked_pairs_for("a")
        assert store.is_blocked("c", "d") is True  # unrelated pair preserved
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 實作**

`graph.py` `merge_from`:
- 在雙鎖區段內新增：`self._blocked_pairs |= source._blocked_pairs`
- 呼叫 `self._save_blocked()`

`vocab_service.py` `delete_vocab_word` / `batch_delete_vocab_words`:
- 在 `graph.deprecate_links_for(card.id)` 之後新增：`graph.remove_blocked_pairs_for(card.id)`

- [ ] **Step 4: 跑全部 test 確認通過**
Run: `cd backend && python -m pytest tests/ -v`

- [ ] **Step 5: Commit**
Message: `api: merge_from copies blocked pairs, delete_word cleans blocked pairs`

---

## Task 4: iOS — Model + API 呼叫

**Files:**
- Modify: `ios/BooksBrowser/Models/SharedTypes.swift`
- Modify: `ios/BooksBrowser/Services/KGService+Graph.swift`
- Modify: `ios/BooksBrowser/Services/KGServing.swift`

- [ ] **Step 1: `KGCardLinkSummary` 新增 `hidden` 欄位**

```swift
struct KGCardLinkSummary: Codable, Identifiable, Equatable {
    let id: String
    let cardId: String
    let word: String
    let kind: String
    let label: String
    let confidence: Double
    let reason: String
    let hidden: Bool?          // NEW

    var isHidden: Bool { hidden ?? false }
    var isPending: Bool { id.hasPrefix("pending-") }
}
```

- [ ] **Step 2: `KGService+Graph.swift` 新增 API 方法**

```swift
func hideLink(linkId: String, notebookId: String) async throws {
    try await authenticatedRequest(method: "PATCH", path: "api/graph/links/\(linkId)/hide", notebookId: notebookId)
}

func unhideLink(linkId: String, notebookId: String) async throws {
    try await authenticatedRequest(method: "PATCH", path: "api/graph/links/\(linkId)/unhide", notebookId: notebookId)
}
```

- [ ] **Step 3: `KGServing.swift` 新增 protocol 方法**

- [ ] **Step 4: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 5: Commit**
Message: `ios: add hidden field to KGCardLinkSummary, hide/unhide API methods`

---

## Task 5: iOS — CardPresentation + activeLinkGroups

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/CardPresentation.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Presentation/WordDetailPresentation.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewState.swift`

- [ ] **Step 1: `CardPresentation` 新增 `activeLinkGroups`**

```swift
// linkGroups 保持不變（包含 hidden）— 供 Word Detail 使用
// 新增：
let activeLinkGroups: [CardLinkGroupPresentation]  // 排除 hidden

// 建構時：
activeLinkGroups = linkGroups.compactMap { group in
    let activeItems = group.items.filter { !$0.isHidden }
    guard !activeItems.isEmpty else { return nil }
    return CardLinkGroupPresentation(id: group.id, label: group.label, items: activeItems)
}
```

- [ ] **Step 2: `totalLinkCount` 改用 active only**

```swift
var totalLinkCount: Int {
    activeLinkGroups.reduce(0) { $0 + $1.items.count }
}
```

- [ ] **Step 3: `WordDetailPresentation` — metadata 用 activeLinkGroups**

- [ ] **Step 4: `TodayReviewState` — review cards 用 activeLinkGroups**

- [ ] **Step 5: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 6: Commit**
Message: `ios: add activeLinkGroups, exclude hidden from review and metadata`

---

## Task 6: iOS — Hidden Row 視覺 + Context Menu

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/WordDetailComponents.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`

- [ ] **Step 1: `WordDetailGraphLinkRow` 新增 hidden row 視覺**

新增 `onHide` 和 `onUnhide` callback。body 邏輯分四路：
1. `isPending` → 現有 shimmer
2. `isHidden` → hidden row（只顯示單字、quaternaryText、opacity 0.5、不可點擊）
3. navigable → 現有 button
4. non-navigable → 現有 static

```swift
// hiddenRowContent:
private var hiddenRowContent: some View {
    Text(link.word)
        .font(vocabSkin.typography.rowWord)
        .foregroundStyle(vocabSkin.palette.quaternaryText)
        .opacity(0.5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, vocabSkin.metrics.linkRowVerticalPadding)
}
```

- [ ] **Step 2: Context menu 改為三態**

```swift
.contextMenu {
    if !link.isPending {
        if link.isHidden {
            if let onUnhide {
                Button { onUnhide() } label: {
                    Label("恢復連結".localized, systemImage: "eye")
                }
            }
        } else {
            if let onHide {
                Button { onHide() } label: {
                    Label("隱藏連結".localized, systemImage: "eye.slash")
                }
            }
        }
        if let onDelete {
            Button(role: .destructive) { onDelete() } label: {
                Label("刪除連結".localized, systemImage: "trash")
            }
        }
    }
}
```

- [ ] **Step 3: `WordDetailPresenter` 傳遞新 callbacks**

```swift
WordDetailGraphLinkRow(
    link: link,
    onTap: ...,
    onHide: onHideLink != nil ? { onHideLink?(link) } : nil,
    onUnhide: onUnhideLink != nil ? { onUnhideLink?(link) } : nil,
    onDelete: onDeleteLink != nil ? { onDeleteLink?(link) } : nil
)
```

- [ ] **Step 4: `WordDetailSheet` 新增 `handleHideLink` / `handleUnhideLink`**

Optimistic pattern（同現有 handleDeleteLink）：
- Hide: 修改本地 link 的 hidden flag → PATCH API → rollback on failure
- Unhide: 修改本地 link 的 hidden flag → PATCH API → rollback on failure

由於 `KGCardLinkSummary` 是 `let` 欄位，optimistic update 需要替換整個 link 物件：

```swift
private func handleHideLink(_ link: KGCardLinkSummary) {
    let notebookId = entry.notebookId

    // Optimistic: replace link with hidden version
    var current = entry.graphLinksByKind
    if let idx = current[link.kind]?.firstIndex(where: { $0.id == link.id }) {
        current[link.kind]?[idx] = link.withHidden(true)
        entry.graphLinksByKind = current
    }

    Task {
        do {
            try await kgService.hideLink(linkId: link.id, notebookId: notebookId)
        } catch {
            // Rollback
            var rollback = entry.graphLinksByKind
            if let idx = rollback[link.kind]?.firstIndex(where: { $0.id == link.id }) {
                rollback[link.kind]?[idx] = link  // original
                entry.graphLinksByKind = rollback
            }
            linkError = "隱藏連結失敗".localized
        }
    }
}
```

需要在 `KGCardLinkSummary` 新增 helper：
```swift
func withHidden(_ value: Bool) -> KGCardLinkSummary {
    KGCardLinkSummary(id: id, cardId: cardId, word: word, kind: kind,
                      label: label, confidence: confidence, reason: reason,
                      hidden: value)
}
```

- [ ] **Step 5: Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 6: Commit**
Message: `ios: hidden link row visual, hide/unhide/delete context menu`

---

## Task 7: 更新既有測試 + 全面驗證

**Files:**
- Modify: `backend/tests/test_manual_link.py`
- Modify: `backend/tests/test_graph_index.py`
- Modify: `backend/tests/test_vocab_service.py`

- [ ] **Step 1: 修正 `test_manual_link.py` — rejected → hidden/hard-delete**

| 舊 test | 新行為 |
|---------|--------|
| `TestRejectedStatus.test_has_link_returns_true_for_rejected` | 改為 `test_has_link_returns_true_for_hidden` |
| `TestRejectedStatus.test_get_links_for_excludes_rejected` | 改為 `test_get_links_for_includes_hidden` |
| `TestRejectedStatus.test_add_candidate_skips_rejected_pair` | 改為 `test_add_candidate_skips_hidden_pair` |
| `TestFindLinkBetween.test_finds_rejected_link` | 改為 `test_finds_hidden_link` |
| `TestCreateManualLink.test_revives_rejected_link` | 改為 `test_unhides_hidden_link` — unhide 而非新建 |
| `TestRejectGraphLink` | 改為 `TestDeleteGraphLink` — 硬刪除 + blocked |

- [ ] **Step 2: 修正 `test_graph_index.py` — 確認 fixture 傳入 `blocked_path`**

所有 `GraphStore(...)` 呼叫需加上 `blocked_path=tmp_path / "blocked.json"`。

- [ ] **Step 3: 修正 `test_vocab_service.py` — `graph_links_payload` test**

確認 hidden links 不出現在 graph endpoint payload。

- [ ] **Step 4: 全面測試**
Run: `cd backend && python -m pytest tests/ -v`

- [ ] **Step 5: iOS Build**
Run: `./ops/ios_build.sh`

- [ ] **Step 6: Commit**
Message: `test: update graph tests for hidden status and hard delete`

# 單字列表選取模式 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將知識庫單字列表的移動、封存、刪除整合為統一的長按選取模式，取代分散的左滑 + context menu。

**Architecture:** 後端新增 batch move API + move service 函數。iOS 端新增 SelectionModeState 狀態管理、SelectionToolbar 底部工具列、NotebookPickerSheet 選擇器，重構 KGVocabPresenter 移除 VocabSwipeRow，KGVocabCoordinator 集中三種操作邏輯。

**Tech Stack:** Python/FastAPI (backend), Swift/SwiftUI/SwiftData (iOS)

**Spec:** `docs/superpowers/specs/2026-03-18-vocab-selection-mode-design.md`

---

### Task 1: 後端 — move_cards service 函數 + 測試

**Files:**
- Modify: `backend/src/kg/vocab_service.py`
- Modify: `backend/src/kg/cards.py`
- Create: `backend/tests/test_move_cards.py`

- [ ] **Step 1: 寫 CardStore.move_cards 的失敗測試**

在 `backend/tests/test_move_cards.py` 中：

```python
from __future__ import annotations
import pytest
from kg.cards import CardStore

@pytest.fixture
def store(tmp_path):
    return CardStore(tmp_path / "cards.db")

def test_move_cards_basic(store):
    c1 = store.add("apple", "蘋果", notebook_id="nb1")
    c2 = store.add("book", "書", notebook_id="nb1")
    store.add("cat", "貓", notebook_id="nb1")
    moved = store.move_cards(["apple", "book"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 2
    # 驗證 notebook_id 已更新
    updated = store.find_by_content("apple", notebook_id="nb2")
    assert updated is not None
    assert updated.notebook_id == "nb2"
    # 未移動的卡片不受影響
    cat = store.find_by_content("cat", notebook_id="nb1")
    assert cat is not None

def test_move_cards_skips_deleted(store):
    c1 = store.add("apple", "蘋果", notebook_id="nb1")
    store.delete(c1.id)
    moved = store.move_cards(["apple"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0

def test_move_cards_word_not_found(store):
    store.add("apple", "蘋果", notebook_id="nb1")
    moved = store.move_cards(["nonexistent"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0

def test_move_cards_empty_list(store):
    moved = store.move_cards([], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/test_move_cards.py -v`
Expected: FAIL — `AttributeError: 'CardStore' object has no attribute 'move_cards'`

- [ ] **Step 3: 實作 CardStore.move_cards**

在 `backend/src/kg/cards.py` 的 `reassign_notebook` 方法後面加：

```python
def move_cards(self, words: list[str], from_notebook_id: str, to_notebook_id: str) -> int:
    """Move specific cards by word from one notebook to another. Returns count moved."""
    if not words:
        return 0
    now = datetime.now(UTC)
    moved = 0
    with Session(self.engine) as session:
        for word in words:
            norm = unicodedata.normalize("NFC", word).strip()
            row = session.connection().exec_driver_sql(
                "SELECT id FROM card WHERE content = ? COLLATE NOCASE "
                "AND notebook_id = ? AND is_deleted = 0 LIMIT 1",
                (norm, from_notebook_id),
            ).first()
            if row:
                card = session.get(Card, row[0])
                if card:
                    card.notebook_id = to_notebook_id
                    card.updated_at = now
                    session.add(card)
                    moved += 1
        session.commit()
    return moved
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/test_move_cards.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/cards.py backend/tests/test_move_cards.py
git commit -m "api: add CardStore.move_cards for selective card migration"
```

---

### Task 2: 後端 — move_vocab_words service + handler + router

**Files:**
- Modify: `backend/src/kg/vocab_service.py`
- Modify: `backend/src/kg/vocab_handlers.py`
- Modify: `backend/src/kg/api_models.py`
- Modify: `backend/src/kg/routers/vocab.py`
- Modify: `backend/tests/test_move_cards.py`

- [ ] **Step 1: 寫 move_vocab_words service 層測試**

在 `backend/tests/test_move_cards.py` 追加：

```python
from kg.vocab_service import move_vocab_words

class _FakeCardsStore:
    def __init__(self):
        self.moved = None
        self._cards = {}
    def move_cards(self, words, from_notebook_id, to_notebook_id):
        self.moved = (words, from_notebook_id, to_notebook_id)
        return len(words)
    def find_by_content(self, word, notebook_id=None):
        from types import SimpleNamespace
        return self._cards.get(word, SimpleNamespace(id=f"id_{word}"))

class _FakeGraphStore:
    def __init__(self):
        self.deprecated = []
        self.removed = []
    def deprecate_links_for(self, card_id):
        self.deprecated.append(card_id)
        return 1
    def remove_candidates_for(self, card_id):
        self.removed.append(card_id)
        return 0

def test_move_vocab_words_service():
    cards = _FakeCardsStore()
    src_graph = _FakeGraphStore()
    result = move_vocab_words(
        words=["apple", "book"],
        from_notebook_id="nb1",
        to_notebook_id="nb2",
        cards_store=cards,
        source_graph=src_graph,
        target_graph=None,
    )
    assert result == {"moved": 2}
    assert cards.moved == (["apple", "book"], "nb1", "nb2")

def test_move_vocab_words_empty():
    from fastapi import HTTPException
    cards = _FakeCardsStore()
    with pytest.raises(HTTPException) as exc_info:
        move_vocab_words(
            words=[],
            from_notebook_id="nb1",
            to_notebook_id="nb2",
            cards_store=cards,
            source_graph=None,
        )
    assert exc_info.value.status_code == 422
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/test_move_cards.py::test_move_vocab_words_service tests/test_move_cards.py::test_move_vocab_words_empty -v`
Expected: FAIL — `ImportError: cannot import name 'move_vocab_words'`

- [ ] **Step 3: 實作 move_vocab_words service 函數**

在 `backend/src/kg/vocab_service.py` 中 `delete_vocab_word` 後面加：

```python
def move_vocab_words(
    words: list[str],
    *,
    from_notebook_id: str,
    to_notebook_id: str,
    cards_store: Any,
    source_graph: Any = None,
    target_graph: Any = None,
) -> dict[str, int]:
    """Move specific cards between notebooks. Deprecates graph links in source, adds candidates in target."""
    if not words:
        raise HTTPException(422, "No words provided")
    if from_notebook_id == to_notebook_id:
        raise HTTPException(422, "Source and target notebook are the same")

    # Find card IDs before move (for graph cleanup)
    card_ids = []
    for word in words:
        card = cards_store.find_by_content(word, notebook_id=from_notebook_id)
        if card:
            card_ids.append(card.id)

    moved = cards_store.move_cards(words, from_notebook_id=from_notebook_id, to_notebook_id=to_notebook_id)

    # Deprecate graph links in source notebook
    if source_graph is not None:
        for card_id in card_ids:
            source_graph.deprecate_links_for(card_id)
            source_graph.remove_candidates_for(card_id)

    # Add candidates in target notebook so pipeline regenerates links
    if target_graph is not None:
        target_ids = [c.id for c in (cards_store.all(notebook_id=to_notebook_id) or []) if c.id not in card_ids and not c.is_deleted and not c.is_archived]
        for card_id in card_ids:
            for other_id in target_ids[:20]:  # cap to avoid O(n²) explosion
                target_graph.add_candidate(card_id, other_id, similarity=0.0)

    return {"moved": moved}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/test_move_cards.py -v`
Expected: 6 passed

- [ ] **Step 5: 新增 API model 和 router**

在 `backend/src/kg/api_models.py` 追加：

```python
class MoveWordsRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=200)
    to_notebook_id: str
```

在 `backend/src/kg/vocab_handlers.py` 追加 `move_words_response` 函數：

```python
from .vocab_service import move_vocab_words

def move_words_response(
    req,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, int]:
    require_pro_access(user, "knowledge_sync")
    if notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
        validate_notebook_access(notebook_store_factory(user["dir"]), req.to_notebook_id)
    cards = card_store_factory(user["dir"])
    source_graph = graph_store_factory(user["dir"], notebook_id=notebook_id) if graph_store_factory else None
    target_graph = graph_store_factory(user["dir"], notebook_id=req.to_notebook_id) if graph_store_factory else None
    return move_vocab_words(
        words=req.words,
        from_notebook_id=notebook_id,
        to_notebook_id=req.to_notebook_id,
        cards_store=cards,
        source_graph=source_graph,
        target_graph=target_graph,
    )
```

在 `backend/src/kg/routers/vocab.py` 追加 route（放在 `archive_word` 之前，因為它是 `/api/vocab/move` 不帶 path param）：

```python
from ..api_models import MoveWordsRequest
from ..vocab_handlers import move_words_response

@router.patch("/api/vocab/move")
def move_words(
    req: MoveWordsRequest,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return move_words_response(
        req, user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
```

**注意**：此 route 必須在 `@router.patch("/api/vocab/{word}/archive")` 之前註冊，否則 `move` 會被當作 `{word}` 參數。

- [ ] **Step 6: 跑全部後端測試確認無回歸**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/ -x -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add backend/src/kg/vocab_service.py backend/src/kg/vocab_handlers.py backend/src/kg/api_models.py backend/src/kg/routers/vocab.py backend/tests/test_move_cards.py
git commit -m "api: add PATCH /api/vocab/move batch endpoint"
```

---

### Task 3: iOS — SelectionModeState 狀態管理

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Scenes/SelectionModeState.swift`

- [ ] **Step 1: 建立 SelectionModeState**

```swift
import Foundation

@Observable @MainActor
final class SelectionModeState {
    var isSelecting = false
    private(set) var selectedIDs: Set<UUID> = []

    func enter(with id: UUID) {
        isSelecting = true
        selectedIDs = [id]
    }

    func toggle(_ id: UUID) {
        if selectedIDs.contains(id) {
            selectedIDs.remove(id)
        } else {
            selectedIDs.insert(id)
        }
    }

    func selectAll(_ ids: [UUID]) {
        selectedIDs = Set(ids)
    }

    func deselectAll() {
        selectedIDs.removeAll()
    }

    var isAllSelected: Bool = false

    func updateAllSelectedState(visibleIDs: [UUID]) {
        isAllSelected = !visibleIDs.isEmpty && selectedIDs.count == visibleIDs.count
    }

    func exit() {
        isSelecting = false
        selectedIDs.removeAll()
        isAllSelected = false
    }

    var selectionCount: Int { selectedIDs.count }
    var hasSelection: Bool { !selectedIDs.isEmpty }
}
```

- [ ] **Step 2: 加入 Xcode project，build 確認編譯**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/SelectionModeState.swift ios/BooksBrowser.xcodeproj/
git commit -m "ios: add SelectionModeState for vocab list selection mode"
```

---

### Task 4: iOS — SelectionToolbar 底部工具列

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/SelectionToolbar.swift`

參考 design system：使用 `AppTheme`、`VocabSkin` token，不用 raw color/font。

- [ ] **Step 1: 建立 SelectionToolbar**

```swift
import SwiftUI

struct SelectionToolbar: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

    let selectionCount: Int
    let onMove: () -> Void
    let onArchive: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            toolbarButton(
                label: "移動".localized,
                systemImage: "folder",
                tone: appTheme.palette.accent,
                action: onMove
            )
            toolbarButton(
                label: "封存".localized,
                systemImage: "archivebox",
                tone: vocabSkin.palette.quaternaryText,
                action: onArchive
            )
            toolbarButton(
                label: "刪除".localized,
                systemImage: "trash",
                tone: appTheme.palette.destructive,
                action: onDelete
            )
        }
        .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
        .padding(.vertical, AppMetrics.spacingSmall)
        .background(
            vocabSkin.palette.cardBackground
                .shadow(.drop(color: .black.opacity(0.1), radius: 8, y: -2))
        )
    }

    @ViewBuilder
    private func toolbarButton(label: String, systemImage: String, tone: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: vocabSkin.spacing.microGap) {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconMedium)
                Text(label)
                    .font(vocabSkin.typography.caption)
            }
            .foregroundStyle(selectionCount > 0 ? tone : vocabSkin.palette.quaternaryText)
            .frame(maxWidth: .infinity)
        }
        .disabled(selectionCount == 0)
    }
}

#Preview {
    AppThemeContainer {
        VStack {
            Spacer()
            SelectionToolbar(
                selectionCount: 3,
                onMove: {},
                onArchive: {},
                onDelete: {}
            )
        }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/SelectionToolbar.swift ios/BooksBrowser.xcodeproj/
git commit -m "ios: add SelectionToolbar component for batch operations"
```

---

### Task 5: iOS — NotebookPickerSheet

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookPickerSheet.swift`

- [ ] **Step 1: 建立 NotebookPickerSheet**

```swift
import SwiftUI
import SwiftData

struct NotebookPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]

    let excludeNotebookId: String
    let onPick: (Notebook) -> Void

    private var availableNotebooks: [Notebook] {
        notebooks.filter { !$0.isDeleted && $0.remoteId != excludeNotebookId }
    }

    var body: some View {
        NavigationStack {
            Group {
                if availableNotebooks.isEmpty {
                    VStack {
                        Spacer()
                        VocabEmptyStateCard(
                            title: "沒有其他單字本".localized,
                            systemImage: "folder.badge.questionmark",
                            description: "請先建立新的單字本。".localized
                        )
                        Spacer()
                    }
                    .padding(vocabSkin.metrics.cardBlockPadding)
                } else {
                    List(availableNotebooks) { notebook in
                        Button {
                            onPick(notebook)
                            dismiss()
                        } label: {
                            HStack {
                                if let color = notebook.color {
                                    Circle()
                                        .fill(Color(hex: color) ?? vocabSkin.palette.accent)
                                        .frame(width: 12, height: 12)
                                }
                                Text(notebook.name)
                                    .font(vocabSkin.typography.body)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                Spacer()
                            }
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("移動到...".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
            }
        }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookPickerSheet.swift ios/BooksBrowser.xcodeproj/
git commit -m "ios: add NotebookPickerSheet for move-to-notebook flow"
```

---

### Task 6: iOS — KGService.moveCards API 呼叫 + KGServing protocol 更新

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+VocabCRUD.swift`
- Modify: `ios/BooksBrowser/Services/KGServing.swift`

- [ ] **Step 1: 在 KGServing protocol 新增 moveCards 簽章**

在 `ios/BooksBrowser/Services/KGServing.swift` 的 `archiveCard` 下方加：

```swift
func moveCards(words: [String], fromNotebook: String, toNotebook: String) async throws
```

- [ ] **Step 2: 新增 moveCards 實作**

在 `KGService+VocabCRUD.swift` 的 `archiveCard` 方法後面加：

```swift
func moveCards(words: [String], fromNotebook: String, toNotebook: String) async throws {
    let token = try await currentAuthToken()
    guard var components = URLComponents(url: baseURL.appendingPathComponent("api/vocab/move"), resolvingAgainstBaseURL: false) else {
        throw KGError.serverError("Invalid URL for move")
    }
    components.queryItems = [URLQueryItem(name: "notebook_id", value: fromNotebook)]
    guard let url = components.url else {
        throw KGError.serverError("Invalid URL for move")
    }
    var request = URLRequest(url: url)
    request.httpMethod = "PATCH"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    applyAuth(to: &request, token: token)

    let body: [String: Any] = ["words": words, "to_notebook_id": toNotebook]
    request.httpBody = try JSONSerialization.data(withJSONObject: body)

    let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

    guard let httpResponse = response as? HTTPURLResponse else {
        throw KGError.serverError("Invalid response")
    }

    if httpResponse.statusCode == 401 { throw KGError.unauthorized }
    guard httpResponse.statusCode == 200 else {
        throw KGError.serverError("Failed to move cards")
    }
}
```

- [ ] **Step 3: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+VocabCRUD.swift ios/BooksBrowser/Services/KGServing.swift
git commit -m "ios: add KGService.moveCards + KGServing protocol update"
```

---

### Task 7: iOS — KGVocabCoordinator 新增批次操作方法

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabCoordinator.swift`

- [ ] **Step 1: 在 protocol 新增方法簽章**

在 `KGVocabCoordinating` protocol 追加：

```swift
func handleBatchDelete(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], modelContext: ModelContext)
func handleBatchArchive(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext) async
func handleBatchMove(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], toNotebook: String, fromNotebook: String, kgService: any KGServing, modelContext: ModelContext) async throws
```

- [ ] **Step 2: 實作三個方法**

在 `KGVocabCoordinator` class 中：

```swift
func handleBatchDelete(
    _ entryIDs: Set<UUID>,
    syncedEntries: [VocabularyEntry],
    modelContext: ModelContext
) {
    let entries = syncedEntries.filter { entryIDs.contains($0.id) }
    for entry in entries {
        entry.queueDelete()
    }
    modelContext.safeSave()
}

func handleBatchArchive(
    _ entryIDs: Set<UUID>,
    syncedEntries: [VocabularyEntry],
    kgService: any KGServing,
    modelContext: ModelContext
) async {
    let entries = syncedEntries.filter { entryIDs.contains($0.id) }
    var failCount = 0
    for entry in entries {
        do {
            try await kgService.archiveCard(word: entry.word, archived: true, notebookId: entry.notebookId)
            entry.isArchived = true
        } catch {
            failCount += 1
            AppLog.kg.error("Batch archive failed '\(entry.word)': \(error.localizedDescription)")
        }
    }
    modelContext.safeSave()
    if failCount > 0 {
        let successCount = entries.count - failCount
        errorMessage = L10n.format("%@/%@ 張卡片已封存，部分失敗", "\(successCount)", "\(entries.count)")
    }
}

func handleBatchMove(
    _ entryIDs: Set<UUID>,
    syncedEntries: [VocabularyEntry],
    toNotebook: String,
    fromNotebook: String,
    kgService: any KGServing,
    modelContext: ModelContext
) async throws {
    let entries = syncedEntries.filter { entryIDs.contains($0.id) }
    let words = entries.map(\.word)
    try await kgService.moveCards(words: words, fromNotebook: fromNotebook, toNotebook: toNotebook)
    for entry in entries {
        entry.notebookId = toNotebook
    }
    modelContext.safeSave()
}
```

- [ ] **Step 3: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabCoordinator.swift
git commit -m "ios: add batch delete/archive/move to KGVocabCoordinator"
```

---

### Task 8: iOS — 重構 KGVocabPresenter（移除 swipe/context menu，加入選取模式）

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift`

這是最大的變更。核心改動：
- 移除 `VocabSwipeRow` wrapper 和 `activeSwipeID`
- 移除 `contextMenu`
- 移除 `onDeleteTapped` 和 `onArchiveTapped` callback
- 新增 `selectionState` 參數
- 長按進入選取模式
- 選取模式下顯示 checkbox

- [ ] **Step 1: 重寫 KGVocabPresenter**

替換整個列表渲染區域（`LazyVStack` 部分），新增選取模式邏輯：

1. 移除 properties：`onDeleteTapped`、`onArchiveTapped`、`activeSwipeID`
2. 新增 properties：`selectionState: SelectionModeState`、`onLongPress: (UUID) -> Void`
3. 列表行改為：

```swift
// 取代 VocabSwipeRow + contextMenu 區塊
LazyVStack(spacing: 0) {
    ForEach(Array(state.rows.enumerated()), id: \.element.id) { index, item in
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            if selectionState.isSelecting {
                Image(systemName: selectionState.selectedIDs.contains(item.id) ? "checkmark.circle.fill" : "circle")
                    .font(vocabSkin.typography.iconMedium)
                    .foregroundStyle(
                        selectionState.selectedIDs.contains(item.id)
                            ? vocabSkin.palette.accent
                            : vocabSkin.palette.quaternaryText
                    )
                    .onTapGesture { selectionState.toggle(item.id) }
                    .transition(.scale.combined(with: .opacity))
            }

            WordRow(viewData: item.row)
                .contentShape(Rectangle())
                .onTapGesture {
                    if selectionState.isSelecting {
                        selectionState.toggle(item.id)
                    } else {
                        onRowTapped(item.id)
                    }
                }
                .onLongPressGesture {
                    if !selectionState.isSelecting {
                        onLongPress(item.id)
                    }
                }
        }
        .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)
        .animation(AppMotion.standardSpring, value: selectionState.isSelecting)

        if index < state.rows.count - 1 {
            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: AppMetrics.dividerThin)
                .padding(.leading, vocabSkin.metrics.listDividerInset)
        }
    }
}
```

4. 更新 Preview 移除 `onDeleteTapped`、`onArchiveTapped`，加入 `selectionState` 和 `onLongPress`。

- [ ] **Step 2: 不單獨 build — Task 8 與 Task 9 是原子操作**

KGVocabPresenter 移除了 `onDeleteTapped`、`onArchiveTapped` 參數，KGVocabView 還在傳這些 callback，因此 Task 8 單獨無法 build。必須與 Task 9 一起完成後再 build + commit。

---

### Task 9: iOS — 重構 KGVocabView 整合選取模式

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`

- [ ] **Step 1: 加入選取狀態和 sheet**

在 `KGVocabView` 中：

1. 新增 state 屬性：

```swift
@State private var selectionState = SelectionModeState()
@State private var showNotebookPicker = false
```

2. `selectedReviewState` 的 `onChange` 自動退出選取模式：

```swift
.onChange(of: selectedReviewState) { _, _ in
    selectionState.exit()
}
```

3. 在 `content` computed property 中更新 `KGVocabPresenter` 呼叫：
   - 移除 `onDeleteTapped` 和 `onArchiveTapped`
   - 新增 `selectionState: selectionState`
   - 新增 `onLongPress: { id in selectionState.enter(with: id) }`

4. 移除 `handleArchiveTap` 和 `handleDeleteTap` 方法

5. 在 body 中加入 SelectionToolbar overlay 和 NotebookPickerSheet：

```swift
.overlay(alignment: .bottom) {
    if selectionState.isSelecting {
        SelectionToolbar(
            selectionCount: selectionState.selectionCount,
            onMove: { showNotebookPicker = true },
            onArchive: { handleBatchArchive() },
            onDelete: { handleBatchDelete() }
        )
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}
.animation(AppMotion.standardSpring, value: selectionState.isSelecting)
.sheet(isPresented: $showNotebookPicker) {
    NotebookPickerSheet(excludeNotebookId: notebookId) { notebook in
        handleBatchMove(to: notebook)
    }
    .presentationDetents([.medium])
}
```

6. 選取模式導覽列（透過 toolbar modifier，在 parent view 或此 view 中）：

```swift
.toolbar {
    if selectionState.isSelecting {
        ToolbarItem(placement: .cancellationAction) {
            Button("取消".localized) { selectionState.exit() }
        }
        ToolbarItem(placement: .primaryAction) {
            Button(selectionState.isAllSelected ? "取消全選".localized : "全選".localized) {
                if selectionState.isAllSelected {
                    selectionState.deselectAll()
                } else {
                    selectionState.selectAll(filteredEntries.map(\.id))
                }
                selectionState.updateAllSelectedState(visibleIDs: filteredEntries.map(\.id))
            }
        }
    }
}
```

7. 新增 handler 方法：

```swift
private func handleBatchDelete() {
    coordinator.handleBatchDelete(
        selectionState.selectedIDs,
        syncedEntries: syncedEntries,
        modelContext: modelContext
    )
    selectionState.exit()
}

private func handleBatchArchive() {
    let ids = selectionState.selectedIDs
    selectionState.exit()
    Task {
        await coordinator.handleBatchArchive(
            ids,
            syncedEntries: syncedEntries,
            kgService: kgService,
            modelContext: modelContext
        )
    }
}

private func handleBatchMove(to notebook: Notebook) {
    let ids = selectionState.selectedIDs
    selectionState.exit()
    Task {
        do {
            try await coordinator.handleBatchMove(
                ids,
                syncedEntries: syncedEntries,
                toNotebook: notebook.remoteId,
                fromNotebook: notebookId,
                kgService: kgService,
                modelContext: modelContext
            )
        } catch {
            coordinator.errorMessage = error.localizedDescription
        }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift
git commit -m "ios: replace swipe/context menu with unified selection mode"
```

---

### Task 10: iOS — 清理 VocabSwipeRow

**Files:**
- Delete or simplify: `ios/BooksBrowser/Views/Vocabulary/Components/VocabSwipeRow.swift`

- [ ] **Step 1: 確認 VocabSwipeRow 不再有引用**

搜尋 `VocabSwipeRow` 的所有引用，確認只剩 `ArchivedVocabSheet.swift`（封存列表仍在用左滑解除封存）。

若 `ArchivedVocabSheet` 仍在用 → 保留 `VocabSwipeRow.swift` 不動。
若無其他引用 → 可刪除。

- [ ] **Step 2: Build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: Commit（若有變更）**

```bash
git add -A ios/BooksBrowser/Views/Vocabulary/Components/VocabSwipeRow.swift ios/BooksBrowser.xcodeproj/
git commit -m "ios: clean up VocabSwipeRow references after selection mode refactor"
```

---

### Task 11: 整合驗證

**Files:** 無新增修改，純驗證。

KGServing protocol 已在 Task 6 更新。

- [ ] **Step 1: 全域 build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 3: 跑後端全部測試**

Run: `cd /Users/chenliangyu/kg/backend && python -m pytest tests/ -x -q`
Expected: all passed

- [ ] **Step 3: Commit（若有修正）**

```bash
git add -A ios/
git commit -m "ios: finalize selection mode integration"
```

---

### Task 12: Preview 驗證

**Files:**
- 各已修改的 View 檔案

- [ ] **Step 1: 確認 KGVocabPresenter Preview 正確渲染**

確保 `#Preview` block 更新為新的 API（移除 `onDeleteTapped`、`onArchiveTapped`，加入 `selectionState`、`onLongPress`）。

- [ ] **Step 2: 確認 SelectionToolbar Preview**

已在 Task 4 中建立。

- [ ] **Step 3: Final build**

Run: `cd /Users/chenliangyu/kg && ./ops/ios_build.sh`
Expected: exit 0

- [ ] **Step 4: Final commit（如有調整）**

```bash
git add -A ios/
git commit -m "ios: update previews for selection mode"
```

# Collocation Explain Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 搭配 pill 支援個別長按解釋 + 本地儲存，explain prompt 精簡為 1-2 句。
**Architecture:** 複用現有 `/api/translate/explain` 端點（僅改 prompt）。iOS 端在 `VocabularyEntry` 加本地欄位，`CollocationsBlock` 加 contextMenu，新增 sheet 元件。
**Tech Stack:** Python/FastAPI（prompt 修改）、SwiftUI（contextMenu + sheet + 樣式）、SwiftData（本地持久化）
**依賴:** PR #338（`CollocationFlowLayout` 的 `maxRows` 參數）需先合併

---

### Task 1: Backend — 精簡 explain prompt

**Files:**
- Modify: `backend/src/kg/translate_service.py:89-101`
- Test: `backend/tests/test_translate.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_explain_prompt_concise():
    """Verify the explain prompt requests 1-2 sentences, not 3-5."""
    from kg.translate_service import explain_translate_prompt
    from kg.api_models import TranslateRequest
    req = TranslateRequest(word="progenitor", context="their progenitor")
    prompt = explain_translate_prompt(req, "en", "zh-Hant")
    assert "1-2 sentence" in prompt.lower() or "1–2 sentence" in prompt.lower()
    assert "3-5" not in prompt
    assert "bullet" not in prompt.lower()
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `python -m pytest backend/tests/test_translate.py::test_explain_prompt_concise -v`
Expected: FAIL（目前 prompt 含 "3-5 sentences"）

- [ ] **Step 3: 修改 prompt**

將 `explain_translate_prompt`（`translate_service.py:89-101`）替換為：

```python
def explain_translate_prompt(req: TranslateRequest, source_lang: str, target_lang: str) -> str:
    src_name = SUPPORTED_LANGUAGES.get(source_lang, "English")
    tgt_name = SUPPORTED_LANGUAGES.get(target_lang, "Traditional Chinese")
    return f'''Explain what "{req.word}" means in the given context, then briefly break down the {src_name} components/structure. 1-2 sentences max, in {tgt_name} (use 繁體中文 characters, never 简体).

Word: "{req.word}"
Context: "{_context_around_word(req.context, req.word)}"
Output pure JSON (no Markdown): {{ "e": "..." }}'''
```

- [ ] **Step 4: 跑 test 確認通過**
- [ ] **Step 5: Commit** `api: shorten explain prompt to 1-2 sentences`

---

### Task 2: iOS — VocabularyEntry 新增 collocationExplanations 欄位

**Files:**
- Modify: `ios/BooksBrowser/Models/VocabularyEntry.swift`

- [ ] **Step 1: 在 `VocabularyEntry` class 中新增欄位**

在 `collocations` 後面加：

```swift
var collocationExplanationsJSON: String = "{}"
```

- [ ] **Step 2: 新增 computed accessor**

在 `VocabularyEntry` 底部的 extension 區域加：

```swift
extension VocabularyEntry {
    var collocationExplanations: [String: String] {
        get {
            guard let data = collocationExplanationsJSON.data(using: .utf8),
                  let dict = try? JSONDecoder().decode([String: String].self, from: data)
            else { return [:] }
            return dict
        }
        set {
            collocationExplanationsJSON = (try? JSONEncoder().encode(newValue))
                .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        }
    }
}
```

- [ ] **Step 3: Build 驗證**
Run: `./ops/ios_build.sh`
- [ ] **Step 4: Commit** `ios: add collocationExplanations local field to VocabularyEntry`

---

### Task 3: iOS — CollocationExplainSheet 元件

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/CollocationExplainSheet.swift`

- [ ] **Step 1: 建立 sheet 元件**

```swift
import SwiftUI

struct CollocationExplainSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    let collocation: String
    let existingExplanation: String?
    let onSave: (String) -> Void
    let onDelete: () -> Void

    @State private var phase: Phase = .idle
    @State private var explanation: String = ""

    enum Phase {
        case idle
        case loading
        case loaded
        case error(String)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // 標題
            Text(collocation)
                .font(vocabSkin.typography.detailWord)
                .foregroundStyle(vocabSkin.palette.primaryText)

            CardSectionDivider(horizontalPadding: 0)

            // 內容區
            contentSection

            Spacer()

            // Footer
            footerToolbar
        }
        .padding(.horizontal, vocabSkin.metrics.readerPanelHorizontalInset)
        .padding(.top, 20)
        .padding(.bottom, vocabSkin.metrics.readerPanelBottomInset)
        .appSheet(.medium)
        .task { await loadIfNeeded() }
    }

    @ViewBuilder
    private var contentSection: some View {
        switch phase {
        case .idle:
            EmptyView()
        case .loading:
            VocabStateMessageCard(title: "正在解釋…", systemImage: "text.bubble") {
                ProgressView().scaleEffect(AppMetrics.loadingIndicatorScaleSmall)
            }
        case .loaded:
            Text(explanation)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(3)
        case .error(let message):
            VocabStateMessageCard(
                title: "解釋失敗",
                systemImage: "exclamationmark.triangle.fill",
                description: message
            )
        }
    }

    private var footerToolbar: some View {
        HStack(spacing: 4) {
            // 儲存 — 有內容且未儲存時顯示
            if case .loaded = phase, existingExplanation == nil {
                Button {
                    onSave(explanation)
                    dismiss()
                } label: {
                    Label("儲存", systemImage: "checkmark.circle")
                        .font(vocabSkin.typography.captionStrong)
                }
                .buttonStyle(.plain)
                .foregroundStyle(vocabSkin.palette.success)
            }

            Spacer()

            // 刪除 — 已有儲存時顯示
            if existingExplanation != nil {
                VocabChromeIconButton(
                    systemImage: "trash",
                    tone: vocabSkin.palette.destructive
                ) {
                    onDelete()
                    dismiss()
                }
            }

            // 關閉
            VocabChromeIconButton(systemImage: "xmark") {
                dismiss()
            }
        }
    }

    private func loadIfNeeded() async {
        if let existing = existingExplanation {
            explanation = existing
            phase = .loaded
            return
        }
        // 需要呼叫 API — 由外部注入的 fetchExplanation 完成
        // 此處先設 loading，實際 fetch 邏輯在 Task 5 整合
        phase = .loading
    }
}
```

- [ ] **Step 2: Build 驗證**
- [ ] **Step 3: Commit** `ios: add CollocationExplainSheet component`

---

### Task 4: iOS — CollocationsBlock 改造（contextMenu + 樣式）

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CardDocumentView.swift`（`CardDocumentCollocationsBlock`、`CardDocumentView`）

- [ ] **Step 1: 擴展 `CardDocumentView` 簽名**

新增參數：

```swift
var collocationExplanations: [String: String] = [:]
var onExplainCollocation: ((String) -> Void)? = nil
var onViewCollocationExplanation: ((String) -> Void)? = nil
var onDeleteCollocationExplanation: ((String) -> Void)? = nil
```

在 `.collocations` case 中傳遞：

```swift
case .collocations(let items):
    CardDocumentCollocationsBlock(
        items: items,
        compact: compact,
        explanations: collocationExplanations,
        onExplain: onExplainCollocation,
        onView: onViewCollocationExplanation,
        onDelete: onDeleteCollocationExplanation
    )
    .padding(blockPadding)
```

- [ ] **Step 2: 改造 `CardDocumentCollocationsBlock`**

```swift
private struct CardDocumentCollocationsBlock: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let items: [String]
    var compact: Bool = false
    var explanations: [String: String] = [:]
    var onExplain: ((String) -> Void)? = nil
    var onView: ((String) -> Void)? = nil
    var onDelete: ((String) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
            CardSectionLabel(title: "搭配".localized, systemImage: "text.word.spacing")

            CollocationFlowLayout(spacing: vocabSkin.metrics.cardBlockInnerGap, maxRows: compact ? 2 : nil) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    collocationPill(item)
                }
            }
        }
    }

    private func collocationPill(_ item: String) -> some View {
        let hasExplanation = explanations[item] != nil
        return Text(item)
            .font(vocabSkin.typography.monoBody)
            .foregroundStyle(vocabSkin.palette.secondaryText)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule().fill(
                    hasExplanation
                        ? vocabSkin.palette.accent.opacity(0.12)
                        : vocabSkin.palette.divider.opacity(0.5)
                )
            )
            .overlay(alignment: .leading) {
                if hasExplanation {
                    Circle()
                        .fill(vocabSkin.palette.accent)
                        .frame(width: 4, height: 4)
                        .offset(x: 2)
                }
            }
            .contextMenu {
                if hasExplanation {
                    Button("查看", systemImage: "text.bubble") { onView?(item) }
                    Button("複製", systemImage: "doc.on.doc") { PlatformClipboard.copy(item) }
                    Button("刪除", systemImage: "trash", role: .destructive) { onDelete?(item) }
                } else {
                    Button("解釋", systemImage: "text.bubble") { onExplain?(item) }
                    Button("複製", systemImage: "doc.on.doc") { PlatformClipboard.copy(item) }
                }
            }
    }
}
```

- [ ] **Step 3: Build 驗證**
- [ ] **Step 4: Commit** `ios: collocation pills — per-pill contextMenu + saved style`

---

### Task 5: iOS — 狀態整合（TodayReviewView + sheet 掛載 + API 呼叫）

> **架構關鍵**：`TodayReviewPresenter` 只拿到 `TodayReviewPresenterState`（struct snapshot），無法存取 `VocabularyEntry`。
> 所有需要寫入 entry 的操作（儲存/刪除解釋）和 sheet 掛載都在 `TodayReviewView` 層處理，
> 透過回調穿透到 `TodayReviewPresenter` → `CardDocumentView`。

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewView.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter+CardContent.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CollocationExplainSheet.swift`

- [ ] **Step 1: 定義 CollocationExplainItem**

在 `TodayReviewView.swift` 頂部（或獨立小檔案）：

```swift
struct CollocationExplainItem: Identifiable {
    let id = UUID()
    let collocation: String
    let context: String
    let existingExplanation: String?
}
```

- [ ] **Step 2: TodayReviewView 新增 @State + sheet 掛載**

在 `TodayReviewView` 加：

```swift
@State private var explainSheetItem: CollocationExplainItem? = nil
```

在 body 中現有 `.toastSheet` 後面加：

```swift
.toastSheet(item: $explainSheetItem) { item in
    CollocationExplainSheet(
        collocation: item.collocation,
        context: item.context,
        existingExplanation: item.existingExplanation,
        onSave: { explanation in
            state.currentEntry?.collocationExplanations[item.collocation] = explanation
        },
        onDelete: {
            state.currentEntry?.collocationExplanations.removeValue(forKey: item.collocation)
        }
    )
    .appSheet(.medium)
}
```

- [ ] **Step 3: TodayReviewPresenter 新增回調參數**

在 `TodayReviewPresenter` struct 加：

```swift
let onExplainCollocation: (String) -> Void      // collocation text
let onViewCollocationExplanation: (String) -> Void
let onDeleteCollocationExplanation: (String) -> Void
var collocationExplanations: [String: String] = [:]
```

在 `TodayReviewView.body` 中 `TodayReviewPresenter(...)` 的呼叫加入：

```swift
onExplainCollocation: { collocation in
    guard let entry = state.currentEntry else { return }
    explainSheetItem = CollocationExplainItem(
        collocation: collocation,
        context: entry.context,
        existingExplanation: nil
    )
},
onViewCollocationExplanation: { collocation in
    guard let entry = state.currentEntry else { return }
    explainSheetItem = CollocationExplainItem(
        collocation: collocation,
        context: entry.context,
        existingExplanation: entry.collocationExplanations[collocation]
    )
},
onDeleteCollocationExplanation: { collocation in
    state.currentEntry?.collocationExplanations.removeValue(forKey: collocation)
},
collocationExplanations: state.currentEntry?.collocationExplanations ?? [:]
```

- [ ] **Step 4: combinedAnswerContent 傳遞到 CardDocumentView**

在 `TodayReviewPresenter+CardContent.swift` 的 `CardDocumentView` 呼叫加入：

```swift
CardDocumentView(
    document: currentCard.backDocument,
    truncateRadius: exampleRadius,
    targetWord: card.word,
    compact: true,
    collocationExplanations: collocationExplanations,
    onExplainCollocation: onExplainCollocation,
    onViewCollocationExplanation: onViewCollocationExplanation,
    onDeleteCollocationExplanation: onDeleteCollocationExplanation
)
```

- [ ] **Step 5: CollocationExplainSheet 加入 API 呼叫**

新增 `context: String` 參數，修改 `loadIfNeeded()`：

```swift
let context: String

private func loadIfNeeded() async {
    if let existing = existingExplanation {
        explanation = existing
        phase = .loaded
        return
    }
    phase = .loading
    do {
        let service = TranslationService()
        let (result, _) = try await service.fetchExplanation(
            word: collocation,
            context: context
        )
        explanation = result
        phase = .loaded
    } catch {
        phase = .error(error.localizedDescription)
    }
}
```

- [ ] **Step 6: Build 驗證**
- [ ] **Step 7: Commit** `ios: wire collocation explain sheet to review card + API`

---

### Task 6: 端到端驗證

- [ ] **Step 1: Backend test**
Run: `python -m pytest backend/tests/test_translate.py -x -q`

- [ ] **Step 2: iOS build**
Run: `./ops/ios_build.sh`

- [ ] **Step 3: 手動驗證清單**
- 未儲存 pill 長按 → 出現「解釋」「複製」
- 點「解釋」→ sheet 出現 → loading → 顯示 1-2 句解釋
- 點「儲存」→ sheet 關閉 → pill 樣式變化（底色 + 圓點）
- 已儲存 pill 長按 → 出現「查看」「複製」「刪除」
- 點「查看」→ sheet 直接顯示已存解釋
- 點「刪除」→ pill 恢復原樣

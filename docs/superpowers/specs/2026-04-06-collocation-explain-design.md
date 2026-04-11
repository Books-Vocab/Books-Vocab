# Collocation Explain — Design Spec

## Goal

搭配 pill 從「長按複製整區」升級為「個別互動 + AI 解釋 + 本地儲存」，讓複習時能即時理解搭配用法。

## 互動流程

```
未儲存 pill ──長按──→ contextMenu「複製」「解釋」
                              │
                         點「解釋」
                              ↓
                    .sheet(.medium) 半頁彈窗
                    ┌───────────────────────┐
                    │  ── drag indicator    │
                    │                       │
                    │  the progenitor of    │  ← 搭配短語
                    │  ─────────────────    │
                    │  [loading → 解釋內容]  │
                    │                       │
                    │  ☑儲存   🗑刪除   ✕   │
                    └───────────────────────┘
                              │
                         點「儲存」
                              ↓
              pill 樣式變化（底色加深 + 左側小圓點）

已儲存 pill ──長按──→ contextMenu「查看」「複製」「刪除」
                              │
                         點「查看」→ 同一 sheet，直接顯示已存解釋
                         點「刪除」→ 移除解釋，pill 恢復原樣
```

## Backend — Prompt 精簡

修改 `explain_translate_prompt`（`backend/src/kg/translate_service.py:89`）。

**Before（3-5 句）：**
```
Write a cohesive explanation ... that naturally weaves together:
1. The meaning in this specific context
2. Core usage patterns (common collocations, typical sentence structures, register/formality)
3. Nuances, connotations, or subtle distinctions from near-synonyms if relevant
Write as a single flowing paragraph (3-5 sentences).
```

**After（1-2 句）：**
```
Explain what "{word}" means in the given context, then briefly break down
the English components/structure. 1-2 sentences max, in {target_lang}.
```

同一端點 `/api/translate/explain`，同一 `TranslateRequest`，無新 API。

## iOS 資料層

### `VocabularyEntry` 新欄位

```swift
// VocabularyEntry.swift
var collocationExplanationsJSON: String = "{}"
```

存 `[String: String]` 字典，key = collocation 文字，value = 解釋。

SwiftData 自動 schema migration（新增 optional/default 欄位無需手動 migration）。

### Accessor

```swift
extension VocabularyEntry {
    var collocationExplanations: [String: String] {
        get { (try? JSONDecoder().decode([String: String].self, from: Data(collocationExplanationsJSON.utf8))) ?? [:] }
        set { collocationExplanationsJSON = (try? String(data: JSONEncoder().encode(newValue), encoding: .utf8)) ?? "{}" }
    }
}
```

## iOS UI 層

### 1. `CardDocumentCollocationsBlock` 改造

- 移除整區 `.contextMenu`
- 每個 pill 獨立 `.contextMenu`：
  - 未儲存：「複製」「解釋」
  - 已儲存：「查看」「複製」「刪除」
- 需要從外部注入：`explanations: [String: String]`、回調 `onExplain: (String) -> Void`、`onDelete: (String) -> Void`

### 2. `CollocationExplainSheet`（新檔案）

- 位置：`ios/BooksBrowser/Views/Vocabulary/Components/CollocationExplainSheet.swift`
- 使用 `.sheet` + `.appSheet(.medium)`
- 結構類似 `TranslationVocabPresenter`：
  - 標題：搭配短語（`vocabSkin.typography.detailWord`）
  - 分隔線
  - 內容區：loading / 解釋文字 / error
  - Footer toolbar：儲存按鈕、刪除按鈕、關閉按鈕（用 `VocabChromeIconButton`）
- 狀態機：`.loading` → `.content(String)` → `.saved` / `.error(String)`

### 3. Pill 樣式差異

已儲存的 pill：
- 底色：`vocabSkin.palette.accent.opacity(0.12)`（比原本 `divider.opacity(0.5)` 更明顯）
- 左側小圓點：`Circle().fill(vocabSkin.palette.accent).frame(width: 4, height: 4)`

### 4. 狀態管理

在 `TodayReviewState` 或 `TodayReviewPresenter` 中：
- `@State var explainSheetCollocation: String?`（控制 sheet 顯示）
- Sheet 內部用 `@State` 管理 loading/content 狀態
- 儲存時直接寫入當前 `VocabularyEntry.collocationExplanations`

### 5. 資料流穿透

```
TodayReviewView
  → TodayReviewPresenter
    → combinedAnswerContent
      → CardDocumentView(compact: true)
        → CardDocumentCollocationsBlock(
            items: [...],
            compact: true,
            explanations: currentEntry.collocationExplanations,  // NEW
            onExplain: { collocation in ... },                    // NEW
            onViewExplanation: { collocation in ... },            // NEW
            onDeleteExplanation: { collocation in ... }           // NEW
          )
```

需要把 `VocabularyEntry` 的引用（或至少 explanations dict）從 `TodayReviewState.CurrentCard` 一路傳到 `CardDocumentCollocationsBlock`。

## 不做的事

- 不同步 collocation explanations 到 backend
- 不新增 API 端點
- 不改 `CardPresentation` model（explanations 從 entry 直取）
- WordDetail 頁面的搭配暫不改（只改 review card）

## 測試要點

- explain API 回傳 1-2 句（prompt 修改後）
- 未儲存 pill 長按出「複製」「解釋」
- 解釋 sheet 正確顯示 loading → 內容
- 儲存後 pill 樣式改變
- 已儲存 pill 長按出「查看」「複製」「刪除」
- 刪除後 pill 恢復原樣
- 殺 app 重開，已存解釋仍在

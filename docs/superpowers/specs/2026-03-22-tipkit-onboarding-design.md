# TipKit Contextual Onboarding

## Context

BooksBrowser's Welcome screen (4-page carousel) tells users what features exist but never teaches how to use them. Three critical knowledge gaps cause new-user friction:

1. **Long-press to look up words** — the core interaction in the reader is invisible
2. **Sync pending vocabulary** — after looking up words, users don't know they need to sync
3. **Where to get EPUBs** — empty bookshelf has an import button but no guidance on sourcing books

## Approach

Use iOS 17 TipKit framework for contextual tips. TipKit provides:
- System-native popover/inline tips with automatic lifecycle management
- Rule-based display (event counts, parameters, tip dependencies)
- Automatic "don't show again" after dismissal
- No manual UserDefaults state management needed

## Constraints

- iOS 17+ (already the deployment target)
- Tips must not block interaction — dismissible with a tap
- Tips should appear at most once per trigger condition
- No changes to existing view layout or navigation structure
- Follow existing VocabSkin/AppTheme styling where possible (TipKit allows limited customization)

## Scope

3 tips, each independently shippable.

---

### 1. LongPressTip — Reader Word Lookup

**What:** A popover tip anchored near the top of the reader view, telling the user they can long-press words.

**Trigger rules:**
- The user has opened a book (ReaderView appeared)
- The user has never looked up a word before (event `wordLookedUp` count == 0)
- Tip has not been dismissed or invalidated

**Content:**
- Title: "長按查詞"
- Message: "長按任何單字即可查詢 AI 翻譯與詞性解析"

**Invalidation:** When the user looks up their first word, donate the event AND explicitly invalidate: call `LongPressTip.wordLookedUp.donate()` followed by `LongPressTip().invalidate(reason: .actionPerformed)`. This is consistent with how the other two tips handle invalidation.

**Display style:** `.popover` anchored to the reading area, or `.inline` at the top of the reader overlay.

---

### 2. SyncPendingTip — Vocabulary Sync Reminder

**What:** An inline tip displayed at the top of `NotebookListView` (the notebook tab's root view), nudging the user to sync when they first navigate to the notebook tab with pending words.

**Why not popover on tab icon:** SwiftUI's `TabView` does not expose tab bar item views for `.popoverTip()` anchoring. An inline tip inside the notebook list is simpler and equally effective.

**Trigger rules:**
- There are pending (unsynced) vocabulary entries (pendingCount > 0)
- The user has never completed a sync before (event `syncCompleted` count == 0)

**Content:**
- Title: "同步你的單字"
- Message: "你有未同步的生詞，點擊同步按鈕推送到雲端"

**Invalidation:** When the user completes their first sync, call `SyncPendingTip.syncCompleted.donate()`.

**Display style:** `.inline` at the top of `NotebookListView`, above the notebook list. The pending count condition is evaluated in the View layer (SwiftUI `if` guard), not via TipKit `@Parameter`, since `pendingCount` is View state.

**Edge case:** If the user enters NotebookListView with pendingCount == 0 and it later becomes > 0, the tip won't appear until the next view rebuild. This is an accepted trade-off — the user will see the tip the next time they navigate to the tab.

---

### 3. EPUBGuideTip — Where to Find Books

**What:** An inline tip in the bookshelf empty state, linking to the EPUB sourcing guide.

**Trigger rules:**
- The bookshelf is empty (no books imported)
- Tip has not been dismissed

**Content:**
- Title: "哪裡找電子書？"
- Message: "查看 EPUB 取得指南，了解如何取得免費或付費電子書"
- Action: "查看指南" → opens `AppURLs.guide`

**Invalidation:** When the user imports their first book, call `EPUBGuideTip().invalidate(reason: .actionPerformed)` to permanently dismiss the tip. Do not rely on view rebuild alone — the user may delete all books later and the tip should not reappear.

**Display style:** `.inline` within the empty state VStack, below the existing import button.

**Note:** The existing `epubGuideHint` link only appears in the book grid view (when books exist). This tip fills the gap for the empty state, where no guide link currently exists. They do not overlap.

---

## Implementation Notes

### TipKit Setup

- Call `try? await Tips.configure()` directly inside `BooksBrowserApp`'s `.task {}` modifier (`.task` already provides an async context — do NOT wrap in an additional `Task {}`)
- Define all tips in a single file: `ios/BooksBrowser/Models/AppTips.swift`
- Each tip is a `struct: Tip` with `title`, `message`, optional `actions`, and `rules`

### Event Tracking

TipKit events are lightweight — just call `.donate()` at the right moment:
- `wordLookedUp`: donate in the coordinator/handler layer when a translation result is successfully received (not in TranslationPanel UI layer, which is a pure presenter)
- `syncCompleted`: donate when `SyncPresenter` reaches `.completed` phase

### Tip Dependencies

No tip dependencies needed — all three are independent. Each tip should set `var options: [TipOption] { [Tips.MaxDisplayCount(1)] }` to ensure it appears at most once per user.

## Non-Goals

- No custom tip styling (use system default — it's clean enough)
- No tip analytics or tracking
- No changes to Welcome carousel
- No demo book bundling

## Risk

Low. TipKit is a stable iOS 17 framework. Tips are purely additive — if they cause issues, they can be disabled with `Tips.configure([.datastoreLocation(.applicationDefault)])` reset or by removing the tip structs.

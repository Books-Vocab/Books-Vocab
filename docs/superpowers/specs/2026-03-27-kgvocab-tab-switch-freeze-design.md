# KGVocab Tab Switch Freeze: Root Cause & Fix Plan

**Date:** 2026-03-27
**Scope:** `KGVocabView` — switching to "已複習" tab freezes UI with 400+ entries
**Severity:** User-facing freeze / potential watchdog kill

## Problem

Switching to the "已複習" tab in the vocabulary list causes the UI to freeze. The freeze only occurs on this tab because it contains the majority of entries (~80-90% of all vocabulary). "待複習" and "未學習" tabs are unaffected due to small entry counts.

### Reproduction

1. Accumulate 400+ synced vocabulary entries
2. Open KG vocabulary list
3. Tap "已複習" tab
4. **Result:** UI freezes for several seconds

## Root Cause Analysis

Five compounding issues in the render path, all executing synchronously on the main thread:

### Issue 1: `countKnowledgeEntries` sorts entire array just to count

**File:** `ios/BooksBrowser/Views/Vocabulary/Presentation/VocabularyEntryPresentation.swift:76-81`

```swift
static func countKnowledgeEntries(...) -> Int {
    syncedKnowledgeEntries(in: entries)  // ← sorts ALL entries (O(n log n))
        .filter { $0.reviewState == reviewState }.count  // ← just needs a count
}
```

Called 3 times (once per tab) via `reviewStateOptions` → `count(for:)`.
**Total cost:** 3 × O(n log n) sort + 3 × O(n) filter = ~3 × n × log(n) comparisons, **all unnecessary**.

### Issue 2: `Date()` called thousands of times per render

**File:** `ios/BooksBrowser/Models/VocabularyReview.swift:98-119`

Every access to `entry.reviewState` chains through:
1. `reviewState` → `isReviewDue` → `reviewSnapshot` (struct allocation) → `.isDue` → `Date()`

The sort comparator `compareKnowledgeEntries` accesses `reviewState` for both `lhs` and `rhs` on every comparison. For n=400: sort ≈ 400 × log₂(400) ≈ 3,450 comparisons × 2 sides × `Date()` call each.

Combined with 3 count calls + 1 filtered list + filter passes:
**Estimated total:** ~15,000+ `Date()` calls + `VocabularyReviewSnapshot` struct allocations per tab switch.

### Issue 3: "已複習" is the largest tab

With 400+ total entries, "已複習" may contain 350-400 entries (all reviewed words not yet due). The other tabs have far fewer. This means:
- The sort and filter cost is maximized on this specific tab
- All subsequent row-building work is maximized too

### Issue 4: Eager ViewData materialization defeats LazyVStack

**File:** `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift:189-198`

```swift
rows: filteredEntries.map {  // ← eagerly builds ALL 400 ViewData objects
    KGVocabPresenter.State.RowItem(
        id: $0.id,
        row: $0.wordRowViewData(...)  // ← each calls reviewState again
    )
}
```

Despite using `LazyVStack` in the presenter, all `WordRow.ViewData` objects are created upfront in the computed property. Each `wordRowViewData()` call internally accesses `reviewState` (more `Date()` calls) and performs string formatting.

### Issue 5: `.id(selectedReviewState)` forces full view tree rebuild

**File:** `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift:117`

```swift
.id(selectedReviewState)
.transition(.contentSwap)
```

This tells SwiftUI to destroy the entire old view tree and rebuild from scratch on every tab change, rather than diffing. Combined with the eager ViewData creation, it maximizes the main-thread work.

### Combined Impact

| Step | Cost (n=400) | Main thread? |
|------|-------------|:---:|
| 3 × countKnowledgeEntries (sort + filter) | 3 × O(n log n) | ✅ |
| 1 × filteredKnowledgeEntries (filter + sort) | O(n log n) | ✅ |
| ~15,000 Date() + struct allocs | O(n log n) | ✅ |
| 400 × wordRowViewData() | O(n) | ✅ |
| Full view tree destroy + rebuild | O(n) | ✅ |

**Total:** ~4 × n log n + n, all synchronous, all blocking the main thread.

## Fix Plan

### Fix A: Eliminate redundant sort in count (trivial, highest impact)

**File:** `VocabularyEntryPresentation.swift`

Replace `countKnowledgeEntries`:
```swift
// Before: sorts entire array just to count
static func countKnowledgeEntries(...) -> Int {
    syncedKnowledgeEntries(in: entries).filter { ... }.count
}

// After: single O(n) pass, no sort
static func countKnowledgeEntries(...) -> Int {
    entries.count { $0.shouldAppearInKnowledgeList && $0.reviewState == reviewState }
}
```

**Eliminates:** 3 × O(n log n) sorts → 3 × O(n) scans.

### Fix B: Snapshot `Date()` once per render cycle

**File:** `VocabularyEntryPresentation.swift`, `VocabularyReview.swift`

Add a `reviewState(at:)` method that accepts a pre-captured `Date`:

```swift
// VocabularyReview.swift
extension VocabularyEntry {
    func reviewState(at now: Date) -> VocabularyReviewState {
        if reviewCount == 0 { return .unlearned }
        return nextReviewAt <= now ? .due : .reviewed
    }
}
```

Update `filteredKnowledgeEntries`, `countKnowledgeEntries`, and `compareKnowledgeEntries` to accept and pass through a single `now: Date = Date()` parameter.

**Eliminates:** ~15,000 `Date()` calls → 1 `Date()` call per render. Also eliminates ~15,000 `VocabularyReviewSnapshot` struct allocations.

### Fix C: Defer row ViewData creation to LazyVStack

**Files:** `KGVocabView.swift`, `KGVocabPresenter.swift`

Change the presenter's data model to pass filtered entry IDs/references instead of pre-built `WordRow.ViewData`. Let `LazyVStack` rows build their own ViewData on demand:

**Option C1 (minimal change):** Change `State.rows` to only carry lightweight identifiers + the entry reference. Build `WordRow.ViewData` inside the `ForEach` body (which `LazyVStack` only evaluates for visible rows).

```swift
// KGVocabPresenter.State
struct RowItem: Identifiable {
    let id: UUID
    let entry: VocabularyEntry  // pass entry, not pre-built ViewData
}

// In ForEach body (only runs for visible rows):
WordRow(viewData: item.entry.wordRowViewData(...))
```

**Option C2 (cleaner separation):** Keep the presenter pure by passing a closure/builder, but this is more architectural change.

**Recommendation:** Option C1 — minimal diff, directly fixes the eager allocation issue.

**Eliminates:** 400 × `wordRowViewData()` upfront → only ~15 visible rows computed.

### Fix D: Replace `.id()` with matched geometry or manual diffing (optional, lower priority)

**File:** `KGVocabPresenter.swift:117`

Remove `.id(selectedReviewState)` and let SwiftUI diff naturally. The `.transition(.contentSwap)` animation can be achieved with `animation(.default, value: selectedReviewState)` on the parent, or a custom `matchedGeometryEffect`.

**Trade-off:** May slightly change the tab-switch animation. Test visually before committing.

**Priority:** Low — Fixes A-C should resolve the freeze. Only pursue if residual jank remains.

## Expected Impact

| Fix | Date() calls | Sort passes | ViewData allocs | Difficulty |
|-----|:---:|:---:|:---:|:---:|
| A: count without sort | — | 4→1 | — | Trivial |
| B: snapshot Date() | 15000→1 | — | — | Small |
| C: lazy ViewData | — | — | 400→~15 | Medium |
| D: remove .id() | — | — | — | Small |

**Combined:** Main-thread work drops from O(4 × n log n) + O(n) eager allocs to O(n log n) + O(visible) lazy allocs. For n=400, estimated **~20x reduction** in main-thread blocking time.

## Implementation Order

1. **Fix A** — one-line change, immediate impact
2. **Fix B** — small refactor, eliminates the Date() storm
3. **Fix C** — moderate refactor of presenter data flow, makes LazyVStack actually lazy
4. **Fix D** — optional polish, only if needed after A-C

## Files Affected

| File | Fixes |
|------|-------|
| `ios/BooksBrowser/Views/Vocabulary/Presentation/VocabularyEntryPresentation.swift` | A, B |
| `ios/BooksBrowser/Models/VocabularyReview.swift` | B |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift` | C |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift` | C, D |

## Verification

- Populate 400+ vocabulary entries in "已複習" state
- Measure tab-switch time before/after (Instruments → Time Profiler, or manual stopwatch)
- Confirm no visual regression in tab animations
- Confirm counts remain accurate across all 3 tabs

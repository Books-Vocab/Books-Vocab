# Visual Polish: Notion-Style Tool Surface

## Context

BooksBrowser's product focus has shifted from "immersive EPUB reader" to "reading + review tool." The visual language still reflects the former identity — Morandi palette, serif navigation titles, invisible UI philosophy. The reader should stay immersive, but the tool surfaces (vocab list, review, sync, stats, settings, bookshelf) need interaction density and feedback closer to Notion's style: responsive press states, meaningful transitions, and alive empty states.

**Constraints:**
- Typography stays as-is (Athelas serif nav titles, ElmsSans body). No font changes.
- Color palette stays as-is (Morandi / VocabSkin). No palette changes.
- Layout stays as-is. No view restructuring, no new tabs, no new features.
- Reader stays untouched.
- All new animations must use `AppMotion` tokens (add new tokens as needed).

## Scope

8 work items, all additive (no removals, no rewrites).

**Minimum deployment target:** iOS 17+ (required for `.symbolEffect`, `.sensoryFeedback`).

---

### 1. Press Feedback System

**What:** A unified `ViewModifier` that gives all interactive elements tactile press response.

**Behavior:**
- On press: `scale(0.96)` + `opacity(0.85)`, spring-driven
- On release: bounce back via `AppMotion` spring token
- Haptic: `.sensoryFeedback(.selection)` on press

**Where to apply (buttons only — cards use Item 7 instead):**
- `.vocabAction` buttons (primary/neutral/destructive/warning)
- `SettingsButtonChromeModifier` buttons
- `NotebookRow` tap targets
- Any `.borderedProminent` in tool surfaces

**Implementation:**
- New `PressableStyle: ButtonStyle` in VocabSkin components
- Reuse existing `AppMotion.buttonSpring` if parameters fit (response: 0.35, dampingFraction: 0.7); only create a new `pressFeedback` token if different values are needed
- Apply via `.buttonStyle(PressableStyle())` or a convenience `.pressable()` modifier

**Not included:** Reader buttons, navigation bar buttons, system controls, card containers (see Item 7).

---

### 2. List Animations

**What:** Insertion, deletion, and reorder animations for all `LazyVStack` lists.

**Behavior:**
- Insertion: `opacity(0) + offset(y: 8)` → `opacity(1) + offset(y: 0)`, using `AppMotion` token
- Deletion: `opacity → 0` + height collapse via `.transition(.asymmetric(...))`
- Sort change: `.animation()` on the `LazyVStack` so reordering is continuous, not jump-cut

**Where to apply:**
- `NotebookListView` (notebook rows)
- `KGVocabView` / `VocabularyListView` (`WordRow` items)

**Implementation:**
- New `AnyTransition.listInsert` / `AnyTransition.listRemove` extensions in `AppMetrics.swift` (following existing `AnyTransition.listItemFade` / `AnyTransition.contentSwap` pattern)
- Wrap list data changes in `withAnimation(AppMotion.<token>)`
- Ensure `ForEach` items have stable `id` for smooth reorder

---

### 3. Stats Chart Fade-In

**What:** Animated transition when stats data loads (replacing ProgressView with content).

**Behavior:**
- Content appears with `opacity(0→1) + scale(0.98→1.0)`, ~300ms
- Numeric counters already use `.contentTransition(.numericText())` — keep those

**Where to apply:**
- `StatsPresenter`: streak cards, heatmap, forecast chart
- The `ProgressView` → content switch

**Implementation:**
- New `AppMotion.contentReveal` token
- Wrap the phase transition in `withAnimation(AppMotion.contentReveal)`

---

### 4. Review Completion Celebration

**What:** A moment of delight when all review cards are completed.

**Behavior:**
- Checkmark SF Symbol with `.symbolEffect(.bounce)` + scale overshoot (1.0 → 1.15 → 1.0)
- `.sensoryFeedback(.success)` haptic
- Subtle: no confetti, no particle effects. Restrained celebration matching the app's personality.

**Where to apply:**
- `TodayReviewPresenter` when transitioning to the completed empty state (`VocabEmptyStateContent`)

**Implementation:**
- New `AppMotion.celebrationBounce` spring token (higher bounce than standard)
- Apply `.symbolEffect(.bounce)` to the completion icon
- Wrap the scale overshoot in `withAnimation(AppMotion.celebrationBounce)`

---

### 5. Sheet Content Appear Transition

**What:** Sheet _content_ (not the modal slide-up itself, which is system-controlled) gets a branded appear animation.

**Behavior:**
- When sheet content appears: first-layer content fades in with `opacity(0→1) + scale(0.97→1.0)` via `AppMotion` spring
- This runs _inside_ the sheet, after the system slide-up completes
- Dismiss uses the system default (no override possible from SwiftUI)

**Where to apply:**
- All `.appSheet` usages across tool surfaces (WordDetailSheet, WordEditSheet, ReviewCalendarPresenter, ArchivedVocabSheet, settings sheets)

**Implementation:**
- New `AppMotion.sheetContentAppear` spring token
- Add an `.onAppear` + state-driven transition inside the sheet content wrapper
- No modification to the `.appSheet` modifier's presentation mechanics

---

### 6. Empty State Upgrade

**What:** Bring empty states to life with animated SF Symbols and guiding copy.

**Behavior:**
- SF Symbol gains `.symbolEffect(.breathe)` (gentle pulse, not distracting)
- Add a secondary line of guiding text below the existing message (e.g., bookshelf empty: primary "No books yet", secondary "Import your first EPUB to get started")

**Where to apply:**
- `BookshelfView` empty state (`AppEmptyStateContent`)
- `VocabEmptyStateContent` (vocabulary list empty)
- `NotebookListView` empty state (if applicable)
- `KGVocabView` empty filter results

**Implementation:**
- `AppEmptyStateContent` already has a `description` field. Add a new optional `guidanceText: String? = nil` field displayed _below_ `description` in a lighter weight / smaller font, providing actionable next-step copy (e.g., "Import your first EPUB to get started"). Existing call sites pass no `guidanceText` and are unchanged.
- `VocabEmptyStateContent`: same pattern — add optional `guidanceText` below existing copy.
- Add `.symbolEffect(.breathe)` to the icon Image
- Provide guidanceText strings per context

---

### 7. Card Press Lift

**What:** Cards feel "liftable" — pressing makes them subtly rise.

**Behavior:**
- On press: shadow radius increases (e.g., 2→6), shadow y-offset increases (1→3), scale 1.005
- On release: spring back
- Effect is extremely subtle — the card "lifts" toward you

**Where to apply:**
- `VocabListCard` (the rounded card container used in KGVocab, Stats, Sync)
- `VocabCard` (smaller card variant)
- `BookCard` (bookshelf grid items)

**Mutual exclusion with Item 1:** Cards use lift (scale up + shadow), buttons use press (scale down + opacity). They are separate modifiers and must not be stacked on the same element.

**Implementation:**
- New `LiftableModifier: ViewModifier` (separate from `PressableStyle`)
- Reuse `AppMotion.buttonSpring` or the press feedback token for the spring
- Shadow values as new constants in `AppShellMetrics` or `VocabSkin.Spacing`

---

### 8. List Swipe Actions

**What:** Quick actions on word rows via swipe gestures, reducing dependence on context menus.

**Behavior:**
- Leading swipe (right): "Archive" action, `skin.palette.neutral` background
- Trailing swipe (left): "Quick Review" action, `skin.palette.accent` background
- Threshold: 80pt drag to reveal, full swipe to trigger

**Technical note:** `.swipeActions` only works with `List`, not `LazyVStack`. Since the app uses `LazyVStack` + `ScrollView`, this requires a custom swipe row implementation using `DragGesture` + offset + clipped action buttons.

**Where to apply:**
- `WordRow` in `KGVocabView` / `VocabularyListView`

**Implementation:**
- New `SwipeActionRow: ViewModifier` wrapping content in `ZStack` with hidden action buttons
- `DragGesture` on the row with spring snap-back via `AppMotion` token
- Action buttons revealed behind the row as it slides
- Wire to existing archive and review-scheduling logic
- SF Symbol icons: `archivebox` (archive), `arrow.clockwise` (quick review)

**Out of scope:** `ArchivedVocabSheet` already uses native `List` with `.swipeActions` — no changes needed there.

---

## Non-Goals

- No typography changes
- No color palette changes
- No layout restructuring
- No new product features (view switching, filtering, search)
- No reader modifications
- No accessibility work (Dynamic Type, VoiceOver)

## Dependencies

- All new animation tokens added to `AppMetrics.swift` (`AppMotion` / `AppTransition`)
- No external dependencies

## Risk

Low. All changes are additive modifiers and tokens. No data model changes, no API changes, no architectural changes. Each item is independently shippable.

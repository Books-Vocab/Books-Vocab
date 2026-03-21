# Visual Polish: Notion-Style Tool Surface — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the tool-surface interactions (everything outside the reader) to feel responsive and alive, Notion-style — press feedback, list animations, card lift, sheet content transitions, review celebration, and empty state upgrades.

**Architecture:** All changes are additive ViewModifiers/ButtonStyles and AppMotion tokens. No layout, color, or typography changes. Each task is independently shippable. New tokens go into `AppMetrics.swift`, new modifiers go into existing component files or a new `PressableInteraction.swift`.

**Tech Stack:** SwiftUI (iOS 17+), existing AppMotion/AnyTransition token system in `AppMetrics.swift`, VocabSkin design system.

**Spec:** `docs/superpowers/specs/2026-03-21-visual-polish-notion-style-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `ios/BooksBrowser/Models/AppMetrics.swift` | New AppMotion tokens + AnyTransition extensions |
| Create | `ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift` | `PressableStyle`, `LiftableModifier`, `SwipeActionRow` |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents+Lists.swift` | Upgrade `VocabActionButtonStyle` press feedback |
| Modify | `ios/BooksBrowser/Views/Settings/SettingsPresenter+Controls.swift` | Apply `PressableStyle` to settings buttons |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Components/NotebookRow.swift` | Apply `PressableStyle` |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift` | List animations + swipe actions on WordRow |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/VocabularyListPresenter.swift` | List animations |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift` | Content reveal animation |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift` | Completion celebration |
| Modify | `ios/BooksBrowser/UIComponents/AppSheetModifier.swift` | Sheet content appear transition |
| Modify | `ios/BooksBrowser/UIComponents/AppEmptyStateCard.swift` | `guidanceText` parameter + `.symbolEffect(.breathe)` |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift` | `VocabEmptyStateContent` `guidanceText` passthrough |
| Modify | `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift` | Card lift on BookCard + empty state guidanceText |
| Modify | `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift` | PressableStyle + list animations |

---

## Task 1: Add New AppMotion Tokens

**Files:**
- Modify: `ios/BooksBrowser/Models/AppMetrics.swift:111-171`

- [ ] **Step 1: Add new spring tokens to AppMotion**

In `AppMetrics.swift`, inside `enum AppMotion`, after the existing `swipeTrackingSpring` (around L139), add:

```swift
// --- Visual polish tokens ---
static let pressFeedback: Animation = .spring(response: 0.25, dampingFraction: 0.65)
static let contentReveal: Animation = .spring(response: 0.35, dampingFraction: 0.82)
static let celebrationBounce: Animation = .spring(response: 0.4, dampingFraction: 0.55)
static let sheetContentAppear: Animation = .spring(response: 0.3, dampingFraction: 0.78)
static let swipeRowSnap: Animation = .spring(response: 0.3, dampingFraction: 0.75)
```

- [ ] **Step 2: Add new AnyTransition extensions**

In `AppMetrics.swift`, inside the existing `extension AnyTransition` block (after `listItemFade`, around L171), add:

```swift
static let listInsert: AnyTransition = .opacity.combined(with: .offset(y: 8))
static let listRemove: AnyTransition = .opacity
```

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Models/AppMetrics.swift
git commit -m "ios: add visual polish AppMotion tokens and list transitions"
```

---

## Task 2: Press Feedback — PressableStyle

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift`

- [ ] **Step 1: Create PressableStyle**

Create `PressableInteraction.swift` with:

```swift
import SwiftUI

/// Spring-driven press feedback for buttons. Scale down + opacity dim.
/// For cards, use LiftableModifier instead (scale up + shadow).
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .animation(AppMotion.pressFeedback, value: configuration.isPressed)
            .sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
    }
}

extension ButtonStyle where Self == PressableStyle {
    static var pressable: PressableStyle { PressableStyle() }
}
```

**Note:** The `sensoryFeedback` filter `{ _, newValue in newValue }` ensures haptic only fires on press-down (false→true), not on release (true→false).

- [ ] **Step 2: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift
git commit -m "ios: add PressableStyle button style for spring press feedback"
```

---

## Task 3: Upgrade VocabActionButtonStyle Press Feedback

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents+Lists.swift:160-162`

- [ ] **Step 1: Replace existing subtle press with spring-driven press**

In `VocabActionButtonStyle.makeBody`, replace lines 160-162:

```swift
// Old:
.opacity(configuration.isPressed ? 0.82 : 1)
.scaleEffect(configuration.isPressed ? 0.992 : 1)
.animateControl(configuration.isPressed)
```

With:

```swift
// New:
.scaleEffect(configuration.isPressed ? 0.96 : 1)
.opacity(configuration.isPressed ? 0.85 : 1)
.animation(AppMotion.pressFeedback, value: configuration.isPressed)
.sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
```

**Note:** This replaces the old `.animateControl` (easeOut 0.14s) with a spring-driven press. The `.animateControl` convenience is intentionally bypassed here — the spring provides better tactile feel.

- [ ] **Step 2: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/VocabShellComponents+Lists.swift
git commit -m "ios: upgrade VocabActionButtonStyle to spring press feedback"
```

---

## Task 4: Apply PressableStyle to Settings Buttons and NotebookRow

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/NotebookRow.swift`
- Modify: `ios/BooksBrowser/Views/Settings/SettingsPresenter+Controls.swift:55-68`

- [ ] **Step 1: Apply PressableStyle to NotebookRow's NavigationLink**

In `NotebookListView.swift` (where `NotebookRow` is used, around L53-85), the `NavigationLink` already has `.buttonStyle(.plain)`. Change it to `.buttonStyle(.pressable)`:

```swift
NavigationLink(value: notebook.remoteId) {
    NotebookRow(name: ..., ...)
}
.buttonStyle(.pressable)   // was .plain
```

- [ ] **Step 2: Add press feedback to SettingsButtonChromeModifier**

In `SettingsPresenter+Controls.swift`, modify `SettingsButtonChromeModifier.body` to add press-like interaction. Since this is a `ViewModifier` (not a `ButtonStyle`), the buttons using `.appSettingsButtonChrome()` should instead use `.buttonStyle(.pressable)` at their call site. Find all buttons that use `.appSettingsButtonChrome()` and add `.buttonStyle(.pressable)` to them.

Alternatively, if `SettingsButtonChromeModifier` wraps Button-like views, keep the modifier for styling and add `.pressable` at the `Button` level.

Search for `.appSettingsButtonChrome()` usages:

```bash
grep -rn "appSettingsButtonChrome" ios/BooksBrowser/
```

Apply `.buttonStyle(.pressable)` to each `Button` that uses this modifier.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
git add ios/BooksBrowser/Views/Settings/
git commit -m "ios: apply PressableStyle to notebook rows and settings buttons"
```

---

## Task 5: Card Press Lift — LiftableModifier

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`

- [ ] **Step 1: Add LiftableModifier to PressableInteraction.swift**

Append to `PressableInteraction.swift`:

```swift
/// Shadow constants for LiftableModifier. Extracted per token rules.
private enum LiftShadow {
    static let idleOpacity: Double = 0.06
    static let pressedOpacity: Double = 0.12
    static let idleRadius: CGFloat = 2
    static let pressedRadius: CGFloat = 6
    static let idleY: CGFloat = 1
    static let pressedY: CGFloat = 3
    static let pressedScale: CGFloat = 1.005
}

/// Subtle lift effect for cards. Scale up + shadow deepen on press.
/// For buttons, use PressableStyle instead (scale down + opacity dim).
struct LiftableModifier: ViewModifier {
    @GestureState private var isPressed = false

    func body(content: Content) -> some View {
        content
            .shadow(
                color: .black.opacity(isPressed ? LiftShadow.pressedOpacity : LiftShadow.idleOpacity),
                radius: isPressed ? LiftShadow.pressedRadius : LiftShadow.idleRadius,
                y: isPressed ? LiftShadow.pressedY : LiftShadow.idleY
            )
            .scaleEffect(isPressed ? LiftShadow.pressedScale : 1)
            .animation(AppMotion.pressFeedback, value: isPressed)
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .updating($isPressed) { _, state, _ in state = true }
            )
    }
}

extension View {
    func liftable() -> some View {
        modifier(LiftableModifier())
    }
}
```

- [ ] **Step 2: Apply `.liftable()` to BookCard**

In `BookshelfView.swift`, find the `NavigationLink` wrapping `BookCard` (around L144-162). Add `.liftable()` to the `BookCard`:

```swift
NavigationLink(value: book) {
    BookCard(book: book, coverHeight: coverHeight)
        .liftable()
}
```

- [ ] **Step 3: Apply `.liftable()` to VocabListCard and VocabCard**

Search for `VocabListCard` and `VocabCard` usages across KGVocabPresenter, StatsPresenter, SyncPresenter. Add `.liftable()` to each card container that is tappable (has `onTapGesture` or is inside a `NavigationLink`).

**Note:** Only apply to cards that are interactive (tappable). Static display-only cards should not lift.

- [ ] **Step 4: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift
git add ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/
git commit -m "ios: add LiftableModifier card press lift to BookCard and VocabCards"
```

---

## Task 6: List Animations

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift:72-115`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/VocabularyListPresenter.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift`

- [ ] **Step 1: Add list transitions to KGVocabPresenter**

In `KGVocabPresenter.swift`, find the `ForEach` rendering `WordRow` items (around L85-100). Add transitions:

```swift
ForEach(Array(state.rows.enumerated()), ...) { index, item in
    HStack {
        // existing content...
        WordRow(viewData: item.row)
            // existing modifiers...
    }
    .transition(.asymmetric(insertion: .listInsert, removal: .listRemove))
    // existing padding and divider...
}
```

Also ensure the parent container animates sort changes by finding where `state.rows` is derived and wrapping the state change in `withAnimation(AppMotion.listReorder)`.

- [ ] **Step 2: Add list transitions to VocabularyListPresenter**

Apply the same `.transition(.asymmetric(insertion: .listInsert, removal: .listRemove))` pattern to `WordRow` items in `VocabularyListPresenter`.

- [ ] **Step 3: Add list transitions to NotebookListView**

In `NotebookListView.swift`, find the `ForEach(notebooks)` rendering `NotebookRow` items. Add the same transition pattern:

```swift
ForEach(notebooks) { notebook in
    NavigationLink(value: notebook.remoteId) {
        NotebookRow(...)
    }
    .buttonStyle(.pressable)
    .transition(.asymmetric(insertion: .listInsert, removal: .listRemove))
    // existing contextMenu...
}
```

- [ ] **Step 4: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/VocabularyListPresenter.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
git commit -m "ios: add insertion/deletion/reorder animations to word lists"
```

---

## Task 7: Stats Content Reveal Animation

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift:40-61`

- [ ] **Step 1: Add content reveal to StatsPresenter**

`StatsPresenter` already uses `VocabSceneShell(phase:)` with `.animatePhaseChange(summary != nil)` which provides a basic phase animation. To add a richer reveal, wrap the `ScrollView` content in a state-driven opacity+scale transition.

In `StatsPresenter.swift`, add a `@State private var contentReady = false` property and modify the body:

```swift
@State private var contentReady = false

// Inside body, replace:
if let summary {
    ScrollView { ... }
        .vocabCanvasBackground()
}

// With:
if let summary {
    ScrollView { ... }
        .vocabCanvasBackground()
        .opacity(contentReady ? 1 : 0)
        .scaleEffect(contentReady ? 1 : 0.98)
        .onAppear {
            withAnimation(AppMotion.contentReveal) {
                contentReady = true
            }
        }
}
```

- [ ] **Step 2: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/StatsPresenter.swift
git commit -m "ios: add content reveal animation to stats presenter"
```

---

## Task 8: Review Completion Celebration

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift:189-202`

- [ ] **Step 1: Add celebration animation to completionState**

In `TodayReviewPresenter.swift` (which is a `struct: View`), add `@State private var celebrationTriggered = false` as a **top-level stored property** of the struct (next to the other `@State` properties). Then modify the `completionState` computed property (around L189-202):

```swift
// Add this as a stored property on the struct (NOT inside completionState):
@State private var celebrationTriggered = false

// Then modify the computed property:
var completionState: some View {
    VStack(spacing: vocabSkin.metrics.cardBlockPadding) {
        Spacer()
        VocabEmptyStateContent(
            title: "今天複習完成".localized,
            systemImage: "checkmark.circle",
            description: "這一輪 session 的卡片都處理完了。".localized
        )
        .scaleEffect(celebrationTriggered ? 1 : 0.8)
        .opacity(celebrationTriggered ? 1 : 0)
        .onAppear {
            withAnimation(AppMotion.celebrationBounce) {
                celebrationTriggered = true
            }
        }
        Button("返回單字本".localized, action: onClose)
            .buttonStyle(.ghost(vocabSkin.palette.primaryText))
        Spacer()
    }
    .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
    .sensoryFeedback(.success, trigger: celebrationTriggered)
}
```

Also add `.symbolEffect(.bounce, value: celebrationTriggered)` to the checkmark icon inside `VocabEmptyStateContent`. Since `VocabEmptyStateContent` doesn't expose the Image directly, this requires either:
- (a) Adding a `symbolEffect` parameter to `VocabEmptyStateContent`, or
- (b) Applying `.symbolEffect` at the `AppEmptyStateContent` level with a binding

The simpler approach is (b): modify `AppEmptyStateContent` to accept an optional `symbolEffectTrigger: Bool = false` and apply `.symbolEffect(.bounce, value: symbolEffectTrigger)` to the Image. Then thread it through `VocabEmptyStateContent`.

- [ ] **Step 2: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift
git add ios/BooksBrowser/UIComponents/AppEmptyStateCard.swift
git add ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift
git commit -m "ios: add celebration bounce animation on review completion"
```

---

## Task 9: Sheet Content Appear Transition

**Files:**
- Modify: `ios/BooksBrowser/UIComponents/AppSheetModifier.swift`

- [ ] **Step 1: Add content appear animation to AppSheetModifier**

In `AppSheetModifier.swift`, add a state-driven content reveal inside the modifier. The sheet content should fade+scale in after the system slide-up:

```swift
private struct AppSheetModifier: ViewModifier {
    let preset: AppSheetPreset
    @State private var contentVisible = false

    func body(content: Content) -> some View {
        Group {
            switch preset {
            case .large:
                content
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            case .medium:
                content.presentationDetents([.medium])
            case .adaptive:
                content
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
            }
        }
        .opacity(contentVisible ? 1 : 0)
        .scaleEffect(contentVisible ? 1 : 0.97)
        .onAppear {
            withAnimation(AppMotion.sheetContentAppear) {
                contentVisible = true
            }
        }
    }
}
```

- [ ] **Step 2: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/UIComponents/AppSheetModifier.swift
git commit -m "ios: add branded content appear transition to all app sheets"
```

---

## Task 10: Empty State Upgrade

**Files:**
- Modify: `ios/BooksBrowser/UIComponents/AppEmptyStateCard.swift:14-46`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift:95-109`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`

- [ ] **Step 1: Add guidanceText and symbolEffect to AppEmptyStateContent**

In `AppEmptyStateCard.swift`, modify `AppEmptyStateContent`:

```swift
struct AppEmptyStateContent: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String
    let guidanceText: String?       // NEW
    let customStyle: AppEmptyStateStyle?

    init(
        title: String,
        systemImage: String,
        description: String,
        guidanceText: String? = nil,    // NEW, default nil
        style: AppEmptyStateStyle? = nil
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.guidanceText = guidanceText    // NEW
        self.customStyle = style
    }

    var body: some View {
        let style = customStyle ?? .themed(appTheme)
        VStack(spacing: style.spacing) {
            Image(systemName: systemImage)
                .font(style.iconFont)
                .foregroundStyle(style.iconColor)
                .symbolEffect(.breathe)         // NEW
            Text(title.localized)
                .font(style.titleFont)
                .foregroundStyle(style.titleColor)
            Text(description.localized)
                .font(style.descriptionFont)
                .foregroundStyle(style.descriptionColor)
                .multilineTextAlignment(.center)
            if let guidanceText {               // NEW
                Text(guidanceText.localized)
                    .font(style.descriptionFont)
                    .foregroundStyle(style.descriptionColor.opacity(0.7))
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
    }
}
```

- [ ] **Step 2: Thread guidanceText through VocabEmptyStateContent**

In `VocabSkinComponents.swift`, modify `VocabEmptyStateContent`:

```swift
struct VocabEmptyStateContent: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let systemImage: String
    let description: String
    let guidanceText: String?       // NEW

    init(
        title: String,
        systemImage: String,
        description: String,
        guidanceText: String? = nil     // NEW
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.guidanceText = guidanceText
    }

    var body: some View {
        AppEmptyStateContent(
            title: title,
            systemImage: systemImage,
            description: description,
            guidanceText: guidanceText,     // NEW
            style: .vocab(vocabSkin)
        )
    }
}
```

- [ ] **Step 3: Add guidance text to bookshelf empty state**

In `BookshelfView.swift`, find the `AppEmptyStateContent` usage in the empty state and add:

```swift
AppEmptyStateContent(
    title: /* existing */,
    systemImage: /* existing */,
    description: /* existing */,
    guidanceText: "點擊上方匯入按鈕加入你的第一本書"
)
```

- [ ] **Step 4: Add guidance text to review completion**

In `TodayReviewPresenter.swift`, update the `VocabEmptyStateContent` in `completionState` (already modified in Task 8):

```swift
VocabEmptyStateContent(
    title: "今天複習完成".localized,
    systemImage: "checkmark.circle",
    description: "這一輪 session 的卡片都處理完了。".localized,
    guidanceText: "明天再來複習新到期的單字".localized
)
```

- [ ] **Step 5: Add guidance text to KGVocabView empty filter results**

In `KGVocabPresenter.swift`, find where `VocabEmptyStateContent` is used for empty filter results. Add `guidanceText`:

```swift
VocabEmptyStateContent(
    title: /* existing */,
    systemImage: /* existing */,
    description: /* existing */,
    guidanceText: "嘗試切換篩選條件或新增單字"
)
```

- [ ] **Step 6: Add guidance text to NotebookListView empty state (if applicable)**

In `NotebookListView.swift`, check if there is an empty state when no notebooks exist. If so, add appropriate `guidanceText`.

- [ ] **Step 7: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

**Note:** `AppEmptyStateCard` (the card-styled wrapper) is intentionally not upgraded with `guidanceText` — it's a style container. Callers that need guidance text should use `AppEmptyStateContent` or `VocabEmptyStateContent` directly.

- [ ] **Step 8: Commit**

```bash
git add ios/BooksBrowser/UIComponents/AppEmptyStateCard.swift
git add ios/BooksBrowser/Views/Vocabulary/Components/VocabSkinComponents.swift
git add ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/NotebookListView.swift
git commit -m "ios: upgrade empty states with breathing icons and guidance text"
```

---

## Task 11: List Swipe Actions — SwipeActionRow

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift`

- [ ] **Step 1: Add SwipeActionRow modifier to PressableInteraction.swift**

This is the most complex item. Since `WordRow` lives in `LazyVStack` (not `List`), native `.swipeActions` won't work. Build a custom gesture-based swipe row:

```swift
struct SwipeActionRow<Leading: View, Trailing: View>: ViewModifier {
    @ViewBuilder let leading: Leading
    @ViewBuilder let trailing: Trailing

    @State private var offset: CGFloat = 0
    @GestureState private var dragOffset: CGFloat = 0

    private let threshold: CGFloat = 80

    func body(content: Content) -> some View {
        ZStack {
            // Leading action (revealed on right swipe)
            HStack {
                leading
                    .frame(width: threshold)
                Spacer()
            }

            // Trailing action (revealed on left swipe)
            HStack {
                Spacer()
                trailing
                    .frame(width: threshold)
            }

            // Main content
            content
                .offset(x: offset + dragOffset)
                .gesture(
                    DragGesture()
                        .updating($dragOffset) { value, state, _ in
                            // Rubber-band effect past threshold
                            let translation = value.translation.width
                            if abs(translation) > threshold {
                                let excess = abs(translation) - threshold
                                let dampened = threshold + excess * 0.3
                                state = translation > 0 ? dampened : -dampened
                            } else {
                                state = translation
                            }
                        }
                        .onEnded { value in
                            let translation = value.translation.width
                            if abs(translation) > threshold {
                                // Snap open
                                withAnimation(AppMotion.swipeRowSnap) {
                                    offset = translation > 0 ? threshold : -threshold
                                }
                            } else {
                                // Snap back
                                withAnimation(AppMotion.swipeRowSnap) {
                                    offset = 0
                                }
                            }
                        }
                )
                .onChange(of: offset) { _, newValue in
                    // Auto-close after action tap via external reset
                    if newValue == 0 { return }
                }
        }
        .clipped()
    }
}

extension View {
    func swipeActions(
        @ViewBuilder leading: () -> some View,
        @ViewBuilder trailing: () -> some View
    ) -> some View {
        modifier(SwipeActionRow(leading: leading(), trailing: trailing()))
    }
}
```

- [ ] **Step 2: Apply swipe actions to WordRow in KGVocabPresenter**

In `KGVocabPresenter.swift`, wrap each `WordRow` (inside the `HStack`) with `.swipeActions`:

```swift
HStack {
    WordRow(viewData: item.row)
        .contentShape(Rectangle())
        .onTapGesture { ... }
        .onLongPressGesture { ... }
}
.swipeActions {
    Button {
        // archive action
    } label: {
        Label("封存", systemImage: "archivebox")
    }
    .tint(vocabSkin.palette.secondaryText)
} trailing: {
    Button {
        // quick review action
    } label: {
        Label("複習", systemImage: "arrow.clockwise")
    }
    .tint(vocabSkin.palette.accent)
}
```

**Important:** Wire the archive button to the existing archive logic and the review button to the existing review-scheduling logic. Check `KGVocabPresenter` for existing archive/review callbacks.

- [ ] **Step 3: Build and verify**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Manual test**

Open the app in simulator, go to the vocabulary list (KG Vocab), and test:
- Left swipe reveals "Quick Review" button
- Right swipe reveals "Archive" button
- Partial swipe snaps back
- Full swipe snaps open
- Tapping action button triggers the action

- [ ] **Step 5: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/PressableInteraction.swift
git add ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift
git commit -m "ios: add custom swipe actions to word rows in vocabulary list"
```

---

## Task 12: Final Build + Smoke Test

- [ ] **Step 1: Full build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 2: Manual smoke test checklist**

Open the app in simulator and verify each item:

1. Press any `.vocabAction` button — should scale down 0.96 + spring back
2. Press a notebook row — should scale down + spring back
3. Press a BookCard — should subtly lift (shadow deepen)
4. Open any sheet (WordDetailSheet) — content should fade+scale in
5. Go to Stats — content should reveal with opacity+scale animation
6. Complete a review session — checkmark should bounce + scale overshoot
7. Empty bookshelf — icon should gently breathe + guidance text visible
8. In KG vocab list — swipe a word row left/right to see actions

- [ ] **Step 3: Commit any fixes**

If any fixes were needed during smoke testing, commit them.

<!-- doc-meta
tier: archive
authority: derived
update_trigger: design-decision
scope:
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackMetrics.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookPalette.swift
  - ios/BooksAndVocab/Debug/Scenarios/NotebookListScenarios.swift
verified_against: frozen
-->
# Notebook Editorial Stack Implementation Plan

> **執行方式:** 使用 phased-workflow skill，所有 agent 皆 opus。
> **Spec:** `docs/specs/2026-05-23-notebook-editorial-stack-design.md`
> **Branch:** `refine-notebook-deck-aesthetics`

**Goal:** 把 Notebook 立體堆卡從「同色 darken 階梯」升級為「Morandi 彩色封面 + cream 紙頁」editorial 視覺，加入 deterministic 微旋轉 + edge jitter 帶入手感。同步把 `NotebookPalette` 12 色 swap 為 Morandi "Clearly Brighter" 色卡，並對老 notebook hex 做 render-time legacy migration。

**Architecture:**
- Token 層：`NotebookStackMetrics` 新增 `ghostPaperColor` / `seedJitter` / rotation tables；deprecate `deckColor` (brightness-based)
- View 層：`NotebookStackedCoverView` 接 `seed: Int`，每層套 rotation + jitter + cream paper color + hairline；rotation 套整層（cover 含 pill 一起轉）
- 互動層：press 物理不變（既有 `NotebookDeckButtonStyle`），rotation 不參與動畫
- `NotebookCard` 傳 seed（`data.name.hashValue`）、加 cover↔metadata hairline rule、AddCard editorial restyle

**Tech Stack:** SwiftUI、既有 `AppColors` / `AppSkin` / `AppElevation` / `AppSpacing` tokens；無新依賴。

**Verification 哲學:** SwiftUI 視覺改動 — 每個 Task 完成以 `./ops/ios_build.sh` 編譯通過為硬門檻；視覺正確性由 `NotebookListScenarios` previews + 模擬器手動驗證（Task 7 集中）。**不信 4s 快速 success**（PR #573 教訓）— 強制 clean build 才信。

---

## Task 0: Morandi palette swap + legacy migration

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookPalette.swift`

- [ ] **Step 1: 替換 12 色 hex（中文名稱不變）**
```swift
static let colors: [(name: String, hex: String)] = [
    ("森林", "#B1C5AE"), ("海洋", "#AFC2D3"),
    ("琥珀", "#DEC69C"), ("紫藤", "#C5B2D0"),
    ("珊瑚", "#DCABA4"), ("石墨", "#AFB2B7"),
    ("薄荷", "#B7D2C9"), ("靛藍", "#ADABCB"),
    ("玫瑰", "#DEBAC2"), ("焦糖", "#D2B69D"),
    ("天空", "#C5DAE2"), ("薰衣草", "#C3BCCF"),
]

static let defaultHex = "#AFC2D3"  // 海洋 Dusty Blue → 新 default
```

- [ ] **Step 2: 加 legacy migration map + 改 color(for:) 套用**
```swift
private static let legacyMigration: [String: String] = [
    "#5B8C5A": "#B1C5AE", "#4A90D9": "#AFC2D3",
    "#D4A843": "#DEC69C", "#A855C7": "#C5B2D0",
    "#D9534F": "#DCABA4", "#6B7280": "#AFB2B7",
    "#5CC6B0": "#B7D2C9", "#4F46E5": "#ADABCB",
    "#E8789A": "#DEBAC2", "#B8763E": "#D2B69D",
    "#7CB9E8": "#C5DAE2", "#9B8EC4": "#C3BCCF",
]

static func color(for hex: String?) -> Color {
    guard let raw = hex else { return Color(hex: defaultHex) ?? .blue }
    let mapped = legacyMigration[raw.uppercased()] ?? raw
    return Color(hex: mapped) ?? Color(hex: defaultHex) ?? .blue
}
```
注意：DB 不寫回老 hex，純 render-time 替換。User 下次改 cover、UI 會寫新 hex。

- [ ] **Step 3: grep 其他 callsite 確認無破壞**
```bash
grep -rn "NotebookPalette\|#5B8C5A\|#4A90D9\|#D4A843" ios/BooksAndVocab --include="*.swift"
```
預期：`NotebookEditSheet` / `BookshelfView` / `PodcastEpisodeListView` / `NotebookCard` 只 reference `NotebookPalette.colors` 或 `.color(for:)`，無 hardcoded 舊 hex。**若有 hardcoded 同步更新**。

- [ ] **Step 4: 編譯**
Run: `./ops/ios_build.sh`
Expected: success

- [ ] **Step 5: Commit**
`feat(ios): notebook palette → morandi clearly-brighter + legacy hex migration`

---

## Task 1: NotebookStackMetrics token surface

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackMetrics.swift`

- [ ] **Step 1: 加 cream paper palette helper**
新增 static method：
```swift
/// Ghost cream 紙頁三階 — index = depth (1/2/3)
static func ghostPaperColor(depth: Int, scheme: ColorScheme) -> Color {
    _ = scheme  // dark variant 待下輪 design；保留參數簽名以利之後 swap-in，silence unused warning
    switch depth {
    case 1:  return AppColors.paperLight
    case 2:  return AppColors.paperSepia
    default: return AppColors.paperSepiaDeep  // depth >= 3
    }
}
```
Dark mode 暫不分流（spec 已寫「ghost 套 dark cream variant（待 design check）」— 此 plan 先 light/dark 同色，下一輪 design 再決定 dark variant）。

- [ ] **Step 2: 加 rotation / jitter tables + seedJitter**
```swift
/// 每層基準 rotation（index = depth，0 = cover top）— deg
static let layerRotations: [Double] = [0.5, -0.8, 1.5, -1.5]
/// 每層 dx 額外 jitter（在 layerInsetX 之外）— pt
static let layerDxJitter: [CGFloat] = [0, 0.5, -1, 1]
/// Rotation overhang 保守常數（典型 cover ~160pt × sin(1.5°) ≈ 4.2pt，8pt = 2× 安全邊際）
static let rotationOverhang: CGFloat = AppSpacing.s2

/// Per-notebook deterministic jitter — seed 由 caller 傳入（notebook ID/name hash）
/// 同一 seed × 同一 depth 永遠回傳同一 (angle, dx)
static func seedJitter(seed: Int, depth: Int) -> (angle: Double, dx: CGFloat) {
    let idx = min(depth, layerRotations.count - 1)
    let baseAngle = layerRotations[idx]
    let baseDx = layerDxJitter[idx]
    // perturb ∈ [-0.5, +0.5]，依 seed × depth 決定（同一 seed 各 depth 不同擾動）
    let perturb = Double((seed &+ depth &* 31) % 100) / 100.0 - 0.5
    return (
        angle: baseAngle * (1.0 + perturb * 0.5),
        dx:    baseDx * (1.0 + CGFloat(perturb) * 0.5)
    )
}
```

- [ ] **Step 3: Deprecate brightness-based deck color**
保留 `deckColor(_:depth:scheme:)` 簽名以避免外部 callsite 立即壞（雖然只有 `NotebookStackedCoverView` 一處），加 `@available(*, deprecated, message: "Use ghostPaperColor — editorial stack switched to cream paper ghosts")` 標記。
保留 `brightnessStepLight` / `brightnessStepDark` const（forwarded by 舊 deckColor）— 同一 commit 內 view 層改完後 Task 6 集中清除。

- [ ] **Step 4: 編譯通過**
Run: `./ops/ios_build.sh`
Expected: success（無 callsite 改動，仍能編）。**若 4s 完成 + log 顯示 incremental cache，rm -rf build cache 重跑**。

- [ ] **Step 5: Commit**
`feat(ios): notebook stack metrics — cream paper + seed jitter tokens`

---

## Task 2: NotebookStackedCoverView 重寫 ghost 層

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift`

- [ ] **Step 1: View 簽名加 seed 參數**
```swift
struct NotebookStackedCoverView: View {
    let color: Color
    let pattern: NotebookCoverPattern?
    let coverImagePath: String?
    let name: String
    let layerCount: Int
    let aspectRatio: CGFloat
    let seed: Int  // 新增 — 由 NotebookCard 傳入 name.hashValue
    // ...
}
```

- [ ] **Step 2: ghost 改用 cream paper + rotation + jitter**
替換現有 `ghostLayer(depth:)`：
```swift
@ViewBuilder
private func ghostLayer(depth: Int) -> some View {
    let baseInset = NotebookStackMetrics.layerInsetX * CGFloat(depth)
    let baseDy = NotebookStackMetrics.layerOffsetY * CGFloat(depth)
    let jitter = NotebookStackMetrics.seedJitter(seed: seed, depth: depth)
    let pressBoost = isPressed && !reduceMotion
        ? NotebookStackMetrics.pressedGhostOffsetY * CGFloat(depth)
        : 0

    RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
        .fill(NotebookStackMetrics.ghostPaperColor(depth: depth, scheme: colorScheme))
        .overlay(
            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                .stroke(skin.palette.cardBorder, lineWidth: AppMetrics.dividerThin)
        )
        .padding(.horizontal, baseInset + jitter.dx)
        .offset(y: baseDy + pressBoost)
        .rotationEffect(.degrees(jitter.angle), anchor: .bottom)
        .appElevation(isPressed ? .z2 : .z1)
        .accessibilityHidden(true)
}
```
注意：`@Environment(\.appSkin)` 已在現有 file 用到（press button style），確認 view 內可拿到 — 否則加 `@Environment(\.appSkin) private var skin`。

- [ ] **Step 3: Top cover 套 rotation + hairline**
頂層原 `NotebookCoverView` 加：
```swift
.clipShape(UnevenRoundedRectangle(
    topLeadingRadius: AppRadius.md,
    bottomLeadingRadius: 0,
    bottomTrailingRadius: 0,
    topTrailingRadius: AppRadius.md,
    style: .continuous
))
.overlay(
    UnevenRoundedRectangle(
        topLeadingRadius: AppRadius.md,
        bottomLeadingRadius: 0,
        bottomTrailingRadius: 0,
        topTrailingRadius: AppRadius.md,
        style: .continuous
    )
    .stroke(skin.palette.cardBorder, lineWidth: AppMetrics.dividerThin)
)
.appElevation(.z2)
.offset(y: isPressed && !reduceMotion ? NotebookStackMetrics.pressedTopOffsetY : 0)
.scaleEffect(isPressed && !reduceMotion ? AppMotion.TapFeedback.scaleDown : 1.0, anchor: .center)
.rotationEffect(.degrees(NotebookStackMetrics.seedJitter(seed: seed, depth: 0).angle), anchor: .bottom)
```

- [ ] **Step 4: 調 padding 預留 rotation overhang**
```swift
.aspectRatio(aspectRatio, contentMode: .fit)
.padding(.bottom, maxGhostDy + NotebookStackMetrics.rotationOverhang)
.padding(.horizontal, NotebookStackMetrics.rotationOverhang)
```

- [ ] **Step 5: 編譯（強制清 cache）**
Run: `rm -rf ~/Library/Developer/Xcode/DerivedData/BooksAndVocab-* && ./ops/ios_build.sh`
Expected: success。若仍 4s — 走 Xcode GUI build 確認。

- [ ] **Step 6: Commit**
`feat(ios): notebook stacked cover — cream ghosts + editorial rotation`

---

## Task 3: NotebookCard wire seed + cover↔metadata rule + pill 隨轉

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`

- [ ] **Step 1: 傳 seed**
`coverArea` 內 `.grid` 分支：
```swift
NotebookStackedCoverView(
    color: coverColor,
    pattern: pattern,
    coverImagePath: data.coverImagePath,
    name: data.name,
    layerCount: NotebookStackMetrics.layerCount(forCardCount: data.cardCount),
    aspectRatio: coverAspectRatio,
    seed: data.name.hashValue  // ← 新增
)
```

- [ ] **Step 2: Pill 隨 cover rotation 一起轉**

**修正 Task 2 Step 3**：top cover 內部不套 rotation（從 Task 2 Step 3 移除該 `.rotationEffect`）。

理由：pill overlay 在 `NotebookCard.coverArea` 外層，rotation 套在 cover 內部 pill 不會跟著轉，會脫離卡片邊界。

落地：rotation 上提到 `coverArea` 結尾，包 pill overlay 一起：
```swift
// NotebookCard.coverArea 結尾（pill overlay 之後）
.rotationEffect(
    .degrees(NotebookStackMetrics.seedJitter(seed: data.name.hashValue, depth: 0).angle),
    anchor: .bottom
)
```
view API 不變、ghost 內部 rotation 仍各自獨立。

- [ ] **Step 3: Cover↔metadata hairline rule**
`body` 內：
```swift
VStack(alignment: .leading, spacing: 0) {
    coverArea

    // ★ 新增 editorial divider
    Rectangle()
        .fill(skin.palette.cardBorder)
        .frame(height: AppMetrics.dividerStandard)

    metadataArea
        .padding(.horizontal, skin.spacing.cardPadding)
        .padding(.vertical, skin.spacing.cardPadding * 0.8)
}
```

- [ ] **Step 4: 編譯**
Run: `rm -rf ~/Library/Developer/Xcode/DerivedData/BooksAndVocab-* && ./ops/ios_build.sh`
Expected: success

- [ ] **Step 5: Commit**
`feat(ios): notebook card — seed pass-through + editorial rule + pill 隨 rotation`

---

## Task 4: NotebookAddCard editorial restyle

**Files:**
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`（同檔下半段）

- [ ] **Step 0: 確認 "新增單字本" L10n key 已存在**
```bash
grep -rn "新增單字本" ios/BooksAndVocab/Resources/
```
應 hit `Localizable.strings`。若 miss → 加 key 或改用既有等價 key。避免 `i18n_lint.sh` failure。

- [ ] **Step 1: 重寫 body**
```swift
struct NotebookAddCard: View {
    @Environment(\.appSkin) private var skin

    var body: some View {
        VStack(spacing: skin.spacing.inlineGap) {
            Image(systemName: "plus")
                .font(.system(size: 18, weight: .regular))
                .foregroundStyle(skin.palette.tertiaryText)
                .frame(width: 36, height: 36)
                .overlay(
                    Circle().strokeBorder(skin.palette.cardBorder, lineWidth: 1)
                )
            Text("新增單字本".localized)
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.tertiaryText)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .aspectRatio(LayoutMode.notebookCardAspectRatio, contentMode: .fit)
        .background(AppColors.paperLight)   // ← 從 cardBackground 改 paperLight
        .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous)
                .strokeBorder(skin.palette.cardBorder, lineWidth: 1)  // dashed → solid
        )
    }
}
```

- [ ] **Step 2: 編譯**
Run: `./ops/ios_build.sh`
Expected: success

- [ ] **Step 3: Commit**
`feat(ios): notebook add card — solid hairline + cream + ringed plus`

---

## Task 5: Scenarios + token cleanup

**Files:**
- Modify: `ios/BooksAndVocab/Debug/Scenarios/NotebookListScenarios.swift`
- Modify: `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackMetrics.swift`

- [ ] **Step 1: NotebookListScenarios 加 editorial state cases**
新增 / 補齊：
- `editorialStack_0/30/100/500` 字本（4 種 layer count）
- `editorialStack_addCardAlignment`（真實 + add 並列高度齊）
- `editorialStack_dark`（dark mode 全 layer count）
- `editorialStack_a11y3`（Dynamic Type accessibility3）
- `editorialStack_pillRotation`（active notebook pill 隨 rotation）

- [ ] **Step 2: 移除 deprecated brightness 路徑**
View 層已全切 cream paper → 從 `NotebookStackMetrics` 刪：
- `brightnessStepLight`
- `brightnessStepDark`
- `deckColor(_:depth:scheme:)`
- `Color.shiftingBrightness(by:)` extension（若無其他 callsite — grep 確認）

確認 grep 無外部 callsite：
```bash
grep -rn "deckColor\|shiftingBrightness\|brightnessStep" ios/BooksAndVocab
```
應只剩 NotebookStackMetrics 自身。

- [ ] **Step 3: 編譯**
Run: `rm -rf ~/Library/Developer/Xcode/DerivedData/BooksAndVocab-* && ./ops/ios_build.sh`
Expected: success

- [ ] **Step 4: Commit**
`refactor(ios): drop brightness-based deck color + add editorial scenarios`

---

## Task 6: 模擬器手動驗證 + Doc 同步

**Files:**
- Modify: `docs/sop/ui-design.md`
- Modify: `docs/reference/feature_boundary/notebook.md`
- Modify: `docs/reference/ui/components.md`
- Modify: `docs/reference/ui/state_matrix.md`

- [ ] **Step 1: 模擬器逐 case 驗證**（spec Verification 全項）：
  - 兩本並列（左有資料、右 0 字）：高度齊、底部無空白
  - 同本 reload 多次：rotation/jitter 完全一致（deterministic seed）
  - 不同本：rotation 視覺隨機
  - Cream 三階 ghost 可辨（paperLight → Sepia → SepiaDeep）
  - Cover↔metadata hairline rule 可見但克制
  - AddCard 與真實卡同 row 高度一致、cream paperLight 同語言
  - Press：top 抽出 + ghost 微下沉、rotation 不變
  - Active pill：與 cover 一起轉、不脫離卡片邊界
  - Dark mode：cream 仍可辨、hairline 不糊
  - VoiceOver：每本只念一次
  - Reduce Motion：rotation 在、press 物理關
  - Dynamic Type a11y3：metadata 不溢出
  - 鍵盤 Return：push 不跑 press-in

- [ ] **Step 2: `docs/sop/ui-design.md`**
新增 §「editorial imperfection / static rotation」段：
- 規則：rotation 屬 layout 非 motion 時，Reduce Motion **不關**
- 條件：rotation 在 mount 後不再變動（純視覺、非動畫）
- 案例：`NotebookStackedCoverView` editorial stack rotation
- Motion table 不動（這不是 motion token）

- [ ] **Step 3: `docs/reference/feature_boundary/notebook.md`**
- 元件清單 `NotebookStackedCoverView` 行數 drift 重算
- 新增「Cream paper ghost + editorial rotation」段落，引用 spec path

- [ ] **Step 4: `docs/reference/ui/components.md`**
更新 `NotebookStackedCoverView` 條目：seed param、cream ghost、editorial rotation

- [ ] **Step 5: `docs/reference/ui/state_matrix.md`**
更新 Notebook stack state 表（與 spec State 矩陣同步）

- [ ] **Step 6: `ops/docs_lint.sh`** 通過 / `ops/i18n_lint.sh` 通過

- [ ] **Step 7: Commit**
`docs: notebook editorial stack — RM precedent + state matrix + boundary sync`

---

## Final: PR

- [ ] Push branch、開 PR、貼 spec + plan 連結
- [ ] PR template doc-sync 段：勾選 ui-design / feature_boundary / components / state_matrix
- [ ] 等 user merge

---

## Critical reminders

- **不信 4s 快速 success** — PR #573 教訓，Task 2/3/6 強制清 DerivedData
- **`lab/` 不碰** — user 並行修改中
- **逐 Task review** — 每 commit 後 dispatch opus code-reviewer 對照 spec / plan，PASS 才下一個（鐵律 4）
- **不主動跑 `ios_test.sh`**（鐵律：iOS 編譯 only via `ios_build.sh`）
- **commit prefix `ios:` / `docs:`**（per workspace `CLAUDE.md`）

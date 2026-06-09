<!-- doc-meta
tier: reference
authority: derived
update_trigger: design-decision
scope:
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackMetrics.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookPalette.swift
verified_against: HEAD
-->
# Notebook Editorial Stack — Design Spec

## Context

Notebooks 列表頁的「立體堆卡」首版（PR #571 / #573）視覺仍偏「色塊向下延伸的色階階梯」，使用者反饋「不像真的卡片在 stacking」，並指定走 editorial / Anthropic 風（cream、serif、hairline、克制、有手感）。

本 spec 把堆卡視覺從 **同色 darken 階梯** 升級為 **彩色封面 + cream 紙頁的 notebook 隱喻**，加入微旋轉與邊緣 jitter 帶入手感，但全程使用 codebase 已存在的 token 詞彙（`paperLight` / `paperSepia` / `AppFonts.serif` / `dividerThin` / `AppElevation`），不發明新的命名空間。

## Goals

1. Ghost 層讀起來是「notebook 內頁」而非「同色另一張卡」
2. 整疊有「桌上隨手放」的手感，**不是**精密對齊
3. 手感**克制**到 editorial 程度（遠看似對齊、湊近才看出歪）
4. Press 互動維持既有物理（top 抽出 + ghost 微下沉），**不**加 rotation 動畫
5. 0 字 notebook 平面單卡也吸收同套 editorial 細節（hairline、cover↔metadata rule）

## Morandi Palette Swap（同 PR）

現有 `NotebookPalette.colors` 12 色（森林 #5B8C5A / 海洋 #4A90D9 / ...）為中高飽和，與 cream ghost 並列會產生「彩色封面 + 米白內頁」的撕裂感。本 spec 同步把 palette 替換為 Morandi 低飽和色卡（HSB sat 13-30% / bright 67-86%），與 cream ghost 收進同一視覺族群。

### 最終 hex（已與使用者對齊 — 比初版 Morandi 亮一階「Clearly Brighter」）

| 中文名 | EN | 新 hex | 舊 hex |
|---|---|---|---|
| 森林 | Sage | `#B1C5AE` | `#5B8C5A` |
| 海洋 | Dusty Blue | `#AFC2D3` | `#4A90D9` |
| 琥珀 | Sand | `#DEC69C` | `#D4A843` |
| 紫藤 | Dusty Mauve | `#C5B2D0` | `#A855C7` |
| 珊瑚 | Terra Rose | `#DCABA4` | `#D9534F` |
| 石墨 | Warm Stone | `#AFB2B7` | `#6B7280` |
| 薄荷 | Dusty Mint | `#B7D2C9` | `#5CC6B0` |
| 靛藍 | Dusty Indigo | `#ADABCB` | `#4F46E5` |
| 玫瑰 | Dusty Rose | `#DEBAC2` | `#E8789A` |
| 焦糖 | Dusty Caramel | `#D2B69D` | `#B8763E` |
| 天空 | Dusty Sky | `#C5DAE2` | `#7CB9E8` |
| 薰衣草 | Dusty Lavender | `#C3BCCF` | `#9B8EC4` |

### Migration 策略：auto swap

老 notebook DB 存的是 hex 字串，不是 token name。需在 `NotebookPalette.color(for:)` 加 hex 轉換 map：

```swift
private static let legacyMigration: [String: String] = [
    "#5B8C5A": "#B1C5AE",  // 森林
    "#4A90D9": "#AFC2D3",  // 海洋
    "#D4A843": "#DEC69C",  // 琥珀
    "#A855C7": "#C5B2D0",  // 紫藤
    "#D9534F": "#DCABA4",  // 珊瑚
    "#6B7280": "#AFB2B7",  // 石墨
    "#5CC6B0": "#B7D2C9",  // 薄荷
    "#4F46E5": "#ADABCB",  // 靛藍
    "#E8789A": "#DEBAC2",  // 玫瑰
    "#B8763E": "#D2B69D",  // 焦糖
    "#7CB9E8": "#C5DAE2",  // 天空
    "#9B8EC4": "#C3BCCF",  // 薰衣草
]

static func color(for hex: String?) -> Color {
    guard let raw = hex else { return Color(hex: defaultHex) ?? .blue }
    let normalized = raw.uppercased()
    let mapped = legacyMigration[normalized] ?? raw
    return Color(hex: mapped) ?? Color(hex: defaultHex) ?? .blue
}
```

- 不寫 DB，純 render-time 替換（讀 DB 老 hex → render 新 hex）
- 後續 user 改 cover 時，UI 寫回 DB 自然會是新 hex
- 零感知 migration、無風險

### 影響範圍

- `NotebookPalette.swift` — hex 表 + legacy migration
- `NotebookEditSheet` color picker — 自動拿新 hex，layout 不變（12 色仍 3×4 / 4×3 grid）
- `BookshelfView` / `PodcastEpisodeListView` — 若 reference NotebookPalette 也自動切（grep 確認用法）

### 新名（advisory）

中文名是否同步改為 EN？目前 picker UI 顯示中文（如「森林」），EN 英文 metadata 在 spec / code comment 用、UI 顯示維持中文不動。**無 i18n_lint 風險**（既有資料字串、非 `Text("...")` raw 中文）。

## Non-Goals

- 不改 layer count 規則（仍 0→1 / 1-50→2 / 51-200→3 / 200+→4）
- 不改 `NotebookCoverView` / `NotebookPalette` / pattern 系統
- 不改 metadata stable-height 設計
- 不動 hero 變體（單本平面，維持現狀）
- 不擴張顏色到 12 色以外
- 不動 `lab/`、不動 sync / coordinator 邏輯

## Design Decisions（已與使用者對齊）

| 維度 | 決定 |
|---|---|
| Ghost 顏色 | Cream 紙頁三階：`paperLight` / `paperSepia` / `paperSepiaDeep` |
| 頂層 cover | 維持原 cover 色 + 0.5pt `cardBorder` hairline |
| 手感程度 | 明顯但克制 — rotation ±1.5°、edge jitter ±1pt |
| 頂層也歪 | 是（整疊都是隨手放） |
| Rotation seed | Per-notebook deterministic（notebook ID hash），同一本每次同一歪法 |
| Rotation anchor | `.bottom`（從底部「擺上桌」） |
| Press 行為 | 既有物理不變（top scale 0.97 + offset、ghost 微下沉），**rotation 不動** |
| Cover↔metadata | 補 1pt `cardBorder` hairline rule（editorial 分隔） |
| AddCard | 1.5pt dashed → 1pt 實線 hairline + `paperLight` 背景 + plus 包 36pt soft ring；**不旋轉** |
| Dark mode | rotation 幅度一致、ghost cream 套 dark variant、shadow 仍 ×1.8 自動 |
| Reduce Motion | rotation **不關**（為靜態視覺、非動畫）；offset/scale 仍依現規關閉 |

## 精確幾何

### Ghost 層配置

| depth | 顏色 | rotation | dx jitter（單側 inset 之外加值） |
|---|---|---|---|
| 1 | `AppColors.paperLight` (`#FBFAF8`) | -0.8° | +0.5pt |
| 2 | `AppColors.paperSepia` (`#FAF6EF`) | +1.5° | -1pt |
| 3 | `AppColors.paperSepiaDeep` (`#F5EDDE`) | -1.5° | +1pt |
| top cover | original cover color | +0.5° | 0 |

- 全層 `AppRadius.md` 圓角
- 全層 0.5pt `cardBorder` hairline border（cream-on-cream 沒邊讀不出層次）
- Rotation anchor `.bottom`、所有 layer 同 anchor 讓「底部擺平、頂部微張」

### Per-notebook seed jitter

```swift
// NotebookStackMetrics
static func seedJitter(seed: Int, depth: Int) -> (angle: Double, dx: CGFloat) {
    // Base table 提供基準歪法，seed 在基準上 ±50% 擾動
    let baseAngle = layerRotations[min(depth, layerRotations.count - 1)]
    let baseDx    = layerDxJitter[min(depth, layerDxJitter.count - 1)]
    let perturb   = Double((seed &+ depth &* 31) % 100) / 100.0 - 0.5  // [-0.5, +0.5]
    return (
        angle: baseAngle * (1.0 + perturb * 0.5),
        dx:    baseDx * (1.0 + CGFloat(perturb) * 0.5)
    )
}
```

`seed` 由 caller 傳入（`NotebookCard` 對 notebook name 或 ID hash），同一本永遠同一個 jitter。

### Layout 副作用

Rotation ±1.5° 讓 bounding box overhang ≈ `sin(1.5°) × width` ≈ width × 0.026。需把 `padding(.bottom, maxGhostDy)` 改為：

```swift
let rotationOverhang = width * sin(1.5° in radians) ≈ width * 0.026
.padding(.bottom, maxGhostDy + rotationOverhang)
.padding(.horizontal, rotationOverhang)
```

`width` 不能在 padding 計算時取得 — 用 `GeometryReader` 或固定一個保守常數（e.g. `AppSpacing.s2 = 8pt`）。**選後者**：避免 GeometryReader 在 grid 內造成 layout 反覆。

### Cover ↔ metadata rule

```swift
// 在 NotebookCard.body 的 VStack 中、cover 與 metadata 之間
Divider()
    .frame(height: 1)
    .background(skin.palette.cardBorder)
    .opacity(0.6)  // 比 cover hairline 更克制，避免變強斷線
```

或更簡單：cover 區的下緣 overlay 1pt cardBorder 線，metadata 上緣自然接邊。實作時擇一即可，視覺結果相同。

### Empty notebook（0 字）

- `layerCount == 1`：仍是平面單卡
- 加 0.5pt `cardBorder` hairline（與 ghost 同 hairline）
- 加 cover↔metadata 1pt rule
- **不旋轉**（單卡沒有「堆」的隱喻，rotation 反而像 bug）

### AddCard

```swift
// 注意：paperLight/Sepia/SepiaDeep 在 AppColors（非 skin.palette），實作時直引 AppColors
.background(AppColors.paperLight)  // 微暖背景，與 ghost 同語言
.clipShape(RoundedRectangle(cornerRadius: skin.radii.card))
.overlay(
    RoundedRectangle(cornerRadius: skin.radii.card)
        .strokeBorder(skin.palette.cardBorder, lineWidth: 1)  // dashed → solid hairline
)
// plus icon
.overlay(
    Image(systemName: "plus")
        .font(.system(size: 18, weight: .regular))
        .foregroundStyle(skin.palette.tertiaryText)
        .frame(width: 36, height: 36)
        .overlay(
            Circle().strokeBorder(skin.palette.cardBorder, lineWidth: 1)
        )
)
```

- 不旋轉、不加 shadow（empty slot 語意）
- `paperLight` 背景把它與 ghost 紙頁系列收進同一視覺族群

## Token 變更

### `NotebookStackMetrics` 內新增

```swift
/// Editorial 手感 jitter — 每層基準歪法
static let layerRotations: [Double] = [0.5, -0.8, 1.5, -1.5]
static let layerDxJitter:  [CGFloat] = [0, 0.5, -1, 1]

/// Ghost cream 紙頁三階
static func ghostPaperColor(depth: Int, scheme: ColorScheme) -> Color

/// Per-notebook deterministic jitter
static func seedJitter(seed: Int, depth: Int) -> (angle: Double, dx: CGFloat)

/// Rotation overhang 保守常數（避免 GeometryReader）
/// 典型 cover width ~160pt，真實 sin(1.5°) overhang ≈ 4.2pt；8pt = 2× 安全邊際
static let rotationOverhang: CGFloat = AppSpacing.s2  // 8pt
```

### 移除 / deprecate

- `brightnessStepLight` / `brightnessStepDark` — 不再用 brightness shift
- `deckColor(_:depth:scheme:)` — 由 `ghostPaperColor` 取代（保留簽名做 graceful migration，內部 forward 到 paperColor，加 `@available(*, deprecated)` 註解）

### 不動

- `layerOffsetY`、`layerInsetX`、`pressedTopOffsetY`、`pressedGhostOffsetY`、`layerCount(forCardCount:)`、`AppMotion.cardDeckRelease`

## 互動規格（不變）

- Press-in：top `offset(y: -14)` + `scaleEffect(0.97)` + shadow z1→z2，ghost `+depth × 1pt` 微下沉
- 動畫：`AppMotion.TapFeedback.animation`（press-in）/ `AppMotion.cardDeckRelease`（release）
- Haptic：`.sensoryFeedback(.selection, ...)`
- Navigation：`NavigationLink(value:)` 邊抽邊 push
- **rotation 完全不參與動畫** — 是靜態 layout

## Accessibility

- 既有 accessibility element 邏輯不動（single element + label + isButton trait）
- ghost 各層 `.accessibilityHidden(true)` 不變
- Reduce Motion：rotation **保留**（屬 layout 非動畫；rotation 在 mount 後不再改變）。HIG 對 RM 主要規範動態 motion；本案 rotation 為靜態 visual，與 Wallet/Books 既有圖示同性質。precedent 同步寫入 `docs/sop/ui-design.md` 以正式化此判斷。press 物理 offset/scale 依現規關
- Differentiate Without Color：cream 三階加 hairline 已提供邊界區分，不需額外處理
- VoiceOver：rotation 不影響 hit-test（SwiftUI 自動處理 rotated frame）

## State 矩陣（更新）

| State | 視覺 |
|---|---|
| 0 字 | 平面單卡 + hairline + cover↔metadata rule，不旋轉 |
| 1-50 | 2 層（cover + L1 paperLight），都微歪 |
| 51-200 | 3 層（cover + L1 + L2 paperSepia） |
| 200+ | 4 層（cover + L1 + L2 + L3 paperSepiaDeep） |
| Active | 既有 `使用中` pill 貼最上層 cover 右上，**隨 cover rotation 一起轉**（落地策略：rotation 應用於整個 `coverArea`，含 pill overlay；pill 本身不再單獨 rotate） |
| Dark | ghost 套 dark cream variant（待 design check），其餘同 |
| Reduce Motion | rotation 不變，offset/scale 關 |
| 自訂照片封面 | top 仍是 image，ghost 仍 paperLight/Sepia（不混照片） |

## Verification

### 編譯與靜態
- `./ops/ios_build.sh` 通過（**新檔不信 4s 快速 success — 強制清 cache 重建**）
- `ops/i18n_lint.sh` 通過
- 0 個 raw `.spring(...)` / `.shadow(...)` / `.rotationEffect(...)` 直寫於 view（全走 token）

### 視覺手動驗
- 兩本並列：左有資料、右 0 字 — 高度齊、底部無空白
- 同一本 reload 多次：rotation 與 jitter 完全一樣（seed deterministic）
- 不同本 random 角度不撞色
- ghost 三層 cream tonal gradient 清楚（paperLight → Sepia → SepiaDeep）
- Cover↔metadata 之間 hairline rule 可見但克制
- AddCard 與真實卡同 row 高度一致、視覺族群一致（同 paperLight 背景）
- Press 任一本：top 抽出 + ghost 微下沉，rotation 不變
- Dark mode：cream 仍可辨、hairline 不糊

### A11y
- VoiceOver：每本只念一次、label 含 name + 字數
- Reduce Motion：rotation 仍在、offset/scale 關
- Dynamic Type a11y3：metadata 不溢出
- 鍵盤 Return：push 不跑 press-in

### 回歸
- 既有 `NotebooksScenarios` previews 全跑、無異常
- `NotebookListScenarios`（新建於 PR #571）跑全 state matrix
- iOS 17 / 18 雙版本

## Doc 同步（同 PR）

- `docs/sop/ui-design.md` — Motion table 無變動；新增「editorial imperfection」段（rotation/jitter 屬靜態 layout，非 motion）
- `docs/reference/feature_boundary/notebook.md` — `NotebookStackedCoverView` 行數 drift；新增 cream paper ghost 視覺說明
- `docs/reference/ui/components.md` — `NotebookStackedCoverView` 條目更新
- `docs/reference/ui/state_matrix.md` — 上方 state 矩陣同步

## 不在 scope

- `AppFonts.display1/display2` 補齊（SOP 提到但 source 缺）— 與本 spec 無關
- `AppCard` shell primitive 抽取 — 既有 ad-hoc 組合可用
- `lab/` 任何檔案
- Sync / coordinator / 多帳戶
- Notebook detail 頁、podcast、reader

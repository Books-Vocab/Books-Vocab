<!-- doc-meta
tier: archive
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/
verified_against: frozen
-->
# Feature Metrics Inventory

掃描來源：`ios/BooksAndVocab/` 所有 `private enum *Metrics` / `private struct *Metrics`

---

## Token 升降規則

1. **升級到 AppMetrics**：被 ≥2 個 feature 使用的 spacing / radius / shadow
2. **保留 local**：只在一個 feature 用的 dimension（如 `coverHeight`、`progressBarHeight`）
3. **合併同義**：不同 feature 相同 px 值的 spacing 統一命名

---

## Metrics 清冊

### BookshelfMetrics
**位置**：`Views/Bookshelf/BookshelfView.swift`
**Token 數**：13（已刪除 5 個升級候選）

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| ~~`emptyStateSpacing`~~ | 20 | = `AppMetrics.sectionInset` (20) | ✅ 已升級 |
| ~~`cardSpacing`~~ | 8 | = `AppMetrics.spacingSmall` (8) | ✅ 已升級 |
| ~~`cardMetadataSpacing`~~ | 3 | = `AppMetrics.spacingTiny` (3) | ✅ 已升級 |
| `placeholderTitleHorizontalPadding` | 12 | 無對應 | 保留 local |
| `coverHeight` | 210 | feature-specific | 保留 local |
| `coverHeightRegular` | 260 | feature-specific | 保留 local |
| `coverCornerRadius` | 6 | = `AppMetrics.cornerRadiusSmall` (8) 接近但不同 | 保留 local（語義不同） |
| ~~`coverStrokeWidth`~~ | 0.5 | = `AppMetrics.dividerThin` (0.5) | ✅ 已升級 |
| `coverShadowOpacity` | 0.10 | 無對應，AppShadows.coverOpacity = 0.06 | 保留 local（值不同）|
| `coverShadowRadius` | 6 | 無直接對應 | 保留 local |
| `coverShadowY` | 3 | 無直接對應 | 保留 local |
| `progressBarHeight` | 4 | feature-specific | 保留 local |
| `progressBarCornerRadius` | 2 | feature-specific | 保留 local |
| `progressBarAccentOpacity` | 0.55 | feature-specific | 保留 local |
| `progressBarSpacing` | 6 | feature-specific | 保留 local |
| ~~`loadingOverlaySpacing`~~ | 16 | = `AppMetrics.spacingMedium` (16) | ✅ 已升級 |
| `loadingOverlayPadding` | 28 | 無對應 | 保留 local |
| `loadingOverlayCornerRadius` | `AppMetrics.cornerRadiusMedium` | 已引用 AppMetrics | 已升級 |

---

### WelcomeMetrics
**位置**：`Views/Welcome/WelcomeView.swift`
**Token 數**：6（已刪除 2 個升級候選）

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `iconBottomPadding` | 12 | 無對應 | 保留 local |
| `pageHeight` | 240 | feature-specific | 保留 local |
| ~~`pageContentSpacing`~~ | 16 | = `AppMetrics.spacingMedium` (16) | ✅ 已升級 |
| `featureIconSize` | 32 | feature-specific | 保留 local |
| `featureIconFrame` | 64 | feature-specific | 保留 local |
| `subtitleHorizontalPadding` | 40 | feature-specific | 保留 local |
| ~~`buttonSpacing`~~ | 8 | = `AppMetrics.spacingSmall` (8) | ✅ 已升級 |
| `bottomPadding` | 40 | feature-specific | 保留 local |

---

### AccountMetrics
**位置**：`Views/Settings/SettingsAccountSection.swift`
**Token 數**：9（已刪除 3 個升級候選）

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `authHeroSpacing` | 10 | 無對應 | 保留 local |
| ~~`authCopySpacing`~~ | 4 | = `AppMetrics.spacingExtraSmall` (4) | ✅ 已升級 |
| `authActionSpacing` | 10 | 無對應 | 保留 local |
| ~~`authHeroVerticalPadding`~~ | 24 | = `AppMetrics.spacingLarge` (24) | ✅ 已升級 |
| ~~`authBlockPadding`~~ | 16 | = `AppMetrics.spacingMedium` (16) | ✅ 已升級 |
| `authButtonSpacing` | 12 | 無對應 | 保留 local |
| `authRowSpacing` | 14 | 無對應 | 保留 local |
| `authStatusSpacing` | 6 | 無對應 | 保留 local |
| `authAvatarSize` | 46 | feature-specific | 保留 local |
| `authSocialBadgeSize` | 22 | feature-specific | 保留 local |
| `authSocialShadowRadius` | `AppShadows.controlRadius` | 已引用 AppShadows | 已升級 |
| `authSocialShadowY` | `AppShadows.controlY` | 已引用 AppShadows | 已升級 |

---

### ReviewSettingsMetrics
**位置**：`Views/Settings/SettingsReviewSection.swift`
**Token 數**：3（已刪除 1 個升級候選）

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `modeTileGap` | 10 | 無對應 | 保留 local |
| ~~`modeTileContentGap`~~ | 8 | = `AppMetrics.spacingSmall` (8) | ✅ 已升級 |
| `stepperGap` | 12 | 無對應 | 保留 local |
| `valueMinWidth` | 52 | feature-specific | 保留 local |

---

### AppOverlayMetrics
**位置**：`Views/Vocabulary/Overlay/LinkedCardOverlayStack.swift`（前稱 `LinkedCardStackMetrics`，token 名稱隨重命名更新）
**Token 數**：3（已刪除 2 個升級候選）

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `linkedCardLayerOffsetX` | 8 | feature-specific（堆疊動畫幾何） | 保留 local |
| `linkedCardLayerOffsetY` | 10 | feature-specific（堆疊動畫幾何） | 保留 local |
| `linkedCardLayerShrinkStep` | 18 | feature-specific（堆疊動畫幾何） | 保留 local |
| ~~`baseHorizontalPadding`~~ | 16 | = `AppMetrics.spacingMedium` (16) | ✅ 已升級 |
| ~~`baseVerticalPadding`~~ | 20 | = `AppMetrics.sectionInset` (20) | ✅ 已升級 |

---

### MacDetailPanelMetrics
**位置**：`Views/Vocabulary/MacDetailPanelMetrics.swift`（Mac Catalyst 雙欄詳情面板）
**Token 數**：7

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `defaultWidth` | 420 | feature-specific | 保留 local |
| `minWidth` | 280 | feature-specific | 保留 local |
| `maxWidth` | 600 | feature-specific | 保留 local |
| `leftMinWidth` | 300 | feature-specific | 保留 local |
| `hitAreaWidth` | 8 | feature-specific（拖曳 handle） | 保留 local |
| `dividerIdleOpacity` | 0.2 | 無對應 | 保留 local |
| `dividerActiveOpacity` | 0.5 | 無對應 | 保留 local |

---

### PodcastPlayerMetrics
**位置**：`Views/Podcast/PodcastPlayerMetrics.swift`
**Token 數**：6

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `seekBarTrackHeight` | 5 | feature-specific | 保留 local |
| `seekBarThumbSize` | 16 | feature-specific | 保留 local |
| `seekBarThumbOffset` | 8 | = `AppMetrics.spacingSmall` (8)，但語意不同 | 保留 local |
| `seekBarHitArea` | 20 | = `AppMetrics.sectionInset` (20)，但語意不同 | 保留 local |
| `controlsClusterSpacing` | 8 | = `AppMetrics.spacingSmall` (8) | 升級候選（需確認是否跨 feature） |
| `controlsBottomPadding` | 20 | = `AppMetrics.sectionInset` (20) | 升級候選 |

---

### ReaderMetrics
**位置**：`Views/Reader/ReaderMetrics.swift`（從 `AppSkin.Metrics` 遷出）
**Cross-feature 借用**：`UIComponents/AppShellComponents.swift`、`Views/Vocabulary/Components/CollocationExplainSheet.swift`
**Token 數**：19（panel / settings handle / settings layout / divider opacity）

主要分群：
- **Panel handle**：`panelHorizontalInset(18)` / `panelBottomInset(16)` / `panelHandleWidth(32)` / `panelHandleHeight(4)` / `panelHandleTopInset(10)` / `panelHandleBottomInset(12)`
- **Settings handle**：`settingsHandleWidth(48)` / `settingsHandleHeight(5)` / `settingsHandleTopInset(12)` / `settingsHandleBottomInset(14)`
- **Settings layout**：`settingsHorizontalInset(18)` / `settingsBottomInset(20)` / `settingsHeaderSpacing(14)` / `settingsHeaderBottomInset(16)` / `settingsHeaderMicroInset(4)`
- **Settings card**：`settingsCardPadding(16)` / `settingsControlHorizontalPadding(14)` / `settingsControlVerticalPadding(14)` / `settingsDividerOpacity(0.6)`

升級候選：`settingsCardPadding(16) = spacingMedium`；`settingsBottomInset(20) = sectionInset`。

---

### AppBannerMetrics
**位置**：`UIComponents/AppBannerMetrics.swift`（App Shell 層共用）
**Token 數**：5

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `spacing` | 10 | 無對應 | 保留 local |
| `horizontalPadding` | 14 | 無對應 | 保留 local |
| `verticalPadding` | 8 | = `AppMetrics.spacingSmall` (8) | 升級候選 |
| `borderOpacity` | 0.2 | 無對應 | 保留 local |
| `backgroundOpacity` | 0.08 | 無對應 | 保留 local |

---

### AppTagMetrics
**位置**：`UIComponents/AppTagMetrics.swift`（App Shell 層共用；被 `TodayReviewMetrics` 引用）
**Token 數**：3

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `horizontalPadding` | 10 | 無對應 | 保留 local |
| `verticalPadding` | 5 | 無對應 | 保留 local |
| `cornerRadius` | 6 | 接近 `AppRadius.sm`，語意相近 | 升級候選 |

---

### NotebookStackMetrics
**位置**：`Views/Vocabulary/Components/NotebookStackMetrics.swift`（Notebook 立體堆卡）
**Token 數**：5 簡單常數 + 3 個 computed 方法（`layerCount` / `seedJitter` / `stableSeed`）+ ghost color

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `layerOffsetY` | `AppSpacing.s1` (4pt) | 已引用 AppSpacing | 已升級 |
| `layerInsetX` | `AppSpacing.s1` (4pt) | 已引用 AppSpacing | 已升級 |
| `pressedTopOffsetY` | -14 | feature-specific（動畫幾何） | 保留 local |
| `pressedGhostOffsetY` | 1 | feature-specific | 保留 local |
| `rotationOverhang` | `AppSpacing.s2` (8pt) | 已引用 AppSpacing | 已升級 |
| `patternOpacity` | 0.12 | 無對應 | 保留 local |

Ghost color 走 `AppColors.paperLight / paperSepia / paperSepiaDeep`（已升級）。

---

### TodayReviewMetrics
**位置**：`Views/Vocabulary/Scenes/TodayReviewMetrics.swift`（從 `AppSkin.Metrics` Phase 4 遷出）
**Token 數**：34（含大量 feature-specific 幾何、opacity、font size、swipe 閾值）

主要分群：
- **Stack 動畫**：`promoteYOffset(22)` / `promoteScale(0.96)`
- **Opacity**：`cardBorderOpacity(0.45)` / `cardBorderActiveOpacity(0.72)` / `dimTextOpacity(0.72)` / `dividerFillOpacity(0.85)`
- **Font size**：`counterFontSize{Compact/Medium/Large/XLarge}` = 22/26/28/30pt
- **Card layout**：`cardHorizontalInset/TopInset/BottomInset` = `AppSpacing.s2` (已升級)
- **TopBar**：`topBarHorizontalInset(20)` = `sectionInset`（升級候選）
- **Swipe**：`swipeThreshold(100)` / `swipeMaxRotation(12°)` / `swipeOpacityFloor(0.3)`
- **Fold 幾何**：`foldJoinRadius(4)` / `paperFoldOffsetY(12)` / `foldPadding(28)` / `foldSectionSpacing(24)` / `foldHintBottomInset(22)`

Tag 相關 token（`tagHorizontalPadding` / `tagVerticalPadding` / `tagCornerRadius`）直接引用 `AppTagMetrics`（已升級）。

---

## 跨 Feature 同義值統整

以下 spacing 值在多個 feature 中出現，已有對應 AppMetrics token：

| 值 | AppMetrics Token | 出現位置 |
|----|------------------|---------|
| 4 | `spacingExtraSmall` | AccountMetrics.authCopySpacing |
| 8 | `spacingSmall` | BookshelfMetrics.cardSpacing、WelcomeMetrics.buttonSpacing、ReviewSettingsMetrics.modeTileContentGap、PodcastPlayerMetrics.seekBarThumbOffset* |
| 16 | `spacingMedium` | AccountMetrics.authBlockPadding、WelcomeMetrics.pageContentSpacing、AppOverlayMetrics.baseHorizontalPadding、ReaderMetrics.settingsCardPadding* |
| 20 | `sectionInset` | BookshelfMetrics.emptyStateSpacing、AppOverlayMetrics.baseVerticalPadding、PodcastPlayerMetrics.controlsClusterSpacing*、ReaderMetrics.settingsBottomInset* |
| 24 | `spacingLarge` | AccountMetrics.authHeroVerticalPadding |
| 0.5 | `dividerThin` | BookshelfMetrics.coverStrokeWidth |

標 `*` 為新發現升級候選（尚未執行升級）。原 10 個 token 已全數升級完成，對應 local constant 已刪除。

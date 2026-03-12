# Feature Metrics Inventory

掃描來源：`ios/BooksBrowser/` 所有 `private enum *Metrics` / `private struct *Metrics`

---

## Token 升降規則

1. **升級到 AppMetrics**：被 ≥2 個 feature 使用的 spacing / radius / shadow
2. **保留 local**：只在一個 feature 用的 dimension（如 `coverHeight`、`progressBarHeight`）
3. **合併同義**：不同 feature 相同 px 值的 spacing 統一命名

---

## Metrics 清冊

### BookshelfMetrics
**位置**：`Views/Bookshelf/BookshelfView.swift`
**Token 數**：18

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `emptyStateSpacing` | 20 | = `AppMetrics.sectionInset` (20) | 升級 → 改用 `AppMetrics.sectionInset` |
| `cardSpacing` | 8 | = `AppMetrics.spacingSmall` (8) | 升級 → 改用 `AppMetrics.spacingSmall` |
| `cardMetadataSpacing` | 3 | = `AppMetrics.spacingTiny` (3) | 升級 → 改用 `AppMetrics.spacingTiny` |
| `placeholderTitleHorizontalPadding` | 12 | 無對應 | 保留 local |
| `coverHeight` | 210 | feature-specific | 保留 local |
| `coverHeightRegular` | 260 | feature-specific | 保留 local |
| `coverCornerRadius` | 6 | = `AppMetrics.cornerRadiusSmall` (8) 接近但不同 | 保留 local（語義不同） |
| `coverStrokeWidth` | 0.5 | = `AppMetrics.dividerThin` (0.5) | 升級 → 改用 `AppMetrics.dividerThin` |
| `coverShadowOpacity` | 0.10 | 無對應，AppShadows.coverOpacity = 0.06 | 保留 local（值不同）|
| `coverShadowRadius` | 6 | 無直接對應 | 保留 local |
| `coverShadowY` | 3 | 無直接對應 | 保留 local |
| `progressBarHeight` | 4 | feature-specific | 保留 local |
| `progressBarCornerRadius` | 2 | feature-specific | 保留 local |
| `progressBarAccentOpacity` | 0.55 | feature-specific | 保留 local |
| `progressBarSpacing` | 6 | feature-specific | 保留 local |
| `loadingOverlaySpacing` | 16 | = `AppMetrics.spacingMedium` (16) | 升級 → 改用 `AppMetrics.spacingMedium` |
| `loadingOverlayPadding` | 28 | 無對應 | 保留 local |
| `loadingOverlayCornerRadius` | `AppMetrics.cornerRadiusMedium` | 已引用 AppMetrics | 已升級 |

---

### WelcomeMetrics
**位置**：`Views/Welcome/WelcomeView.swift`
**Token 數**：8

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `iconBottomPadding` | 12 | 無對應 | 保留 local |
| `pageHeight` | 240 | feature-specific | 保留 local |
| `pageContentSpacing` | 16 | = `AppMetrics.spacingMedium` (16) | 升級 → 改用 `AppMetrics.spacingMedium` |
| `featureIconSize` | 32 | feature-specific | 保留 local |
| `featureIconFrame` | 64 | feature-specific | 保留 local |
| `subtitleHorizontalPadding` | 40 | feature-specific | 保留 local |
| `buttonSpacing` | 8 | = `AppMetrics.spacingSmall` (8) | 升級 → 改用 `AppMetrics.spacingSmall` |
| `bottomPadding` | 40 | feature-specific | 保留 local |

---

### AccountMetrics
**位置**：`Views/Settings/SettingsAccountSection.swift`
**Token 數**：12

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `authHeroSpacing` | 10 | 無對應 | 保留 local |
| `authCopySpacing` | 4 | = `AppMetrics.spacingExtraSmall` (4) | 升級 → 改用 `AppMetrics.spacingExtraSmall` |
| `authActionSpacing` | 10 | 無對應 | 保留 local |
| `authHeroVerticalPadding` | 24 | = `AppMetrics.spacingLarge` (24) | 升級 → 改用 `AppMetrics.spacingLarge` |
| `authBlockPadding` | 16 | = `AppMetrics.spacingMedium` (16) | 升級 → 改用 `AppMetrics.spacingMedium` |
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
**Token 數**：4

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `modeTileGap` | 10 | 無對應 | 保留 local |
| `modeTileContentGap` | 8 | = `AppMetrics.spacingSmall` (8) | 升級 → 改用 `AppMetrics.spacingSmall` |
| `stepperGap` | 12 | 無對應 | 保留 local |
| `valueMinWidth` | 52 | feature-specific | 保留 local |

---

### LinkedCardStackMetrics
**位置**：`Views/Vocabulary/Overlay/LinkedCardOverlayStack.swift`
**Token 數**：6

| Token | 值 | 與 AppMetrics 比對 | 建議 |
|-------|----|--------------------|------|
| `layerOffsetX` | 8 | feature-specific（堆疊動畫幾何） | 保留 local |
| `layerOffsetY` | 10 | feature-specific（堆疊動畫幾何） | 保留 local |
| `layerShrinkStep` | 18 | feature-specific（堆疊動畫幾何） | 保留 local |
| `baseHorizontalPadding` | 16 | = `AppMetrics.spacingMedium` (16) | 升級 → 改用 `AppMetrics.spacingMedium` |
| `baseVerticalPadding` | 20 | = `AppMetrics.sectionInset` (20) | 升級 → 改用 `AppMetrics.sectionInset` |

---

## 跨 Feature 同義值統整

以下 spacing 值在多個 feature 中出現，已有對應 AppMetrics token：

| 值 | AppMetrics Token | 出現位置 |
|----|------------------|---------|
| 4 | `spacingExtraSmall` | AccountMetrics.authCopySpacing |
| 8 | `spacingSmall` | BookshelfMetrics.cardSpacing、WelcomeMetrics.buttonSpacing、ReviewSettingsMetrics.modeTileContentGap |
| 16 | `spacingMedium` | AccountMetrics.authBlockPadding、WelcomeMetrics.pageContentSpacing、LinkedCardStackMetrics.baseHorizontalPadding |
| 20 | `sectionInset` | BookshelfMetrics.emptyStateSpacing、LinkedCardStackMetrics.baseVerticalPadding |
| 24 | `spacingLarge` | AccountMetrics.authHeroVerticalPadding |
| 0.5 | `dividerThin` | BookshelfMetrics.coverStrokeWidth |

這 10 個 token 為優先升級候選，替換後可直接刪除對應 local constant。

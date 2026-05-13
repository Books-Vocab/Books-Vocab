<!-- doc-meta
tier: structural
scope:
  - ios/BooksBrowser
verified_against: c16321f
-->
# BooksBrowser UI Design System

> 文檔網絡：
> - 開發入口與編譯流程：`docs/dev/ios-dev.md`
> - App 架構與 UI 脈絡：`docs/dev/architecture.md`
> - 元件 / pattern 現況清單：`docs/references/ui_component_pattern_inventory.md`
> - 狀態覆蓋矩陣：`docs/references/ui_state_matrix.md`
> - UI Review Checklist：`docs/references/ui_review_checklist.md`

## 設計系統概覽

BooksBrowser 使用莫蘭迪色調的 design token 系統：

| 層級 | Token 來源 | 適用範圍 |
|------|-----------|---------|
| App Shell | `AppTheme` / `AppColors` / `AppFonts` / `AppMetrics`（含 `AppSpacing`/`AppRadius`/`AppElevation`/`AppLayout`/`AppMotion`/`AppShadows`/`AppShellMetrics`） | 全 app chrome（toolbar、tab、banner、toast） |
| Vocabulary Skin | `VocabSkin`（Palette / Typography / Spacing） | Vocabulary feature 所有 View |
| Reader | `ReaderContentStyle` | EPUB/PDF reader 內容樣式 |

### 環境注入

- `@Environment(\.appTheme)` — App Shell 層
- `@Environment(\.vocabSkin)` — Vocabulary 層
- 不可硬建 instance

### macOS 平台適配

- `Platform/PlatformRepresentable.swift`：跨平台 typealias（PlatformView / Color / Image / Font）
- `Platform/PlatformCompatibility.swift`：iOS-only modifier 的 macOS fallback
- Reader 系列以 `#if os(iOS)` 整檔隔離，macOS 暫不啟用
- 其餘 View 共用，平台差異以條件編譯處理

---

## Motion Contract

BooksBrowser 的 motion system 不接受各頁自由書寫 `.spring(...)` / `.easeOut(...)`。
動畫必須優先走 `BooksBrowser/Models/AppMetrics.swift` 中的 `AppMotion` 與共享 `AnyTransition` 語意 token。

### 核心原則

1. 先選語意，再選數值。
2. 同一類互動跨 feature 必須共用同一 token。
3. feedback 要成對出現：
   視覺 feedback 與 haptic feedback 應一起設計。
4. 不為了「有在動」而加動畫。
   animation 只服務於 state change、hierarchy、feedback、continuity。

### AppMotion 語意層

| Token | 用途 | 目前主要路徑 |
|------|------|-------------|
| `panelState` | panel / drawer / settings 開合 | Reader、Translation、Graph Settings |
| `panelSnapBack` | drag release 回位 | TranslationPanel |
| `headerState` | compact / expanded header 切換 | Reader header |
| `phaseChange` | 流程狀態切換 | Sync、Settings 狀態卡 |
| `feedbackPulse` | 成功保存、數字跳動、局部確認 | Translation save、Sync step、Review feedback、Toast |
| `contentFade` | 短暫內容淡出 | Reader progress / transient overlay |
| `loadingState` | loading 文案、loading overlay 的 state swap | Reader loading |
| `reviewRevealSpring` | review front/back/details 展開 | Today Review |
| `reviewNavigationSpring` | review 上一張 / 下一張 / 洗牌 | Today Review |
| `reviewCardSwapSpring` | review 回答後換卡 | Today Review |
| `toastPresent` | toast capsule 進出 | AppToast（全 app） |
| `emphasizedDecelerate` | 非對稱進場曲線（Material 3） | AppOfflineBanner、未來 sheet/panel 進場 |
| `emphasizedAccelerate` | 非對稱退場曲線（Material 3） | 未來 sheet/panel 退場 |
| `subtleBreath` | 2.4s easeInOut autoreverse | `AppSkeleton` pulse、empty state 呼吸 |
| `shimmer` | 1.4s linear repeatForever | skeleton mask（dormant，待 callsite） |
| `TapFeedback` triplet | `scaleDown 0.97` / `opacityDip 0.92` / `animation` | PressableInteraction / ButtonStyle 統一按壓物理感 |

### Transition 語意層

| Token | 用途 |
|------|------|
| `overlayFade` | scrim、暫時性 overlay、toolbar 進出 |
| `readerPanelReveal` | 底部 panel / drawer 進出 |
| `headerSwap` | header compact / expanded swap |
| `feedbackBadge` | saved / success 類 badge |
| `linkedOverlayCard` | linked card 疊層卡片 |
| `modalSwap` | 同區塊登入/登出、模式切換 |
| `statusRowReveal` | Settings / status row 延伸顯示 |

### 禁止事項

- 不要在 feature 檔案裡直接寫新的 `.spring(response:...)`，除非先把它提升為 `AppMotion` 語意 token。
- 不要為相似 overlay 各自定義不同 transition。
- 不要把 loading、success、error 都混用同一個動畫。
- 不要用 `.default` 當正式產品互動動畫。

### Feature Mapping

- Reader：
  `panelState`、`panelSnapBack`、`headerState`、`loadingState`、`feedbackBadge`
- Review：
  `reviewRevealSpring`、`reviewNavigationSpring`、`reviewCardSwapSpring`、`overlayFade`
- Sync：
  `phaseChange`、`feedbackPulse`、`blurReplace`
- Settings：
  `modalSwap`、`statusRowReveal`
- Toast：
  `toastPresent`、`feedbackPulse`
- Graph：
  `panelState`（settings panel）、`linkedOverlayCard`

### 文件責任

- 若是要改 token 定義：
  先更新 `BooksBrowser/Models/AppMetrics.swift`
- 若是要改互動規則：
  先更新本頁，再改程式
- 若是要排查編譯或 SwiftUI 實作錯誤：
  回到 `docs/dev/ios-dev.md`
- 若是要理解 UI 為何出現在某個資料流程中：
  回到 `docs/dev/architecture.md`
- 若是要新增 spacing/radius/elevation 數值：
  先在 `AppSpacing` / `AppRadius` / `AppElevation` 加 token，不可在 view 寫 magic number

---

## Layout / Spacing / Elevation token（Models/AppMetrics.swift）

PR #402 七階段升級補完語意分層。新元件優先使用以下 token，舊 `AppMetrics.spacing*` 保留為相容別名。

| Token tier | 內容 | 採用率 |
|-----------|------|--------|
| `AppSpacing` | 8pt grid：`s0=0/s1=4/s2=8/.../s7=64`、`hairline=1`；語意 alias `cardOuterPadding/innerGap/sectionGap` | 部分 — 新元件已切，舊 view 仍多 raw 數字 |
| `AppRadius` | `xs=4/sm=8/md=12/lg=16/xl=24/pill=999`；禁用鄰近半階值（7/9/13/14/18） | 部分 |
| `AppElevation` | `z0...z4` 替代 `paperFloat`/`cover`/`panel` 命名；`.appElevation(.z2)` modifier；dark mode 透過 `AppElevationModifier` 自動加強 opacity | **dormant — zero callsites** |
| `AppLayout` | `maxReadableWidth=680`、`maxContentWidth=920`、compact/regular/expanded page padding (20/32/48)；`.appReadableFrame()` modifier | **dormant — zero callsites** |
| `AppFonts.display1/display2` | 56/48pt serif hero typography；hero / onboarding 用 | **dormant — zero callsites** |
| `AppFonts.Tracking` / `LineSpacing` | letter-spacing / 行高 token | dormant |

舊 `AppShadows.panelOpacity` 在本 PR 由 0.70 → 0.18（paper-tone shadows）；後續逐步以 `AppElevation` 取代分散的 paperFloat/cover/panel 命名。

---

## Color token：Brand Hero + 狀態 bg

`AppColors.brandHeroLight` (HSB 232°/0.55/0.62) / `brandHeroDark` (232°/0.45/0.78) + `AppColors.brandHero(_:)` scheme-aware accessor。

`AppTheme.Palette` 新欄位：
- `accentHero` — 品牌 hero 主色（scheme-aware）
- `accentSubtle` — 弱化 accent
- `successBg` / `warningBg` / `infoBg` / `destructiveBg` — 10% tint 狀態背景，配狀態前景文字
- `borderStrong` — 加強邊框（給 outline button 等）

`VocabSkin.Palette` 已整合 brand hero 三色階。

---

## 新 primitives（UIComponents/）

PR #402 引入：

- `AppCompactActionButtonStyle` — 取代 `.borderedProminent.controlSize(.small)`，inline 主 CTA；`.appCompactAction(.primary/.neutral/.outline/.destructive)`
- `AppOfflineBanner` — `.appOfflineBanner()` modifier，root 層套用；訂閱 `NetworkMonitor.shared.isConnected`
- `AppSkeletonLine` / `AppSkeletonCard` — Loading 骨架 primitive；新 loading state 應改用此元件而非自製 placeholder（dormant，0 callsites）

---

## Dark Mode 故事

- **Paper-tone 統一**：`AppShadows.panelOpacity` 0.70 → 0.18，整 app shadow 改走低對比浮紙語意。Reader/large panel 視覺層次降低，refactor 後續以 `AppElevation` 取代。
- **Dark mode brand tint**：`accentHero` 在 dark mode 走 `brandHeroDark`；`AppElevationModifier` 在 dark mode 自動加強 shadow opacity，避免黑底黑影失語意。

---

## Known Polish Debt

下列 issue 已知，列入後續 polish pass PR：

1. **`AppOfflineBanner` light mode 對比 ≈ 3.21:1**（destructiveLight 12pt semibold on 10% destructiveLight bg），**fail WCAG AA 4.5:1**。修法：darken text 或 fall back 到 `primaryText` 配 destructive icon。
2. **`accentHero` dark mode footgun**：`brandHeroDark` + white text = 4.02:1（逼近 WCAG AA 邊界）。目前僅 `AppCompactActionButtonStyle.primary` 內部 guard（dark mode 改走 `brandHeroLight`）；**其他 callsite 不要直接配 `.white`**，需待 `onBrandHero` token 抽出。
3. **`AppCompactActionButtonStyle` primary foreground raw `.white`** — 待替換為 `onBrandHero` token。
4. **Dormant tokens（~60% 新 surface）**：`AppSkeleton`、`display1/2`、`appReadableFrame`、`AppElevation` 已定義但 0 callsite，使用前注意可能無實際 reference 樣本。

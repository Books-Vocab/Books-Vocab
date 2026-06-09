<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/BooksBrowser/
verified_against: 84f6998e
-->
# Books & Vocab UI Design System

> 文檔網絡：
> - 開發入口與編譯流程：`docs/sop/ios.md`
> - App 架構與 UI 脈絡：`docs/sop/architecture.md`
> - 元件 / pattern 現況清單：`docs/reference/ui/components.md`
> - 狀態覆蓋矩陣：`docs/reference/ui/state_matrix.md`
> - UI Review Checklist：`docs/reference/ui/review_checklist.md`

## 設計系統概覽

Books & Vocab 使用 Notion-inspired 的 design token 系統（純淨表面、border 分層、俐落小角半徑）。**CTA 採極淡奶黃** `brandHero #FCDE9A`(pastel cream，兩 mode 同色) — Phase 1c 拍板由古銅蜂蜜金 `#E8C77F` 改淡至 `#FCDE9A`。**Chrome（tab bar / nav button / toolbar）走灰階 tint** (`tintLight #37352F` / `tintDark #E6E6E3`)，刻意不採奶黃以避免稀釋 CTA 訊號。藍色 Morandi grey-blue `accent #4D7396` 維持為**被動色**，留給 link / info / 裝飾：

| 層級 | Token 來源 | 適用範圍 |
|------|-----------|---------|
| App Shell | `AppTheme` / `AppColors` / `AppFonts` / `AppMetrics`（含 `AppSpacing`/`AppRadius`/`AppElevation`/`AppMotion`/`ElevationDirection`） | 全 app chrome（toolbar、tab、banner、toast） |
| Vocabulary Skin | `VocabSkin`（Palette / Typography / Spacing） | Vocabulary feature 所有 View |
| Reader | `ReaderContentStyle` | EPUB/PDF reader 內容樣式 |

### 環境注入

- `@Environment(\.appTheme)` — App Shell 層
- `@Environment(\.vocabSkin)` — Vocabulary 層
- 不可硬建 instance

### Mochi 化北極星五條（2026-05 拍板）

KG UI 對齊 [mochi.cards](https://mochi.cards/docs/api/) editorial 質感。以下五條為 hard rule，新 view / refactor PR 違反 → review block。

1. **單色頁面、無 chrome 分隔**　top toolbar、tab bar、content 共用 `pageBackground`。禁止用 navigation chrome 改色分區（toolbar bg ≠ content bg 屬違反）。
2. **border 退場、divider 進場**　list cards 預設無 border。分區走 `hr-style divider`（hairline + `AppMetrics.dividerAirMargin = 16` 上下 margin）+ 留白。例外：modal / popover / sticky group 必須有邊界，可保留 border。
3. **shadow 收到 z0 / z1 兩階**　list / resting cards 用 z0（無 shadow，純背景區分）或 z1（極輕）。z2 以上保留給 sheet / drawer / modal / overlay。禁止 raw `.shadow(...)`，一律走 `.appElevation(.zN)`。
4. **單一強調色策略**　全 app 強調色只有以下軸線，禁止為了好看引入新色：
   - `brandHero` 奶黃 — 日常 CTA（既有）
   - `accent` Morandi grey-blue — 連結 / info / 被動裝飾（既有）
   - `inlineCode` 深藍綠 — 技術 token（API 端點 / 短語引用 / ID）— **Phase 3 Notebook 套皮時隨需引入**
   - `ctaCritical` 深炭 — 不可錯過 CTA — **暫不上線**，產品決策觸發場景後再引入
5. **互動 motion 收斂**　按鈕按壓統一走 `TapFeedback` triplet；非按鈕互動禁 transform，只動 `bg-color` / `opacity`，曲線預設 `quickEaseOut`（0.15s）或 `controlEaseOut`（0.14s），對齊 Mochi `transition: bg .1s` 路線。

> 落地原則：北極星規則先於 token。新 token 於 Phase N 真正需要時才加入 `AppColors` / `AppTheme.Palette` / `AppMetrics`，避免提前累積 dormant token。Phase 路線：1 = AppSurface flat / 2 = Bookshelf / 3 = Notebook / 4 = Reader / 5 = Today Review motion / 6 = Settings / 7 = Auth / 8 = 全域 motion / 9 = docs + review。

### Mac Catalyst 平台適配

KG 的 Mac 支援走 **Mac Catalyst**（`SUPPORTS_MACCATALYST = YES`），**非原生 macOS**（核心依賴 Readium 僅宣告 `platforms: [.iOS]`）。Catalyst 下 `os(iOS)` 為 true、`os(macOS)` 為 false。

- **分流一律 `#if targetEnvironment(macCatalyst)`，禁 `#if os(macOS)`**（死碼，永不編譯）。Mac 專屬 UX 用 Catalyst 可用的 iOS API（`.onKeyPress` / `UIPointerInteraction` / `UIWindowScene`），不用 AppKit；`.pointerStyle`(iOS 18+) 在 Catalyst 不可用。
- `Platform/PlatformRepresentable.swift`：UIKit typealias（PlatformView / Color / Image / Font）。
- `Platform/PlatformCompatibility.swift`：iOS / Catalyst SwiftUI modifier wrapper；含取 `UIWindowScene` 的先例（`connectedScenes.compactMap { $0 as? UIWindowScene }.first`）。
- `Platform/MacWindowChrome.swift`：Catalyst 視窗 chrome 單一來源。`.defaultSize` / `.windowResizability` 在 Catalyst **靜默無效**，視窗尺寸改走 UIKit `sizeRestrictions.minimumSize` + `requestGeometryUpdate(.Mac(...))`，尺寸常數集中此處。Reader 沉浸 title bar 走 `setTitlebarHidden` **scoped 可逆**（進 Reader 隱藏、離開復原，不可在 App 啟動時全域設死，否則其他頁失去標題列）。
- Reader 系列以 `#if os(iOS)` 整檔隔離 —— Catalyst 下 `os(iOS)` true **仍編譯仍啟用**（非死碼）。
- 其餘 View 共用，平台差異以條件編譯處理。

**指標 / hover 回饋**（`UIComponents/HoverHighlight.swift`）：

- `.appHoverLift()`：卡片 hover 時輕微 scale 浮起（1.02）。卡片屬按鈕互動，scale 合 Motion Contract；已 gate `accessibilityReduceMotion`（Reduce Motion 退回無 transform）。
- `.appHoverRowTint()`：扁平可點 list-row hover 時 bg tint（`primaryText.opacity(0.05)`，只動 background，合「非按鈕互動禁 transform」）。卡片型可點走 `.appHoverLift` / 既有 `.liftable`，不重複套 tint。
- **不分流**：`.onHover` 在純觸控 iPhone 無指標事件自動 no-op，iPad 觸控板 + Mac Catalyst 共益，故 hover modifier **不**包 `#if`。
- **欄寬游標**（`Platform/MacColumnResizeCursor.swift`，**Catalyst-only**）：`.pointerStyle`(iOS 18+) 在 Catalyst 不可用，改走 UIKit `UIPointerInteraction` + `UIPointerStyle(shape: .verticalBeam(length:))`，疊到 `DraggableDivider`。其 `PassthroughPointerView` 對 `event.type == .touches` 的 hitTest 回 nil（touch 穿透到底下 SwiftUI `dragGesture` / 雙擊），hover 才回 self（pointer region 生效），故游標與拖曳並存不衝突。

---

## Motion Contract

Books & Vocab 的 motion system 不接受各頁自由書寫 `.spring(...)` / `.easeOut(...)`。
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
| `cardDeckRelease` | `spring response=0.28, dampingFraction=0.85` | `NotebookDeckButtonStyle` release/cancel 回彈（press-in 走 `TapFeedback.animation`） |

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
  回到 `docs/sop/ios.md`
- 若是要理解 UI 為何出現在某個資料流程中：
  回到 `docs/sop/architecture.md`
- 若是要新增 spacing/radius/elevation 數值：
  先在 `AppSpacing` / `AppRadius` / `AppElevation` 加 token，不可在 view 寫 magic number

---

## Layout / Spacing / Elevation token（Models/AppMetrics.swift）

PR #402 七階段升級補完語意分層。新元件優先使用以下 token，舊 `AppMetrics.spacing*` 保留為相容別名。

| Token tier | 內容 | 採用率 |
|-----------|------|--------|
| `AppSpacing` | 8pt grid：`s0=0/s1=4/s2=8/.../s7=64`、`hairline=1`；語意 alias `cardOuterPadding/innerGap/sectionGap` | 部分 — 新元件已切，舊 view 仍多 raw 數字 |
| `AppRadius` | `xs=4/sm=8/md=12/lg=16/xl=24/pill=999`；禁用鄰近半階值（7/9/13/14/18） | 部分 |
| `AppElevation` | `z0...z4` 替代 `paperFloat`/`cover`/`panel` 命名；`.appElevation(.zN)` modifier；dark mode 透過 `AppElevationModifier` 自動加強 opacity | **live — 全 app shadow 唯一入口，~24 callsites**（AppSurface / AppToast / Card / cover / overlay / 各 presenter）。raw `.shadow(...)` 一律改走此 token。 |
| `AppFonts.hero` / `TypeScale.hero` | 40pt serif hero typography（`TypeScale`：caption2/caption/subhead/body/h2/h1/hero，無 display1/2）；`AppFonts.hero(weight:)` 取用 | 視場景使用 |
| `AppFonts.Tracking` / `LineSpacing` | letter-spacing / 行高 token | 部分 |

舊 `AppShadows.panelOpacity` 在本 PR 由 0.70 → 0.18（paper-tone shadows）；後續逐步以 `AppElevation` 取代分散的 paperFloat/cover/panel 命名。

### Editorial imperfection / static rotation

某些 editorial 元件（如 `NotebookStackedCoverView` 的 cream paper ghost）需要 deterministic 微旋轉帶入「桌上隨手疊」手感。**Rotation 屬 layout 非 motion** 時 — i.e. 角度在 mount 後不再改變、不隨 state 動畫 — `accessibilityReduceMotion` **不關閉** rotation。Apple HIG 的 RM 規範針對動態 motion；靜態 visual rotation 與 Wallet/Books 既有圖示同性質、不適用 RM gate。

落地規則：
- Rotation 角度由 deterministic seed 推得（如 `NotebookStackMetrics.stableSeed(for:)` djb2 over utf8），**禁用 `String.hashValue`**（per-process random seed 會導致跨 launch 角度跳動）
- Rotation 不參與 press / 任何 state transition
- Reduce Motion 仍關 offset/scale 動畫；只保留 rotation 與 opacity dip

Precedent callsite：`NotebookStackedCoverView` editorial stack。

---

## Color token：Brand Hero + 狀態 bg

`AppColors.brandHeroLight` `#FCDE9A` (HSB ~41°/0.39/0.99) / `brandHeroDark` `#FCDE9A` (兩 mode 同色) + `AppColors.brandHero(_:)` scheme-aware accessor。色相為極淡奶黃 pastel cream(Phase 1c)，與 `accent`(Morandi blue) 分家 — `brandHero` 主 CTA，`accent` 退為被動點綴。`onBrandHero` 採 `#1C1A17` 深炭灰(白字 fail AA)，配新奶黃對比 ~13.5:1 ✓ AAA。**`tint` 走灰階 chrome** (`tintLight #37352F` / `tintDark #E6E6E3`)，不再跟 brandHero — chrome ≠ CTA。

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

1. ~~**`AppOfflineBanner` light mode 對比 ≈ 3.21:1**~~ — 已解除。banner 前景已是 `primaryText`（灰階高對比）非 destructive 紅字；primaryText 疊於 destructiveBg（destructive 10~14% tint over pageBackground）實測 light ~9.85:1 / dark ~11.6:1 ✓ WCAG AAA。原 3.21:1 為「紅字當前景」的舊設計數據，已不適用。
2. ~~**`accentHero` dark mode footgun**~~ — 已解除。Phase 1b 起 brandHero 改奶黃，前景採 `AppColors.onBrandHero` deep charcoal `#1C1A17`，light/dark 變體配 onBrandHero 對比 5.11/7.05:1 ✓ AA/AAA。
3. ~~**`AppCompactActionButtonStyle` primary foreground raw `.white`**~~ — 已解除。改走 `AppColors.onBrandHero` token；奶黃 + 白字 fail AA → onBrandHero 強制 deep charcoal 是 token-level 保證。
4. **低採用率 tokens**：`AppSkeletonLine` 目前無外部直接 callsite（僅 def + `AppSkeletonCard` 內部 + preview）；`AppSkeletonCard` 已用於 `VocabSceneShell`、`AppElevation` 已是全 app shadow 唯一入口（~24 callsites）。注意 PR #402 曾規劃的 `display1/2` / `appReadableFrame` / `AppLayout` token **從未進入 codebase**，勿引用。

---

## Component Hard Rules（防破圖）

以下規則適用所有 list row / inline metric / 中英混排場景。新元件 PR 違反 → review block。

1. **List row 內所有 user-content text 必須有 `.lineLimit(n)` + `.truncationMode(.tail)`**  
   不限定 row 高度時，至少要 truncate 而非 wrap 撐高（破壞 list 節奏）。Word/title 一般 `lineLimit(1)`；中譯/說明可 `lineLimit(2)` 但仍要 truncate。
2. **數字 metric 一律 `.monospacedDigit()`**  
   `42d / 2d`、百分比、進度、剩餘秒數等任何會動態變動的數字。避免比例字寬抖動。例：`VocabReviewProgressBar.detailLabel`、`WordRow.trailingLabel`。
3. **同 row 含 text + spacer + button 時 spacer 必須有 `minLength: 8`**  
   防止內容擠壓到 trailing element 黏 leading text。
4. **partOfSpeech / unit / 短 label 用 `.fixedSize(horizontal: true, vertical: false)`**  
   保留視覺重量，防止被中間 text 撐到換行。
5. **新增高密度 list 元件時，必加對應 `Debug/Scenarios/*Scenarios.swift`**  
   涵蓋 happy / long-content / large-numbers / narrow-width / dynamicTypeSize(.accessibility3) 五種 stress case，作為 visual baseline。範例：`NotebookListScenarios.swift`、`BookCardScenarios.swift`。

> Phase 2(2026-05) 起 `WordRow` / `VocabReviewProgressBar` 已套用上述規則。新元件 PR Reviewer 看到缺漏直接退件。

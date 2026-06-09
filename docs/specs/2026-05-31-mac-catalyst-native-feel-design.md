<!-- doc-meta
tier: archive
authority: derived
update_trigger: design-decision
scope:
  - ios/BooksAndVocab/BooksAndVocabApp.swift
  - ios/BooksAndVocab/ContentView.swift
  - ios/BooksAndVocab/Platform/LayoutMode.swift
  - ios/BooksAndVocab/Platform/PlatformCompatibility.swift
  - ios/BooksAndVocab/Views/Reader/ReaderView.swift
  - ios/BooksAndVocab/Views/Vocabulary/MacDividerHandle.swift
  - ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift
  - ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift
  - docs/sop/ui-design.md
verified_against: frozen
-->
# KG Mac Catalyst 原生化 — Umbrella Design Spec

## 性質

**這是 umbrella spec,不是單一 plan 的 spec。** 它訂下整體架構決策與四個 workstream 的範圍/取捨/排除。**每個 workstream(A/B/C/D)各自落成一份獨立 plan**,各自獨立 PR、獨立 phased-workflow 執行、逐項 review。reviewer 評 scope 時請以「umbrella + 四個子 plan」框架評斷,而非「一個 spec 對一個 plan」。

## Context

KG 已從 designed-for-iPad 遷移到 Mac Catalyst(`SUPPORTS_MACCATALYST = YES`,commit `fde67689`/`144d9528`/`c042c06b`/`dfc4e216`/`0c817d34`)。Mac 版目前仍是「iPad app 套殼」觀感:底部 TabView、無選單列、視窗手機直式比例、零滑鼠 hover 回饋。使用者要求 Mac 版「更像原生 mac app」,四個面向全做。

選 Catalyst 而非原生 macOS 的決定性原因:核心依賴 **Readium swift-toolkit 只宣告 `platforms: [.iOS]`**,原生 macOS(AppKit)拿不到閱讀器。Catalyst 底層仍是 iOS UIKit,Readium 照用。

**架構前提(四面向定論,經平行盤點):**
- 根導覽 `ContentView.swift:21-43` = `VStack { DemoBanner? ; TabView{ 書庫 / 單字本 / 總覽 } }`,外掛 offlineBanner + toastOverlay。
- 三個 tab 各自持有獨立 `NavigationStack`;Reader/Podcast 是 `BookshelfView` stack 內 `navigationDestination` push,非獨立 window。
- 全 codebase **零 hover 基礎建設**(`.hoverEffect`/`.onHover`/`UIPointerInteraction` 全 0 命中)。
- App scene 是裸 `WindowGroup`,**無** scene modifier、**無** SceneDelegate、Info.plist scene manifest 由 build setting 生成。
- App-level commands **零**;唯一鍵盤系統是 TodayReview 的局部 `.onKeyPress`。

## Cross-cutting 鐵律(四個 workstream 共用)

1. **Mac 專屬分流一律 `#if targetEnvironment(macCatalyst)`**,禁 `#if os(macOS)`(死碼,Catalyst 下 `os(macOS)`=false)。hover 是唯一例外——iPad 觸控板/妙控同樣受益,該層用 size-class 或不分流。
2. **iPhone / iPad 行為零回歸**:所有 Mac 改動走分流,compact 與 iPad 既有版面、導覽、touch target 不變。iPad 維持 TabView(不走 sidebar)。
3. **既有 `#if os(iOS)` whole-file guard(BookshelfView 等 68 檔)在 Catalyst 仍編譯仍 active**,別誤判「mac 沒這頁」;新分流用 `targetEnvironment(macCatalyst)`,且書庫在 Catalyst 必須在。
4. **L10n 鐵律延伸**:menu 標題/item label 必走 `L10n.string(_:)`。`ops/i18n_lint.sh` 的 regex **擋不到** `CommandMenu("中")`,review agent 必須顯式把關。
5. 每個 workstream 獨立 PR;每完成一個 fix/feature 立即 dispatch review agent,PASS 才下一步;TDD 先紅後綠。

## Goals

讓 KG Mac 版在四個維度具備原生 mac app 觀感與操作:側欄導覽、頂部選單列+全域快捷鍵、像樣的視窗尺寸與沉浸閱讀、滑鼠 hover/指標精準回饋。

## Non-Goals(YAGNI,本輪明確不做)

- iPad 改 sidebar(只 Catalyst 走 split,iPad 維持 TabView)。
- 單字本 inline detail panel(`DetailRouter` + `DraggableDivider`)升級成 three-column `NavigationSplitView`——現有手刻 panel 保留不動。
- `platformFullScreenCover`(`PlatformCompatibility.swift:23-38`)改 Mac 原生呈現——列為 known debt,本輪不碰。
- `UISupportsTrueScreenSizeOnMac` 真實點數座標——改座標系、衝擊 `LayoutMode` 720 寬度假設,高 regression,需獨立 PR + 全視覺回歸,本輪不做。
- TodayReview 的 Space/箭頭/d/s/p 升級成全域 menu shortcut——會干擾文字輸入,明確不做,維持局部 `.onKeyPress`。
- 雙擊開啟改單擊選取的 mac list 慣例——大改,延後。
- mac 多視窗(multi-window)——KG 是單視窗 + TabView/NavigationStack 架構,不引入。

---

## Workstream A — 視窗外觀(window chrome)

**目標:** Mac 視窗有像樣的預設尺寸、最小尺寸,Reader 進入時沉浸(隱 title bar)、退出復原。

### 技術決策

- **A-D1 主力走 UIKit,非 SwiftUI scene modifier。** `.defaultSize` / `.windowResizability` 在 Catalyst **靜默無效**(為原生 macOS 設計)。最小尺寸用 `windowScene.sizeRestrictions?.minimumSize`,首發尺寸用 `windowScene.requestGeometryUpdate(.Mac(...))`(iOS 16+,Catalyst 可靠)。SwiftUI modifier 至多當 fallback。
- **A-D2 取 scene 不加 SceneDelegate。** 沿用 `PlatformStore`(`PlatformCompatibility.swift:115-122`)既有先例:`UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first`,在 root view `.onAppear` 設定。**不** 動 generated scene manifest、不加 `@UIApplicationDelegateAdaptor`(改 build 生成路徑風險高)。
- **A-D3 Reader 沉浸 title bar 必須 scoped 可逆。** Reader 與書庫/單字本共用同一 window,不能 app 啟動時一次性隱藏 title bar(否則所有 tab 失去標題列)。進 `ReaderView`(`.onAppear`)設 `titlebar?.titleVisibility = .hidden`,`onDisappear` 復原,與既有 `ReaderChromeState` 整合。建議首發尺寸 1100×760、最小尺寸防縮成手機條。

### 不動

Info.plist、scene manifest、`LayoutMode` 720 寬度假設、iPad orientation。

### 風險

- 取 `connectedScenes.first` 在單視窗 app 安全;`.defaultSize` 可能誤以為生效。
- title bar 全域隱藏會誤傷非 Reader 頁——沉浸只能 scoped,需可逆狀態管理。

---

## Workstream B — 指標 / hover

**目標:** 滑鼠懸停有高亮回饋、可拖曳分隔線有 resize 游標、右鍵選單補齊、mac 下 touch target 不鬆散。

### 技術決策

- **B-D1 新建 `.appHoverHighlight()` ViewModifier,不直接用系統 `.hoverEffect`。** 內部 `.onHover { }` + app 既有 `AppElevation`/opacity token 自繪高亮,保持 Notion 風格設計一致(系統 `.hoverEffect` 預設樣式可能不吃 `cardBackground`)。先套 BookCard / PodcastSeriesCard / NotebookCard,再擴及可點 row。**此層 iPad 共益**,用 size-class 或不分流。
- **B-D2 contextMenu 免費受益 + 補缺。** Catalyst 下 `.contextMenu` 自動變右鍵選單,既有 8 處(BookshelfView 刪書、NotebookCard、WordDetail、CardSections×5 等)無需改。補缺:PodcastSeriesCard(`BookshelfView.swift:264` 無 contextMenu)、設定/總覽可點 row。新增 item 走 L10n。
- **B-D3 divider resize 游標走 UIKit。** `.pointerStyle`(iOS 18+)在 Catalyst SDK **不可用**(已驗證編譯錯)。做 `MacResizeCursorView: UIViewRepresentable` 內含 `UIView` + `UIPointerInteraction`,`pointerInteraction(_:styleFor:)` 回 `.verticalBeam`,以 `.overlay`/`allowsHitTesting(false)` 疊到 `DraggableDivider`(`MacDividerHandle.swift`)hit area,不擋既有 `highPriorityGesture`。`#if targetEnvironment(macCatalyst)` 包。
- **B-D4 touch-target 緊縮必須分流,不可改全域常數。** `minHeight: 50`(`AppShellComponents+Styles.swift:121,135,149`)、`iconButtonSize: 52`(`AppMetrics.swift:24`)、按鈕 padding 為觸控 44pt+ 設計,全域改會破 iPhone HIG。抽成 `targetEnvironment(macCatalyst)`-aware 較密值。**此項風險最高,放 B 的最後階段。**

### 風險

- `.onHover` 在大 LazyVGrid 每 cell `@State isHovered` 增 view body 重算,需驗卷動效能 + Inject 熱重載。
- `UIPointerInteraction` region 與 8pt hit area 對齊,否則游標跳變。

---

## Workstream C — 選單列 + 全域快捷鍵

**目標:** 頂部選單列(Catalyst-only)接全 app 核心動作 + Cmd 快捷鍵。

### 技術決策

- **C-D1 混合觸發機制。** 動作分散在 per-view coordinator(非 app-singleton),menu 在 scene 層宣告,無法直接 reference。故:
  - **全域恆定動作走 app-level `AppCommandCoordinator`**(新建 `@Observable`,比照既有 `syncCoordinator`/`toastCoordinator` 在 `BooksAndVocabApp.swift:118-121` 注入 environment)。持 intent flag,`.commands` 設、各 view `.onChange` 消費。接:**設定 ⌘,**(`CommandGroup(replacing: .appSettings)`)、**立即同步 ⌘R**(`kgService.backgroundSync`)。
  - **畫面相關動作走 `.focusedSceneValue`**,menu `@FocusedValue` 取出 + `.disabled(action == nil)` 自動 enable/disable。接:**匯入書籍 ⌘I**(BookshelfView)、**新增單字本 ⌘N**(NotebookListView,需登入 gate)、**開始今日複習 ⌘⏎**(預設「全部」模式)。
- **C-D2 `.commands {}` 整段 gate `#if targetEnvironment(macCatalyst)`**,避免 iPad 外接鍵盤出現多餘 menu。
- **C-D3 搜尋 ⌘F** 已存在(`VocabularyListPresenter.swift:52` 隱藏 Button)。整合進 Edit menu(`CommandGroup(after: .textEditing)`),確保不與既有隱藏 Button 重複觸發。
- **C-D4 TodayReview 局部快捷鍵維持不動**;僅在 View menu 補「今日複習快捷鍵說明…」觸發既有 `showHelp` overlay 做 discoverability。
- **C-D5 menu 標題/label 全走 `L10n.string(_:)`**;可複用現成 key:`"匯入"`、`"新增單字本"`、`"今日複習"`、`"全部複習（%@）"`、`"快捷鍵"` 等。

### 風險

- 焦點/responder chain:sheet(設定/匯入/複習 modal)開著時 menu 該 disable 或轉發,需逐一定義。
- 登入/demo gate:新增單字本/同步/複習依登入狀態,menu enable 須同步反映。
- i18n linter 對 `CommandMenu` 標題是盲區,靠 review 把關。
- ⌘1/2/3 切 section **不在 C**,歸入 D(需 selection/section 概念)。

---

## Workstream D — 側欄導覽(壓軸,風險最高)

**目標:** Catalyst 下根導覽從底部 TabView 改成左側 `NavigationSplitView` sidebar;iPad/iPhone 維持 TabView。

### 技術決策

- **D-D1 兩欄 `NavigationSplitView`(sidebar + detail),非三欄。** sidebar 列三 section(書庫/單字本/總覽),detail = 既有 tab 根 view **原封不動**。三欄會與單字本既有 inline detail panel 打架,故只動 root 這一層。
- **D-D2 抽 `RootSection` enum + section→view 對應,TabView 與 sidebar 共用。** `#if targetEnvironment(macCatalyst)` 走 split、`#else` 走既有 TabView(分流靠 `targetEnvironment(macCatalyst)`,**不靠** size class——Catalyst 視窗縮小會變 compact)。書庫在兩個分支都要有。
- **D-D3 Reader / Podcast / DetailRouter / 單字本 inline panel 完全不動。** sidebar 只切 section,深層導覽完全沿用各 tab 既有 `NavigationStack`(Reader/Podcast push)與 `NotebookListView` 的 `DetailRouter` + `NotebookDetailPresentation`。sidebar 改造不需動 Reader/Podcast/DetailRouter 任何一行。
- **D-D4 ⌘1/2/3 切 section** 在此 workstream 落地(此時才有 `RootSection` selection binding 可綁)。
- **D-D5 DemoBanner / offlineBanner / toastOverlay 原地保留**(都在 ContentView/App 層,與 split 無關)。

### 不動

Reader/Podcast 導覽、DetailRouter、DraggableDivider inline panel、各 tab 內部。

### 風險

- **書庫消失風險**:分流時若把書庫包進純 iOS `#else`,Catalyst 會丟書庫。書庫必須在 split 與 TabView 兩分支都在。
- `.id(appLanguage.selection)`(`BooksAndVocabApp.swift:109`)切語言重建整棵 tree,sidebar `@State selection` 會 reset——需確認可接受(回預設 section)或還原。
- Catalyst 視窗縮放使 size class 變動,須驗證單字本 inline panel 不異常 dismiss(`NotebookDetailPresentation.swift:101-106`)。
- toolbar placement 在 NavigationSplitView 下落點改變(sidebar toolbar vs detail toolbar),settings/import/sort/archive 按鈕需逐一驗證仍在預期欄位。

---

## 執行順序與依賴

**A 視窗 → B hover → C 選單列 → D 側欄**(風險遞增 + 依賴):

1. **A 先做**:風險最低、立即見效,建立「取 `UIWindowScene`」pattern 供後續複用。
2. **B 次之**:獨立、iPad 共益、低風險。
3. **C 第三**:中風險,需 `AppCommandCoordinator` 基礎設施。
4. **D 壓軸**:動根導覽、風險最高,放最後讓前三者先穩;⌘1/2/3 併入 D。

跨 workstream 無硬性程式碼依賴(各自獨立 PR),順序純為風險管理。C 的 ⌘1/2/3 刻意延到 D。

## Doc 同步(doc-as-code)

- `docs/sop/ui-design.md:50-54`「macOS 平台適配」段**已過時**(仍寫「Reader 以 `#if os(iOS)` 整檔隔離,macOS 暫不啟用」)。需於相關 workstream PR 內更新為 Catalyst hover/pointer/window 規範(`.pointerStyle` 禁用理由、`UIPointerInteraction` 路徑、`.appHoverHighlight()` 用法、window chrome UIKit 路徑)。
- 新增 user-facing 能力(選單列、快捷鍵)→ `docs/reference/product_surface.md` 追加 bullet。
- 新 env/scene 行為、新 modifier → `docs/reference/tech_index.md` 同步。

## 各 workstream → 獨立 plan

| Workstream | Plan 檔名(待寫) |
|---|---|
| A 視窗外觀 | `docs/plans/2026-05-31-mac-window-chrome.md` |
| B 指標/hover | `docs/plans/2026-05-31-mac-pointer-hover.md` |
| C 選單列 | `docs/plans/2026-05-31-mac-menu-commands.md` |
| D 側欄導覽 | `docs/plans/2026-05-31-mac-sidebar-navigation.md` |

每份 plan 經獨立 plan-document-reviewer loop + 使用者確認後,交 phased-workflow 執行。

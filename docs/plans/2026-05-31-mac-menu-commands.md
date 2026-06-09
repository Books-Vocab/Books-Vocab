<!-- doc-meta
tier: archive
authority: derived
update_trigger: plan-execution
scope:
  - ios/BooksAndVocab/Platform/
  - ios/BooksAndVocab/BooksAndVocabApp.swift
  - ios/BooksAndVocab/Views/Bookshelf/
  - ios/BooksAndVocab/Views/Vocabulary/
verified_against: frozen
-->
# Plan: Workstream C — Mac Catalyst 選單列 + 全域快捷鍵

umbrella spec:`docs/specs/2026-05-31-mac-catalyst-native-feel-design.md` §Workstream C。

**目標**:Catalyst-only 頂部選單列接全 app 核心動作 + ⌘ 快捷鍵。iPhone/iPad 零回歸。

## Cross-cutting 鐵律

- 整段 `.commands {}` 與所有新增 menu code gate `#if targetEnvironment(macCatalyst)`(C-D2:避免 iPad 外接鍵盤冒出多餘 menu)。
- menu 標題/label 全走 `L10n.string(_:)` / `L10n.format`(C-D5)。**`ops/i18n_lint.sh` 擋不到 `CommandMenu("中")`,review agent 顯式把關**。
- 複用現成 L10n key,不新增(全部已 verify 存在):`"匯入"`(zh-Hant:43)、`"新增單字本"`(:656)、`"今日複習"`(:574)、`"全部複習（%@）"`(:452)、`"設定"`(:150)、`"同步"`(:29,**`"立即同步"` key 不存在,menu label 用 `"同步"`**)、`"顯示快捷鍵"`(:795)、搜尋 menu label 用 **`"搜尋單字"`(:97)**(與 in-view search prompt `VocabularyListPresenter.swift:28` 一致,使用者心智統一;`"搜尋"` 裸 key **不存在**)。
- 逐 task review,PASS 才下一個。

## 既有事實(plan 依據,已 verify)

- `BooksAndVocabApp.swift`:`WindowGroup` `:81-92`,後僅接 `.modelContainer` `:92`,**目前無任何 `.commands`**。app 持有 `let kgService`(:22)、`@State modelContainer`(:19)、`let syncCoordinator`(:31)、`let toastCoordinator`(:32);env 注入在 `mainAppContent` `:98-122`。
- coordinator pattern:`@Observable @MainActor final class`(SyncCoordinator.swift:50);env key 在 `Services/AppEnvironment.swift`(`EnvironmentKey` + `EnvironmentValues` accessor,:51-97)。
- `kgService.backgroundSync(container: ModelContainer) async`(KGService+Sync.swift:143);**無時間 cooldown,僅併發互斥** `claimBackgroundSync()` + 離線跳過。app 直接持 `modelContainer` 可呼叫。
- 匯入:`coordinator.presentImporter()`(BookshelfCoordinator.swift:17/38),**無登入 gate**。
- 新增單字本:NotebookListView.swift `showCreateSheet = true`(:187),**`.disabled(!authManager.isLoggedIn)`**(:198)。
- 今日複習「全部」:`startReview(with: filteredDueEntries + filteredUnlearnedEntries)`(NotebookListView.swift:108),設 `activeReviewSession`(:42)。
- ⌘F:`VocabularyListPresenter.swift:52 .keyboardShortcut("f", modifiers: .command)`(隱藏 Button,:45-56),**全庫唯一 keyboardShortcut**。
- 設定入口:`coordinator.presentSettings()` → `showSettings` → `.toastSheet { SettingsView() }`(BookshelfView.swift:105/143);`SettingsView()` 無參(:105)。
- **`.focusedSceneValue`/`@FocusedValue`/`FocusedValueKey` 全庫 0 先例**。

---

## Task 1: `AppCommandCoordinator` 基建 + app-global 命令(設定 ⌘, / 同步 ⌘R)

**Files:**
- Create: `ios/BooksAndVocab/Platform/AppCommandCoordinator.swift`
- Create: `ios/BooksAndVocab/Platform/MacMenuCommands.swift`(`Commands` 結構,Catalyst-only)
- Modify: `ios/BooksAndVocab/Services/AppEnvironment.swift`(env key)
- Modify: `ios/BooksAndVocab/BooksAndVocabApp.swift`(持有 + 注入 + `.commands`)

- [ ] **Step 1: `AppCommandCoordinator`** — `@Observable @MainActor final class`,持 app-global 命令 intent:
```swift
import SwiftUI
@Observable @MainActor
final class AppCommandCoordinator {
    /// ⌘, 觸發 — root view 觀察並以 sheet 呈現 SettingsView。
    var presentingSettings = false
}
```
(同步 ⌘R 不需 flag:app 直接持 `kgService` + `modelContainer`,命令內 `Task { await kgService.backgroundSync(container: modelContainer) }`。)

- [ ] **Step 2: env key** — `AppEnvironment.swift` 比照 SyncCoordinatorKey 加 `AppCommandCoordinatorKey`(`MainActor.assumeIsolated { AppCommandCoordinator() }`)+ `EnvironmentValues.appCommandCoordinator` accessor。

- [ ] **Step 3: app 持有 + 注入** — `BooksAndVocabApp.swift`:`let appCommandCoordinator = AppCommandCoordinator()`(:32 旁);`mainAppContent` 加 `.environment(\.appCommandCoordinator, appCommandCoordinator)`。

- [ ] **Step 4: root 觀察 settings flag** — `mainAppContent` 的 `rootView` 加(gate macCatalyst)`.toastSheet(isPresented: ...)` 呈現 `SettingsView()`;binding 取 `appCommandCoordinator.presentingSettings`。**雙開決策(已定論)**:root settings sheet(⌘,)與既有 per-view toolbar gear sheet(`coordinator.showSettings`)是兩條獨立 state,跨-view state 不可見故無法程式互斥。決策:**接受兩條獨立路徑,靠 SwiftUI「已有 sheet 呈現時第二個 presentation 被忽略」的行為自然防疊**(實測若 race 出現 console warning 屬無害);⌘, 走 root sheet 為 app-level 唯一路徑,不加跨-view 協調(YAGNI)。

- [ ] **Step 5: `MacMenuCommands`** — 新檔,`#if targetEnvironment(macCatalyst)` 整檔:
```swift
struct MacMenuCommands: Commands {
    var coordinator: AppCommandCoordinator
    var kgService: any KGServing
    var modelContainer: ModelContainer
    var body: some Commands {
        CommandGroup(replacing: .appSettings) {
            Button(L10n.string("設定")) { coordinator.presentingSettings = true }
                .keyboardShortcut(",", modifiers: .command)
        }
        CommandGroup(after: .newItem) {
            Button(L10n.string("同步")) {
                Task { await kgService.backgroundSync(container: modelContainer) }
            }.keyboardShortcut("r", modifiers: .command)
        }
    }
}
```
- [ ] **Step 6: 掛上 WindowGroup** — `BooksAndVocabApp.swift` `WindowGroup{…}.modelContainer(...)` 後加:
```swift
#if targetEnvironment(macCatalyst)
.commands { MacMenuCommands(coordinator: appCommandCoordinator, kgService: kgService, modelContainer: modelContainer) }
#endif
```
- [ ] **Step 7: build 驗證** — iOS sim build(確認 macCatalyst 分支不參照、無 undefined symbol)+ Catalyst build(確認 menu code 編譯)。
- [ ] **Step 8: Commit** `ios: AppCommandCoordinator + settings/sync menu commands (Workstream C)`

---

## Task 2: 畫面相關命令(匯入 ⌘I / 新增單字本 ⌘N / 今日複習 ⌘⏎)走 focusedSceneValue

**Files:**
- Create: `ios/BooksAndVocab/Platform/FocusedCommandValues.swift`(`FocusedValueKey` 定義)
- Modify: `MacMenuCommands.swift`(`@FocusedValue` 讀取 + `.disabled`)
- Modify: `BookshelfView.swift`、`NotebookListView.swift`(publish `.focusedSceneValue`)

- [ ] **Step 1: FocusedValueKeys** — 三個動作各一,值型別 `() -> Void`(optional):
```swift
struct ImportBookAction { let run: () -> Void }
struct NewNotebookAction { let run: () -> Void }
struct StartReviewAction { let run: () -> Void }
// 各自 FocusedValueKey + Environment…→ FocusedValues extension
```
(用 wrapper struct 避免 closure 直接當 FocusedValue 的限制。)

- [ ] **Step 2: publish** —
  - BookshelfView:`.focusedSceneValue(\.importBook, ImportBookAction { coordinator.presentImporter() })`。
  - NotebookListView:**僅在 `authManager.isLoggedIn` 時** publish `.focusedSceneValue(\.newNotebook, ...)`(未登入不 publish → menu 自動 disable);另 publish `\.startReview`,**僅在有可複習項時**(`!(filteredDueEntries + filteredUnlearnedEntries).isEmpty`)。
- [ ] **Step 3: menu 讀取** — `MacMenuCommands` 加 `@FocusedValue(\.importBook) ...` 等,各 Button `action?.run()` + `.disabled(action == nil)`:
  - 匯入書籍 ⌘I → `CommandGroup(after: .newItem)`
  - 新增單字本 ⌘N → `CommandGroup(after: .newItem)`
  - 開始今日複習 ⌘⏎(`.return`)→ 自訂 `CommandMenu(L10n.string("今日複習"))`
- [ ] **Step 4: build 驗證**(雙 build)
- [ ] **Step 5: Commit** `ios: focused-scene menu commands — import/new-notebook/start-review (Workstream C)`

---

## Task 3: ⌘F 整合進 Edit menu + 今日複習快捷鍵說明

**Files:**
- Modify: `VocabularyListPresenter.swift`(既有隱藏 ⌘F button gate 非-Catalyst)
- Modify: `VocabularyListView`(publish 搜尋 focusedSceneValue)
- Modify: `TodayReviewView.swift`(session active 時 publish `\.showReviewHelp`)
- Modify: `FocusedCommandValues.swift`(加 `ShowReviewHelpAction` / `FocusSearchAction` key)
- Modify: `MacMenuCommands.swift`(Edit menu ⌘F + View menu 說明)

- [ ] **Step 1: 解雙綁** — C-D3 風險:menu ⌘F 與隱藏 button ⌘F 同時存在會雙重綁定衝突。決策:既有隱藏 button 改 `#if !targetEnvironment(macCatalyst)`(iPad 外接鍵盤保留),Catalyst 改由 menu 提供 ⌘F。
- [ ] **Step 2: 搜尋 action** — VocabularyListView publish `.focusedSceneValue(\.focusSearch, ...)`(觸發既有 `searchFocused = true` 等同隱藏 button 行為);僅在 search field 可用時 publish。
- [ ] **Step 3: Edit menu** — `CommandGroup(after: .textEditing)` 加搜尋 Button + `.keyboardShortcut("f", modifiers: .command)` + `.disabled(focusSearch == nil)`。label = `L10n.string("搜尋單字")`(:97,已鎖定)。
- [ ] **Step 4: 快捷鍵說明(C-D4)** — TodayReview 局部快捷鍵(Space/箭頭/d/s/p)**不動**。`showHelp` 是 `TodayReviewView` 的 private `@State isHelpPresented`(:66),僅 review session active 期間存在,scene menu 不可直接觸發 → **定論走 focusedSceneValue**:TodayReviewView 在 session active 時 publish `\.showReviewHelp`(`ShowReviewHelpAction { run }` 翻轉 `isHelpPresented`),自訂 menu 加「`顯示快捷鍵`」(:795)Button `action?.run()` + `.disabled(action == nil)`(非複習中自動 disable)。沿用 Task2 已建的 FocusedCommandValues 基建。
- [ ] **Step 5: build 驗證**(雙 build)+ **i18n review**(CommandMenu/Button label 全 L10n)
- [ ] **Step 6: Commit** `ios: ⌘F into Edit menu + review-shortcut help discoverability (Workstream C)`

---

## Task 4: Doc Sync(走 background doc-sync agent)

完成 Task 1-3 後,**派 background doc-sync agent**(`docs/sop/doc_sync.md`)同步 Task 1-3 的 commit range:
- `product_surface.md` Mac Catalyst bullet 追加「頂部選單列 + ⌘ 快捷鍵(設定/同步/匯入/新增單字本/今日複習/搜尋)」。
- `tech_index.md` Platform 層追加 `AppCommandCoordinator` / `MacMenuCommands` / `FocusedCommandValues`。
- `ui-design.md` Mac Catalyst 段補一句選單列觸發機制(app-global coordinator vs focusedSceneValue 分流)。
主線不阻塞,agent 自 bump verified_against + docs_lint + `docs:` commit。

---

## Non-Goals(明確不做)

- TodayReview 的 Space/箭頭/d/s/p **不**升級成全域 menu shortcut(會干擾文字輸入),維持局部 `.onKeyPress`。
- ⌘1/2/3 切 section → 歸 Workstream D(需 selection/section 概念)。
- 不引入 `SceneDelegate`(沿用 `connectedScenes` 先例)。
- 不為 menu 新增 L10n key(複用現成)。

## 驗收策略(TDD 誠實標註)

menu command 副作用(scene-level focus 傳遞、`Commands.body` 重算、`@FocusedValue` enable/disable)**無法穩定單元測** — 不寫 XCTest 屬刻意誠實,非偷懶。驗收 = (a) iOS sim build + Catalyst build 雙綠;(b) Catalyst 手動驗 enable/disable matrix:登入/未登入 × 在書架/單字本/複習中 × sheet 開/關,各命令 enable 狀態正確、觸發行為正確、L10n label 正確。每 task 完成派 review agent 把關(含 i18n:CommandMenu label 全 L10n,linter 盲區靠 review)。

## 風險

- **⌘R 是第三條 sync 觸發點**:既有 scenePhase `.active`(BooksAndVocabApp.swift:197)+ post-login(:174)已各觸發 sync,⌘R 為第三條。三者共用 `claimBackgroundSync()` 併發互斥,連按/併發無害不重入。
- **focus / responder chain**:sheet(設定/匯入/複習 modal)開著時 focusedSceneValue 可能仍 active → menu 命令在 modal 上觸發。實作時逐一驗證 modal 開啟時對應命令 disable 或無害。
- **登入/demo gate**:新增單字本依 `isLoggedIn`,以「未登入不 publish focusedSceneValue」自動反映 menu disable;切換登入狀態時 focus 重算須驗證。
- **單視窗 focus**:Catalyst 單 window 下 focusedSceneValue 是否穩定傳遞 — 0 先例,Task 2 首次落地需 Catalyst 實機/模擬驗證 menu enable/disable 正確。
- **⌘R 無 cooldown**:連按觸發多次 backgroundSync,靠既有 `claimBackgroundSync()` 併發互斥擋,不會重入;可接受。

//
//  MacMenuCommands.swift
//  Books & Vocab
//
//  Mac Catalyst 頂部選單列 + ⌘ 快捷鍵。整檔 Catalyst-only —— iPhone/iPad 不編譯,
//  避免 iPad 外接鍵盤冒出多餘 menu。menu label 全走 L10n(i18n_lint 擋不到 CommandMenu)。
//

import SwiftUI
import SwiftData

#if targetEnvironment(macCatalyst)
struct MacMenuCommands: Commands {
    var coordinator: AppCommandCoordinator
    var kgService: KGService
    var modelContainer: ModelContainer
    var toastCoordinator: AppToastCoordinator
    var authManager: any AuthManaging

    // 畫面相關動作 — view 經 .focusedSceneValue publish,無 publish 時 nil → menu 自動 disable。
    @FocusedValue(\.importBook) private var importBook
    @FocusedValue(\.newNotebook) private var newNotebook
    @FocusedValue(\.startReview) private var startReview
    @FocusedValue(\.focusSearch) private var focusSearch
    @FocusedValue(\.showReviewHelp) private var showReviewHelp

    var body: some Commands {
        // 設定 ⌘, — 取代系統 App menu 的 Settings 項
        CommandGroup(replacing: .appSettings) {
            Button(L10n.string("設定")) {
                coordinator.presentingSettings = true
            }
            .keyboardShortcut(",", modifiers: .command)
        }

        // 立即同步 ⌘R — 置於 App menu(設定下方),語意為全域資料動作,任一畫面可觸發。
        // 經 `ExplicitSync` 與書架 toolbar 鈕 / pull-to-refresh 共用同一資格 gate(登出 /
        // demo → no-op)+ 回饋政策(成功彈確認 toast、失敗 warning + read-then-clear);
        // 底層 claimBackgroundSync() 仍與 scenePhase/post-login 併發互斥,不重入。
        CommandGroup(after: .appSettings) {
            Button(L10n.string("同步")) {
                Task {
                    await ExplicitSync.run(
                        kgService: kgService,
                        isLoggedIn: authManager.isLoggedIn,
                        isDemoMode: authManager.isDemoMode,
                        container: modelContainer,
                        toastCoordinator: toastCoordinator
                    )
                }
            }
            .keyboardShortcut("r", modifiers: .command)
        }

        // 匯入書籍 ⌘I / 新增單字本 ⌘N — File menu。`replacing: .newItem` 取代 SwiftUI 自動
        // 注入的「新增視窗 ⌘N」(requestNewScene:),否則 Catalyst 啟動即因 ⌘N 重複綁定 fatal。
        // KG 為單視窗(多視窗為 Non-Goal),移除 New Window 同時讓 ⌘N 回歸 app 主要新增動作。
        // disabled 由 focusedSceneValue 有無決定。
        CommandGroup(replacing: .newItem) {
            Button(L10n.string("新增單字本")) { newNotebook?.run() }
                .keyboardShortcut("n", modifiers: .command)
                .disabled(newNotebook == nil)
            Button(L10n.string("匯入")) { importBook?.run() }
                .keyboardShortcut("i", modifiers: .command)
                .disabled(importBook == nil)
        }

        // 搜尋 ⌘F — 整合進 Edit menu。Catalyst 唯一 ⌘F 來源(隱藏 button 已 gate 非-Catalyst)。
        CommandGroup(after: .textEditing) {
            Button(L10n.string("搜尋單字")) { focusSearch?.run() }
                .keyboardShortcut("f", modifiers: .command)
                .disabled(focusSearch == nil)
        }

        // 今日複習 ⌘⏎ — 預設「全部」模式;複習快捷鍵說明僅 session active 時 enable。
        CommandMenu(L10n.string("今日複習")) {
            Button(L10n.string("複習")) { startReview?.run() }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(startReview == nil)
            Divider()
            Button(L10n.string("顯示快捷鍵")) { showReviewHelp?.run() }
                .disabled(showReviewHelp == nil)
        }
    }
}
#endif

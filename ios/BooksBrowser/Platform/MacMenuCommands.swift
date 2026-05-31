//
//  MacMenuCommands.swift
//  BooksBrowser
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

    // 畫面相關動作 — view 經 .focusedSceneValue publish,無 publish 時 nil → menu 自動 disable。
    @FocusedValue(\.importBook) private var importBook
    @FocusedValue(\.newNotebook) private var newNotebook
    @FocusedValue(\.startReview) private var startReview

    var body: some Commands {
        // 設定 ⌘, — 取代系統 App menu 的 Settings 項
        CommandGroup(replacing: .appSettings) {
            Button(L10n.string("設定")) {
                coordinator.presentingSettings = true
            }
            .keyboardShortcut(",", modifiers: .command)
        }

        // 立即同步 ⌘R — 置於 App menu(設定下方),語意為全域資料動作。
        // app 直接持 kgService + modelContainer,不經 coordinator;與 scenePhase/post-login
        // 的 sync 共用 claimBackgroundSync() 併發互斥,不重入。
        CommandGroup(after: .appSettings) {
            Button(L10n.string("同步")) {
                Task { await kgService.backgroundSync(container: modelContainer) }
            }
            .keyboardShortcut("r", modifiers: .command)
        }

        // 匯入書籍 ⌘I / 新增單字本 ⌘N — File menu。disabled 由 focusedSceneValue 有無決定。
        CommandGroup(after: .newItem) {
            Button(L10n.string("新增單字本")) { newNotebook?.run() }
                .keyboardShortcut("n", modifiers: .command)
                .disabled(newNotebook == nil)
            Button(L10n.string("匯入")) { importBook?.run() }
                .keyboardShortcut("i", modifiers: .command)
                .disabled(importBook == nil)
        }

        // 今日複習 ⌘⏎ — 預設「全部」模式。
        CommandMenu(L10n.string("今日複習")) {
            Button(L10n.string("複習")) { startReview?.run() }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(startReview == nil)
        }
    }
}
#endif

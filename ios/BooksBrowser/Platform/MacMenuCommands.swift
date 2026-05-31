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

    var body: some Commands {
        // 設定 ⌘, — 取代系統 App menu 的 Settings 項
        CommandGroup(replacing: .appSettings) {
            Button(L10n.string("設定")) {
                coordinator.presentingSettings = true
            }
            .keyboardShortcut(",", modifiers: .command)
        }

        // 立即同步 ⌘R — app 直接持 kgService + modelContainer,不經 coordinator。
        // 與 scenePhase/post-login 的 sync 共用 claimBackgroundSync() 併發互斥,不重入。
        CommandGroup(after: .newItem) {
            Button(L10n.string("同步")) {
                Task { await kgService.backgroundSync(container: modelContainer) }
            }
            .keyboardShortcut("r", modifiers: .command)
        }
    }
}
#endif

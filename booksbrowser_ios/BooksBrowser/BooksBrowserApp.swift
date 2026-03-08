//
//  BooksBrowserApp.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData

import GoogleSignIn

@main
struct BooksBrowserApp: App {
    let modelContainer: ModelContainer
    let authManager = AuthManager.shared
    let kgService = KGService()
    let readiumService: any ReadiumServing = ReadiumService.shared
    let bookshelfImportService: any BookshelfImporting
    let bookFileManager: any BookFileManaging

    init() {
        bookshelfImportService = BookshelfImportService(readiumService: readiumService)
        bookFileManager = LocalBookFileManager()
        let schema = Schema([Book.self, VocabularyEntry.self])

        // 先嘗試正常建立
        if let container = try? ModelContainer(for: schema) {
            modelContainer = container
            AuthManager.shared.modelContainer = container
            return
        }

        // 遷移失敗 → 刪除舊資料庫
        print("⚠️ SwiftData migration failed, deleting old database...")

        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let storeFiles = ["default.store", "default.store-wal", "default.store-shm"]
        for file in storeFiles {
            let url = appSupport.appendingPathComponent(file)
            try? FileManager.default.removeItem(at: url)
            print("🗑 Deleted: \(url.lastPathComponent)")
        }

        // 重新建立
        do {
            modelContainer = try ModelContainer(for: schema)
            AuthManager.shared.modelContainer = modelContainer
            print("✅ Database recreated successfully")
        } catch {
            fatalError("Cannot create ModelContainer: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            AppThemeContainer {
                ContentView()
                    .environment(\.authManager, authManager)
                    .environment(\.kgService, kgService)
                    .environment(\.readiumService, readiumService)
                    .environment(\.bookshelfImportService, bookshelfImportService)
                    .environment(\.bookFileManager, bookFileManager)
                    .onOpenURL { url in
                        GIDSignIn.sharedInstance.handle(url)
                    }
                    .task {
                        // 啟動清理：未登入時移除殘留的 KG 同步資料
                        if !authManager.isLoggedIn {
                            let actor = BackgroundSyncActor(modelContainer: modelContainer)
                            try? await actor.clearSyncedData()
                        }
                    }
            }
        }
        .modelContainer(modelContainer)
    }
}

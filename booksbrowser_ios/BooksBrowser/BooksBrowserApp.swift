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
    let subscriptionManager = SubscriptionManager.shared

    init() {
        let schema = Schema([Book.self, VocabularyEntry.self])

        if let container = try? ModelContainer(for: schema) {
            modelContainer = container
            AuthManager.shared.modelContainer = container
            return
        }

        print("⚠️ SwiftData migration failed, deleting old database...")

        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let storeFiles = ["default.store", "default.store-wal", "default.store-shm"]
        for file in storeFiles {
            let url = appSupport.appendingPathComponent(file)
            try? FileManager.default.removeItem(at: url)
            print("🗑 Deleted: \(url.lastPathComponent)")
        }

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
                    .environment(\.subscriptionManager, subscriptionManager)
                    .tint(AppColors.tint)
                    .onOpenURL { url in
                        GIDSignIn.sharedInstance.handle(url)
                    }
                    .task {
                        if !authManager.isLoggedIn {
                            let actor = BackgroundSyncActor(modelContainer: modelContainer)
                            try? await actor.clearSyncedData()
                        }
                        await subscriptionManager.loadProducts()
                        await subscriptionManager.refresh(using: kgService, authManager: authManager)
                    }
            }
        }
        .modelContainer(modelContainer)
    }
}

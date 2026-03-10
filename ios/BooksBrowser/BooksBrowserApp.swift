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
    @StateObject private var appLanguage = AppLanguageStore.shared
    @StateObject private var appearanceStore = AppAppearanceStore.shared
    let modelContainer: ModelContainer
    let authManager = AuthManager.shared
    let kgService = KGService()
    let subscriptionManager = SubscriptionManager.shared
    let readiumService: any ReadiumServing = ReadiumService.shared
    let bookshelfImportService: any BookshelfImporting
    let bookFileManager: any BookFileManaging

    init() {
        NSUbiquitousKeyValueStore.default.synchronize()
        bookshelfImportService = BookshelfImportService(readiumService: readiumService)
        bookFileManager = LocalBookFileManager()

        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self]),
            cloudKitDatabase: .automatic
        )

        if let container = try? ModelContainer(
            for: Book.self, VocabularyEntry.self,
            configurations: localConfig, cloudConfig
        ) {
            modelContainer = container
            AuthManager.shared.modelContainer = container
            Self.runMigrationIfNeeded(container: container)
            return
        }

        print("SwiftData migration failed, deleting old database...")

        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let storeFiles = [
            "default.store", "default.store-wal", "default.store-shm",
            "LocalStore.store", "LocalStore.store-wal", "LocalStore.store-shm",
            "CloudStore.store", "CloudStore.store-wal", "CloudStore.store-shm"
        ]
        for file in storeFiles {
            let url = appSupport.appendingPathComponent(file)
            try? FileManager.default.removeItem(at: url)
        }

        do {
            modelContainer = try ModelContainer(
                for: Book.self, VocabularyEntry.self,
                configurations: localConfig, cloudConfig
            )
            AuthManager.shared.modelContainer = modelContainer
        } catch {
            fatalError("Cannot create ModelContainer: \(error)")
        }
    }

    private static func runMigrationIfNeeded(container: ModelContainer) {
        let migrationKey = "iCloudDataMigrationCompleted_v1"
        guard !UserDefaults.standard.bool(forKey: migrationKey) else { return }

        // Migrate EPUBs to iCloud Documents
        let localEpubsDir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EPUBs")
        if let iCloudURL = FileManager.default.url(forUbiquityContainerIdentifier: nil)?
            .appendingPathComponent("Documents/EPUBs") {
            try? FileManager.default.createDirectory(at: iCloudURL, withIntermediateDirectories: true)
            if let files = try? FileManager.default.contentsOfDirectory(
                at: localEpubsDir,
                includingPropertiesForKeys: nil
            ) {
                for file in files where file.pathExtension == "epub" {
                    let dest = iCloudURL.appendingPathComponent(file.lastPathComponent)
                    if !FileManager.default.fileExists(atPath: dest.path) {
                        try? FileManager.default.copyItem(at: file, to: dest)
                    }
                }
            }
        }

        UserDefaults.standard.set(true, forKey: migrationKey)
    }

    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            AppThemeContainer {
                ContentView()
                    .environmentObject(appLanguage)
                    .environmentObject(appearanceStore)
                    .preferredColorScheme(appearanceStore.resolvedColorScheme)
                    .environment(\.authManager, authManager)
                    .environment(\.kgService, kgService)
                    .environment(\.subscriptionManager, subscriptionManager)
                    .environment(\.locale, appLanguage.locale)
                    .tint(AppColors.tint)
                    .environment(\.readiumService, readiumService)
                    .environment(\.bookshelfImportService, bookshelfImportService)
                    .environment(\.bookFileManager, bookFileManager)
                    .onOpenURL { url in
                        GIDSignIn.sharedInstance.handle(url)
                    }
                    .task {
                        if !authManager.isLoggedIn {
                            let actor = BackgroundSyncActor(modelContainer: modelContainer)
                            try? await actor.clearSyncedData()
                        }
                        subscriptionManager.listenForTransactionUpdates(using: kgService, authManager: authManager)
                        await subscriptionManager.loadProducts()
                        await subscriptionManager.refresh(using: kgService, authManager: authManager)
                    }
                    .onChange(of: scenePhase) { _, newPhase in
                        if newPhase == .active, authManager.isLoggedIn {
                            Task {
                                await subscriptionManager.refresh(using: kgService, authManager: authManager)
                            }
                        }
                    }
            }
        }
        .modelContainer(modelContainer)
    }
}

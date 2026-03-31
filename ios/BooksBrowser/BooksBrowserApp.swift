//
//  BooksBrowserApp.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import os

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
    let iCloudDownloadManager = ICloudDownloadManager()
    let networkMonitor = NetworkMonitor.shared
    let syncCoordinator = SyncCoordinator()
    let toastCoordinator = AppToastCoordinator()
    let startupFailure: AppStartupFailure?

    init() {
        AppFonts.ensureSerifCJKAvailable()
        AppFonts.configureGlobalAppearance()
        NSUbiquitousKeyValueStore.default.synchronize()
        bookshelfImportService = BookshelfImportService(readiumService: readiumService)
        bookFileManager = LocalBookFileManager()

        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self]),
            cloudKitDatabase: .automatic
        )

        let allModels: [any PersistentModel.Type] = [Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self]

        do {
            modelContainer = try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: localConfig, cloudConfig
            )
            startupFailure = nil
            AuthManager.shared.modelContainer = modelContainer
            Self.runMigrationIfNeeded(container: modelContainer)
            AppLog.app.info("ModelContainer initialized — models: \(allModels.map { String(describing: $0) }.joined(separator: ", "))")
        } catch {
            AppLog.app.error("ModelContainer init failed: \(error.localizedDescription) — attempting store reset")

            // 嘗試刪除損壞的本機 store 後重試
            if let retryContainer = Self.retryAfterStoreReset(localConfig: localConfig, cloudConfig: cloudConfig) {
                modelContainer = retryContainer
                startupFailure = nil
                AuthManager.shared.modelContainer = retryContainer
                AppLog.app.warning("ModelContainer recovered after store reset — user data will re-sync from server")
            } else {
                AppLog.app.error("ModelContainer recovery failed — falling back to in-memory store")
                startupFailure = AppStartupFailure.storageInitialization(error: error)
                modelContainer = Self.makeFallbackModelContainer()
            }
        }

        // Always recover orphan book files (idempotent — skips files with existing records)
        Self.recoverOrphanBooks(container: modelContainer)
    }

    private static func runMigrationIfNeeded(container: ModelContainer) {
        let migrationKey = "iCloudDataMigrationCompleted_v1"
        guard !UserDefaults.standard.bool(forKey: migrationKey) else { return }

        let localBooksDir = Book.localBooksDirectory
        guard let iCloudDir = Book.iCloudBooksDirectory else {
            AppLog.app.info("iCloud not available, deferring book migration")
            return
        }

        let files: [URL]
        do {
            files = try FileManager.default.contentsOfDirectory(
                at: localBooksDir,
                includingPropertiesForKeys: nil
            )
        } catch {
            AppLog.app.warning("Cannot list local books for migration: \(error.localizedDescription)")
            UserDefaults.standard.set(true, forKey: migrationKey)
            return
        }

        let epubs = files.filter { $0.pathExtension == "epub" }
        var failedCount = 0
        for file in epubs {
            let dest = iCloudDir.appendingPathComponent(file.lastPathComponent)
            if !FileManager.default.fileExists(atPath: dest.path) {
                do {
                    try FileManager.default.copyItem(at: file, to: dest)
                } catch {
                    failedCount += 1
                    AppLog.app.error("iCloud EPUB copy failed (\(file.lastPathComponent)): \(error.localizedDescription)")
                }
            }
        }

        if failedCount == 0 {
            UserDefaults.standard.set(true, forKey: migrationKey)
            AppLog.app.info("iCloud EPUB migration completed: \(epubs.count) files")
        } else {
            AppLog.app.warning("iCloud EPUB migration incomplete: \(failedCount)/\(epubs.count) failed, will retry next launch")
        }
    }

    @Environment(\.scenePhase) private var scenePhase

    private static let fontObserver: Any? = NotificationCenter.default.addObserver(
        forName: .serifCJKFontDidBecomeAvailable,
        object: nil,
        queue: .main
    ) { _ in
        AppFonts.configureGlobalAppearance()
    }

    @State private var showWelcome =
        !ProcessInfo.processInfo.arguments.contains("-skipWelcome") &&
        !UserDefaults.standard.bool(forKey: "hasSeenWelcome")

    var body: some Scene {
        WindowGroup {
            AppThemeContainer {
                rootView
                    .environmentObject(appLanguage)
                    .environment(\.reviewSettingsStore, ReviewSettingsStore.shared)
                    .preferredColorScheme(appearanceStore.resolvedColorScheme)
                    .environment(\.authManager, authManager)
                    .environment(\.kgService, kgService)
                    .environment(\.subscriptionManager, subscriptionManager)
                    .environment(\.locale, appLanguage.locale)
                    .tint(AppColors.tint)
                    .environment(\.readiumService, readiumService)
                    .environment(\.bookshelfImportService, bookshelfImportService)
                    .environment(\.bookFileManager, bookFileManager)
                    .environment(\.iCloudDownloadManager, iCloudDownloadManager)
                    .environment(\.syncCoordinator, syncCoordinator)
                    .environment(\.quotaStore, QuotaStore.shared)
                    .environment(\.speechService, SpeechService.shared)
                    .environment(\.readerSettings, .shared)
                    .environment(\.toastCoordinator, toastCoordinator)
                    .overlay(alignment: .top) {
                        if let toast = toastCoordinator.current {
                            AppToast(item: toast, onDismiss: { toastCoordinator.dismiss() })
                                .transition(.bannerReveal)
                                .zIndex(999)
                        }
                    }
            }
            .environmentObject(appearanceStore)
        }
        .modelContainer(modelContainer)
    }

    @ViewBuilder
    private var rootView: some View {
        if let startupFailure {
            AppStartupRecoveryView(failure: startupFailure)
        } else {
            ContentView()
                .onOpenURL { url in
                    GIDSignIn.sharedInstance.handle(url)
                }
                .task {
                    iCloudDownloadManager.startMonitoring()
                }
                .task {
                    try? Tips.configure()
                }
                .task {
                    if !authManager.isLoggedIn {
                        let actor = BackgroundSyncActor(modelContainer: modelContainer)
                        do {
                            try await actor.clearSyncedData()
                            // Force full sync on next login by clearing the incremental boundary.
                            // Without this, re-login after a Keychain-only wipe (e.g. Xcode rebuild)
                            // would do an incremental sync that skips already-deleted entries.
                            UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
                            UserDefaults.standard.removeObject(forKey: "kg_review_payload_version")
                        } catch {
                            AppLog.app.error("clearSyncedData failed: \(error.localizedDescription)")
                        }
                    }
                    let migrationContext = ModelContext(modelContainer)
                    ReviewActivityLog.migrateFromUserDefaultsIfNeeded(context: migrationContext)

                    subscriptionManager.listenForTransactionUpdates(using: kgService, authManager: authManager)
                    await subscriptionManager.loadProducts()
                    await subscriptionManager.refresh(using: kgService, authManager: authManager, force: false)
                }
                .onChange(of: authManager.isLoggedIn) { wasLoggedIn, isNowLoggedIn in
                    // Trigger sync immediately after login (scenePhase won't re-fire .active)
                    guard !wasLoggedIn, isNowLoggedIn, !authManager.isDemoMode else { return }
                    Task {
                        AppLog.kg.info("Post-login sync triggered")
                        await kgService.backgroundSync(container: modelContainer)
                        // Poke main context so @Query picks up background actor's save
                        try? modelContainer.mainContext.save()
                        if let error = kgService.lastBackgroundSyncError {
                            toastCoordinator.warning(error)
                            kgService.lastBackgroundSyncError = nil
                        }
                    }
                }
                .onChange(of: scenePhase) { _, newPhase in
                    switch newPhase {
                    case .active:
                        AppAnalytics.track(.appSessionStarted)
                        Task {
                            await subscriptionManager.refresh(using: kgService, authManager: authManager)
                            guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
                            AppAnalytics.track(.backgroundSyncTriggered)
                            let syncStart = Date()
                            await kgService.backgroundSync(container: modelContainer)
                            // Poke main context so @Query picks up background actor's save
                            try? modelContainer.mainContext.save()
                            let durationMs = Int(Date().timeIntervalSince(syncStart) * 1000)
                            let success = kgService.lastBackgroundSyncError == nil
                            AppAnalytics.track(.backgroundSyncCompleted(durationMs: durationMs, success: success))
                            if let error = kgService.lastBackgroundSyncError {
                                toastCoordinator.warning(error)
                                kgService.lastBackgroundSyncError = nil
                            }
                        }
                    case .background:
                        SessionMetrics.shared.snapshot().logSummary()
                        AppAnalytics.track(.appEnteredBackground)
                        Task {
                            guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
                            await kgService.pushReviewQuietly(container: modelContainer)
                        }
                    default:
                        break
                    }
                }
                .alert(
                    L10n.string("登入已過期"),
                    isPresented: Binding(
                        get: { kgService.sessionExpiredReason != nil },
                        set: { if !$0 { kgService.sessionExpiredReason = nil } }
                    )
                ) {
                    Button(L10n.string("確定")) {
                        kgService.sessionExpiredReason = nil
                    }
                } message: {
                    if let reason = kgService.sessionExpiredReason {
                        Text(reason)
                    }
                }
                .fullScreenCover(isPresented: $showWelcome) {
                    WelcomeView(
                        onStart: {
                            UserDefaults.standard.set(true, forKey: "hasSeenWelcome")
                            showWelcome = false
                        },
                        onTryDemo: {
                            UserDefaults.standard.set(true, forKey: "hasSeenWelcome")
                            showWelcome = false
                            authManager.enterDemoMode(modelContainer: modelContainer)
                        }
                    )
                }
        }
    }

    /// 刪除本機 SwiftData store 後重建 ModelContainer（CloudKit store 從 iCloud 恢復）
    private static func retryAfterStoreReset(localConfig: ModelConfiguration, cloudConfig: ModelConfiguration) -> ModelContainer? {
        // 刪除 LocalStore + CloudStore（CloudKit 資料會從 iCloud 自動恢復）
        for storeURL in [localConfig.url, cloudConfig.url] {
            let storePaths = [storeURL, storeURL.appendingPathExtension("shm"), storeURL.appendingPathExtension("wal")]
            for path in storePaths {
                try? FileManager.default.removeItem(at: path)
            }
            AppLog.app.info("Removed store files at \(storeURL.lastPathComponent)")
        }

        // First try: dual-store (local + CloudKit)
        if let container = try? ModelContainer(
            for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: localConfig, cloudConfig
        ) {
            return container
        }

        // Second try: all local, no CloudKit (iOS 26 CloudKit schema validation may fail)
        AppLog.app.warning("Dual-store retry failed — attempting single-store without CloudKit")
        let localOnlyConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self]),
            cloudKitDatabase: .none
        )
        return try? ModelContainer(
            for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: localOnlyConfig
        )
    }

    private static func makeFallbackModelContainer() -> ModelContainer {
        do {
            return try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
        } catch {
            fatalError("Cannot create fallback in-memory ModelContainer: \(error)")
        }
    }

    /// Store reset 後掃描磁碟上的書籍檔案，重建遺失的 Book 記錄
    @MainActor
    private static func recoverOrphanBooks(container: ModelContainer) {
        let context = ModelContext(container)
        let fm = FileManager.default
        let supportedExtensions: Set<String> = ["epub", "txt", "md", "pdf"]

        // Scan both local and iCloud directories
        var allFiles: [URL] = []
        if let files = try? fm.contentsOfDirectory(at: Book.localBooksDirectory, includingPropertiesForKeys: nil) {
            allFiles.append(contentsOf: files.filter { supportedExtensions.contains($0.pathExtension.lowercased()) })
        }
        if let iCloudDir = Book.iCloudBooksDirectory,
           let files = try? fm.contentsOfDirectory(at: iCloudDir, includingPropertiesForKeys: nil) {
            allFiles.append(contentsOf: files.filter { supportedExtensions.contains($0.pathExtension.lowercased()) })
        }

        AppLog.app.info("recoverOrphanBooks: local=\(Book.localBooksDirectory.path), iCloud=\(Book.iCloudBooksDirectory?.path ?? "nil"), found \(allFiles.count) book file(s)")
        guard !allFiles.isEmpty else {
            AppLog.app.info("recoverOrphanBooks: no book files found on disk")
            return
        }

        // Get existing book fileNames
        let existing: Set<String>
        if let books = try? context.fetch(FetchDescriptor<Book>()) {
            existing = Set(books.map(\.epubFileName))
        } else {
            existing = []
        }

        var recovered = 0
        for file in allFiles {
            let fileName = file.lastPathComponent
            guard !existing.contains(fileName) else { continue }

            // Skip .icloud placeholder files and Originals directory
            guard !fileName.hasPrefix("."), fileName != "Originals" else { continue }

            let ext = file.pathExtension.lowercased()
            let format: BookFormat = switch ext {
            case "epub": .epub
            case "txt":  .txt
            case "md":   .md
            case "pdf":  .pdf
            default: .epub
            }

            // Derive title from fileName (strip UUID prefix if present)
            let baseName = file.deletingPathExtension().lastPathComponent
            let title = baseName.count > 37 && baseName.dropFirst(36).first == "_"
                ? String(baseName.dropFirst(37))  // UUID_originalName pattern
                : baseName

            let book = Book(title: title, author: "", fileName: fileName, format: format)
            context.insert(book)
            recovered += 1
        }

        if recovered > 0 {
            try? context.save()
            AppLog.app.info("Recovered \(recovered) orphan book(s) from disk")
        }
    }
}

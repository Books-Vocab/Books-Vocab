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
    @State private var modelContainer: ModelContainer
    @State private var startupFailure: AppStartupFailure?
    let authManager = AuthManager.shared
    let kgService = KGService()
    let subscriptionManager = SubscriptionManager.shared
    #if os(iOS)
    let readiumService: any ReadiumServing = ReadiumService.shared
    let bookshelfImportService: any BookshelfImporting
    #endif
    let bookFileManager: any BookFileManaging
    let iCloudDownloadManager = ICloudDownloadManager()
    let networkMonitor = NetworkMonitor.shared
    let syncCoordinator = SyncCoordinator()
    let toastCoordinator = AppToastCoordinator()
    private let localDataCleaner: any LocalDataClearing = LocalDataCleanerService()

    init() {
        // Initialize crash reporting first so any subsequent startup failure is captured.
        AppCrashReporting.bootstrap()

        #if os(iOS)
        AppFonts.ensureSerifCJKAvailable()
        AppFonts.configureGlobalAppearance()
        #endif
        NSUbiquitousKeyValueStore.default.synchronize()
        #if os(iOS)
        bookshelfImportService = BookshelfImportService(readiumService: readiumService)
        #endif
        bookFileManager = LocalBookFileManager()

        let outcome = Self.bootstrapModelContainer()
        _modelContainer = State(initialValue: outcome.container)
        _startupFailure = State(initialValue: outcome.failure)

        // Always recover orphan book files (idempotent — skips files with existing records)
        Self.recoverOrphanBooks(container: outcome.container)
    }

    /// Encapsulates the full ModelContainer bootstrap path so it can be re-run
    /// from `AppStartupRecoveryView` when the first attempt fails.
    private struct BootstrapOutcome {
        let container: ModelContainer
        let failure: AppStartupFailure?
    }

    private static func bootstrapModelContainer() -> BootstrapOutcome {
        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self, PodcastProgress.self]),
            cloudKitDatabase: .automatic
        )

        let allModels: [any PersistentModel.Type] = [Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self]

        do {
            let container = try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
                configurations: localConfig, cloudConfig
            )
            AuthManager.shared.modelContainer = container
            Self.runMigrationIfNeeded(container: container)
            AppLog.app.info("ModelContainer initialized — models: \(allModels.map { String(describing: $0) }.joined(separator: ", "))")
            return BootstrapOutcome(container: container, failure: nil)
        } catch {
            AppLog.app.error("ModelContainer init failed: \(error.localizedDescription) — attempting store reset")

            // 嘗試刪除損壞的本機 store 後重試
            if let retryContainer = Self.retryAfterStoreReset(localConfig: localConfig, cloudConfig: cloudConfig) {
                AuthManager.shared.modelContainer = retryContainer
                AppLog.app.warning("ModelContainer recovered after store reset — user data will re-sync from server")
                return BootstrapOutcome(container: retryContainer, failure: nil)
            }

            AppLog.app.error("ModelContainer recovery failed — falling back to in-memory store")
            let fallback = Self.makeFallbackModelContainer()
            return BootstrapOutcome(
                container: fallback,
                failure: AppStartupFailure.storageInitialization(error: error)
            )
        }
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

    #if os(iOS)
    private static let fontObserver: Any? = NotificationCenter.default.addObserver(
        forName: .serifCJKFontDidBecomeAvailable,
        object: nil,
        queue: .main
    ) { _ in
        AppFonts.configureGlobalAppearance()
    }
    #endif

    @State private var showWelcome =
        !ProcessInfo.processInfo.arguments.contains("-skipWelcome") &&
        !UserDefaults.standard.bool(forKey: "hasSeenWelcome")
    @State private var showLoginFromWelcome = false

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
                    #if os(iOS)
                    .environment(\.readiumService, readiumService)
                    .environment(\.bookshelfImportService, bookshelfImportService)
                    .environment(\.readerSettings, .shared)
                    #endif
                    .environment(\.bookFileManager, bookFileManager)
                    .environment(\.iCloudDownloadManager, iCloudDownloadManager)
                    .environment(\.syncCoordinator, syncCoordinator)
                    .environment(\.quotaStore, QuotaStore.shared)
                    .environment(\.speechService, SpeechService.shared)
                    .environment(\.toastCoordinator, toastCoordinator)
                    .toastOverlay()
            }
            .environmentObject(appearanceStore)
        }
        .modelContainer(modelContainer)
    }

    @ViewBuilder
    private var rootView: some View {
        if let startupFailure {
            AppStartupRecoveryView(
                failure: startupFailure,
                actions: makeStartupRecoveryActions()
            )
        } else {
            ContentView()
                .modifier(AutoSyncMonitor())
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
                    // Tag Sentry scope with user id (clear on logout) — runs on every transition.
                    AppCrashReporting.setUser(id: isNowLoggedIn ? authManager.userId : nil)
                    // Trigger sync immediately after login (scenePhase won't re-fire .active)
                    guard !wasLoggedIn, isNowLoggedIn, !authManager.isDemoMode else { return }
                    Task {
                        AppLog.kg.info("Post-login sync triggered")
                        await kgService.backgroundSync(container: modelContainer)
                        await kgService.fetchQuota()
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
                            await kgService.fetchQuota()
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
                        SessionMetrics.shared.reset()
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
                .platformFullScreenCover(isPresented: $showWelcome) {
                    WelcomeView(
                        onStart: {
                            UserDefaults.standard.set(true, forKey: "hasSeenWelcome")
                            showWelcome = false
                        },
                        onLogin: {
                            UserDefaults.standard.set(true, forKey: "hasSeenWelcome")
                            showWelcome = false
                            showLoginFromWelcome = true
                        },
                        onTryDemo: {
                            UserDefaults.standard.set(true, forKey: "hasSeenWelcome")
                            showWelcome = false
                            authManager.enterDemoMode(modelContainer: modelContainer)
                        }
                    )
                }
                .sheet(isPresented: $showLoginFromWelcome) {
                    LoginSheet()
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
            for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
            configurations: localConfig, cloudConfig
        ) {
            return container
        }

        // Second try: all local, no CloudKit (iOS 26 CloudKit schema validation may fail)
        AppLog.app.warning("Dual-store retry failed — attempting single-store without CloudKit")
        let localOnlyConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self]),
            cloudKitDatabase: .none
        )
        return try? ModelContainer(
            for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
            configurations: localOnlyConfig
        )
    }

    // MARK: - Startup Recovery Actions

    @MainActor
    private func makeStartupRecoveryActions() -> AppStartupRecoveryActions {
        AppStartupRecoveryActions(
            retry: { @MainActor in
                AppLog.app.info("AppStartupRecoveryView: retry requested")
                let outcome = Self.bootstrapModelContainer()
                if outcome.failure == nil {
                    // 重建成功 — 替換 container 並關閉 recovery 畫面。SwiftUI 會以新 container 重掛 view tree。
                    modelContainer = outcome.container
                    startupFailure = nil
                    Self.recoverOrphanBooks(container: outcome.container)
                    AppLog.app.info("AppStartupRecoveryView: retry succeeded — switching to main UI")
                    return true
                }
                AppLog.app.warning("AppStartupRecoveryView: retry failed — still in recovery mode")
                return false
            },
            clearLocalCache: { @MainActor [localDataCleaner, modelContainer] in
                AppLog.app.info("AppStartupRecoveryView: clearLocalCache requested")
                // LocalDataCleanerService 透過 BackgroundSyncActor 清 in-memory fallback container 內的
                // VocabularyEntry / ReviewRecord / Notebook，以及與同步相關的 UserDefaults 標記。
                // 對 in-memory store 而言主要效果是清 UserDefaults — 為下次 retry 移除可能造成
                // migration crash 的殘留狀態。雲端資料不受影響（remote 仍保留，登入後會 re-sync）。
                await localDataCleaner.clearLocalData(
                    container: modelContainer,
                    reason: "startup-recovery"
                )
                // 額外清除 store 檔案以便下一次 retry 走「全新建立」路徑。
                Self.purgePersistentStoreFiles()
                AppCrashReporting.record(
                    NSError(
                        domain: "AppStartupRecovery",
                        code: 1,
                        userInfo: [NSLocalizedDescriptionKey: "User cleared local cache from startup recovery view"]
                    ),
                    context: "startup-recovery-clear-cache"
                )
                return true
            },
            supportMailURL: { failure in
                Self.composeSupportMailURL(for: failure)
            }
        )
    }

    /// Best-effort 刪除已知的 SwiftData store files —
    /// 與 `retryAfterStoreReset` 使用同樣的檔名（LocalStore / CloudStore + shm/wal）。
    private static func purgePersistentStoreFiles() {
        // 用 ModelConfiguration 反推 store URL，避免硬編路徑。
        let localURL = ModelConfiguration(
            "LocalStore",
            schema: Schema([Notebook.self]),
            cloudKitDatabase: .none
        ).url
        let cloudURL = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self]),
            cloudKitDatabase: .automatic
        ).url
        for storeURL in [localURL, cloudURL] {
            for path in [storeURL, storeURL.appendingPathExtension("shm"), storeURL.appendingPathExtension("wal")] {
                try? FileManager.default.removeItem(at: path)
            }
            AppLog.app.info("purgePersistentStoreFiles: removed \(storeURL.lastPathComponent)")
        }
    }

    private static func composeSupportMailURL(for failure: AppStartupFailure) -> URL? {
        let recipient = "support@wordnexus.lol"
        let version = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "-"
        let build = (Bundle.main.infoDictionary?["CFBundleVersion"] as? String) ?? "-"
        let bundleId = Bundle.main.bundleIdentifier ?? "-"

        let subject = L10n.string("[WordNexus] 啟動保護模式 — 需要技術協助")
        let bodyLines = [
            L10n.string("您好，我的 App 在啟動時觸發保護模式，需要技術協助。"),
            "",
            L10n.string("--- 請保留以下技術資訊 ---"),
            "Bundle: \(bundleId)",
            "Version: \(version) (\(build))",
            "Failure: \(failure.title)",
            "Detail: \(failure.technicalDetails)"
        ]
        let body = bodyLines.joined(separator: "\n")

        var components = URLComponents()
        components.scheme = "mailto"
        components.path = recipient
        components.queryItems = [
            URLQueryItem(name: "subject", value: subject),
            URLQueryItem(name: "body", value: body)
        ]
        return components.url
    }

    private static func makeFallbackModelContainer() -> ModelContainer {
        do {
            return try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
        } catch {
            // Fail-soft: attempt a minimal-schema in-memory container so the app can still
            // display AppStartupRecoveryView (driven by `startupFailure`) instead of crashing.
            AppLog.app.critical("Fallback ModelContainer init failed: \(error.localizedDescription); attempting minimal schema")
            if let minimal = try? ModelContainer(
                for: Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            ) {
                return minimal
            }
            AppLog.app.critical("Minimal ModelContainer init also failed: \(error.localizedDescription)")
            fatalError("Cannot create any ModelContainer: \(error)")
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

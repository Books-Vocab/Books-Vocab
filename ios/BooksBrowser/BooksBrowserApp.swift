//
//  BooksBrowserApp.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
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
    let startupFailure: AppStartupFailure?

    init() {
        AppFonts.ensureSerifCJKAvailable()
        AppFonts.configureGlobalAppearance()
        NSUbiquitousKeyValueStore.default.synchronize()
        bookshelfImportService = BookshelfImportService(readiumService: readiumService)
        bookFileManager = LocalBookFileManager()

        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self, ReviewRecord.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self]),
            cloudKitDatabase: .automatic
        )

        do {
            modelContainer = try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self,
                configurations: localConfig, cloudConfig
            )
            startupFailure = nil
            AuthManager.shared.modelContainer = modelContainer
            Self.runMigrationIfNeeded(container: modelContainer)
        } catch {
            AppLog.app.error("Cannot create persistent ModelContainer: \(error.localizedDescription)")
            startupFailure = AppStartupFailure.storageInitialization(error: error)
            modelContainer = Self.makeFallbackModelContainer()
        }
    }

    private static func runMigrationIfNeeded(container: ModelContainer) {
        let migrationKey = "iCloudDataMigrationCompleted_v1"
        guard !UserDefaults.standard.bool(forKey: migrationKey) else { return }

        let localEpubsDir = Book.localEpubsDirectory
        guard let iCloudDir = Book.iCloudEpubsDirectory else {
            AppLog.app.info("iCloud not available, deferring EPUB migration")
            return
        }

        guard let files = try? FileManager.default.contentsOfDirectory(
            at: localEpubsDir,
            includingPropertiesForKeys: nil
        ) else {
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

    @State private var showWelcome =
        !ProcessInfo.processInfo.arguments.contains("-skipWelcome") &&
        !UserDefaults.standard.bool(forKey: "hasSeenWelcome")

    var body: some Scene {
        WindowGroup {
            AppThemeContainer {
                rootView
                    .environmentObject(appLanguage)
                    .environmentObject(appearanceStore)
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
                    .environment(\.quotaStore, QuotaStore.shared)
                    .environment(\.speechService, SpeechService.shared)
                    .environment(\.readerSettings, .shared)
            }
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
                    if !authManager.isLoggedIn {
                        let actor = BackgroundSyncActor(modelContainer: modelContainer)
                        do {
                            try await actor.clearSyncedData()
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
                            let durationMs = Int(Date().timeIntervalSince(syncStart) * 1000)
                            AppAnalytics.track(.backgroundSyncCompleted(durationMs: durationMs, success: true))
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

    private static func makeFallbackModelContainer() -> ModelContainer {
        do {
            return try ModelContainer(
                for: Book.self, VocabularyEntry.self, ReviewRecord.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true)
            )
        } catch {
            fatalError("Cannot create fallback in-memory ModelContainer: \(error)")
        }
    }
}

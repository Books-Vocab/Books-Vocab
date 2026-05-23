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
    @State var modelContainer: ModelContainer
    @State var startupFailure: AppStartupFailure?
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
    let localDataCleaner: any LocalDataClearing = LocalDataCleanerService()

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

        let outcome = AppBootstrap.run()
        _modelContainer = State(initialValue: outcome.container)
        _startupFailure = State(initialValue: outcome.failure)

        // Always recover orphan book files (idempotent — skips files with existing records)
        AppOrphanBookRecovery.run(container: outcome.container)

        #if os(iOS)
        // PodcastDownloadManager must hold a ModelContainer ref before any
        // background URLSession delegate callback can persist localAudioPath.
        PodcastDownloadManager.shared.configure(modelContainer: outcome.container)
        #endif
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
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("-catalog") {
                CatalogScene()
            } else {
                mainAppContent
            }
            #else
            mainAppContent
            #endif
        }
        .modelContainer(modelContainer)
    }

    private var mainAppContent: some View {
        AppThemeContainer {
            rootView
                .environmentObject(appLanguage)
                .environment(\.reviewSettingsStore, ReviewSettingsStore.shared)
                .preferredColorScheme(appearanceStore.resolvedColorScheme)
                .environment(\.authManager, authManager)
                .environment(\.kgService, kgService)
                .environment(\.subscriptionManager, subscriptionManager)
                .environment(\.locale, appLanguage.locale)
                // Why: L10n.string(_:) 是 non-reactive function;絕大多數 view 不訂閱
                // AppLanguageStore,切 selection 後 UI 中英混雜直到 navigation/redraw。
                // .id(selection) 強制 SwiftUI 在 selection 變更時重建整棵 view tree,
                // 讓所有 L10n.string 重新計算。代價是切語言瞬間全 tree 重建(可接受)。
                .id(appLanguage.selection)
                .tint(AppColors.tintLight)
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
                        // Device is now unlocked — retry any keychain token read that failed
                        // transiently at launch (cold boot), resolving the unknown auth state
                        // before the sync guards below evaluate `isLoggedIn`.
                        authManager.refreshSessionIfNeeded()
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

}

import Foundation
import SwiftData
import os

@MainActor protocol SettingsCoordinating: AnyObject, Observable {
    var showSubscriptionPaywall: Bool { get set }
    var connectionPulse: Bool { get }
    var iconBreathing: Bool { get }
    var showDeleteAccountConfirm: Bool { get set }
    var isDeletingAccount: Bool { get }
    var deleteAccountError: String? { get }
    var translationSourceLang: TranslationLanguage { get set }
    var translationTargetLang: TranslationLanguage { get set }
    func handleAppear()
    func loadData(authManager: any AuthManaging, kgService: any KGServing) async
    func requestDeleteAccount()
    func clearDeleteAccountError()
    func presentSubscriptionPaywall()
    func deleteAccount(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async
    func updateTranslationLanguage(source: TranslationLanguage, target: TranslationLanguage, authManager: any AuthManaging, kgService: any KGServing, toastCoordinator: AppToastCoordinator) async -> Bool
}

@Observable @MainActor
final class SettingsCoordinator: SettingsCoordinating {
    var showSubscriptionPaywall = false
    var connectionPulse = false
    var iconBreathing = false
    var showDeleteAccountConfirm = false
    var isDeletingAccount = false
    var isResyncing = false
    var isManualLoggingIn = false
    var deleteAccountError: String?
    var manualLoginUserId = ""
    var debugLocalServerURL = ""
    var observationPreviewLines: [String] = []
    var observationTotalCount = 0
    var translationSourceLang: TranslationLanguage = TranslationLanguage.currentSource
    var translationTargetLang: TranslationLanguage = TranslationLanguage.currentTarget
    /// 這一輪同步的逐步進度。`isResyncing` 只回答「在不在跑」；這個回答「跑到哪」。
    /// 兩者並存而非取代：`isResyncing` 同時守著重入 guard 與按鈕 disabled。
    let syncProgress = SyncProgressStore()
    init() {
        #if DEBUG
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        #endif
    }

    func handleAppear() {
        iconBreathing = true
        refreshObservationPreview()
    }

    func loadData(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        refreshObservationPreview()
        await kgService.healthCheck()
        connectionPulse.toggle()

        if authManager.isLoggedIn {
            do {
                let config = try await kgService.fetchUserConfig()
                applyServerTranslationConfig(config.translation)
                applyServerReviewClock(config.review_clock)
                applyServerReviewMode(config.review_mode)
                applyServerAutoLink(config.auto_link)
            } catch {
                // Non-fatal: local + iCloud KV remain the fallback authority for
                // translation / review_clock / review_mode config, so we log rather than report to Sentry.
                AppLog.kg.warning("fetchUserConfig failed: \(error.localizedDescription)")
            }
        }
    }

    /// Reconcile server-provided translation config with local + iCloud KV state.
    ///
    /// Backend 現已持久化 `updated_at`（Feature C / C1），故 cold-start 套用時能寫回
    /// server 的真實時戳；但 `serverTranslationLwwEnabled` 仍 off，維持 cold-start-only
    /// 政策（不做真 LWW 比較，避免翻 flag 前語意回歸）：
    ///
    /// - **Flag off (current)**: server-wins ONLY on cold-start —— 本機從未寫過
    ///   translation（source/target 兩時戳皆 nil）且 server 帶真實 `updated_at` 時，以
    ///   server 值 + server 的單一 group 時戳初始化本地層（**不回寫 iCloud KVS**，
    ///   避免新 Apple 裝置覆蓋他裝置未傳播的 local write）。任一本機寫入後 iCloud KV
    ///   即跨裝置權威。
    /// - **Flag on (future)**: 比較 server `updated_at` 與本地，server 較新才整組套。
    private func applyServerTranslationConfig(_ translation: KGTranslationConfig?) {
        guard let translation else { return }
        _ = KGFeatureFlags.serverTranslationLwwEnabled  // keep wired for future LWW flip

        // Cold-start only（設計 A group LWW，對齊 vocab_ui / review_mode）：兩時戳皆 nil
        // ＝整組從未被本機 touch，且 server 帶真實 updated_at 才套。任一非 nil ＝已 touch
        // → 保留本機值（避免重套迴圈：套後本地時戳非 nil，下次 fetch 不再套）。
        guard TranslationLanguage.sourceUpdatedAt == nil,
              TranslationLanguage.targetUpdatedAt == nil,
              let ts = translation.updated_at,
              let src = translation.source_lang, let srcLang = TranslationLanguage(rawValue: src),
              let tgt = translation.target_lang, let tgtLang = TranslationLanguage(rawValue: tgt)
        else { return }

        TranslationLanguage.applyServerColdStart(source: srcLang, target: tgtLang, updatedAt: ts)
        translationSourceLang = srcLang
        translationTargetLang = tgtLang
    }

    /// Reconcile server pause-clock with local + iCloud KV (mirrors translation).
    /// Cold-start only: server wins ONLY when this device has never written the
    /// pause clock locally (`snapshot.updatedAt == nil`). After any local write,
    /// iCloud KV is the cross-device authority. Real LWW awaits the backend flag.
    private func applyServerReviewClock(_ clock: KGReviewClockConfig?) {
        guard let clock else { return }
        let store = ReviewSettingsStore.shared
        guard store.pauseClockSnapshot.updatedAt == nil else { return }
        _ = KGFeatureFlags.serverReviewClockLwwEnabled  // keep wired for future LWW flip
        let pausedAt = clock.paused_at.flatMap(AppDateFormatters.parseISO8601)
        store.applyServerPauseState(
            isPaused: clock.is_paused,
            pausedAt: clock.is_paused ? pausedAt : nil,
            updatedAt: clock.updated_at
        )
    }

    /// Reconcile server review-mode with local + iCloud KV (mirrors pause clock).
    /// Cold-start only: server wins ONLY when this device has never written the
    /// review mode locally (`snapshot.updatedAt == nil`). After any local write,
    /// iCloud KV is the cross-device authority. Real LWW awaits the backend flag.
    /// 後端 snake_case wire(`KGReviewModeConfig`)→ iOS `ReviewModeState` 的轉換在此。
    private func applyServerReviewMode(_ mode: KGReviewModeConfig?) {
        guard let mode else { return }
        let store = ReviewSettingsStore.shared
        guard store.reviewModeSnapshot.updatedAt == nil else { return }
        _ = KGFeatureFlags.serverReviewModeLwwEnabled  // keep wired for future LWW flip
        store.applyServerModeState(
            ReviewModeState(
                mode: ReviewSettingsMode(rawValue: mode.mode) ?? .relaxed,
                customInitialIntervalHours: mode.custom_initial_interval_hours,
                customRememberedMultiplier: mode.custom_remembered_multiplier,
                customForgotMultiplier: mode.custom_forgot_multiplier,
                customMinimumIntervalHours: mode.custom_minimum_interval_hours,
                customMaximumIntervalHours: mode.custom_maximum_interval_hours,
                updatedAt: mode.updated_at
            )
        )
    }

    /// Reconcile server auto-link 開關與本地快取。與 translation / review_* 的
    /// cold-start-only 政策不同:auto_link 是新 group、無 iCloud KV 層與歷史包袱,
    /// 直接走真 LWW(store.applyServer 內比較 updated_at,server 較新才套)。
    private func applyServerAutoLink(_ autoLink: KGAutoLinkConfig?) {
        guard let autoLink else { return }
        AutoLinkSettingsStore.shared.applyServer(
            enabled: autoLink.enabled,
            updatedAt: autoLink.updated_at
        )
    }

    /// 切換自動連結:樂觀寫本地,登入則 push 後端;push 失敗 rollback(含原時戳,
    /// 避免 rollback 被 LWW 當成新寫入)。回 true=已存(或免存的 guest),false=遠端失敗。
    @discardableResult
    func updateAutoLink(
        enabled: Bool,
        autoLinkStore: AutoLinkSettingsStore,
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async -> Bool {
        let prevEnabled = autoLinkStore.isEnabled
        let prevUpdatedAt = autoLinkStore.updatedAt

        autoLinkStore.setEnabled(enabled)
        PerfLog.settings.mark("autoLink.toggled", "enabled=\(enabled)")

        guard authManager.isLoggedIn else { return true }

        do {
            _ = try await kgService.updateAutoLinkConfig(
                KGAutoLinkConfig(enabled: enabled, updated_at: autoLinkStore.updatedAt)
            )
            return true
        } catch {
            autoLinkStore.restore(enabled: prevEnabled, updatedAt: prevUpdatedAt)
            reportConfigSaveFailure(error, label: "updateAutoLinkConfig", toastCoordinator: toastCoordinator)
            return false
        }
    }

    /// 切換複習時鐘暫停:樂觀寫本地+iCloud,登入則 push 後端;push 失敗 rollback 三層
    /// (對標 updateTranslationLanguage)。回 true=已存(或免存的 guest),false=遠端失敗。
    @discardableResult
    func updateReviewClock(
        isPaused: Bool,
        reviewSettingsStore: ReviewSettingsStore,
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async -> Bool {
        let snapshot = reviewSettingsStore.pauseClockSnapshot   // 寫之前快照,rollback 用

        var s = reviewSettingsStore.settings
        if isPaused { s.pauseProgress() } else { s.resumeProgress() }
        reviewSettingsStore.update(s)
        // Semantic perf mark: the optimistic local write is the moment the pause
        // state becomes effective for the UI (backend push is best-effort after).
        PerfLog.settings.mark("reviewClock.pause", "isPaused=\(isPaused)")

        guard authManager.isLoggedIn else { return true }

        let newSnapshot = reviewSettingsStore.pauseClockSnapshot
        let pausedAtISO = newSnapshot.pausedAt.map { AppDateFormatters.iso8601.string(from: $0) }
        do {
            _ = try await kgService.updateReviewClockConfig(
                KGReviewClockConfig(
                    is_paused: isPaused,
                    paused_at: pausedAtISO,
                    updated_at: newSnapshot.updatedAt
                )
            )
            return true
        } catch {
            reviewSettingsStore.restorePauseState(snapshot)
            reportConfigSaveFailure(error, label: "updateReviewClockConfig", toastCoordinator: toastCoordinator)
            return false
        }
    }

    /// 更新複習模式 + 自訂 SRS 參數:樂觀寫本地+iCloud,登入則 push 後端;push 失敗 rollback
    /// 三層(對標 updateReviewClock)。回 true=已存(或免存的 guest),false=遠端失敗。
    /// iOS `ReviewSettings`(camelCase customParams)→ 後端 snake_case wire 的轉換在此。
    @discardableResult
    func updateReviewMode(
        _ newSettings: ReviewSettings,
        reviewSettingsStore: ReviewSettingsStore,
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async -> Bool {
        let snapshot = reviewSettingsStore.reviewModeSnapshot   // 寫之前快照,rollback 用
        reviewSettingsStore.update(newSettings)
        PerfLog.settings.mark("reviewMode.changed", "mode=\(newSettings.mode.rawValue)")

        guard authManager.isLoggedIn else { return true }

        let newSnapshot = reviewSettingsStore.reviewModeSnapshot
        do {
            _ = try await kgService.updateReviewModeConfig(
                KGReviewModeConfig(
                    mode: newSnapshot.mode.rawValue,
                    custom_initial_interval_hours: newSnapshot.customInitialIntervalHours,
                    custom_remembered_multiplier: newSnapshot.customRememberedMultiplier,
                    custom_forgot_multiplier: newSnapshot.customForgotMultiplier,
                    custom_minimum_interval_hours: newSnapshot.customMinimumIntervalHours,
                    custom_maximum_interval_hours: newSnapshot.customMaximumIntervalHours,
                    updated_at: newSnapshot.updatedAt
                )
            )
            return true
        } catch {
            reviewSettingsStore.restoreModeState(snapshot)
            reportConfigSaveFailure(error, label: "updateReviewModeConfig", toastCoordinator: toastCoordinator)
            return false
        }
    }

    private func reportConfigSaveFailure(_ error: Error, label: String, toastCoordinator: AppToastCoordinator) {
        toastCoordinator.error("設定儲存失敗".localized)
        AppLog.kg.error("\(label) failed: \(error.localizedDescription)")
    }

    func refreshObservationPreview() {
        let preview = AppObservationStore.shared.preview()
        observationPreviewLines = preview.entries.map(\.previewLine)
        observationTotalCount = preview.totalCount
    }

    func requestDeleteAccount() {
        showDeleteAccountConfirm = true
    }

    func clearDeleteAccountError() {
        deleteAccountError = nil
    }

    func presentSubscriptionPaywall() {
        showSubscriptionPaywall = true
    }

    func deleteAccount(
        authManager: any AuthManaging,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        guard authManager.isLoggedIn, !isDeletingAccount else { return }
        isDeletingAccount = true
        defer { isDeletingAccount = false }

        do {
            try await kgService.deleteAccount()
            // 成功後關閉 confirm sheet，再觸發 logout（logout 會清理 Settings 畫面）
            showDeleteAccountConfirm = false
            authManager.logout(modelContainer: modelContext.container, reason: "delete_account")
        } catch {
            deleteAccountError = L10n.format("無法刪除帳號：%@", error.localizedDescription)
            // 失敗時關閉 confirm sheet，讓使用者看到錯誤 alert
            showDeleteAccountConfirm = false
        }
    }

    /// 回傳 true 代表已儲存（或免儲存的 guest 路徑），false 代表遠端 update 失敗。
    /// 失敗時除了回傳 false 也會顯示 toast，呼叫端可選擇額外 inline 反饋。
    /// 遠端失敗會 rollback UserDefaults / iCloud KV / in-memory state,避免
    /// 「本地已寫但 server / 其他裝置不知道」的分裂狀態。
    @discardableResult
    func updateTranslationLanguage(
        source: TranslationLanguage,
        target: TranslationLanguage,
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async -> Bool {
        // Snapshot previous values + their timestamps for rollback on remote failure.
        let prevSource = TranslationLanguage.currentSource
        let prevTarget = TranslationLanguage.currentTarget
        let prevSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        let prevTargetUpdatedAt = TranslationLanguage.targetUpdatedAt

        translationSourceLang = source
        translationTargetLang = target
        TranslationLanguage.currentSource = source
        TranslationLanguage.currentTarget = target
        PerfLog.settings.mark("translation.changed", "source=\(source.rawValue) target=\(target.rawValue)")

        guard authManager.isLoggedIn else { return true }
        do {
            _ = try await kgService.updateTranslationConfig(
                KGTranslationConfig(
                    source_lang: source.rawValue,
                    target_lang: target.rawValue,
                    // 單一 group 時戳（設計 A）：source/target 剛由上方 setter 同刻寫入，
                    // 取兩者較新者作整組 LWW 時戳，push 給後端 vocab/web cold-start 用。
                    updated_at: [TranslationLanguage.sourceUpdatedAt, TranslationLanguage.targetUpdatedAt].compactMap { $0 }.max()
                )
            )
            return true
        } catch {
            // Rollback: restore values WITH their original timestamps so that
            // iCloud KV's LWW doesn't treat the rollback as "newer" than a
            // concurrent write from another device.
            TranslationLanguage.restore(
                source: prevSource,
                sourceUpdatedAt: prevSourceUpdatedAt,
                target: prevTarget,
                targetUpdatedAt: prevTargetUpdatedAt
            )
            translationSourceLang = prevSource
            translationTargetLang = prevTarget
            reportConfigSaveFailure(error, label: "updateUserConfig (translation lang)", toastCoordinator: toastCoordinator)
            return false
        }
    }

    func handleManualLogin(authManager: any AuthManaging) {
        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        // in-flight guard：login(customToken:) 現為 async，會 await clearLocalData；
        // 無 guard 時連點兩下會 spawn 兩個 Task，兩者都在第一個的 await 解開前讀到舊 userId
        // → 重複清理（第二次為 no-op 但多一次 BackgroundSyncActor purge）。對齊 isResyncing。
        guard !id.isEmpty, !isManualLoggingIn else { return }
        isManualLoggingIn = true
        Task {
            await authManager.login(customToken: id)
            isManualLoggingIn = false
        }
    }

    func resync(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async {
        // 資格 gate：demo 模式 `isLoggedIn == true` 但無真 token，同步會踩 `unauthorized`
        // → 誤彈「登入已過期」。與 `ExplicitSync` / 自動同步同政策：登出 / demo 一律 no-op。
        // （UI 已以 syncSummary 擋登出，此處 defense-in-depth 並補上 demo 漏洞。）
        guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
        guard !isResyncing else { return }
        isResyncing = true
        defer { isResyncing = false }

        // 進度模型：宣告 backgroundSync 會跑的步驟 + 本函式自己收尾的那一列。
        // UI 必須先知道完整清單才畫得出「還沒輪到」的灰列與正確的進度條分母。
        syncProgress.begin(stepIDs: KGService.syncStepIDs() + [.status])

        // reporter 走 AsyncStream 而不是每個事件開一個 `Task { @MainActor in }`。
        // 後者**不保證順序**——事件從多條併行的腿發出，各自排進 MainActor 佇列後
        // 到達順序就散了，計數器會肉眼可見地彈回。store 內部雖有單調守衛擋著，
        // 但那是防線不是設計；`continuation.yield` 是 FIFO，讓「送出順序 = 套用
        // 順序」在正常路徑上就成立。
        let (events, continuation) = AsyncStream<SyncProgressEvent>.makeStream()
        let pump = Task { @MainActor [syncProgress] in
            for await event in events { syncProgress.apply(event) }
        }

        let outcome = await kgService.backgroundSync(container: modelContext.container) { event in
            continuation.yield(event)
        }
        do {
            try modelContext.container.mainContext.save()
        } catch {
            AppLog.kg.error("resync mainContext save failed: \(error.localizedDescription)")
        }

        // 額度與連線檢查併發。兩者都是唯讀 GET、彼此無依賴，序列跑純粹是多一趟
        // 往返的等待；它們寫的欄位互不相交（healthCheck → isConnected /
        // serverCardCount，fetchQuota → QuotaStore），所以這兩條併發是安全的。
        //
        // **但刻意不把它們再拉進 backgroundSync 一起三方併發。** 那時 `serverCardCount`
        // 會與 pull 撞在一起，而 `KGService` 是 `@Observable` 卻不是 `@MainActor`
        // ——為了省約 100ms 去換一個真實的 data race 不划算。這一輪真正的 6 秒在
        // podcast，那筆已經收掉了。
        continuation.yield(.started(.status))
        async let health: Void = kgService.healthCheck()
        async let quota: Void = kgService.fetchQuota()
        _ = await (health, quota)
        continuation.yield(.finished(.status, status: .done, detail: ""))

        continuation.finish()
        await pump.value

        // 終態取自這一輪自己的回報，**不是** `lastBackgroundSyncError`。那是四個
        // trigger 共用的全域欄位，對「被別的 round 佔著 claim 所以什麼都沒做」與
        // 「跑到一半被取消」這兩條路徑，它會讓面板宣稱 100% 完成。
        switch outcome {
        case .completed: syncProgress.finish(.completed)
        case .failed:    syncProgress.finish(.failed)
        case .didNotRun: syncProgress.reset()  // 直接收合，不宣稱任何事
        }

        refreshObservationPreview()
    }

    #if DEBUG
    func useProductionBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.useProductionServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
        refreshObservationPreview()
    }

    func useLocalBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.setDebugLocalServerURL(debugLocalServerURL)
        KGService.useLocalServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
        refreshObservationPreview()
    }
    #endif
}

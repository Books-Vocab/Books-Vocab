//
//  SettingsCoordinatorReviewClockTests.swift
//  Books & Vocab Tests
//
//  Defect A 回歸測試：`SettingsCoordinator.applyServerReviewClock` 冷啟動套用
//  server pause-clock 時，`paused_at` 若走 strict `AppDateFormatters.iso8601`
//  （要求小數秒）解析，後端回傳不含小數秒的 ISO8601 時戳會靜默解析失敗
//  （`.date(from:)` 回 nil）→ 凍結沒套上，但 config 仍回報 `is_paused=true`
//  （false-green）。修法：改用 `AppDateFormatters.parseISO8601`（含小數秒優先，
//  失敗再 fallback 不含小數秒），對稱寫入側（`SettingsCoordinator.swift:207`
//  `iso8601.string(from:)` 恆產小數秒）。
//
//  走公開路徑 `SettingsCoordinator.loadData` 觸發（`applyServerReviewClock` 為
//  private），對齊 `ReviewSettingsStore.shared` 單例 + `UserDefaults.standard`
//  的既有測試慣例（見 TranslationLanguageDefaultTests 的 snapshot/restore）。
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct SettingsCoordinatorReviewClockTests {

    // MARK: - Mocks

    private final class MockAuth: AuthManaging {
        var isLoggedIn: Bool = true
        var userId: String? = "test_user"
        var token: String? = "test_token"
        var displayName: String?
        var userEmail: String?
        var avatarURL: URL?
        var authError: String?
        var isAuthenticating: Bool = false
        var isDemoMode: Bool = false

        func enterDemoMode(modelContainer: ModelContainer) {}
        func exitDemoMode(modelContainer: ModelContainer) {}
        func refreshSessionIfNeeded() {}
        func login(userId: String, token: String) {}
        func login(customToken: String) async {}
        func logout(modelContainer: ModelContainer?, reason: String) {}
        func loginWithGoogle(modelContainer: ModelContainer?) {}
        func loginWithApple(modelContainer: ModelContainer?) {}
    }

    /// `loadData` 只用到 `healthCheck` + `fetchUserConfig`；其餘成員維持
    /// fatalError stub，對齊 `PodcastPlayerLoaderTests.StubKGService` 慣例。
    private final class StubKGService: KGServing {
        var lastBackgroundSyncError: String?
        var serverURL: String = "https://example.com"
        var isConnected: Bool = true
        var lastSyncDate: Date?
        var serverCardCount: Int = 0
        var sessionExpiredReason: String?

        var userConfigToReturn = KGUserConfig(
            translation: nil, review_clock: nil, review_mode: nil, vocab_ui: nil, auto_link: nil
        )

        func currentAuthToken() async throws -> String { "token" }
        func backgroundSync(container: ModelContainer) async {}
        func healthCheck() async {}
        func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse { fatalError("unused") }
        func triggerPipeline(notebookId: String) async throws { fatalError("unused") }
        func copyDeck(deckId: String, idempotencyKey: String, notebookName: String?) async throws -> DeckCopyResponse { fatalError("unused") }
        func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> Bool { fatalError("unused") }
        func fetchNotebooks() async throws -> [KGNotebook] { fatalError("unused") }
        func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
        func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
        func deleteNotebook(id: String) async throws { fatalError("unused") }
        func fetchUserConfig() async throws -> KGUserConfig { userConfigToReturn }
        func fetchEntitlements() async throws -> KGEntitlements { fatalError("unused") }
        func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements { fatalError("unused") }
        func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateReviewClockConfig(_ reviewClock: KGReviewClockConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateReviewModeConfig(_ reviewMode: KGReviewModeConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateVocabUIConfig(_ vocabUI: KGVocabUIConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateAutoLinkConfig(_ autoLink: KGAutoLinkConfig) async throws -> KGUserConfig { fatalError("unused") }
        func deleteAccount() async throws { fatalError("unused") }
        func pullGraphLinks() async throws -> [KGGraphLink] { fatalError("unused") }
        func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink { fatalError("unused") }
        func deleteLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
        func hideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
        func unhideLink(linkId: String, notebookId: String) async throws { fatalError("unused") }
        func deleteCard(word: String, notebookId: String) async throws { fatalError("unused") }
        func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse { fatalError("unused") }
        func archiveCard(word: String, archived: Bool, notebookId: String) async throws { fatalError("unused") }
        func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse { fatalError("unused") }
        func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) { fatalError("unused") }
        func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) { fatalError("unused") }
        func pullReviewEvents(container: ModelContainer) async throws { fatalError("unused") }
        func pushReviewQuietly(container: ModelContainer) async {}
        func clearLocalData(container: ModelContainer, reason: String) async {}
        func fetchQuota() async {}
    }

    // MARK: - Helpers

    /// 走 `SettingsCoordinator.loadData` 冷啟動路徑套用 server pause-clock，驗證
    /// `ReviewSettingsStore.shared` 的三層是否套上。強制打開 cold-start gate
    /// （`pauseClockSnapshot.updatedAt == nil`），跑完還原原狀避免污染其他測試。
    private func runColdStartApply(pausedAtISO: String, updatedAt: Double) async -> PauseClockState {
        let store = ReviewSettingsStore.shared
        let originalSnapshot = store.pauseClockSnapshot
        defer { store.restorePauseState(originalSnapshot) }

        // 強制打開 cold-start gate：清掉本地 pause updatedAt，讓 store 視為
        // 「此裝置從未寫過 pause clock」（對齊 SettingsCoordinator 的 guard 條件）。
        UserDefaults.standard.removeObject(forKey: "review_settings_progress_updated_at")

        let coordinator = SettingsCoordinator()
        let auth = MockAuth()
        let kgService = StubKGService()
        kgService.userConfigToReturn = KGUserConfig(
            translation: nil,
            review_clock: KGReviewClockConfig(is_paused: true, paused_at: pausedAtISO, updated_at: updatedAt),
            review_mode: nil,
            vocab_ui: nil,
            auto_link: nil
        )

        await coordinator.loadData(authManager: auth, kgService: kgService)

        return PauseClockState(
            isPaused: store.settings.isProgressPaused,
            pausedAt: store.settings.progressPausedAt,
            updatedAt: nil
        )
    }

    private func expectedUTCDate(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int) -> Date {
        var comps = DateComponents()
        comps.timeZone = TimeZone(identifier: "UTC")
        comps.year = year; comps.month = month; comps.day = day
        comps.hour = hour; comps.minute = minute; comps.second = second
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar.date(from: comps)!
    }

    // MARK: - Tests

    /// Defect A 案例：後端回傳的 `paused_at` 不含小數秒。修前用 strict formatter
    /// 解析回 nil → `progressPausedAt` 沒套上（凍結靜默失效）。
    @Test func coldStartAppliesPauseClock_whenPausedAtHasNoFractionalSeconds() async {
        let result = await runColdStartApply(
            pausedAtISO: "2026-07-09T14:59:59Z",
            updatedAt: 1_800_000_000
        )
        let expected = expectedUTCDate(year: 2026, month: 7, day: 9, hour: 14, minute: 59, second: 59)
        #expect(result.isPaused == true)
        #expect(result.pausedAt == expected)
    }

    /// 對照案例：含小數秒的既有格式仍要正確解析（防迴歸）。
    @Test func coldStartAppliesPauseClock_whenPausedAtHasFractionalSeconds() async {
        let result = await runColdStartApply(
            pausedAtISO: "2026-07-09T14:59:59.000Z",
            updatedAt: 1_800_000_001
        )
        let expected = expectedUTCDate(year: 2026, month: 7, day: 9, hour: 14, minute: 59, second: 59)
        #expect(result.isPaused == true)
        #expect(result.pausedAt == expected)
    }
}

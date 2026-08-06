//
//  SettingsResyncConcurrencyTests.swift
//  Books & Vocab Tests
//
//  `SettingsCoordinator.resync` 的兩個契約：
//
//  1. **額度與連線檢查是併發的**，不是兩趟序列往返。用重疊探針量「同時在裡面的
//     最大人數」——量時間會 flaky，量 peak 不會，而且它與排程順序無關。
//  2. **它把 backgroundSync 的事件餵進 SyncProgressStore，而且順序不亂。** reporter
//     走 AsyncStream 就是為了這個：每個事件開一個 `Task { @MainActor in }` 不保證
//     順序，計數器會彈回。這裡直接把亂序來源（多條腿併發送事件）造出來檢查。
//
//  podcast 那條腿的併發**沒有**在這裡測：`runPodcastLeg` 直接 new
//  `PodcastSyncService`，要驗它得讓單元測試打真網路。那條的驗收在 kg-pool-2 對
//  felix 生產 log 的端到端量測（podcast 段 6.1s → 2.5s 以下）。這裡誠實留白，
//  不用一個假的替身假裝測過了。
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct SettingsResyncConcurrencyTests {

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

    /// 重疊探針：記錄「同時在裡面的最大人數」。
    ///
    /// **不記錄「誰看見了誰」。** 那個版本對排程順序敏感——先進的那支 observe 時
    /// 看得到後進者，後進者 observe 時先進者可能已經離開，於是 `sawPeer` 只收到
    /// 一半，測試以「實作是序列的」的形式紅掉，而實作其實是併發的。peak 是
    /// 順序無關的同一個性質：peak == 2 就是「某個瞬間兩支都在裡面」，而序列執行
    /// 的 peak 恆為 1。（同一個形狀在 `PodcastCatalogSkipTests.ConcurrencyTracker`
    /// 已經穩定跑過。）
    private actor OverlapProbe {
        private var inFlight = 0
        private(set) var peak = 0
        private(set) var visited: Set<String> = []

        func enter(_ name: String) {
            inFlight += 1
            peak = max(peak, inFlight)
            visited.insert(name)
        }

        func leave() { inFlight -= 1 }
    }

    private final class ProbeKGService: KGServing {
        var lastBackgroundSyncError: String?
        var serverURL: String = "https://example.com"
        var isConnected: Bool = true
        var lastSyncDate: Date?
        var serverCardCount: Int = 0
        var sessionExpiredReason: String?

        let probe = OverlapProbe()
        /// backgroundSync 要送出的事件；測試用它模擬多條腿發出的回報。
        var eventsToEmit: [SyncProgressEvent] = []
        /// 從**兩個併發 task** 交錯送出，模擬 pull 腿與 reviewEvents 腿同時回報。
        /// 單一同步迴圈證明不了 AsyncStream 的順序保證——那種順序是發送端給的。
        var concurrentEventLegs: [[SyncProgressEvent]] = []
        var outcome: SyncRoundOutcome = .completed

        func backgroundSync(container: ModelContainer) async {}

        @discardableResult
        func backgroundSync(container: ModelContainer, progress: SyncProgressReporting?) async -> SyncRoundOutcome {
            for event in eventsToEmit { progress?(event) }
            await withTaskGroup(of: Void.self) { group in
                for leg in concurrentEventLegs {
                    group.addTask {
                        for event in leg {
                            progress?(event)
                            await Task.yield()
                        }
                    }
                }
            }
            return outcome
        }

        func healthCheck() async { await run("health") }
        func fetchQuota() async { await run("quota") }

        private func run(_ name: String) async {
            await probe.enter(name)
            // 兩次 yield：留給對方被排進來並跑到自己 enter 的機會。序列實作下，
            // 第一支會在第二支開始前就 leave，peak 停在 1。
            await Task.yield()
            await Task.yield()
            await probe.leave()
        }

        // MARK: 其餘成員維持 fatalError stub（對齊 StubKGService 慣例）
        func currentAuthToken() async throws -> String { "t" }
        func batchAdd(entries: [VocabularyEntry], notebookId: String) async throws -> KGAddResponse { fatalError("unused") }
        func triggerPipeline(notebookId: String) async throws {}
        func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)?, notebookId: String?) async throws -> KGPullOutcome { .unchanged }
        func fetchNotebooks() async throws -> [KGNotebook] { [] }
        func createNotebook(name: String, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
        func updateNotebook(id: String, name: String?, color: String?, coverPattern: String?) async throws -> KGNotebook { fatalError("unused") }
        func deleteNotebook(id: String) async throws {}
        func fetchUserConfig() async throws -> KGUserConfig { fatalError("unused") }
        func fetchEntitlements() async throws -> KGEntitlements { fatalError("unused") }
        func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements { fatalError("unused") }
        func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateReviewClockConfig(_ reviewClock: KGReviewClockConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateReviewModeConfig(_ reviewMode: KGReviewModeConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateVocabUIConfig(_ vocabUI: KGVocabUIConfig) async throws -> KGUserConfig { fatalError("unused") }
        func updateAutoLinkConfig(_ autoLink: KGAutoLinkConfig) async throws -> KGUserConfig { fatalError("unused") }
        func deleteAccount() async throws {}
        func pullGraphLinks() async throws -> [KGGraphLink] { [] }
        func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink { fatalError("unused") }
        func deleteLink(linkId: String, notebookId: String) async throws {}
        func hideLink(linkId: String, notebookId: String) async throws {}
        func unhideLink(linkId: String, notebookId: String) async throws {}
        func deleteCard(word: String, notebookId: String) async throws {}
        func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse { fatalError("unused") }
        func archiveCard(word: String, archived: Bool, notebookId: String) async throws {}
        func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse { fatalError("unused") }
        func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) { (0, 0) }
        func pushReviewEvents(container: ModelContainer) async throws -> (inserted: Int, skipped: Int) { (0, 0) }
        func pullReviewEvents(container: ModelContainer) async throws {}
        func pushReviewQuietly(container: ModelContainer) async {}
        func clearLocalData(container: ModelContainer, reason: String) async {}
        func pullCopiedDeck(container: ModelContainer, notebookId: String) async {}
        func copyDeck(deckId: String, idempotencyKey: String, notebookName: String?) async throws -> DeckCopyResponse { fatalError("unused") }
        // `DictionaryServing` 整組走 protocol extension 的預設實作（全部 throw
        // "unavailable"），這裡不覆寫。
    }

    private static func makeContainer() -> ModelContainer {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try! ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            PodcastSeries.self, PodcastEpisode.self,
            configurations: config
        )
    }

    // MARK: - Tests

    @Test("額度與連線檢查併發，不是兩趟序列往返")
    func quotaAndHealthOverlap() async {
        let coordinator = SettingsCoordinator()
        let service = ProbeKGService()

        // container 必須用 local 撐住：`resync` 會走 `modelContext.container
        // .mainContext.save()`，容器若是暫時值，那句在 SwiftData 內部直接 SIGTRAP。
        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: MockAuth(), kgService: service, modelContext: container.mainContext
        )

        let peak = await service.probe.peak
        let visited = await service.probe.visited
        #expect(visited == ["health", "quota"], "兩支都要真的跑到")
        #expect(peak == 2, "某個瞬間兩支都要在裡面；序列執行時 peak 恆為 1。實際：\(peak)")
    }

    @Test("resync 把 backgroundSync 的事件依序餵進 store，計數器不倒退")
    func progressEventsReachTheStoreInOrder() async {
        let coordinator = SettingsCoordinator()
        let service = ProbeKGService()
        service.eventsToEmit = [.started(.push), .finished(.push, status: .done, detail: "p")]
        // 兩條腿併發送事件——這才是 AsyncStream 要對付的亂序來源。pull 那條的
        // current 必須嚴格遞增抵達，否則計數器會彈回。
        service.concurrentEventLegs = [
            [
                .started(.pull),
                .advanced(.pull, current: 10, total: 100, detail: "a"),
                .advanced(.pull, current: 40, total: 100, detail: "b"),
                .advanced(.pull, current: 80, total: 100, detail: "c"),
                .finished(.pull, status: .done, detail: "q")
            ],
            [
                .started(.reviewEvents),
                .finished(.reviewEvents, status: .done, detail: "r")
            ]
        ]

        // container 必須用 local 撐住：`resync` 會走 `modelContext.container
        // .mainContext.save()`，容器若是暫時值，那句在 SwiftData 內部直接 SIGTRAP。
        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: MockAuth(), kgService: service, modelContext: container.mainContext
        )

        let steps = coordinator.syncProgress.steps
        #expect(steps.map(\.id) == KGService.syncStepIDs().map(\.rawValue) + ["status"])
        #expect(steps.first(where: { $0.id == "push" })?.status == .done)
        #expect(steps.first(where: { $0.id == "pull" })?.status == .done)
        #expect(steps.first(where: { $0.id == "pull" })?.current == 80,
                "advanced 事件必須依序抵達；亂序時 80 會被 10 蓋掉")
        #expect(steps.first(where: { $0.id == "reviewEvents" })?.status == .done,
                "另一條併發腿的事件不得被 pull 那條擠掉")
        #expect(steps.first(where: { $0.id == "status" })?.status == .done,
                "額度與連線那一列由 resync 自己收尾")
    }

    @Test("成功一輪收在 .completed 且進度條走到滿")
    func successfulRoundCompletes() async {
        let coordinator = SettingsCoordinator()
        let service = ProbeKGService()

        // container 必須用 local 撐住：`resync` 會走 `modelContext.container
        // .mainContext.save()`，容器若是暫時值，那句在 SwiftData 內部直接 SIGTRAP。
        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: MockAuth(), kgService: service, modelContext: container.mainContext
        )

        #expect(coordinator.syncProgress.phase == .completed)
        #expect(coordinator.syncProgress.fraction == 1.0)
    }

    @Test("backgroundSync 回報錯誤時收在 .failed，且不把沒跑的步驟刷成綠勾")
    func failedRoundDoesNotFakeCompletion() async {
        let coordinator = SettingsCoordinator()
        let service = ProbeKGService()
        service.outcome = .failed
        service.eventsToEmit = [.finished(.push, status: .error, detail: "boom")]

        // container 必須用 local 撐住：`resync` 會走 `modelContext.container
        // .mainContext.save()`，容器若是暫時值，那句在 SwiftData 內部直接 SIGTRAP。
        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: MockAuth(), kgService: service, modelContext: container.mainContext
        )

        #expect(coordinator.syncProgress.phase == .failed)
        #expect(coordinator.syncProgress.fraction < 1.0)
        #expect(coordinator.syncProgress.steps.first(where: { $0.id == "pull" })?.status == .waiting,
                "沒跑到的步驟不得被收尾邏輯打勾")
    }

    @Test("被別的 round 佔著 claim（.didNotRun）→ 面板收合，不得宣稱 100% 完成")
    func abandonedRoundDoesNotClaimSuccess() async {
        let coordinator = SettingsCoordinator()
        let service = ProbeKGService()
        // `claimBackgroundSync()` 失敗那條出口在 `lastBackgroundSyncError` 被重置
        // **之前**就 return，所以那個全域欄位留著上一輪的 nil。舊寫法會據此判定
        // 「成功」，於是一輪什麼都沒做的同步顯示 100% 完成。取消那條路徑同理。
        service.outcome = .didNotRun
        service.lastBackgroundSyncError = nil

        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: MockAuth(), kgService: service, modelContext: container.mainContext
        )

        #expect(coordinator.syncProgress.phase == .ready)
        #expect(coordinator.syncProgress.fraction == 0)
        #expect(coordinator.syncProgress.steps.isEmpty, "什麼都沒做的一輪不該留下任何綠勾")
    }

    @Test("demo 模式與登出一律 no-op，連進度都不該開始")
    func resyncIsNoOpWithoutARealSession() async {
        let demoAuth = MockAuth()
        demoAuth.isDemoMode = true
        let coordinator = SettingsCoordinator()

        let container = Self.makeContainer()
        await coordinator.resync(
            authManager: demoAuth, kgService: ProbeKGService(),
            modelContext: container.mainContext
        )

        #expect(coordinator.syncProgress.phase == .ready)
        #expect(coordinator.syncProgress.steps.isEmpty)
    }
}

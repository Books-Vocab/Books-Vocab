import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite("Settings sync lifecycle root cause", .serialized)
@MainActor
struct SettingsSyncLifecycleRootCauseTests {
    @Test("canonical sync summary accepts terminal error provenance")
    func canonicalSyncSummaryCarriesLifecycleMetadata() {
        let data = Data(#"""
        {
            "isConnected": true,
            "isSyncing": false,
            "summaryText": "Connected",
            "lastSyncedText": null,
            "lifecycle": "terminalError",
            "message": "sync failed",
            "attempt": 1,
            "dataOutcome": "partial"
        }
        """#.utf8)

        let summary = try? JSONDecoder().decode(SettingsFixtureSeed.SyncSummary.self, from: data)
        #expect(summary?.lifecycle == .terminalError)
        #expect(summary?.message == "sync failed")
        #expect(summary?.attempt == 1)
        #expect(summary?.dataOutcome == .partial)
    }

    @Test("illegal lifecycle transitions throw instead of silently changing the state")
    func illegalTransitionsAreObservable() {
        var lifecycle = SettingsSyncLifecycle.idle
        #expect(throws: SettingsSyncLifecycle.TransitionError.self) {
            try lifecycle.transition(.succeed)
        }

        #expect(throws: SettingsSyncLifecycle.TransitionError.self) {
            try lifecycle.transition(.dismiss)
        }
    }

    @Test("cancel returns an in-flight round to idle")
    func cancellationIsAnExplicitTransition() throws {
        var lifecycle = SettingsSyncLifecycle.idle
        try lifecycle.transition(.begin)
        try lifecycle.transition(.cancel)
        #expect(lifecycle == .idle)
    }

    @Test("real backgroundSync preserves a partial pull and succeeds on the next service call")
    func realServiceFailureThenRetryReadsSwiftDataResidual() async throws {
        try #require(NetworkMonitor.shared.isConnected)
        let defaults = UserDefaults.standard
        let defaultKeys = [
            KGService.SyncKeys.incrementalBoundary,
            KGService.SyncKeys.payloadVersion,
            KGService.SyncKeys.lastSyncDate,
            KGService.SyncKeys.reviewEventPullBoundary,
            "kg_dictionary_reader_visibility_migrated_v1"
        ]
        let priorDefaults: [String: Any?] = Dictionary(uniqueKeysWithValues: defaultKeys.map {
            ($0, defaults.object(forKey: $0))
        })
        defer {
            for key in defaultKeys {
                if let stored = priorDefaults[key], let value = stored {
                    defaults.set(value, forKey: key)
                } else {
                    defaults.removeObject(forKey: key)
                }
            }
        }
        defaults.removeObject(forKey: KGService.SyncKeys.incrementalBoundary)
        defaults.removeObject(forKey: KGService.SyncKeys.payloadVersion)
        let transport = ScriptedSyncTransport()
        let service = KGService(
            authSession: TestAuthSession(),
            sessionInvalidator: TestSessionInvalidator(),
            transport: transport
        )
        let container = try Self.makeContainer()

        let first = await service.backgroundSync(container: container)
        #expect(first == .failed)
        let residualAfterFailure = try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(residualAfterFailure.map(\.word) == ["residual"])

        let second = await service.backgroundSync(container: container)
        #expect(second == .completed)
        let entriesAfterRetry = try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(Set(entriesAfterRetry.map(\.word)) == Set(["residual", "complete"]))
        let paths = await transport.snapshotPaths()
        #expect(paths.filter { $0 == "/api/vocab" }.count == 2)
        #expect(paths.filter { $0 == "/api/dictionary-cards" }.count == 2)
    }

    @Test("main-context save failure is fail-closed")
    func saveFailureCannotBecomeTerminalSuccess() async throws {
        let service = CompletedSyncService()
        let coordinator = SettingsCoordinator(
            settingsSyncService: service,
            syncPersistence: FailingSyncPersistence()
        )
        let auth = TestAuthManager()
        let container = try Self.makeContainer()

        await coordinator.resync(
            authManager: auth,
            kgService: service,
            modelContext: container.mainContext
        )

        #expect(coordinator.syncLifecycle == .terminalError(message: L10n.string("同步失敗")))
        #expect(coordinator.syncProgress.phase == .failed)
        #expect(coordinator.syncDataOutcome == .partial)
    }

    private static func makeContainer() throws -> ModelContainer {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            PodcastSeries.self, PodcastEpisode.self,
            configurations: configuration
        )
    }

    private final class TestAuthSession: AuthSessionProviding {
        let isLoggedIn = true
        let token: String? = "settings-sync-test-token"
    }

    private final class TestSessionInvalidator: SessionInvalidating {
        func logout(modelContainer: ModelContainer?, reason: String) {}
        func waitForPendingLocalDataCleanup() async {}
    }

    private final class TestAuthManager: AuthManaging {
        var isLoggedIn = true
        var userId: String? = "settings-sync-test-user"
        var token: String? = "settings-sync-test-token"
        var displayName: String?
        var userEmail: String?
        var avatarURL: URL?
        var authError: String?
        var isAuthenticating = false
        var isDemoMode = false

        func enterDemoMode(modelContainer: ModelContainer) {}
        func exitDemoMode(modelContainer: ModelContainer) {}
        func refreshSessionIfNeeded() {}
        func login(userId: String, token: String) {}
        func login(customToken: String) async {}
        func logout(modelContainer: ModelContainer?, reason: String) {}
        func loginWithGoogle(modelContainer: ModelContainer?) {}
        func loginWithApple(modelContainer: ModelContainer?) {}
    }

    private struct SaveFailure: Error {}

    private final class FailingSyncPersistence: SettingsSyncPersisting {
        func save(container: ModelContainer) throws {
            throw SaveFailure()
        }
    }

    private final class CompletedSyncService: BackgroundSyncing, HealthChecking, QuotaServing {
        var lastBackgroundSyncError: String?

        func backgroundSync(container: ModelContainer) async {}

        @discardableResult
        func backgroundSync(
            container: ModelContainer,
            progress: SyncProgressReporting?
        ) async -> SyncRoundOutcome {
            .completed
        }

        func healthCheck() async {}
        func fetchQuota() async {}
    }

    private actor PathStore {
        var paths: [String] = []

        func append(_ path: String) {
            paths.append(path)
        }
    }

    private final class ScriptedSyncTransport: KGHTTPTransport, @unchecked Sendable {
        let store = PathStore()
        private let lock = NSLock()
        private var vocabPullCount = 0

        func snapshotPaths() async -> [String] {
            await store.paths
        }

        func data(for request: URLRequest) async throws -> (Data, URLResponse) {
            let path = request.url?.path ?? ""
            await store.append(path)
            switch path {
            case "/api/vocab":
                let attempt = nextVocabPull()
                let body = attempt == 1 ? Self.partialCards : Self.completeCards
                return Self.response(for: request, statusCode: 200, body: body)
            case "/api/dictionary-cards":
                let statusCode = currentVocabPull() == 1 ? 429 : 200
                let body = statusCode == 200 ? Data("[]".utf8) : Data("{}".utf8)
                return Self.response(for: request, statusCode: statusCode, body: body)
            case "/api/vocab/review-events":
                return Self.response(
                    for: request,
                    statusCode: 200,
                    body: Data(#"{"entries":[],"cursor":null}"#.utf8)
                )
            default:
                return Self.response(for: request, statusCode: 404, body: Data("{}".utf8))
            }
        }

        private func nextVocabPull() -> Int {
            lock.lock()
            defer { lock.unlock() }
            vocabPullCount += 1
            return vocabPullCount
        }

        private func currentVocabPull() -> Int {
            lock.lock()
            defer { lock.unlock() }
            return vocabPullCount
        }

        private static func response(
            for request: URLRequest,
            statusCode: Int,
            body: Data
        ) -> (Data, URLResponse) {
            let url = request.url ?? URL(string: "https://settings-test.invalid")!
            let headers = statusCode == 429
                ? ["Content-Type": "application/json", "Retry-After": "0"]
                : ["Content-Type": "application/json"]
            return (
                body,
                HTTPURLResponse(
                    url: url,
                    statusCode: statusCode,
                    httpVersion: nil,
                    headerFields: headers
                )!
            )
        }

        private static let partialCards = Data(#"""
            [
            {"id":"settings-residual","content":"residual","meaning":"residual","examples":["residual"],"mode":"recognition","isDeleted":false,"isArchived":false}
            ]
            """#.utf8)

        private static let completeCards = Data(#"""
            [
            {"id":"settings-residual","content":"residual","meaning":"residual","examples":["residual"],"mode":"recognition","isDeleted":false,"isArchived":false},
            {"id":"settings-complete","content":"complete","meaning":"complete","examples":["complete"],"mode":"recognition","isDeleted":false,"isArchived":false}
            ]
            """#.utf8)
    }
}

#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

@Suite(.serialized) struct SettingsFixturesTests {
    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }

    private static var generatedDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/demo/generated/ios_fixture_dataset.json")
            return try Data(contentsOf: url)
        }
    }

    @Test func settingsFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = SettingsFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = SettingsFixtures.recipes(for: .catalog).map(\.key.rawValue)

        // The enum manifest is the only ordering contract. Do not duplicate the
        // fixture list here: a new fixture must update one SoT, not this test.
        let expectedKeys = SettingsFixtureID.allCases.map { $0.key.rawValue }
        #expect(Set(expectedKeys).count == expectedKeys.count)
        #expect(previewKeys == expectedKeys)

        #expect(catalogKeys == previewKeys)
    }

    @Test func settingsFixtureRegistryIsManifestOnly() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/Settings/SettingsFixtures.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let registryStart = try #require(source.range(of: "private static let registry"))
        let registryEnd = try #require(source.range(of: "static func recipes", range: registryStart.upperBound..<source.endIndex))
        let registrySource = String(source[registryStart.lowerBound..<registryEnd.lowerBound])

        #expect(registrySource.contains("SettingsFixtureID.allCases.map"))
        #expect(registrySource.contains("FixtureDatasetStore.requireSettingsSeed(for: fixtureID)"))
        #expect(!registrySource.contains(".init("), "Settings fixture registry must not construct local seed data")
    }

    @Test func repoAndGeneratedDatasetsDeclareNoUnknownSettingsFixtureKey() throws {
        let expected = Set(SettingsFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        // FROZEN 2026-08-05 — 凍結前這兩行是雙向 `==`（world keys 必須等於 allCases），
        // 那是「加一個 FixtureID 就得回填兩份 world」的稅源。現只驗單向：world 不得含
        // app 不認識的 key（那種 key 永遠不會 render）。兩行各配一個 non-empty 正控——
        // 沒有正控的 subset 對空集合恆真（假綠）。復業第一步＝改回 `==`，完整配方見正本。
        // 正本 docs/reference/catalog_scope.md §FROZEN。
        #expect(!repoDocument.settings.isEmpty)
        #expect(Set(repoDocument.settings.keys).isSubset(of: expected))
        #expect(!generatedDocument.settings.isEmpty)
        #expect(Set(generatedDocument.settings.keys).isSubset(of: expected))
    }

    @Test func subscriptionFreeFixtureComesFromUIWorld() async throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let state = SettingsFixtures.state(for: .subscriptionFree)
            let subscription = try #require(state.subscription)
            #expect(subscription.isActive == false)
            #expect(subscription.planName == "免費方案")
            #expect(subscription.ctaTitle == "升級 Pro")
        }
    }

    @Test func accountLongIdentityFixtureComesFromUIWorld() async throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let state = SettingsFixtures.state(for: .accountLongIdentity)
            #expect(state.auth.isLoggedIn == true)
            #expect(state.auth.displayName.contains("Wonderfully Long Display Name"))
            #expect(state.auth.email?.contains("layout.testing") == true)
            #expect(state.subscription?.isActive == true)
            #expect(state.danger?.isDeletingAccount == false)
        }
    }

    @Test func accountLoggedOutErrorFixtureComesFromUIWorld() async throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let state = SettingsFixtures.state(for: .accountLoggedOutError)
            #expect(state.auth.isLoggedIn == false)
            #expect(state.auth.authError == "無法連線至驗證伺服器，請稍後再試。")
            #expect(state.subscription == nil)
            #expect(state.danger == nil)
        }
    }

    @Test func preferencesFixturesComeFromUIWorld() async throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let autoSyncOff = SettingsFixtures.state(for: .preferencesAutoSyncOff).preferences
            #expect(autoSyncOff.selectedLanguage == "English")
            #expect(autoSyncOff.selectedAppearance == "淺色")
            #expect(autoSyncOff.translationTarget == "日本語")
            #expect(autoSyncOff.selectedReviewMode == "密集")
            #expect(autoSyncOff.autoSyncEnabled == false)
            #expect(autoSyncOff.showAutoSync == true)

            let loggedOut = SettingsFixtures.state(for: .preferencesLoggedOutNoSync).preferences
            #expect(loggedOut.selectedAppearance == "深色")
            #expect(loggedOut.selectedReviewMode == "已凍結 · 自訂")
            #expect(loggedOut.autoSyncEnabled == false)
            #expect(loggedOut.showAutoSync == false)
        }
    }

    @Test func reviewSettingsFixturesComeFromUIWorld() async throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let relaxed = SettingsFixtures.reviewSettings(for: .subscriptionFree)
            #expect(relaxed.mode == .relaxed)
            #expect(relaxed.customInitialIntervalHours == 12)
            #expect(relaxed.isProgressPaused == false)

            let intensive = SettingsFixtures.reviewSettings(for: .preferencesAutoSyncOff)
            #expect(intensive.mode == .intensive)
            #expect(intensive.autoplaySpeed == .fast)

            let custom = SettingsFixtures.reviewSettings(for: .accountLongIdentity)
            #expect(custom.mode == .custom)
            #expect(custom.customInitialIntervalHours == 24)
            #expect(custom.customMaximumIntervalHours == 2160)

            let paused = SettingsFixtures.reviewSettings(for: .preferencesLoggedOutNoSync)
            #expect(paused.mode == .relaxed)
            #expect(paused.isProgressPaused == true)
            #expect(paused.progressPausedAt == Date(timeIntervalSince1970: 1_733_500_000))
        }
    }

    @Test func p15SettingsCounterexamplesAndInformationArchitectureContract() throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedCounterexamples = [
            "long_content_counterexample",
            "reset_counterexample",
        ]

        for fixtureID in expectedCounterexamples {
            #expect(document.settings[fixtureID] != nil, "UI World must inject settings.\(fixtureID)")
        }

        let settingsSourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Views/Settings/SettingsPreferencesSection.swift")
        let settingsSource = try String(contentsOf: settingsSourceURL, encoding: .utf8)
        for identifier in [
            "settings.preferences.appearanceGroup",
            "settings.preferences.learningGroup",
            "settings.preferences.feedbackGroup",
            "settings.preferences.readerGroup",
            "settings.preferences.syncGroup",
        ] {
            #expect(settingsSource.contains(identifier), "Settings section selector missing: \(identifier)")
        }

        let accountDetailURL = settingsSourceURL
            .deletingLastPathComponent()
            .appendingPathComponent("SettingsAccountDetailView.swift")
        let accountDetailSource = try String(contentsOf: accountDetailURL, encoding: .utf8)
        #expect(accountDetailSource.contains("settings.account.dangerGroup"))
    }

    @Test func p15EvidenceContractBindsRequiredAndCounterexampleAssetsOneToOne() throws {
        let expected: [(fixtureID: String, label: String, assetID: String, stepLabel: String)] = [
            ("preferences_auto_sync_off", "required-settings", "settings-required", "required-settings"),
            ("preferences_logged_out_no_sync", "section-navigation", "settings-section-navigation", "section-navigation"),
            ("long_content_counterexample", "long-content-counterexample", "settings-long-content-counterexample", "long-content-counterexample"),
            ("reset_counterexample", "reset-counterexample", "settings-reset-counterexample", "reset-counterexample"),
        ]
        let requiredAssetIDs = Set(expected.prefix(2).map(\.assetID))
        let counterexampleAssetIDs = Set(expected.suffix(2).map(\.assetID))
        #expect(requiredAssetIDs.isDisjoint(with: counterexampleAssetIDs))

        for data in [try Self.marketingDemoData, try Self.generatedDemoData] {
            let root = try Self.jsonObject(data)
            let settings = try #require(root["settings"] as? [String: Any])
            var assetIDs: [String] = []

            for contract in expected {
                let seed = try #require(settings[contract.fixtureID] as? [String: Any])
                let evidence = try #require(seed["evidence"] as? [String: Any])
                #expect(evidence["label"] as? String == contract.label)
                #expect(evidence["assetID"] as? String == contract.assetID)
                #expect(evidence["stepLabel"] as? String == contract.stepLabel)
                assetIDs.append(try #require(evidence["assetID"] as? String))
            }

            #expect(Set(assetIDs).count == expected.count, "Every evidence mapping must resolve to one distinct asset")
        }

        let manifestSourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("ops/ui_world_manifest.py")
        let manifestSource = try String(contentsOf: manifestSourceURL, encoding: .utf8)
        for label in expected.map(\.label) {
            #expect(manifestSource.contains(label), "Manifest must name evidence step label (label)")
        }
    }

    @Test func p15ResetCounterexampleHasObservableLifecycleBoundary() throws {
        let root = try Self.jsonObject(Self.marketingDemoData)
        let settings = try #require(root["settings"] as? [String: Any])
        let seed = try #require(settings["reset_counterexample"] as? [String: Any])
        let lifecycle = try #require(seed["resetLifecycle"] as? [String: Any])
        let before = try #require(lifecycle["before"] as? [String: Any])
        let after = try #require(lifecycle["after"] as? [String: Any])

        #expect((before["localCardCount"] as? Int ?? 0) > (after["localCardCount"] as? Int ?? 0))
        #expect((before["hasCustomPreferences"] as? Bool) != (after["hasCustomPreferences"] as? Bool))
        #expect(before["isLoggedIn"] as? Bool == true)
        #expect(after["isLoggedIn"] as? Bool == true)
        #expect(lifecycle["phase"] as? String == "succeeded")
        #expect(lifecycle["canRetry"] as? Bool == false)
        #expect((lifecycle["terminalMessage"] as? String)?.isEmpty == false)

        let accountDetailURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("BooksAndVocab/Views/Settings/SettingsAccountDetailView.swift")
        let accountDetailSource = try String(contentsOf: accountDetailURL, encoding: .utf8)
        for contractIdentifier in [
            "settings.account.resetBoundary",
            "settings.account.resetBoundary.phase",
            "settings.account.resetBoundary.resetButton",
            "resetLifecycle",
        ] {
            #expect(accountDetailSource.contains(contractIdentifier), "Production reset boundary is missing (contractIdentifier)")
        }
    }

    @Test func p15ResetLifecycleAdapterAndTerminalTransitionsAreObservable() throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let lifecycle = try #require(SettingsFixtures.state(for: .resetCounterexample).danger?.resetLifecycle)
            #expect(lifecycle.phase == .succeeded)
            #expect(lifecycle.before.localCardCount == 3)
            #expect(lifecycle.after.localCardCount == 0)
            #expect(lifecycle.before.hasCustomPreferences == true)
            #expect(lifecycle.after.hasCustomPreferences == false)
            #expect(lifecycle.before.isLoggedIn == lifecycle.after.isLoggedIn)
            #expect(lifecycle.terminalMessage?.isEmpty == false)
            #expect(lifecycle.canRetry == false)

            let preReset = SettingsResetLifecycle.preReset(before: lifecycle.before)
            let resetting = preReset.resetting()
            let failed = resetting.failed(message: "fixture failure")
            let retry = SettingsResetLifecycle.preReset(before: failed.before).resetting()
            #expect(preReset.phase == .preReset)
            #expect(resetting.phase == .resetting)
            #expect(failed.phase == .failed)
            #expect(failed.after == failed.before)
            #expect(failed.canRetry == true)
            #expect(retry.phase == .resetting)
            #expect(retry.before == failed.before)
        }
    }

    @Test @MainActor func p15ResetCoordinatorPropagatesFailureAndRetry() async throws {
        let container = try ModelContainer(
            for: Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let authManager = LoggedInAuthStub()
        let resetService = ScriptedResetService(outcomes: [
            .failure(ResetFailure()),
            .success(())
        ])
        let coordinator = SettingsCoordinator()
        let before = SettingsResetLifecycle.Snapshot(
            localCardCount: 3,
            hasCustomPreferences: true,
            isLoggedIn: true
        )

        await coordinator.resetLocalData(
            before: before,
            authManager: authManager,
            kgService: resetService,
            modelContext: ModelContext(container)
        )

        let failed = try #require(coordinator.resetLifecycle)
        #expect(failed.phase == .failed)
        #expect(failed.before == before)
        #expect(failed.after == before)
        #expect(failed.canRetry == true)
        #expect(resetService.callCount == 1)

        await coordinator.resetLocalData(
            before: before,
            authManager: authManager,
            kgService: resetService,
            modelContext: ModelContext(container)
        )

        let succeeded = try #require(coordinator.resetLifecycle)
        #expect(succeeded.phase == .succeeded)
        #expect(succeeded.before == before)
        #expect(succeeded.after == .init(localCardCount: 0, hasCustomPreferences: false, isLoggedIn: true))
        #expect(succeeded.canRetry == false)
        #expect(resetService.callCount == 2)
    }

    private struct ResetFailure: Error {}

    private final class ScriptedResetService: LocalDataResetting, @unchecked Sendable {
        private var outcomes: [Result<Void, Error>]
        private(set) var callCount = 0

        init(outcomes: [Result<Void, Error>]) {
            self.outcomes = outcomes
        }

        func clearLocalData(container: ModelContainer, reason: String) async throws {
            callCount += 1
            try outcomes.removeFirst().get()
        }
    }

    @MainActor
    private final class LoggedInAuthStub: AuthManaging {
        var isLoggedIn = true
        var userId: String? = "settings-reset-test-user"
        var token: String? = "settings-reset-test-token"
        var displayName: String? = "Settings Reset Test"
        var userEmail: String? = "settings-reset@test.invalid"
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

    private static func jsonObject(_ data: Data) throws -> [String: Any] {
        let object = try JSONSerialization.jsonObject(with: data)
        return try #require(object as? [String: Any])
    }
}
#endif

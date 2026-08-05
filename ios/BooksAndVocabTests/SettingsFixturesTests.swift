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

        #expect(previewKeys == [
            "settings.logged_out",
            "settings.account_logged_out_error",
            "settings.preferences_auto_sync_off",
            "settings.preferences_logged_out_no_sync",
            "settings.subscribed_active",
            "settings.account_long_identity",
            "settings.subscription_free",
            "settings.subscription_loading",
            "settings.deleting_account",
            "settings.pricing_unavailable",
            "settings.debug_backend_local",
        ])

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
}
#endif

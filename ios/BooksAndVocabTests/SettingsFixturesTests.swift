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

    @Test func settingsFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = SettingsFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = SettingsFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "settings.logged_out",
            "settings.subscribed_active",
            "settings.subscription_free",
            "settings.subscription_loading",
            "settings.deleting_account",
            "settings.pricing_unavailable",
            "settings.debug_backend_local",
        ])

        #expect(catalogKeys == previewKeys)
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
}
#endif

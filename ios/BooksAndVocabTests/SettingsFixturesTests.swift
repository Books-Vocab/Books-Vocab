#if DEBUG
import Testing
@testable import BooksAndVocab

@Suite struct SettingsFixturesTests {
    @Test func settingsFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = SettingsFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = SettingsFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "settings.logged_out",
            "settings.subscribed_active",
            "settings.subscription_loading",
            "settings.deleting_account",
            "settings.pricing_unavailable",
            "settings.debug_backend_local",
        ])

        #expect(catalogKeys == previewKeys)
    }
}
#endif

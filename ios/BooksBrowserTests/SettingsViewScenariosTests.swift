import SwiftData
import Testing
@testable import BooksBrowser

@Suite("Settings View Scenarios")
struct SettingsViewScenariosTests {
    @Test("catalog container builds in memory without CloudKit crash")
    @MainActor
    func settingsCatalogContainerBuilds() throws {
        let container = try makeSettingsCatalogContainer(entryCount: 2)
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let entries = try container.mainContext.fetch(descriptor)
        #expect(entries.count == 2)
    }
}

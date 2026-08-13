#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    static func vocabularyFixtureID(for id: String) -> UIWorldVocabularyFixtureID? {
        UIWorldVocabularyFixtureID(rawValue: id)
    }

    @MainActor
    static func seedVocabulary(_ id: String, into container: ModelContainer) {
        guard let fixtureID = vocabularyFixtureID(for: id) else {
            failFixtureSeed("Unknown vocabulary fixture ID: \(id)")
        }

        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixtureID)
        do {
            let entries = try insertVocabularySeed(seed, into: container.mainContext)
            if !AuthManager.shared.isLoggedIn {
                seedSignedInLoginFromWorld()
            }
            AppLog.app.info(
                "UI-test fixture seeded: vocabulary.\(id) (\(entries.count) entries, \(seed.entryOverrides.count) overlays)"
            )
        } catch {
            failFixtureSeed("Failed to seed vocabulary.\(id) fixture: \(error)")
        }
    }
}
#endif

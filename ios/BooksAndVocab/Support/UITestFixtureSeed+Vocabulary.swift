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

        let seed: UIWorldVocabularySeed
        if fixtureID == .reviewCalendarDense {
            seed = FixtureDatasetStore.requireVocabularySeed(for: .reviewCalendarDense)
        } else {
            seed = FixtureDatasetStore.requireVocabularySeed(for: fixtureID)
        }
        let context = container.mainContext
        do {
            if fixtureID == .reviewCalendarDense {
                try clearReviewCalendarFixtures(from: context)
            }
            let entries = try insertVocabularySeed(seed, into: context)
            _ = try FixtureDatasetStore.materializeEvidenceFixture()
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
    @MainActor
    private static func clearReviewCalendarFixtures(from context: ModelContext) throws {
        for record in try context.fetch(FetchDescriptor<ReviewRecord>()) {
            context.delete(record)
        }
        for entry in try context.fetch(FetchDescriptor<VocabularyEntry>()) {
            context.delete(entry)
        }
        for notebook in try context.fetch(FetchDescriptor<Notebook>()) {
            context.delete(notebook)
        }
        try context.save()
    }
}
#endif

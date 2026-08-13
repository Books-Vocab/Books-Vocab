#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    static func vocabularyFixtureID(for id: String) -> UIWorldVocabularyFixtureID? {
        UIWorldVocabularyFixtureID(rawValue: id)
    }

    /// Review Calendar uses a whole-world reset so prior fixture rows cannot
    /// leak into the populated-day buckets under test.
    @MainActor
    static func clearReviewCalendarFixtures(from context: ModelContext) throws {
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

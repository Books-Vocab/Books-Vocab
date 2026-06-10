#if os(iOS)
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedBookshelf(_ id: String, into container: ModelContainer) {
        guard let fixtureID = BookshelfFixtureID(rawValue: id) else {
            AppLog.app.warning("Unknown bookshelf fixture ID: \(id)")
            return
        }
        let model = BookshelfFixtures.renderModel(for: fixtureID)
        let context = container.mainContext
        for source in model.books {
            // Re-create Book so it is not already associated with the fixture's
            // in-memory container.
            let book = Book(
                title: source.title,
                author: source.author,
                fileName: source.epubFileName,
                format: source.format
            )
            book.progression = source.progression
            book.dateAdded = source.dateAdded
            book.dateLastRead = source.dateLastRead
            context.insert(book)
        }
        do {
            try context.save()
            AppLog.app.info("UI-test fixture seeded: bookshelf.\(id) (\(model.books.count) books)")
        } catch {
            AppLog.app.error("Failed to seed bookshelf fixture: \(error)")
        }
    }
}
#endif

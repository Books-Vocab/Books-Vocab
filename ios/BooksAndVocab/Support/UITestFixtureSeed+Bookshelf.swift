#if os(iOS)
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedBookshelf(_ id: String, into container: ModelContainer) {
        guard let fixtureID = BookshelfFixtureID(rawValue: id) else {
            failFixtureSeed("Unknown bookshelf fixture ID: \(id)")
        }
        let seed = FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)
        let context = container.mainContext
        do {
            let document = FixtureDatasetStore.requireDocument()
            for source in seed.books {
                try source.validatePreferredNotebook(
                    in: document,
                    owner: "bookshelf.\(id).\(source.title)"
                )
                let fileName = try BookshelfFixtures.materializeBookFile(for: source)
                let book = Book(
                    title: source.title,
                    author: source.author,
                    fileName: fileName,
                    format: source.format
                )
                book.progression = source.progression
                book.preferredNotebookId = source.preferredNotebookId
                book.dateAdded = source.dateAdded
                book.dateLastRead = source.dateLastRead
                context.insert(book)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: bookshelf.\(id) (\(seed.books.count) books)")
        } catch {
            failFixtureSeed("Failed to seed bookshelf.\(id) fixture: \(error)")
        }
    }
}
#endif

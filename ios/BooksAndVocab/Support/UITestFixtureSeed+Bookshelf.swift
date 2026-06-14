#if os(iOS)
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedBookshelf(_ id: String, into container: ModelContainer) {
        guard let fixtureID = BookshelfFixtureID(rawValue: id) else {
            preconditionFailure("Unknown bookshelf fixture ID: \(id)")
        }
        let seed = FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)
        let context = container.mainContext
        do {
            for source in seed.books {
                let fileName = try materializeBookFile(for: source)
                let book = Book(
                    title: source.title,
                    author: source.author,
                    fileName: fileName,
                    format: source.format
                )
                book.progression = source.progression
                book.dateAdded = source.dateAdded
                book.dateLastRead = source.dateLastRead
                context.insert(book)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: bookshelf.\(id) (\(seed.books.count) books)")
        } catch {
            preconditionFailure("Failed to seed bookshelf fixture: \(error)")
        }
    }

    private static func materializeBookFile(for seed: BookshelfBookSeed) throws -> String {
        guard let ref = seed.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
              !ref.isEmpty else {
            preconditionFailure("UI World bookshelf book \(seed.title) is missing bookAssetRef")
        }
        let installedURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: ref)
        guard installedURL.deletingLastPathComponent().standardizedFileURL == Book.localBooksDirectory.standardizedFileURL else {
            preconditionFailure(
                "UI World bookshelf book \(seed.title) asset \(ref) must install directly under Books/: \(installedURL.path)"
            )
        }
        guard installedURL.lastPathComponent == seed.fileName else {
            preconditionFailure(
                "UI World bookshelf book \(seed.title) fileName \(seed.fileName) must match installed asset \(installedURL.lastPathComponent)"
            )
        }
        return installedURL.lastPathComponent
    }
}
#endif

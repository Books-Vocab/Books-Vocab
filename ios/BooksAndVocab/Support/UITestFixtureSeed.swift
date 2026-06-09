#if os(iOS)
import Foundation
import SwiftData

/// Bridges the existing fixture system into the live SwiftData container for UI tests.
/// Triggered by launch arguments when `-ui-testing` is active.
@MainActor
enum UITestFixtureSeed {
    /// Parse `-seedFixture:<domain>:<id>` arguments and inject matching fixtures.
    static func injectIfNeeded(into container: ModelContainer, arguments: [String]) {
        guard AppRuntimeOptions.isUITesting(arguments: arguments) else { return }

        for arg in arguments {
            guard arg.hasPrefix("-seedFixture:") else { continue }
            let remainder = arg.dropFirst("-seedFixture:".count)
            let parts = remainder.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2 else { continue }
            let domain = parts[0]
            let id = parts[1]

            switch domain {
            case "bookshelf":
                seedBookshelf(id, into: container)
            default:
                AppLog.app.warning("Unknown UI-test fixture domain: \(domain)")
            }
        }
    }

    // MARK: - Bookshelf

    @MainActor
    private static func seedBookshelf(_ id: String, into container: ModelContainer) {
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

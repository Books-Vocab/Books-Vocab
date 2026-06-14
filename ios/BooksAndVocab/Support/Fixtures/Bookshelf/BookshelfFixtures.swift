#if os(iOS)
import Foundation
import SwiftData

enum BookshelfFixtureID: String, CaseIterable {
    case progressCard = "progress_card"
    case placeholderCard = "placeholder_card"
    case emptyLibrary = "empty_library"
    case withBooksLibrary = "with_books_library"
    case loadingOverlay = "loading_overlay"

    var key: FixtureKey {
        FixtureKey("bookshelf.\(rawValue)")
    }
}

struct BookshelfBookSeed: Codable {
    let title: String
    let author: String
    let fileName: String
    let format: BookFormat
    let progression: Double?
    let dateAdded: Date
    let dateLastRead: Date?
}

struct BookshelfFixtureSeed: Codable {
    let books: [BookshelfBookSeed]
    let referenceDate: Date
}

struct BookshelfFixtureRenderModel {
    let books: [Book]
    let container: ModelContainer?
    let referenceDate: Date
}

enum BookshelfFixtures {
    private static let snapshotDate = Date(timeIntervalSince1970: 1_769_385_600) // 2026-01-07 00:00:00 UTC
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<BookshelfFixtureSeed>([
        FixtureRecipe(key: BookshelfFixtureID.progressCard.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                books: [
                    .init(
                        title: "Word Architect",
                        author: "Lena Harper",
                        fileName: "word-architect.epub",
                        format: .epub,
                        progression: 0.64,
                        dateAdded: Date(timeIntervalSince1970: 1_768_521_600),
                        dateLastRead: Date(timeIntervalSince1970: 1_769_126_400)
                    )
                ],
                referenceDate: snapshotDate
            )
        },
        FixtureRecipe(key: BookshelfFixtureID.placeholderCard.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
                books: [
                    .init(
                        title: "Notes on Deliberate Practice",
                        author: "M. Rivera",
                        fileName: "notes-on-deliberate-practice.epub",
                        format: .epub,
                        progression: 0.18,
                        dateAdded: Date(timeIntervalSince1970: 1_768_435_200),
                        dateLastRead: Date(timeIntervalSince1970: 1_769_367_600)
                    )
                ],
                referenceDate: snapshotDate
            )
        },
        FixtureRecipe(key: BookshelfFixtureID.emptyLibrary.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(books: [], referenceDate: snapshotDate)
        },
        FixtureRecipe(key: BookshelfFixtureID.withBooksLibrary.key, surfaces: sharedSurfaces, tags: ["baseline", "marketing"]) {
            .init(
                books: [
                    .init(
                        title: "Word Architect",
                        author: "Lena Harper",
                        fileName: "word-architect.epub",
                        format: .epub,
                        progression: 0.64,
                        dateAdded: Date(timeIntervalSince1970: 1_768_521_600),
                        dateLastRead: Date(timeIntervalSince1970: 1_769_126_400)
                    ),
                    .init(
                        title: "Notes on Deliberate Practice",
                        author: "M. Rivera",
                        fileName: "notes-on-deliberate-practice.epub",
                        format: .epub,
                        progression: 0.18,
                        dateAdded: Date(timeIntervalSince1970: 1_768_435_200),
                        dateLastRead: Date(timeIntervalSince1970: 1_769_367_600)
                    ),
                ],
                referenceDate: snapshotDate
            )
        },
        FixtureRecipe(key: BookshelfFixtureID.loadingOverlay.key, surfaces: sharedSurfaces, tags: ["loading"]) {
            .init(books: [], referenceDate: snapshotDate)
        },
    ])

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<BookshelfFixtureSeed>] {
        registry.recipes(for: surface)
    }

    @MainActor
    static func renderModel(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureRenderModel {
        let seed = FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)
        return .init(
            books: seed.books.map(makeBook(from:)),
            container: makeContainer(from: seed.books),
            referenceDate: seed.referenceDate
        )
    }

    @MainActor
    private static func makeContainer(from seeds: [BookshelfBookSeed]) -> ModelContainer? {
        let schema = Schema([Book.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        do {
            let container = try ModelContainer(for: schema, configurations: config)
            let context = ModelContext(container)
            for book in seeds.map(makeBook(from:)) {
                context.insert(book)
            }
            try? context.save()
            return container
        } catch {
            AppLog.app.warning("BookshelfFixtures container failed: \(error.localizedDescription)")
            return nil
        }
    }

    private static func makeBook(from seed: BookshelfBookSeed) -> Book {
        let book = Book(
            title: seed.title,
            author: seed.author,
            fileName: seed.fileName,
            format: seed.format
        )
        book.progression = seed.progression
        book.dateAdded = seed.dateAdded
        book.dateLastRead = seed.dateLastRead
        return book
    }
}
#endif

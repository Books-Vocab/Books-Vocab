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
    let bookAssetRef: String?
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
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<BookshelfFixtureSeed>(
        BookshelfFixtureID.allCases.map { fixtureID in
            FixtureRecipe(key: fixtureID.key, surfaces: sharedSurfaces, tags: tags(for: fixtureID)) {
                FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)
            }
        }
    )

    private static func tags(for fixtureID: BookshelfFixtureID) -> Set<String> {
        switch fixtureID {
        case .withBooksLibrary:
            return ["baseline", "marketing"]
        case .loadingOverlay:
            return ["loading"]
        case .progressCard, .placeholderCard, .emptyLibrary:
            return ["baseline"]
        }
    }

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

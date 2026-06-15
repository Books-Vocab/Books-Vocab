#if os(iOS)
import Foundation
import SwiftData

enum BookshelfFixtureID: String, CaseIterable {
    case bookCardComplete = "book_card_complete"
    case bookCardLongTitle = "book_card_long_title"
    case bookCardMidProgress = "book_card_mid_progress"
    case bookCardPdfFormat = "book_card_pdf_format"
    case bookCardPlaceholderEpub = "book_card_placeholder_epub"
    case progressCard = "progress_card"
    case placeholderCard = "placeholder_card"
    case readerNotebookBound = "reader_notebook_bound"
    case readerNotebookEmpty = "reader_notebook_empty"
    case readerNotebookLongBound = "reader_notebook_long_bound"
    case readerNotebookUnbound = "reader_notebook_unbound"
    case emptyLibrary = "empty_library"
    case withBooksLibrary = "with_books_library"
    case loadingOverlay = "loading_overlay"

    var key: FixtureKey {
        FixtureKey("bookshelf.\(rawValue)")
    }
}

enum BookshelfFixtureMaterializationError: Error, Equatable {
    case preferredNotebookMissing(owner: String, notebookId: String)
}

struct BookshelfBookSeed: Codable {
    let title: String
    let author: String
    let fileName: String
    let format: BookFormat
    let bookAssetRef: String?
    let progression: Double?
    let preferredNotebookId: String?
    let dateAdded: Date
    let dateLastRead: Date?

    enum CodingKeys: String, CodingKey, CaseIterable {
        case title
        case author
        case fileName
        case format
        case bookAssetRef
        case progression
        case preferredNotebookId
        case dateAdded
        case dateLastRead
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        for key in CodingKeys.allCases where !container.contains(key) {
            throw DecodingError.keyNotFound(
                key,
                DecodingError.Context(
                    codingPath: container.codingPath,
                    debugDescription: "UI World bookshelf book must explicitly declare \(key.rawValue), even when null"
                )
            )
        }
        title = try container.decode(String.self, forKey: .title)
        author = try container.decode(String.self, forKey: .author)
        fileName = try container.decode(String.self, forKey: .fileName)
        format = try container.decode(BookFormat.self, forKey: .format)
        bookAssetRef = try container.decodeIfPresent(String.self, forKey: .bookAssetRef)
        progression = try container.decodeIfPresent(Double.self, forKey: .progression)
        preferredNotebookId = try container.decodeIfPresent(String.self, forKey: .preferredNotebookId)
        dateAdded = try container.decode(Date.self, forKey: .dateAdded)
        dateLastRead = try container.decodeIfPresent(Date.self, forKey: .dateLastRead)
    }

    func validatePreferredNotebook(in document: FixtureDatasetDocument, owner: String) throws {
        guard let preferredNotebookId,
              !preferredNotebookId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        let notebookIDs = Set(document.notebook.values.flatMap { seed in
            seed.notebooks.map(\.remoteId)
        })
        guard notebookIDs.contains(preferredNotebookId) else {
            throw BookshelfFixtureMaterializationError.preferredNotebookMissing(
                owner: owner,
                notebookId: preferredNotebookId
            )
        }
    }
}

struct BookshelfFixtureSeed: Codable {
    let books: [BookshelfBookSeed]
    let referenceDate: Date
}

struct BookshelfFixtureRenderModel {
    let books: [Book]
    let container: ModelContainer
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
        case .bookCardComplete, .bookCardLongTitle, .bookCardMidProgress, .bookCardPdfFormat, .bookCardPlaceholderEpub, .progressCard, .placeholderCard, .readerNotebookBound, .readerNotebookEmpty, .readerNotebookLongBound, .readerNotebookUnbound, .emptyLibrary:
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
            books: books(for: fixtureID),
            container: makeContainer(for: fixtureID, from: seed.books),
            referenceDate: seed.referenceDate
        )
    }

    @MainActor
    static func books(for fixtureID: BookshelfFixtureID) -> [Book] {
        do {
            return try materializeBooks(for: fixtureID)
        } catch {
            preconditionFailure("Failed to materialize UI World bookshelf.\(fixtureID.rawValue): \(error)")
        }
    }

    @MainActor
    static func materializeBooks(for fixtureID: BookshelfFixtureID) throws -> [Book] {
        let document = FixtureDatasetStore.requireDocument()
        let seed = FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)
        return try seed.books.map { seed in
            try makeBook(from: seed, document: document, owner: "bookshelf.\(fixtureID.rawValue).\(seed.title)")
        }
    }

    @MainActor
    private static func makeContainer(for fixtureID: BookshelfFixtureID, from seeds: [BookshelfBookSeed]) -> ModelContainer {
        let schema = Schema([Book.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        do {
            let container = try ModelContainer(for: schema, configurations: config)
            let context = ModelContext(container)
            let document = FixtureDatasetStore.requireDocument()
            for seed in seeds {
                let book = try makeBook(
                    from: seed,
                    document: document,
                    owner: "bookshelf.\(fixtureID.rawValue).\(seed.title)"
                )
                context.insert(book)
            }
            try context.save()
            return container
        } catch {
            preconditionFailure("Failed to materialize UI World bookshelf seed: \(error)")
        }
    }

    private static func makeBook(
        from seed: BookshelfBookSeed,
        document: FixtureDatasetDocument,
        owner: String
    ) throws -> Book {
        try seed.validatePreferredNotebook(in: document, owner: owner)
        let book = Book(
            title: seed.title,
            author: seed.author,
            fileName: seed.fileName,
            format: seed.format
        )
        book.progression = seed.progression
        book.preferredNotebookId = seed.preferredNotebookId
        book.dateAdded = seed.dateAdded
        book.dateLastRead = seed.dateLastRead
        return book
    }
}
#endif

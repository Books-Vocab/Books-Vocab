import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

@MainActor
struct BookLibraryReconcilerTests {
    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            Book.self,
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    private func makeTempRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookLibraryReconcilerTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    @Test func reconcilerRebuildsMissingRowFromManifestAndFile() throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let bookId = UUID()
        let fileName = "manifest-backed.epub"
        try Data("epub".utf8).write(to: root.appendingPathComponent(fileName))
        try BookManifestStore(rootDirectory: root).write(BookManifest(
            bookId: bookId,
            fileName: fileName,
            originalFileName: "Original.epub",
            title: "Manifest Backed",
            author: "Author",
            format: .epub,
            coverImageData: Data([9]),
            dateAdded: Date(timeIntervalSince1970: 1_700_000_000),
            dateLastRead: Date(timeIntervalSince1970: 1_700_000_100),
            progression: 0.5,
            lastReadLocatorJSON: #"{"href":"x"}"#,
            preferredNotebookId: "nb"
        ))

        let result = try BookLibraryReconciler(rootDirectory: root).reconcile(context: context)

        let book = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(result.recoveredRows == 1)
        #expect(book.id == bookId)
        #expect(book.title == "Manifest Backed")
        #expect(book.author == "Author")
        #expect(book.coverImageData == Data([9]))
        #expect(book.epubFileName == fileName)
        #expect(book.format == .epub)
        #expect(book.dateLastRead == Date(timeIntervalSince1970: 1_700_000_100))
        #expect(book.progression == 0.5)
        #expect(book.lastReadLocatorJSON == #"{"href":"x"}"#)
        #expect(book.preferredNotebookId == "nb")
    }

    @Test func reconcilerWritesMissingManifestForExistingRow() throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let book = Book(title: "Row Only", author: "", fileName: "row-only.pdf", format: .pdf)
        context.insert(book)
        try context.save()
        try Data("pdf".utf8).write(to: root.appendingPathComponent(book.epubFileName))

        let result = try BookLibraryReconciler(rootDirectory: root).reconcile(context: context)

        let manifest = try BookManifestStore(rootDirectory: root).read(bookId: book.id)
        #expect(result.writtenManifests == 1)
        #expect(manifest.bookId == book.id)
        #expect(manifest.fileName == "row-only.pdf")
        #expect(manifest.title == "Row Only")
        #expect(manifest.format == .pdf)
    }

    @Test func reconcilerDoesNotCreateBareRowsDuringNormalCloudStartup() throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        try Data("epub".utf8).write(to: root.appendingPathComponent("D8D20CE3-F60E-45E0-9410-12D0A5DCCD78.epub"))

        let result = try BookLibraryReconciler(rootDirectory: root).reconcile(context: context)

        let books = try context.fetch(FetchDescriptor<Book>())
        #expect(result.recoveredRows == 0)
        #expect(books.isEmpty)
    }

    @Test func reconcilerRemovesDuplicateRowsForSameFileNameKeepingMetadataRichRow() throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "7DB3287F-F3E0-4C76-BE97-AC150B8DD4BD.epub"
        try Data("epub".utf8).write(to: root.appendingPathComponent(fileName))

        let cloudBacked = Book(
            title: "Real Book Title",
            author: "Author",
            coverImageData: Data([1, 2, 3]),
            fileName: fileName,
            format: .epub
        )
        cloudBacked.progression = 0.4
        let recoveredBare = Book(
            title: "7DB3287F-F3E0-4C76-BE97-AC150B8DD4BD",
            author: "",
            fileName: fileName,
            format: .epub
        )
        context.insert(cloudBacked)
        context.insert(recoveredBare)
        try context.save()

        let result = try BookLibraryReconciler(rootDirectory: root).reconcile(context: context)

        let books = try context.fetch(FetchDescriptor<Book>())
        let book = try #require(books.first)
        #expect(result.duplicateRowsRemoved == 1)
        #expect(books.count == 1)
        #expect(book.id == cloudBacked.id)
        #expect(book.title == "Real Book Title")
        #expect(book.progression == 0.4)
    }

    @Test func reconcilerToleratesDuplicateManifestsForSameFileName() throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "shared.epub"
        try Data("epub".utf8).write(to: root.appendingPathComponent(fileName))
        let store = BookManifestStore(rootDirectory: root)
        try store.write(BookManifest(
            bookId: UUID(),
            fileName: fileName,
            originalFileName: nil,
            title: "shared",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))
        try store.write(BookManifest(
            bookId: UUID(),
            fileName: fileName,
            originalFileName: nil,
            title: "Metadata Rich",
            author: "Author",
            format: .epub,
            coverImageData: Data([1]),
            dateAdded: Date(timeIntervalSince1970: 2),
            dateLastRead: Date(timeIntervalSince1970: 3),
            progression: 0.2,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))

        let result = try BookLibraryReconciler(rootDirectory: root).reconcile(context: context)

        let books = try context.fetch(FetchDescriptor<Book>())
        let book = try #require(books.first)
        #expect(result.recoveredRows == 1)
        #expect(books.count == 1)
        #expect(book.title == "Metadata Rich")
        #expect(book.author == "Author")
        #expect(book.progression == 0.2)
    }
}

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
}

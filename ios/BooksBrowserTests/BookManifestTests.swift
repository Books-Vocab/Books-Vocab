import Foundation
import Testing
@testable import BooksBrowser

@MainActor
struct BookManifestTests {
    @Test func manifestRoundTripsBookMetadata() throws {
        let book = Book(
            title: "Manifest Book",
            author: "A. Writer",
            coverImageData: Data([1, 2, 3]),
            fileName: "book.epub",
            format: .epub
        )
        book.lastReadLocatorJSON = #"{"href":"chapter.xhtml"}"#
        book.dateLastRead = Date(timeIntervalSince1970: 1_700_000_001)
        book.progression = 0.42
        book.preferredNotebookId = "notebook-1"

        let manifest = BookManifest(book: book, originalFileName: "Original.epub")

        #expect(manifest.bookId == book.id)
        #expect(manifest.fileName == "book.epub")
        #expect(manifest.originalFileName == "Original.epub")
        #expect(manifest.title == "Manifest Book")
        #expect(manifest.author == "A. Writer")
        #expect(manifest.format == .epub)
        #expect(manifest.lastReadLocatorJSON == #"{"href":"chapter.xhtml"}"#)
        #expect(manifest.dateLastRead == Date(timeIntervalSince1970: 1_700_000_001))
        #expect(manifest.progression == 0.42)
        #expect(manifest.preferredNotebookId == "notebook-1")
    }

    @Test func storeWritesAndReadsManifestAtomically() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let store = BookManifestStore(rootDirectory: root)
        let manifest = BookManifest(
            bookId: UUID(),
            fileName: "atomic.pdf",
            originalFileName: "Original.pdf",
            title: "Atomic PDF",
            author: "",
            format: .pdf,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1_700_000_000),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        )

        try store.write(manifest)

        #expect(try store.read(bookId: manifest.bookId) == manifest)
        #expect(FileManager.default.fileExists(atPath: store.url(for: manifest.bookId).path))
    }

    @Test func storeWritesCurrentBookSnapshot() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let book = Book(title: "Updated", author: "Author", fileName: "updated.epub")
        book.progression = 0.8
        book.preferredNotebookId = "nb-2"

        let store = BookManifestStore(rootDirectory: root)
        try store.write(book: book, originalFileName: "source.epub")

        let manifest = try store.read(bookId: book.id)
        #expect(manifest.title == "Updated")
        #expect(manifest.fileName == "updated.epub")
        #expect(manifest.originalFileName == "source.epub")
        #expect(manifest.progression == 0.8)
        #expect(manifest.preferredNotebookId == "nb-2")
    }
}

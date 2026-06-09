import Foundation
import Testing
@testable import BooksAndVocab

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

    // MARK: - merge-on-write 防固化

    @Test func progressWriteDoesNotOverwriteCleanManifestWithFallbackRow() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "F9634750-1CEE-4E8E-A7A7-13594801B886.epub"
        let store = BookManifestStore(rootDirectory: root)

        // 既有乾淨 manifest（已含真 title/author/cover）
        let bookId = UUID()
        try store.write(BookManifest(
            bookId: bookId,
            fileName: fileName,
            originalFileName: "Real Book.epub",
            title: "Real Book",
            author: "Real Author",
            format: .epub,
            coverImageData: Data([1, 2, 3]),
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))

        // reader progress save：row 仍是 fallback（UUID title、空 author、nil cover）但有進度
        let fallbackRow = Book(
            title: "F9634750-1CEE-4E8E-A7A7-13594801B886",
            author: "",
            fileName: fileName,
            format: .epub
        )
        fallbackRow.id = bookId
        fallbackRow.progression = 0.5
        fallbackRow.lastReadLocatorJSON = #"{"href":"x"}"#
        fallbackRow.dateLastRead = Date(timeIntervalSince1970: 100)

        try store.write(book: fallbackRow)

        let merged = try store.read(bookId: bookId)
        // 識別性欄位保留乾淨值
        #expect(merged.title == "Real Book")
        #expect(merged.author == "Real Author")
        #expect(merged.coverImageData == Data([1, 2, 3]))
        #expect(merged.originalFileName == "Real Book.epub")
        // 閱讀位置採 row 當前值
        #expect(merged.progression == 0.5)
        #expect(merged.lastReadLocatorJSON == #"{"href":"x"}"#)
        #expect(merged.dateLastRead == Date(timeIntervalSince1970: 100))
    }

    @Test func cleanRowWriteUpgradesFallbackManifest() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "ABCDEF01-2345-6789-ABCD-EF0123456789.epub"
        let store = BookManifestStore(rootDirectory: root)

        // 既有 fallback manifest
        let bookId = UUID()
        try store.write(BookManifest(
            bookId: bookId,
            fileName: fileName,
            originalFileName: nil,
            title: "ABCDEF01-2345-6789-ABCD-EF0123456789",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))

        // 乾淨 row（repair 後）寫回 → 升級 manifest
        let cleanRow = Book(
            title: "Real Title",
            author: "Real Author",
            coverImageData: Data([9]),
            fileName: fileName,
            format: .epub
        )
        cleanRow.id = bookId

        try store.write(book: cleanRow)

        let merged = try store.read(bookId: bookId)
        #expect(merged.title == "Real Title")
        #expect(merged.author == "Real Author")
        #expect(merged.coverImageData == Data([9]))
    }

    @Test func mergeKeepsIncomingWhenNoExistingManifest() throws {
        let incoming = BookManifest(
            bookId: UUID(),
            fileName: "x.epub",
            originalFileName: nil,
            title: "x",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: 0.1,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        )
        #expect(BookManifestStore.merged(incoming: incoming, existing: nil) == incoming)
    }

    // MARK: - 跨版本 / 損壞容錯

    @Test func writeDoesNotOverwriteNewerSchemaVersionManifest() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let store = BookManifestStore(rootDirectory: root)
        let bookId = UUID()
        let fileName = "future.epub"
        // 既有 manifest 來自「未來版本」的 app
        try store.write(BookManifest(
            schemaVersion: BookManifest.currentSchemaVersion + 1,
            bookId: bookId,
            fileName: fileName,
            originalFileName: "Future.epub",
            title: "Future Title",
            author: "Future Author",
            format: .epub,
            coverImageData: Data([1]),
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))

        let book = Book(title: "Older App Title", author: "X", fileName: fileName, format: .epub)
        book.id = bookId

        // 直接 write(book:) 應拋（拒絕用舊 schema 覆蓋更新的檔）
        #expect(throws: BookManifestStoreError.self) {
            try store.write(book: book)
        }
        // writeBestEffort 吞錯但不覆蓋
        store.writeBestEffort(book: book)

        let onDisk = try store.read(bookId: bookId)
        #expect(onDisk.schemaVersion == BookManifest.currentSchemaVersion + 1)
        #expect(onDisk.title == "Future Title")
    }

    @Test func readAllSkipsCorruptManifestFiles() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookManifestTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }

        let store = BookManifestStore(rootDirectory: root)
        try store.write(BookManifest(
            bookId: UUID(),
            fileName: "good.epub",
            originalFileName: nil,
            title: "Good",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: nil,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))
        // 寫一個損壞的 .json
        try Data("{ not valid json".utf8).write(to: store.metadataDirectory.appendingPathComponent("\(UUID().uuidString).json"))

        let all = store.readAll()
        #expect(all.count == 1)
        #expect(all.first?.title == "Good")
    }
}

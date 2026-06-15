#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Reader-flow fixture (`-seedFixture:reader:realBookLibrary`).
    ///
    /// Seeds a REAL book from the UI World asset manifest. The complete EPUB is
    /// installed through `bookAssetRef`, while `textAssetRef` remains a
    /// provenance/check fixture for the chapter text. A real vocabulary entry
    /// ("introduction" → 「引言；導論」) is seeded into the book's bound notebook so
    /// tapping that word in the reader exercises the library-hit translation
    /// path with real content and zero network.
    ///
    /// Ownership: this fixture resets the bookshelf + its own notebook scope
    /// (the reader flow asserts on exactly one seeded book); other domains'
    /// fixtures are untouched.
    @MainActor
    static func seedReader(_ id: String, into container: ModelContainer) {
        // 模擬器限定：reader fixture 會把 manifest EPUB 寫進「真實」Books
        // 目錄（容器 guard 罩不到的磁碟平面）。真機上殘留檔案會在下次正常
        // 啟動被 orphan recovery 收編進使用者真實書庫——一律拒絕。
        #if targetEnvironment(simulator)
        switch id {
        case "realBookLibrary":
            seedReaderRealBookLibrary(into: container)
        default:
            failFixtureSeed("Unknown reader fixture ID: \(id)")
        }
        #else
        failFixtureSeed("UITestFixtureSeed: refused reader fixture on device — it writes the real Books directory")
        #endif
    }

    @MainActor
    private static func seedReaderRealBookLibrary(into container: ModelContainer) {
        let context = container.mainContext
        do {
            let seed = FixtureDatasetStore.requireReaderSeed(for: .realBookLibrary)
            try clearReaderFixtureWorld(from: context, seed: seed)
            let fixture = try resolveReaderFixture(from: seed)

            let notebook = Notebook(remoteId: fixture.seed.notebookRemoteId, name: fixture.seed.notebookName)
            notebook.syncStatus = fixture.seed.notebookSyncStatus
            context.insert(notebook)

            let entry = makeVocabularyEntry(
                from: fixture.seed.entry,
                notebookId: fixture.seed.notebookRemoteId
            )
            context.insert(entry)

            let book = Book(
                title: fixture.title,
                author: fixture.author,
                fileName: fixture.bookURL.lastPathComponent,
                format: .epub
            )
            book.preferredNotebookId = fixture.seed.notebookRemoteId
            context.insert(book)

            try context.save()
            AppLog.app.info("UI-test fixture seeded: reader.realBookLibrary (book=\(fixture.title), epub=\(fixture.bookURL.lastPathComponent))")
        } catch {
            failFixtureSeed("Failed to seed reader.realBookLibrary fixture: \(error)")
        }
    }

    /// Idempotent re-seed: the simulator container persists across runs.
    /// Resets the world this flow asserts on — all books (exactly one seeded
    /// book must be on the shelf), this flow's notebook + entries, and the
    /// generated fixture EPUB file.
    @MainActor
    private static func clearReaderFixtureWorld(from context: ModelContext, seed: UIWorldReaderSeed) throws {
        for book in try context.fetch(FetchDescriptor<Book>()) {
            context.delete(book)
        }
        let notebookId = seed.notebookRemoteId
        for notebook in try context.fetch(
            FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
        ) {
            context.delete(notebook)
        }
        for entry in try context.fetch(
            FetchDescriptor<VocabularyEntry>(predicate: #Predicate { $0.notebookId == notebookId })
        ) {
            context.delete(entry)
        }
        try context.save()

        let staleEPUB = Book.localBooksDirectory.appendingPathComponent(seed.bookFileName)
        if FileManager.default.fileExists(atPath: staleEPUB.path) {
            try FileManager.default.removeItem(at: staleEPUB)
        }
    }

    private struct ReaderFixture {
        let seed: UIWorldReaderSeed
        let bookURL: URL
        let title: String
        let author: String
    }

    private static func resolveReaderFixture(from seed: UIWorldReaderSeed) throws -> ReaderFixture {
        _ = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.textAssetRef)
        let bookURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.bookAssetRef)
        guard bookURL.deletingLastPathComponent().standardizedFileURL == Book.localBooksDirectory.standardizedFileURL else {
            preconditionFailure("UI World reader.realBookLibrary book asset \(seed.bookAssetRef) must install directly under Books/: \(bookURL.path)")
        }
        guard bookURL.lastPathComponent == seed.bookFileName else {
            preconditionFailure("UI World reader.realBookLibrary bookFileName \(seed.bookFileName) must match installed asset \(bookURL.lastPathComponent)")
        }
        return ReaderFixture(
            seed: seed,
            bookURL: bookURL,
            title: seed.title,
            author: seed.author
        )
    }
}
#endif

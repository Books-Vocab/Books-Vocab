#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Reader-flow fixture (`-seedFixture:reader:realBookLibrary`).
    ///
    /// Seeds a REAL book: a lab-extracted chapter of a real book (Atomic
    /// Habits Introduction, the same fixture mountain the podcast probes use)
    /// is converted through the app's own `EPUBConverter` — the exact import
    /// path a user's TXT goes through — and placed in the local Books
    /// directory. A real vocabulary entry ("introduction" → 「引言；導論」) is
    /// seeded into the book's bound notebook so tapping that word in the
    /// reader exercises the library-hit translation path with real content
    /// and zero network.
    ///
    /// Ownership: this fixture resets the bookshelf + its own notebook scope
    /// (the reader flow asserts on exactly one seeded book); other domains'
    /// fixtures are untouched.
    @MainActor
    static func seedReader(_ id: String, into container: ModelContainer) {
        // 模擬器限定：convertRealTextToEPUB 會把 fixture EPUB 寫進「真實」
        // Books 目錄（容器 guard 罩不到的磁碟平面）。真機上殘留檔案會在下次
        // 正常啟動被 orphan recovery 收編進使用者真實書庫——一律拒絕。
        #if targetEnvironment(simulator)
        switch id {
        case "realBookLibrary":
            seedReaderRealBookLibrary(into: container)
        default:
            AppLog.app.warning("Unknown reader fixture ID: \(id)")
        }
        #else
        AppLog.app.error("UITestFixtureSeed: refused reader fixture on device — it writes the real Books directory")
        #endif
    }

    @MainActor
    private static func seedReaderRealBookLibrary(into container: ModelContainer) {
        let context = container.mainContext
        do {
            let fixture = try resolveReaderTextFixture()
            try clearReaderFixtureWorld(from: context, seed: fixture.seed)
            let epubURL = try convertRealTextToEPUB(fixture)

            let notebook = Notebook(remoteId: fixture.seed.notebookRemoteId, name: fixture.seed.notebookName)
            notebook.syncStatus = 1
            context.insert(notebook)

            let entry = makeVocabularyEntry(
                from: fixture.seed.entry,
                notebookId: fixture.seed.notebookRemoteId,
                defaultBookTitle: fixture.title
            )
            context.insert(entry)

            let book = Book(
                title: fixture.title,
                author: fixture.author,
                fileName: epubURL.lastPathComponent,
                format: .txt
            )
            book.preferredNotebookId = fixture.seed.notebookRemoteId
            context.insert(book)

            try context.save()
            AppLog.app.info("UI-test fixture seeded: reader.realBookLibrary (book=\(fixture.title), epub=\(epubURL.lastPathComponent))")
        } catch {
            AppLog.app.error("Failed to seed reader fixture: \(error)")
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

    private struct ReaderTextFixture {
        let seed: UIWorldReaderSeed
        let sourceURL: URL
        let title: String
        let author: String
    }

    private static func resolveReaderTextFixture() throws -> ReaderTextFixture {
        let seed = FixtureDatasetStore.requireReaderSeed(for: .realBookLibrary)
        let sourceURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.textAssetRef)
        return ReaderTextFixture(
            seed: seed,
            sourceURL: sourceURL,
            title: seed.title,
            author: seed.author
        )
    }

    /// Convert the real chapter text through the production TXT→EPUB path
    /// (one `<p>` per line, so the chapter-opening "Introduction" line is a
    /// deterministic single-word tap target) and install it at a fixed name
    /// in the local Books directory.
    ///
    /// Pipeline annotation lines ("<!-- source: … -->") are extraction
    /// artifacts, not book content — they are dropped; the prose itself is
    /// untouched.
    private static func convertRealTextToEPUB(_ fixture: ReaderTextFixture) throws -> URL {
        let raw = try String(contentsOf: fixture.sourceURL, encoding: .utf8)
        let cleaned = raw
            .components(separatedBy: "\n")
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("<!--") }
            .joined(separator: "\n")

        let fm = FileManager.default
        let tmpSource = fm.temporaryDirectory.appendingPathComponent("kg-uitest-reader-source.txt")
        try cleaned.write(to: tmpSource, atomically: true, encoding: .utf8)

        let converted = try EPUBConverter().convertTXT(at: tmpSource, title: fixture.title)
        let destination = Book.localBooksDirectory.appendingPathComponent(fixture.seed.bookFileName)
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try fm.moveItem(at: converted, to: destination)
        return destination
    }
}
#endif

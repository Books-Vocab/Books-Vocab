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

    private static let readerNotebookId = "ui-reader-notebook"
    private static let readerBookFileName = "kg-uitest-reader-book.epub"
    /// Must stay in sync with ReaderFlowUITests.seededWord/seededTranslation.
    private static let readerSeededWord = "introduction"
    private static let readerSeededTranslation = "引言；導論"

    @MainActor
    private static func seedReaderRealBookLibrary(into container: ModelContainer) {
        let context = container.mainContext
        do {
            try clearReaderFixtureWorld(from: context)

            let fixture = try resolveReaderTextFixture()
            let epubURL = try convertRealTextToEPUB(fixture)

            let notebook = Notebook(remoteId: readerNotebookId, name: "Reader Flow Vocab")
            notebook.syncStatus = 1
            context.insert(notebook)

            // Real library entry in the bound-notebook scope: the reader's
            // handleWordSelected library-hit branch renders this translation
            // without touching the network.
            let entry = VocabularyEntry(
                word: readerSeededWord,
                translation: readerSeededTranslation,
                context: "Introduction — My Story",
                bookTitle: fixture.title
            )
            entry.notebookId = readerNotebookId
            entry.syncStatus = 1
            context.insert(entry)

            let book = Book(
                title: fixture.title,
                author: fixture.author,
                fileName: epubURL.lastPathComponent,
                format: .txt
            )
            book.preferredNotebookId = readerNotebookId
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
    private static func clearReaderFixtureWorld(from context: ModelContext) throws {
        for book in try context.fetch(FetchDescriptor<Book>()) {
            context.delete(book)
        }
        let notebookId = readerNotebookId
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

        let staleEPUB = Book.localBooksDirectory.appendingPathComponent(readerBookFileName)
        if FileManager.default.fileExists(atPath: staleEPUB.path) {
            try FileManager.default.removeItem(at: staleEPUB)
        }
    }

    private struct ReaderTextFixture {
        let sourceURL: URL
        let title: String
        let author: String
    }

    private static func resolveReaderTextFixture() throws -> ReaderTextFixture {
        let env = ProcessInfo.processInfo.environment
        let textPath = env["KG_UI_TEST_READER_TEXT"]
            ?? "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/raw_chapters/raw_ch_04.md"
        let sourceURL = URL(fileURLWithPath: textPath)
        guard FileManager.default.fileExists(atPath: sourceURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: sourceURL.path])
        }
        return ReaderTextFixture(
            sourceURL: sourceURL,
            title: env["KG_UI_TEST_READER_TITLE"] ?? "Atomic Habits — Introduction",
            author: env["KG_UI_TEST_READER_AUTHOR"] ?? "James Clear"
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
        let destination = Book.localBooksDirectory.appendingPathComponent(readerBookFileName)
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try fm.moveItem(at: converted, to: destination)
        return destination
    }
}
#endif

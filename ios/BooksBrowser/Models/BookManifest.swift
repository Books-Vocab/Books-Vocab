import Foundation

struct BookManifest: Codable, Equatable {
    static let currentSchemaVersion = 1

    var schemaVersion: Int
    var bookId: UUID
    var fileName: String
    var originalFileName: String?
    var title: String
    var author: String
    var format: BookFormat
    var coverImageData: Data?
    var dateAdded: Date
    var dateLastRead: Date?
    var progression: Double?
    var lastReadLocatorJSON: String?
    var preferredNotebookId: String?

    init(
        schemaVersion: Int = Self.currentSchemaVersion,
        bookId: UUID,
        fileName: String,
        originalFileName: String?,
        title: String,
        author: String,
        format: BookFormat,
        coverImageData: Data?,
        dateAdded: Date,
        dateLastRead: Date?,
        progression: Double?,
        lastReadLocatorJSON: String?,
        preferredNotebookId: String?
    ) {
        self.schemaVersion = schemaVersion
        self.bookId = bookId
        self.fileName = fileName
        self.originalFileName = originalFileName
        self.title = title
        self.author = author
        self.format = format
        self.coverImageData = coverImageData
        self.dateAdded = dateAdded
        self.dateLastRead = dateLastRead
        self.progression = progression
        self.lastReadLocatorJSON = lastReadLocatorJSON
        self.preferredNotebookId = preferredNotebookId
    }

    init(book: Book, originalFileName: String? = nil) {
        self.init(
            bookId: book.id,
            fileName: book.epubFileName,
            originalFileName: originalFileName,
            title: book.title,
            author: book.author,
            format: book.format,
            coverImageData: book.coverImageData,
            dateAdded: book.dateAdded,
            dateLastRead: book.dateLastRead,
            progression: book.progression,
            lastReadLocatorJSON: book.lastReadLocatorJSON,
            preferredNotebookId: book.preferredNotebookId
        )
    }
}

struct BookManifestStore {
    let rootDirectory: URL

    var metadataDirectory: URL {
        rootDirectory.appendingPathComponent(".metadata", isDirectory: true)
    }

    init(rootDirectory: URL = Book.booksDirectory) {
        self.rootDirectory = rootDirectory
    }

    func url(for bookId: UUID) -> URL {
        metadataDirectory.appendingPathComponent("\(bookId.uuidString).json")
    }

    func write(_ manifest: BookManifest) throws {
        try FileManager.default.createDirectory(at: metadataDirectory, withIntermediateDirectories: true)
        let data = try Self.encoder.encode(manifest)
        try data.write(to: url(for: manifest.bookId), options: [.atomic])
    }

    /// 從 Book 寫 manifest，但與既有 manifest 合併以防固化髒 metadata。
    ///
    /// reader progress / notebook 綁定的落盤都走這條路；若當下 row 仍是 fallback
    /// （UUID title、空 author、nil cover），既有 manifest 的乾淨值不會被覆蓋。
    /// 閱讀位置 / 日期 / notebook 等則一律採 row 的當前值（那正是這次寫入的目的）。
    func write(book: Book, originalFileName: String? = nil) throws {
        let incoming = BookManifest(book: book, originalFileName: originalFileName)
        try write(Self.merged(incoming: incoming, existing: try? read(bookId: book.id)))
    }

    /// 合併策略：incoming 為主，但 fallback/空/nil 的識別性欄位讓位給既有乾淨值。
    static func merged(incoming: BookManifest, existing: BookManifest?) -> BookManifest {
        guard let existing else { return incoming }
        var result = incoming
        if BookMetadataHeuristics.looksLikeFallbackTitle(incoming.title, fileName: incoming.fileName),
           !BookMetadataHeuristics.looksLikeFallbackTitle(existing.title, fileName: existing.fileName) {
            result.title = existing.title
        }
        if BookMetadataHeuristics.looksLikeFallbackAuthor(incoming.author),
           !BookMetadataHeuristics.looksLikeFallbackAuthor(existing.author) {
            result.author = existing.author
        }
        if incoming.coverImageData == nil, let cover = existing.coverImageData {
            result.coverImageData = cover
        }
        if incoming.originalFileName == nil, let original = existing.originalFileName {
            result.originalFileName = original
        }
        return result
    }

    func writeBestEffort(book: Book, originalFileName: String? = nil) {
        do {
            try write(book: book, originalFileName: originalFileName)
        } catch {
            AppLog.book.warning("Book manifest write failed (\(book.epubFileName)): \(error.localizedDescription)")
        }
    }

    func read(bookId: UUID) throws -> BookManifest {
        let data = try Data(contentsOf: url(for: bookId))
        return try Self.decoder.decode(BookManifest.self, from: data)
    }

    func readAll() -> [BookManifest] {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: metadataDirectory,
            includingPropertiesForKeys: nil
        ) else { return [] }

        return files
            .filter { $0.pathExtension == "json" }
            .compactMap { try? Self.decoder.decode(BookManifest.self, from: Data(contentsOf: $0)) }
    }

    func delete(bookId: UUID) {
        try? FileManager.default.removeItem(at: url(for: bookId))
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

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

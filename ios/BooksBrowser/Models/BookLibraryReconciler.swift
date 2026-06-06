import Foundation
import SwiftData
import os

struct BookLibraryReconcileResult: Equatable {
    var recoveredRows = 0
    var writtenManifests = 0
}

struct BookLibraryReconciler {
    let rootDirectory: URL
    let legacyDirectories: [URL]
    let manifestStore: BookManifestStore

    init(
        rootDirectory: URL = Book.booksDirectory,
        legacyDirectories: [URL]? = nil,
        manifestStore: BookManifestStore? = nil
    ) {
        self.rootDirectory = rootDirectory
        self.legacyDirectories = legacyDirectories ?? Self.defaultLegacyDirectories()
        self.manifestStore = manifestStore ?? BookManifestStore(rootDirectory: rootDirectory)
    }

    @MainActor
    func reconcile(context: ModelContext) throws -> BookLibraryReconcileResult {
        let filesByName = scanBookFiles()
        let manifestsByFileName = Dictionary(
            uniqueKeysWithValues: manifestStore.readAll().map { ($0.fileName, $0) }
        )
        var existingBooks = try context.fetch(FetchDescriptor<Book>())
        var existingByFileName = Dictionary(uniqueKeysWithValues: existingBooks.map { ($0.epubFileName, $0) })
        var existingManifestIds = Set(manifestsByFileName.values.map(\.bookId))

        var result = BookLibraryReconcileResult()

        for (fileName, _) in filesByName {
            if let book = existingByFileName[fileName] {
                if !existingManifestIds.contains(book.id) {
                    try manifestStore.write(BookManifest(book: book))
                    existingManifestIds.insert(book.id)
                    result.writtenManifests += 1
                }
                continue
            }

            let book: Book
            if let manifest = manifestsByFileName[fileName] {
                book = Self.book(from: manifest)
            } else {
                book = Self.bookFromFileName(fileName)
            }
            context.insert(book)
            existingBooks.append(book)
            existingByFileName[fileName] = book
            result.recoveredRows += 1
        }

        if result.recoveredRows > 0 || result.writtenManifests > 0 {
            try context.save()
        }

        return result
    }

    private func scanBookFiles() -> [String: URL] {
        var files: [String: URL] = [:]
        for dir in [rootDirectory] + legacyDirectories {
            guard let contents = try? FileManager.default.contentsOfDirectory(
                at: dir,
                includingPropertiesForKeys: nil
            ) else { continue }

            for url in contents {
                guard let fileName = Self.normalizedBookFileName(from: url) else { continue }
                if files[fileName] == nil {
                    files[fileName] = url
                }
            }
        }
        return files
    }

    private static func book(from manifest: BookManifest) -> Book {
        let book = Book(
            title: manifest.title,
            author: manifest.author,
            coverImageData: manifest.coverImageData,
            fileName: manifest.fileName,
            format: manifest.format
        )
        book.id = manifest.bookId
        book.dateAdded = manifest.dateAdded
        book.dateLastRead = manifest.dateLastRead
        book.progression = manifest.progression
        book.lastReadLocatorJSON = manifest.lastReadLocatorJSON
        book.preferredNotebookId = manifest.preferredNotebookId
        return book
    }

    private static func bookFromFileName(_ fileName: String) -> Book {
        let ext = URL(fileURLWithPath: fileName).pathExtension.lowercased()
        let format: BookFormat = switch ext {
        case "epub": .epub
        case "txt": .txt
        case "md": .md
        case "pdf": .pdf
        default: .epub
        }
        let baseName = URL(fileURLWithPath: fileName).deletingPathExtension().lastPathComponent
        let title = baseName.count > 37 && baseName.dropFirst(36).first == "_"
            ? String(baseName.dropFirst(37))
            : baseName
        return Book(title: title, author: "", fileName: fileName, format: format)
    }

    static func normalizedBookFileName(from url: URL) -> String? {
        let supportedExtensions: Set<String> = ["epub", "txt", "md", "pdf"]
        let rawName = url.lastPathComponent
        guard rawName != "Originals", rawName != ".metadata" else { return nil }

        if rawName.hasPrefix("."), rawName.hasSuffix(".icloud") {
            let start = rawName.index(after: rawName.startIndex)
            let end = rawName.index(rawName.endIndex, offsetBy: -".icloud".count)
            let fileName = String(rawName[start..<end])
            let ext = URL(fileURLWithPath: fileName).pathExtension.lowercased()
            return supportedExtensions.contains(ext) ? fileName : nil
        }

        guard !rawName.hasPrefix(".") else { return nil }
        return supportedExtensions.contains(url.pathExtension.lowercased()) ? rawName : nil
    }

    private static func defaultLegacyDirectories() -> [URL] {
        let fm = FileManager.default
        var dirs = [
            fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("EPUBs")
        ]
        if let iCloudContainer = fm.url(forUbiquityContainerIdentifier: nil) {
            dirs.append(iCloudContainer.appendingPathComponent("Documents/EPUBs"))
        }
        return dirs
    }
}

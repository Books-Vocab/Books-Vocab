import Foundation
import SwiftData

struct BookLibraryReconcileResult: Equatable {
    var recoveredRows = 0
    var writtenManifests = 0
    var duplicateRowsRemoved = 0
    var updatedRows = 0
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
    func reconcile(
        context: ModelContext,
        allowBareFileRecovery: Bool = false
    ) throws -> BookLibraryReconcileResult {
        let filesByName = scanBookFiles()
        let manifests = manifestStore.readAll()
        let manifestsByFileName = Self.manifestsByFileName(manifests)
        let manifestsById = Self.manifestsById(manifests)
        var existingBooks = try context.fetch(FetchDescriptor<Book>())
        var result = BookLibraryReconcileResult()
        debugDump(
            stage: "start",
            books: existingBooks,
            manifests: manifests,
            filesByName: filesByName
        )
        result.duplicateRowsRemoved = removeDuplicateRows(
            context: context,
            books: &existingBooks,
            manifestsById: manifestsById
        )
        var existingByFileName = Self.booksByFileName(existingBooks, manifestsById: manifestsById)
        var existingManifestIds = Set(manifestsByFileName.values.map(\.bookId))

        for (fileName, _) in filesByName {
            if let book = existingByFileName[fileName] {
                if let manifest = manifestsByFileName[fileName],
                   Self.mergeManifestMetadata(into: book, from: manifest) {
                    result.updatedRows += 1
                }
                if !existingManifestIds.contains(book.id), Self.shouldPersistManifest(for: book) {
                    try manifestStore.write(BookManifest(book: book))
                    existingManifestIds.insert(book.id)
                    result.writtenManifests += 1
                }
                continue
            }

            let book: Book
            if let manifest = manifestsByFileName[fileName] {
                book = Self.book(from: manifest)
            } else if allowBareFileRecovery {
                book = Self.bookFromFileName(fileName)
            } else {
                continue
            }
            context.insert(book)
            existingBooks.append(book)
            existingByFileName[fileName] = book
            result.recoveredRows += 1
        }

        if result.recoveredRows > 0
            || result.writtenManifests > 0
            || result.duplicateRowsRemoved > 0
            || result.updatedRows > 0 {
            try context.save()
        }
        debugDump(
            stage: "end",
            books: existingBooks,
            manifests: manifestStore.readAll(),
            filesByName: filesByName
        )

        return result
    }

    @MainActor
    private func removeDuplicateRows(
        context: ModelContext,
        books: inout [Book],
        manifestsById: [UUID: BookManifest]
    ) -> Int {
        // 排除空檔名 row 再分組：epubFileName 預設 ""，CloudKit 部分同步可能讓多本書
        // 暫時都是 ""，若一起分組會被互判為「同檔重複」而誤刪不同的書。空檔名是同步
        // 中間態，留待欄位到齊後的下一次 reconcile 處理。
        let grouped = Dictionary(grouping: books.filter { !$0.epubFileName.isEmpty }, by: \.epubFileName)
        var keepersByFileName: [String: Book] = [:]
        var removed = 0

        for (fileName, group) in grouped where group.count > 1 {
            guard let keeper = Self.bestBook(in: group, manifestsById: manifestsById) else { continue }
            keepersByFileName[fileName] = keeper
            for book in group where book !== keeper {
                Self.mergeRecoverableMetadata(into: keeper, from: book)
                context.delete(book)
                removed += 1
            }
        }

        guard removed > 0 else { return 0 }
        books.removeAll { book in
            guard let keeper = keepersByFileName[book.epubFileName] else { return false }
            return book !== keeper
        }
        return removed
    }

    private static func booksByFileName(
        _ books: [Book],
        manifestsById: [UUID: BookManifest]
    ) -> [String: Book] {
        Dictionary(grouping: books, by: \.epubFileName).compactMapValues { group in
            bestBook(in: group, manifestsById: manifestsById)
        }
    }

    /// 取 group 中「恢復價值最高」者。group 必為非空（caller 皆在 count > 1 /
    /// compactMapValues 下呼叫）；回傳 Optional（`max` 對空集合自然回 nil）取代
    /// force-unwrap，避免未來 caller 改了不變式時於 startup 路徑 trap。
    private static func bestBook(
        in group: [Book],
        manifestsById: [UUID: BookManifest]
    ) -> Book? {
        group.max {
            let lhsScore = recoveryScore($0, manifest: manifestsById[$0.id])
            let rhsScore = recoveryScore($1, manifest: manifestsById[$1.id])
            if lhsScore != rhsScore { return lhsScore < rhsScore }
            return $0.dateAdded < $1.dateAdded
        }
    }

    private static func recoveryScore(_ book: Book, manifest: BookManifest?) -> Int {
        var score = 0
        if manifest != nil { score += 100 }
        if book.coverImageData != nil { score += 20 }
        if !looksLikeFallbackTitle(book.title, fileName: book.epubFileName) { score += 15 }
        if !looksLikeFallbackAuthor(book.author) { score += 10 }
        if book.progression != nil { score += 5 }
        if book.dateLastRead != nil { score += 5 }
        if book.lastReadLocatorJSON != nil { score += 5 }
        return score
    }

    private static func mergeRecoverableMetadata(into keeper: Book, from duplicate: Book) {
        if keeper.coverImageData == nil, let cover = duplicate.coverImageData {
            keeper.coverImageData = cover
        }
        if looksLikeFallbackTitle(keeper.title, fileName: keeper.epubFileName)
            && !looksLikeFallbackTitle(duplicate.title, fileName: duplicate.epubFileName) {
            keeper.title = duplicate.title
        }
        if looksLikeFallbackAuthor(keeper.author), !looksLikeFallbackAuthor(duplicate.author) {
            keeper.author = duplicate.author
        }
        if duplicate.dateAdded < keeper.dateAdded {
            keeper.dateAdded = duplicate.dateAdded
        }
        if shouldUseReadingPosition(from: duplicate, over: keeper) {
            keeper.dateLastRead = duplicate.dateLastRead
            keeper.progression = duplicate.progression
            keeper.lastReadLocatorJSON = duplicate.lastReadLocatorJSON
        } else {
            if keeper.progression == nil { keeper.progression = duplicate.progression }
            if keeper.lastReadLocatorJSON == nil { keeper.lastReadLocatorJSON = duplicate.lastReadLocatorJSON }
            if keeper.dateLastRead == nil { keeper.dateLastRead = duplicate.dateLastRead }
        }
        if keeper.preferredNotebookId == nil {
            keeper.preferredNotebookId = duplicate.preferredNotebookId
        }
    }

    private static func mergeManifestMetadata(into book: Book, from manifest: BookManifest) -> Bool {
        var changed = false
        if looksLikeFallbackTitle(book.title, fileName: book.epubFileName)
            && !looksLikeFallbackTitle(manifest.title, fileName: manifest.fileName) {
            book.title = manifest.title
            changed = true
        }
        if looksLikeFallbackAuthor(book.author), !looksLikeFallbackAuthor(manifest.author) {
            book.author = manifest.author
            changed = true
        }
        if book.coverImageData == nil, let cover = manifest.coverImageData {
            book.coverImageData = cover
            changed = true
        }
        if shouldUseManifestReadingPosition(manifest, over: book) {
            book.dateLastRead = manifest.dateLastRead
            book.progression = manifest.progression
            book.lastReadLocatorJSON = manifest.lastReadLocatorJSON
            changed = true
        }
        if book.preferredNotebookId == nil, let notebookId = manifest.preferredNotebookId {
            book.preferredNotebookId = notebookId
            changed = true
        }
        return changed
    }

    private static func shouldUseManifestReadingPosition(_ manifest: BookManifest, over book: Book) -> Bool {
        switch (manifest.dateLastRead, book.dateLastRead) {
        case let (manifestDate?, bookDate?):
            return manifestDate > bookDate
        case (.some, nil):
            return true
        case (nil, .some), (nil, nil):
            return book.progression == nil && manifest.progression != nil
        }
    }

    private static func shouldPersistManifest(for book: Book) -> Bool {
        !looksLikeFallbackTitle(book.title, fileName: book.epubFileName)
            || book.coverImageData != nil
            || book.dateLastRead != nil
            || book.progression != nil
            || book.lastReadLocatorJSON != nil
            || book.preferredNotebookId != nil
    }

    private static func shouldUseReadingPosition(from candidate: Book, over current: Book) -> Bool {
        switch (candidate.dateLastRead, current.dateLastRead) {
        case let (candidateDate?, currentDate?):
            return candidateDate > currentDate
        case (.some, nil):
            return true
        case (nil, .some), (nil, nil):
            return current.progression == nil && candidate.progression != nil
        }
    }

    private static func looksLikeFallbackTitle(_ title: String, fileName: String) -> Bool {
        BookMetadataHeuristics.looksLikeFallbackTitle(title, fileName: fileName)
    }

    private static func looksLikeFallbackAuthor(_ author: String) -> Bool {
        BookMetadataHeuristics.looksLikeFallbackAuthor(author)
    }

    private static func manifestsByFileName(_ manifests: [BookManifest]) -> [String: BookManifest] {
        Dictionary(grouping: manifests, by: \.fileName).compactMapValues { group in
            group.max { manifestScore($0) < manifestScore($1) }
        }
    }

    private static func manifestsById(_ manifests: [BookManifest]) -> [UUID: BookManifest] {
        Dictionary(grouping: manifests, by: \.bookId).compactMapValues { group in
            group.max { manifestScore($0) < manifestScore($1) }
        }
    }

    private static func manifestScore(_ manifest: BookManifest) -> Int {
        var score = 0
        if manifest.coverImageData != nil { score += 20 }
        if !looksLikeFallbackTitle(manifest.title, fileName: manifest.fileName) { score += 15 }
        if !looksLikeFallbackAuthor(manifest.author) { score += 10 }
        if manifest.progression != nil { score += 5 }
        if manifest.dateLastRead != nil { score += 5 }
        if manifest.lastReadLocatorJSON != nil { score += 5 }
        return score
    }

    private func debugDump(
        stage: String,
        books: [Book],
        manifests: [BookManifest],
        filesByName: [String: URL]
    ) {
        #if DEBUG
        let manifestsByFileName = Self.manifestsByFileName(manifests)
        let duplicateFileNames = Dictionary(grouping: books, by: \.epubFileName)
            .filter { $0.value.count > 1 }
            .keys
            .sorted()
        let fallbackRows = books.filter { Self.looksLikeFallbackTitle($0.title, fileName: $0.epubFileName) }
        AppLog.book.debug(
            "BookLibraryReconciler[\(stage, privacy: .public)] summary books=\(books.count) files=\(filesByName.count) manifests=\(manifests.count) duplicateFiles=\(duplicateFileNames.joined(separator: ","), privacy: .public) fallbackRows=\(fallbackRows.count)"
        )
        for book in books.sorted(by: { $0.epubFileName < $1.epubFileName }) {
            let manifest = manifestsByFileName[book.epubFileName]
            let fileURL = filesByName[book.epubFileName]
            let fileReadable = fileURL.map { FileManager.default.isReadableFile(atPath: $0.path) } ?? false
            AppLog.book.debug(
                "BookLibraryReconciler[\(stage, privacy: .public)] row file=\(book.epubFileName, privacy: .public) id=\(book.id.uuidString, privacy: .public) title=\(book.title, privacy: .public) fallback=\(Self.looksLikeFallbackTitle(book.title, fileName: book.epubFileName)) coverBytes=\(book.coverImageData?.count ?? 0) progress=\(book.progression ?? -1, privacy: .public) localReadable=\(fileReadable) manifestTitle=\(manifest?.title ?? "nil", privacy: .public) manifestFallback=\(manifest.map { Self.looksLikeFallbackTitle($0.title, fileName: $0.fileName) } ?? false) manifestCoverBytes=\(manifest?.coverImageData?.count ?? 0) original=\(manifest?.originalFileName ?? "nil", privacy: .public)"
            )
        }
        #endif
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

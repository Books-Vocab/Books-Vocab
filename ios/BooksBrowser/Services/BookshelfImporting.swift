#if os(iOS)
import Foundation
import PDFKit

struct ImportedBookDraft {
    let title: String
    let author: String
    let coverImageData: Data?
    let fileName: String
    let format: BookFormat
}

@MainActor
protocol BookshelfImporting: AnyObject {
    func importBook(from sourceURL: URL, progress: (@Sendable (Double) -> Void)?) async throws -> ImportedBookDraft
    func importTXT(from url: URL, progress: (@Sendable (Double) -> Void)?) async throws -> ImportedBookDraft
    func importMD(from url: URL, progress: (@Sendable (Double) -> Void)?) async throws -> ImportedBookDraft
    func importPDF(from url: URL, progress: (@Sendable (Double) -> Void)?) async throws -> ImportedBookDraft
}

extension BookshelfImporting {
    // 既有呼叫點向後相容
    func importBook(from sourceURL: URL) async throws -> ImportedBookDraft {
        try await importBook(from: sourceURL, progress: nil)
    }
    func importTXT(from url: URL) async throws -> ImportedBookDraft {
        try await importTXT(from: url, progress: nil)
    }
    func importMD(from url: URL) async throws -> ImportedBookDraft {
        try await importMD(from: url, progress: nil)
    }
    func importPDF(from url: URL) async throws -> ImportedBookDraft {
        try await importPDF(from: url, progress: nil)
    }
}

@MainActor
final class BookshelfImportService: BookshelfImporting {
    private let readiumService: any ReadiumServing

    init(readiumService: any ReadiumServing) {
        self.readiumService = readiumService
    }

    func importBook(from sourceURL: URL, progress: (@Sendable (Double) -> Void)? = nil) async throws -> ImportedBookDraft {
        AppCrashReporting.addBreadcrumb(
            category: "import",
            message: "import.start",
            data: ["format": "epub", "ext": sourceURL.pathExtension]
        )
        let (fileName, publication) = try await readiumService.importEPUB(from: sourceURL, progress: progress)
        let metadata = readiumService.extractMetadata(from: publication)
        let coverData = await readiumService.extractCover(from: publication)

        return ImportedBookDraft(
            title: metadata.title,
            author: metadata.author,
            coverImageData: coverData,
            fileName: fileName,
            format: .epub
        )
    }

    func importTXT(from url: URL, progress: (@Sendable (Double) -> Void)? = nil) async throws -> ImportedBookDraft {
        AppCrashReporting.addBreadcrumb(category: "import", message: "import.start", data: ["format": "txt"])
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let epubTmp = try await Task.detached {
            try EPUBConverter().convertTXT(at: url, title: title, progress: progress)
        }.value

        let fileName = epubTmp.lastPathComponent
        let dest = Book.booksDirectory.appendingPathComponent(fileName)
        let fm = FileManager.default
        try fm.createDirectory(at: Book.booksDirectory, withIntermediateDirectories: true)
        try fm.moveItem(at: epubTmp, to: dest)

        // 保留原始檔
        let origDir = Book.booksDirectory.appendingPathComponent("Originals")
        try? fm.createDirectory(at: origDir, withIntermediateDirectories: true)
        try? fm.copyItem(at: url, to: origDir.appendingPathComponent(url.lastPathComponent))

        return ImportedBookDraft(
            title: title,
            author: "",
            coverImageData: nil,
            fileName: fileName,
            format: .txt
        )
    }

    func importMD(from url: URL, progress: (@Sendable (Double) -> Void)? = nil) async throws -> ImportedBookDraft {
        AppCrashReporting.addBreadcrumb(category: "import", message: "import.start", data: ["format": "md"])
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let epubTmp = try await Task.detached {
            try EPUBConverter().convertMD(at: url, title: title, progress: progress)
        }.value

        let fileName = epubTmp.lastPathComponent
        let dest = Book.booksDirectory.appendingPathComponent(fileName)
        let fm = FileManager.default
        try fm.createDirectory(at: Book.booksDirectory, withIntermediateDirectories: true)
        try fm.moveItem(at: epubTmp, to: dest)

        // 保留原始檔
        let origDir = Book.booksDirectory.appendingPathComponent("Originals")
        try? fm.createDirectory(at: origDir, withIntermediateDirectories: true)
        try? fm.copyItem(at: url, to: origDir.appendingPathComponent(url.lastPathComponent))

        return ImportedBookDraft(
            title: title,
            author: "",
            coverImageData: nil,
            fileName: fileName,
            format: .md
        )
    }

    func importPDF(from url: URL, progress: (@Sendable (Double) -> Void)? = nil) async throws -> ImportedBookDraft {
        AppCrashReporting.addBreadcrumb(category: "import", message: "import.start", data: ["format": "pdf"])
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let fileName = UUID().uuidString + "_" + url.lastPathComponent
        let dest = Book.booksDirectory.appendingPathComponent(fileName)
        let fm = FileManager.default
        try fm.createDirectory(at: Book.booksDirectory, withIntermediateDirectories: true)
        try await Self.copyFileChunked(from: url, to: dest, progress: progress)

        let coverData = PDFDocument(url: dest)
            .flatMap { $0.page(at: 0)?.thumbnail(of: CGSize(width: 300, height: 400), for: .artBox) }
            .flatMap { $0.jpegData(compressionQuality: 0.8) }

        return ImportedBookDraft(
            title: title,
            author: "",
            coverImageData: coverData,
            fileName: fileName,
            format: .pdf
        )
    }

    /// 以 ~512 KB 區塊複製檔案，每塊回報一次進度。背景執行緒執行避免阻塞 MainActor。
    nonisolated static func copyFileChunked(
        from src: URL,
        to dst: URL,
        chunkBytes: Int = 512 * 1024,
        progress: (@Sendable (Double) -> Void)? = nil
    ) async throws {
        try await Task.detached(priority: .userInitiated) {
            let attrs = try FileManager.default.attributesOfItem(atPath: src.path)
            let totalBytes = (attrs[.size] as? NSNumber)?.int64Value ?? 0
            let fm = FileManager.default
            if fm.fileExists(atPath: dst.path) { try fm.removeItem(at: dst) }
            fm.createFile(atPath: dst.path, contents: nil)

            let reader = try FileHandle(forReadingFrom: src)
            defer { try? reader.close() }
            let writer = try FileHandle(forWritingTo: dst)
            defer { try? writer.close() }

            var written: Int64 = 0
            progress?(0.0)
            while true {
                let chunk = try reader.read(upToCount: chunkBytes) ?? Data()
                if chunk.isEmpty { break }
                try writer.write(contentsOf: chunk)
                written += Int64(chunk.count)
                if totalBytes > 0 {
                    let ratio = min(1.0, Double(written) / Double(totalBytes))
                    progress?(ratio)
                }
            }
            progress?(1.0)
        }.value
    }
}

enum BookshelfImportError: LocalizedError {
    case securityScopeAccessFailed
    case unsupportedExtension(String)
    case fileTooLarge(bytes: Int, limit: Int)
    case encodingFailed
    case corruptedHeader(format: String)
    case unknown(underlying: String)

    var errorDescription: String? {
        switch self {
        case .securityScopeAccessFailed:
            return "Unable to access the selected file. Please try again."
        case .unsupportedExtension(let ext):
            return "不支援的格式：.\(ext)"
        case .fileTooLarge(let bytes, let limit):
            let mb = Double(bytes) / 1_048_576.0
            let limitMB = limit / 1_048_576
            return String(format: "檔案 %.1f MB 超過 %d MB 上限", mb, limitMB)
        case .encodingFailed:
            return "未支援的文字編碼（請改用 UTF-8）"
        case .corruptedHeader(let format):
            return "\(format) 檔頭損壞或格式無效"
        case .unknown(let underlying):
            return underlying
        }
    }

    /// 失敗類別簡短標籤，供 toast / alert 副標使用。
    var diagnosisLabel: String {
        switch self {
        case .securityScopeAccessFailed: return "權限不足"
        case .unsupportedExtension: return "不支援的格式"
        case .fileTooLarge: return "檔案過大"
        case .encodingFailed: return "編碼錯誤"
        case .corruptedHeader: return "檔頭損壞"
        case .unknown: return "未知錯誤"
        }
    }

    /// 將底層 error 映射到分類診斷。
    static func classify(_ error: Error, sourceURL: URL? = nil) -> BookshelfImportError {
        if let typed = error as? BookshelfImportError { return typed }
        if let converter = error as? EPUBConverterError {
            switch converter {
            case .fileTooLarge(let bytes):
                return .fileTooLarge(bytes: bytes, limit: EPUBConverter.maxBytes)
            case .encodingFailed:
                return .encodingFailed
            case .archiveFailed:
                let ext = sourceURL?.pathExtension.lowercased() ?? "EPUB"
                return .corruptedHeader(format: ext.uppercased())
            }
        }
        let ns = error as NSError
        // Foundation read errors → 多半為檔頭/路徑/權限
        if ns.domain == NSCocoaErrorDomain {
            switch ns.code {
            case NSFileReadCorruptFileError, NSFileReadUnknownError, NSFileReadInapplicableStringEncodingError:
                let ext = sourceURL?.pathExtension.lowercased() ?? "檔案"
                return .corruptedHeader(format: ext.uppercased())
            case NSFileReadNoPermissionError, NSFileReadNoSuchFileError:
                return .securityScopeAccessFailed
            default:
                break
            }
        }
        return .unknown(underlying: error.localizedDescription)
    }
}
#endif

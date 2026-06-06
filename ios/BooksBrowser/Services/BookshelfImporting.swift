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
    ///
    /// 原子性：先寫到同目錄的隱藏 temp 檔，全部寫完才 `moveItem` 到最終位置（同卷 rename
    /// 近似原子）。crash / 被殺 / 寫入失敗時最終路徑**不會**出現截斷的半檔（半檔只會是
    /// 被 reconciler 忽略的隱藏 `.tmp`，且失敗時即清除），避免下次以半檔開書或 bare
    /// recovery 具現壞書。對齊 TXT/MD 既有的 tmp→move 模式。
    nonisolated static func copyFileChunked(
        from src: URL,
        to dst: URL,
        chunkBytes: Int = 512 * 1024,
        progress: (@Sendable (Double) -> Void)? = nil
    ) async throws {
        try await Task.detached(priority: .userInitiated) {
            let fm = FileManager.default
            let attrs = try fm.attributesOfItem(atPath: src.path)
            let totalBytes = (attrs[.size] as? NSNumber)?.int64Value ?? 0

            let tmp = dst.deletingLastPathComponent()
                .appendingPathComponent(".\(UUID().uuidString).tmp")
            fm.createFile(atPath: tmp.path, contents: nil)

            // 寫入區塊：reader/writer 以 defer 無條件 close（含 throw 解開路徑，避免 fd 洩漏），
            // 且 defer 在本 do 結束時即觸發 → 早於下方 move。
            do {
                let reader = try FileHandle(forReadingFrom: src)
                defer { try? reader.close() }
                let writer = try FileHandle(forWritingTo: tmp)
                defer { try? writer.close() }
                var written: Int64 = 0
                progress?(0.0)
                while true {
                    let chunk = try reader.read(upToCount: chunkBytes) ?? Data()
                    if chunk.isEmpty { break }
                    try writer.write(contentsOf: chunk)
                    written += Int64(chunk.count)
                    if totalBytes > 0 {
                        progress?(min(1.0, Double(written) / Double(totalBytes)))
                    }
                }
            } catch {
                try? fm.removeItem(at: tmp)  // 清半檔，最終路徑保持乾淨
                throw error
            }

            // 全部寫完、handle 已關才原子替換最終位置
            do {
                if fm.fileExists(atPath: dst.path) { try fm.removeItem(at: dst) }
                try fm.moveItem(at: tmp, to: dst)
            } catch {
                try? fm.removeItem(at: tmp)
                throw error
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
            return L10n.string("無法存取所選檔案，請再試一次")
        case .unsupportedExtension(let ext):
            return L10n.format("不支援的格式：.%@", ext)
        case .fileTooLarge(let bytes, let limit):
            let mb = String(format: "%.1f", Double(bytes) / 1_048_576.0)
            let limitMB = String(limit / 1_048_576)
            return L10n.format("檔案 %@ MB 超過 %@ MB 上限", mb, limitMB)
        case .encodingFailed:
            return L10n.string("未支援的文字編碼（請改用 UTF-8）")
        case .corruptedHeader(let format):
            return L10n.format("%@ 檔頭損壞或格式無效", format)
        case .unknown(let underlying):
            return underlying
        }
    }

    /// 失敗類別簡短標籤，供 toast / alert 副標使用。
    var diagnosisLabel: String {
        switch self {
        case .securityScopeAccessFailed: return L10n.string("權限不足")
        case .unsupportedExtension: return L10n.string("不支援的格式")
        case .fileTooLarge: return L10n.string("檔案過大")
        case .encodingFailed: return L10n.string("編碼錯誤")
        case .corruptedHeader: return L10n.string("檔頭損壞")
        case .unknown: return L10n.string("未知錯誤")
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

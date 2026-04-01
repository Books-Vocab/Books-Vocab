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
    func importBook(from sourceURL: URL) async throws -> ImportedBookDraft
    func importTXT(from url: URL) async throws -> ImportedBookDraft
    func importMD(from url: URL) async throws -> ImportedBookDraft
    func importPDF(from url: URL) async throws -> ImportedBookDraft
}

@MainActor
final class BookshelfImportService: BookshelfImporting {
    private let readiumService: any ReadiumServing

    init(readiumService: any ReadiumServing) {
        self.readiumService = readiumService
    }

    func importBook(from sourceURL: URL) async throws -> ImportedBookDraft {
        let (fileName, publication) = try await readiumService.importEPUB(from: sourceURL)
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

    func importTXT(from url: URL) async throws -> ImportedBookDraft {
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let epubTmp = try await Task.detached {
            try EPUBConverter().convertTXT(at: url, title: title)
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

    func importMD(from url: URL) async throws -> ImportedBookDraft {
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let epubTmp = try await Task.detached {
            try EPUBConverter().convertMD(at: url, title: title)
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

    func importPDF(from url: URL) async throws -> ImportedBookDraft {
        guard url.startAccessingSecurityScopedResource() else {
            throw BookshelfImportError.securityScopeAccessFailed
        }
        defer { url.stopAccessingSecurityScopedResource() }

        let title = url.deletingPathExtension().lastPathComponent
        let fileName = UUID().uuidString + "_" + url.lastPathComponent
        let dest = Book.booksDirectory.appendingPathComponent(fileName)
        let fm = FileManager.default
        try fm.createDirectory(at: Book.booksDirectory, withIntermediateDirectories: true)
        try fm.copyItem(at: url, to: dest)

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
}

enum BookshelfImportError: LocalizedError {
    case securityScopeAccessFailed

    var errorDescription: String? {
        switch self {
        case .securityScopeAccessFailed:
            return "Unable to access the selected file. Please try again."
        }
    }
}
#endif

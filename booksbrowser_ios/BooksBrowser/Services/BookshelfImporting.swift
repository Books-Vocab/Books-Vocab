import Foundation

struct ImportedBookDraft {
    let title: String
    let author: String
    let coverImageData: Data?
    let epubFileName: String
}

@MainActor
protocol BookshelfImporting: AnyObject {
    func importBook(from sourceURL: URL) async throws -> ImportedBookDraft
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
            epubFileName: fileName
        )
    }
}

#if os(iOS)
import Foundation

/// 從本機可讀 EPUB 抽出的 metadata 快照 — 與 Readium `Publication` 解耦，
/// 讓 repair service 可在 unit test 用 fake extractor，不必碰真 Readium。
struct ExtractedBookMetadata: Equatable {
    var title: String
    var author: String
    var coverImageData: Data?
}

/// metadata 抽取邊界。production 包 `ReadiumServing`；測試注入 fake。
@MainActor
protocol BookMetadataExtracting {
    func extractMetadata(fromEPUBAt url: URL) async throws -> ExtractedBookMetadata
}

/// production adapter — 用既有 Readium 開檔 + 抽 metadata/cover。
@MainActor
struct ReadiumBookMetadataExtractor: BookMetadataExtracting {
    let readiumService: any ReadiumServing

    func extractMetadata(fromEPUBAt url: URL) async throws -> ExtractedBookMetadata {
        let publication = try await readiumService.openPublication(at: url)
        let (title, author) = readiumService.extractMetadata(from: publication)
        let cover = await readiumService.extractCover(from: publication)
        return ExtractedBookMetadata(title: title, author: author, coverImageData: cover)
    }
}
#endif

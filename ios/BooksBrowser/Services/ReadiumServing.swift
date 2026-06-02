#if os(iOS)
import Foundation
import ReadiumShared

/// Readium-related behavior contract for dependency injection and testing.
@MainActor
protocol ReadiumServing: AnyObject {
    func openPublication(at url: URL) async throws -> Publication
    func importEPUB(from sourceURL: URL, progress: (@Sendable (Double) -> Void)?) async throws -> (fileName: String, publication: Publication)
    func extractMetadata(from publication: Publication) -> (title: String, author: String)
    func extractCover(from publication: Publication) async -> Data?
    func extractUniqueWords(from publication: Publication) async -> Set<String>
}

extension ReadiumServing {
    // 既有呼叫點向後相容（無進度版本）
    func importEPUB(from sourceURL: URL) async throws -> (fileName: String, publication: Publication) {
        try await importEPUB(from: sourceURL, progress: nil)
    }
}
#endif

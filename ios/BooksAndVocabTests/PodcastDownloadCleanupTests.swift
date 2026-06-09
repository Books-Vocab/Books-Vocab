#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Account-switch / logout must wipe on-disk podcast audio, not just the
/// SwiftData rows. A residual .mp3 keyed by a reused remoteId could otherwise
/// be served to a different account (#726 reviewer follow-up).
struct PodcastDownloadCleanupTests {

    private func makeTempRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("podcast-cleanup-test-\(UUID().uuidString)", isDirectory: true)
        let seriesDir = root.appendingPathComponent("series-A", isDirectory: true)
        try FileManager.default.createDirectory(at: seriesDir, withIntermediateDirectories: true)
        let mp3 = seriesDir.appendingPathComponent("ep-1.mp3")
        try Data([0x49, 0x44, 0x33]).write(to: mp3) // fake ID3 header
        return root
    }

    @Test func purgeRemovesEntireDownloadsTree() throws {
        let root = try makeTempRoot()
        #expect(FileManager.default.fileExists(atPath: root.path))

        PodcastDownloadManager.purgeDownloads(root: root)

        #expect(!FileManager.default.fileExists(atPath: root.path))
    }

    @Test func purgeIsIdempotentOnMissingRoot() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("podcast-cleanup-absent-\(UUID().uuidString)", isDirectory: true)
        #expect(!FileManager.default.fileExists(atPath: root.path))

        // Must not throw / crash when the directory was never created.
        PodcastDownloadManager.purgeDownloads(root: root)

        #expect(!FileManager.default.fileExists(atPath: root.path))
    }
}
#endif

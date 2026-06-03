#if os(iOS)
import Foundation
import Testing
@testable import BooksBrowser

/// Account-switch / logout must wipe on-disk notebook cover JPEGs, not just the
/// SwiftData rows. `clearUserData` drops the Notebook @Model rows but leaves
/// `Documents/NotebookCovers/<uuid>.jpg` (written by NotebookEditSheet) behind,
/// so a residual cover would survive into account B (#758 follow-up, track-22).
struct NotebookCoverCleanupTests {

    private func makeTempRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("notebook-covers-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let jpg = root.appendingPathComponent("notebook_cover_\(UUID().uuidString).jpg")
        try Data([0xFF, 0xD8, 0xFF]).write(to: jpg) // fake JPEG SOI marker
        return root
    }

    @Test func purgeRemovesEntireCoversTree() throws {
        let root = try makeTempRoot()
        #expect(FileManager.default.fileExists(atPath: root.path))

        LocalDataCleanerService.purgeNotebookCovers(root: root)

        #expect(!FileManager.default.fileExists(atPath: root.path))
    }

    @Test func purgeIsIdempotentOnMissingRoot() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("notebook-covers-absent-\(UUID().uuidString)", isDirectory: true)
        #expect(!FileManager.default.fileExists(atPath: root.path))

        // Must not throw / crash when the directory was never created.
        LocalDataCleanerService.purgeNotebookCovers(root: root)

        #expect(!FileManager.default.fileExists(atPath: root.path))
    }
}
#endif

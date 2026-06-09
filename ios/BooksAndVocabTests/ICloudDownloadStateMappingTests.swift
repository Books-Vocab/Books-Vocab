import Foundation
import Testing
@testable import BooksAndVocab

/// Pure mapping from NSMetadataItem download attributes → `ICloudFileState`.
///
/// Regression focus: during the early download window NSMetadataQuery often
/// reports `status == NotDownloaded` with `percent` nil or 0 even though a
/// download was already triggered. The naive mapping downgraded such files to
/// `.notDownloaded`, making the bookshelf badge flicker between the cloud glyph
/// and the progress ring. Once a file is in `triggeredFiles`, an unavailable
/// percent must hold `.downloading` instead of regressing.
@Suite("ICloudDownloadStateMapping")
struct ICloudDownloadStateMappingTests {

    private let current = NSMetadataUbiquitousItemDownloadingStatusCurrent
    private let downloaded = NSMetadataUbiquitousItemDownloadingStatusDownloaded
    private let notDownloaded = NSMetadataUbiquitousItemDownloadingStatusNotDownloaded

    // MARK: - Terminal / available states

    @Test func currentStatusMapsToCurrent() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: current, percent: nil, hasError: false,
                isTriggered: true, previous: .downloading(0.5)
            ) == .current
        )
    }

    @Test func downloadedStatusMapsToCurrent() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: downloaded, percent: 100, hasError: false,
                isTriggered: false, previous: nil
            ) == .current
        )
    }

    @Test func downloadErrorWinsOverEverything() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: 42, hasError: true,
                isTriggered: true, previous: .downloading(0.42)
            ) == .failed
        )
    }

    // MARK: - Progress reporting

    @Test func midProgressMapsToDownloading() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: 37, hasError: false,
                isTriggered: true, previous: .downloading(0.1)
            ) == .downloading(0.37)
        )
    }

    // MARK: - The flicker window (the bug)

    @Test func triggeredWithNilPercentHoldsDownloading() {
        // Early download window: percent not yet reported → must NOT regress.
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: nil, hasError: false,
                isTriggered: true, previous: nil
            ) == .downloading(0)
        )
    }

    @Test func triggeredWithZeroPercentHoldsDownloading() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: 0, hasError: false,
                isTriggered: true, previous: .downloading(0.2)
            ) == .downloading(0.2)
        )
    }

    @Test func triggeredWithNilPercentKeepsLastKnownPercent() {
        // A transient nil after some progress should carry the prior percent,
        // not reset the ring to 0.
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: nil, hasError: false,
                isTriggered: true, previous: .downloading(0.6)
            ) == .downloading(0.6)
        )
    }

    // MARK: - Genuinely-not-downloaded path (must still work)

    @Test func untriggeredNotDownloadedMapsToNotDownloaded() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: nil, hasError: false,
                isTriggered: false, previous: nil
            ) == .notDownloaded
        )
    }

    @Test func untriggeredZeroPercentMapsToNotDownloaded() {
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: 0, hasError: false,
                isTriggered: false, previous: nil
            ) == .notDownloaded
        )
    }

    // MARK: - Retry path (failed → not regressed into a stuck downloading)

    @Test func previousFailedUntriggeredStaysNotDownloaded() {
        // After a failure triggeredFiles is cleared; a subsequent NotDownloaded
        // poll with no trigger must surface .notDownloaded so the file can be
        // re-triggered, not silently held as downloading.
        #expect(
            ICloudDownloadStateMapping.resolve(
                status: notDownloaded, percent: nil, hasError: false,
                isTriggered: false, previous: .failed
            ) == .notDownloaded
        )
    }
}

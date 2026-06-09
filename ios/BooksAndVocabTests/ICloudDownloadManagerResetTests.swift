import Foundation
import Testing
@testable import BooksAndVocab

@Suite("ICloudDownloadManager — account-switch reset")
@MainActor
struct ICloudDownloadManagerResetTests {

    // MARK: - reset() state clearing

    @Test func resetClearsFileStatesAndHasGathered() {
        let mgr = ICloudDownloadManager()
        // reset() with no prior state must not crash and must leave clean state.
        mgr.reset()
        #expect(mgr.fileStates.isEmpty)
        #expect(!mgr.hasGathered)
    }

    @Test func resetIsIdempotent() {
        let mgr = ICloudDownloadManager()
        mgr.reset()
        mgr.reset()
        #expect(mgr.fileStates.isEmpty)
        #expect(!mgr.hasGathered)
    }

    // MARK: - Notification wiring
    // Observer is registered in init(), not startMonitoring() — so it fires regardless
    // of whether startMonitoring() has been called or stopMonitoring() was called.
    // Use setFileStateForTesting() to inject observable state so reset()'s side effect
    // (clearing fileStates) can be distinguished from "state was already empty".

    @Test func localUserDataDidClearNotificationTriggersReset() {
        let mgr = ICloudDownloadManager()
        mgr.setFileStateForTesting(.notDownloaded, for: "book.epub")
        #expect(!mgr.fileStates.isEmpty)

        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)

        #expect(mgr.fileStates.isEmpty)
        #expect(!mgr.hasGathered)
    }

    @Test func notificationActiveBeforeStartMonitoring() {
        // Account-change observer is wired in init(), independent of startMonitoring.
        let mgr = ICloudDownloadManager()
        mgr.setFileStateForTesting(.current, for: "book.epub")

        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)

        #expect(mgr.fileStates.isEmpty)
    }

    @Test func notificationPersistsAfterStopMonitoring() {
        // stopMonitoring only stops NSMetadataQuery; account-change observer must survive.
        let mgr = ICloudDownloadManager()
        mgr.startMonitoring()
        mgr.stopMonitoring()
        mgr.setFileStateForTesting(.downloading(0.5), for: "book.epub")

        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)

        #expect(mgr.fileStates.isEmpty)
    }
}

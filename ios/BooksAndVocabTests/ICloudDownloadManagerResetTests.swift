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

    @Test func localUserDataDidClearNotificationTriggersReset() {
        let mgr = ICloudDownloadManager()
        // startMonitoring registers the observer even when iCloud is unavailable.
        mgr.startMonitoring()

        // Deliver the notification synchronously (queue: .main, we are on main actor).
        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)

        // reset() was invoked: state must remain clean.
        #expect(mgr.fileStates.isEmpty)
        #expect(!mgr.hasGathered)
    }

    @Test func notificationActiveBeforeStartMonitoring() {
        // Account-change observers are registered at init, independent of startMonitoring.
        let mgr = ICloudDownloadManager()
        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)
        #expect(mgr.fileStates.isEmpty)
        #expect(!mgr.hasGathered)
    }

    @Test func notificationPersistsAfterStopMonitoring() {
        // stopMonitoring only stops NSMetadataQuery; account-change observers must survive.
        let mgr = ICloudDownloadManager()
        mgr.startMonitoring()
        mgr.stopMonitoring()
        // Observer must still be active — posting must not crash.
        NotificationCenter.default.post(name: .localUserDataDidClear, object: nil)
        #expect(mgr.fileStates.isEmpty)
    }
}

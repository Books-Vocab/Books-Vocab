import Foundation
import SwiftData
import os

final class LocalDataCleanerService: LocalDataClearing {
    func clearLocalData(container: ModelContainer, reason: String) async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.sync.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearUserData(reason: reason)
        } catch {
            AppLog.sync.error("clearUserData failed: \(error.localizedDescription)")
        }
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: "kg_last_incremental_sync")
        defaults.removeObject(forKey: "kg_review_payload_version")
        defaults.removeObject(forKey: "activeNotebookId")
        defaults.removeObject(forKey: NotebookFilter.storageKey)
        // Today-review session snapshots are keyed per-user in a single
        // UserDefaults blob. Logout and account-switch both route through here,
        // so clear every user's snapshot to prevent a stale session from being
        // restored on re-login (or surviving until the 7-day maxAge expiry).
        TodayReviewSessionSnapshotStore.clear(for: nil)
    }
}
